"""Operational CLI: serve, worker, migrate, create-admin, verify-audit."""

import argparse
import asyncio
import contextlib
import getpass
import signal
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import uvicorn

from agent_hq.config import get_settings

# Psycopg's async mode cannot run on Windows' default ProactorEventLoop.
LOOP = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _run(coro: Coroutine[Any, Any, int]) -> int:
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


def sandbox_app() -> Any:
    from agent_hq.sandbox.runner import create_sandbox_app

    return create_sandbox_app(get_settings())


def migrate() -> int:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    return 0


async def _worker() -> int:
    from agent_hq.agents import seed_agents
    from agent_hq.db import create_engine, create_sessionmaker
    from agent_hq.logging import configure_logging
    from agent_hq.orchestration.worker import Worker, build_runtime, open_checkpointer

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        await seed_agents(session)
        await session.commit()
    runtime = build_runtime(settings, sessionmaker)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(sig, stop.set)
    try:
        async with open_checkpointer(settings) as checkpointer:
            await Worker(runtime, checkpointer).run_forever(stop)
    finally:
        await runtime.github.aclose()
        await runtime.sandbox.aclose()
        if runtime.pull_requests is not None:
            await runtime.pull_requests.aclose()
        await engine.dispose()
    return 0


async def _create_admin(email: str, display_name: str) -> int:
    from sqlalchemy import func, select

    from agent_hq.db import create_engine, create_sessionmaker
    from agent_hq.events import record_audit
    from agent_hq.models import User
    from agent_hq.security.auth import MIN_PASSWORD_LENGTH, hash_password

    password = getpass.getpass(f"Password for {email} (min {MIN_PASSWORD_LENGTH} chars): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    engine = create_engine(get_settings())
    try:
        async with create_sessionmaker(engine)() as session:
            existing = await session.scalar(
                select(User).where(func.lower(User.email) == email.lower())
            )
            if existing is not None:
                existing.password_hash = password_hash
                action = "user.password_reset"
                user = existing
            else:
                user = User(email=email, display_name=display_name, password_hash=password_hash)
                session.add(user)
                action = "user.created"
            await session.flush()
            await record_audit(
                session,
                actor_type="system",
                actor_id="cli",
                action=action,
                resource_type="user",
                resource_id=user.id,
            )
            await session.commit()
    finally:
        await engine.dispose()
    print(f"{action}: {email}")
    return 0


async def _seed_demo() -> int:
    from agent_hq.db import create_engine, create_sessionmaker
    from agent_hq.demo import seed_demo
    from agent_hq.logging import configure_logging
    from agent_hq.main import validate_settings
    from agent_hq.orchestration.worker import Worker, open_checkpointer
    from agent_hq.runtime import Runtime

    settings = get_settings()
    validate_settings(settings)
    configure_logging(settings.log_level)
    engine = create_engine(settings)

    async def run_worker(runtime: Runtime) -> None:
        async with open_checkpointer(settings) as checkpointer:
            await Worker(runtime, checkpointer).run_until_idle()
        await runtime.github.aclose()
        await runtime.sandbox.aclose()

    try:
        print(await seed_demo(settings, create_sessionmaker(engine), run_worker))
    finally:
        await engine.dispose()
    return 0


async def _two_factor(email: str, enable: bool) -> int:
    from sqlalchemy import func, select

    from agent_hq.db import create_engine, create_sessionmaker
    from agent_hq.events import record_audit
    from agent_hq.models import User, utcnow
    from agent_hq.security import totp

    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
            if user is None:
                print(f"No user {email}", file=sys.stderr)
                return 1
            if not enable:
                user.totp_secret_encrypted = None
                user.totp_enabled_at = None
                user.totp_last_step = None
                action = "user.2fa_disabled"
            else:
                secret = totp.new_secret()
                print("Add this account to your authenticator app (Google Authenticator,")
                print("1Password, Authy...) by scanning or pasting this URI:\n")
                print(totp.provisioning_uri(secret, user.email, settings.brand_name))
                print(f"\nOr enter the secret manually: {secret}\n")
                prompt = "Enter the 6-digit code shown by the app to confirm: "
                code = (await asyncio.to_thread(input, prompt)).strip()
                if totp.matching_step(secret, code) is None:
                    print("Code did not match; 2FA was NOT enabled.", file=sys.stderr)
                    return 1
                user.totp_secret_encrypted = totp.encrypt_secret(settings, secret)
                user.totp_enabled_at = utcnow()
                user.totp_last_step = None
                action = "user.2fa_enabled"
            await record_audit(
                session,
                actor_type="system",
                actor_id="cli",
                action=action,
                resource_type="user",
                resource_id=user.id,
            )
            await session.commit()
    finally:
        await engine.dispose()
    print(f"{action}: {email}")
    return 0


async def _verify_audit() -> int:
    from agent_hq.db import create_engine, create_sessionmaker
    from agent_hq.events import verify_audit_chain

    engine = create_engine(get_settings())
    try:
        async with create_sessionmaker(engine)() as session:
            ok, broken = await verify_audit_chain(session)
    finally:
        await engine.dispose()
    print("audit chain OK" if ok else f"audit chain BROKEN at id {broken}")
    return 0 if ok else 2


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-hq")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser("worker", help="run the job worker (agents)")
    sub.add_parser("migrate", help="apply database migrations")
    admin = sub.add_parser("create-admin", help="create the admin user or reset its password")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default="Administrator")
    sub.add_parser("verify-audit", help="verify the audit log hash chain")
    sub.add_parser("seed-demo", help="fill a demo-mode database by running real workflows")
    enable_2fa = sub.add_parser("enable-2fa", help="enroll an authenticator app (TOTP)")
    enable_2fa.add_argument("--email", required=True)
    disable_2fa = sub.add_parser("disable-2fa", help="remove 2FA (e.g. lost device)")
    disable_2fa.add_argument("--email", required=True)
    sandbox = sub.add_parser("sandbox", help="run the sandbox runner (needs Docker access)")
    sandbox.add_argument("--host", default="127.0.0.1")
    sandbox.add_argument("--port", type=int, default=8080)

    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(
            "agent_hq.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            # Open SSE streams would otherwise block shutdown and reloads indefinitely.
            timeout_graceful_shutdown=5,
            loop=LOOP,
            log_config=None,
        )
        return
    if args.command == "sandbox":
        uvicorn.run(
            "agent_hq.cli:sandbox_app",
            factory=True,
            host=args.host,
            port=args.port,
            loop=LOOP,
            log_config=None,
        )
        return
    if args.command == "migrate":
        code = migrate()
    elif args.command == "worker":
        code = _run(_worker())
    elif args.command in ("enable-2fa", "disable-2fa"):
        code = _run(_two_factor(args.email, enable=args.command == "enable-2fa"))
    elif args.command == "seed-demo":
        code = _run(_seed_demo())
    elif args.command == "create-admin":
        code = _run(_create_admin(args.email, args.name))
    else:
        code = _run(_verify_audit())
    sys.exit(code)
