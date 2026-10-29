import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from agent_hq import __version__
from agent_hq.agents import seed_agents
from agent_hq.api import (
    agents,
    approvals,
    auth,
    events,
    health,
    knowledge,
    metrics,
    projects,
    tasks,
)
from agent_hq.api.events import EventBroadcaster
from agent_hq.config import Settings, get_settings
from agent_hq.db import create_engine, create_sessionmaker
from agent_hq.logging import configure_logging, request_id_var
from agent_hq.security.auth import LoginThrottle

logger = logging.getLogger(__name__)
_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


def validate_settings(settings: Settings) -> None:
    # A demo has no logins, so it needs no session secret.
    needs_secret = settings.environment != "test" and not settings.demo_mode
    if needs_secret and len(settings.session_secret.get_secret_value()) < 32:
        raise RuntimeError("AGENT_HQ_SESSION_SECRET must be set (at least 32 characters)")
    if settings.demo_mode:
        validate_demo_settings(settings)


def validate_demo_settings(settings: Settings) -> None:
    """A public demo must not be able to reach anything real (ADR-0013)."""
    credentials = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "AGENT_HQ_GITHUB_TOKEN": settings.github_token,
        "AGENT_HQ_GITHUB_APP_ID": settings.github_app_id,
        "AGENT_HQ_SLACK_WEBHOOK_URL": settings.slack_webhook_url,
        "AGENT_HQ_TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
    }
    present = sorted(name for name, value in credentials.items() if value)
    if present:
        raise RuntimeError(f"demo mode refuses to start with real credentials: {present}")
    profiles = [settings.model_profile_reasoning, settings.model_profile_fast]
    profiles += list(settings.model_overrides.values())
    if any(not p.startswith("mock:") for p in profiles):
        raise RuntimeError("demo mode only allows the mock model provider")


def create_app(settings: Settings | None = None, *, start_background: bool = True) -> FastAPI:
    settings = settings or get_settings()
    validate_settings(settings)
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await init_state(app, settings, start_background=start_background)
        try:
            yield
        finally:
            await app.state.broadcaster.stop()
            await app.state.engine.dispose()

    app = FastAPI(
        title=f"{settings.brand_name} Agent HQ API",
        version=__version__,
        lifespan=lifespan,
        # Interactive docs only outside production.
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
    )
    for module in (health, auth, projects, tasks, agents, approvals, events, metrics, knowledge):
        app.include_router(module.router)

    @app.middleware("http")
    async def read_only_demo(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Enforced before routing, so no endpoint can change state in a public demo.
        if settings.demo_mode and request.method not in ("GET", "HEAD", "OPTIONS"):
            return JSONResponse({"detail": "public demo is read-only"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    return app


async def init_state(app: FastAPI, settings: Settings, *, start_background: bool = True) -> None:
    app.state.settings = settings
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.login_throttle = LoginThrottle()
    app.state.broadcaster = EventBroadcaster(settings.psycopg_dsn)
    if start_background:
        try:
            async with app.state.sessionmaker() as session:
                await seed_agents(session)
                await session.commit()
        except Exception:
            # The API still starts so /health/ready can report the database problem.
            logger.exception("agent seeding failed")
        app.state.broadcaster.start()
