"""Admin authentication: Argon2id passwords, server-side sessions, CSRF, login throttling.

See ADR-0007.
"""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.config import Settings
from agent_hq.models import User, UserSession, utcnow

SESSION_COOKIE = "agent_hq_session"
CSRF_COOKIE = "agent_hq_csrf"
CSRF_HEADER = "X-CSRF-Token"
MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()
# Verified against when the e-mail is unknown, so response time does not reveal accounts.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(settings: Settings, session_token: str) -> str:
    """CSRF token bound to the session (HMAC), so it cannot be planted from another session."""
    key = settings.session_secret.get_secret_value().encode()
    return hmac.new(key, _token_hash(session_token).encode(), hashlib.sha256).hexdigest()


def csrf_valid(settings: Settings, session_token: str, presented: str | None) -> bool:
    return presented is not None and hmac.compare_digest(
        csrf_token_for(settings, session_token), presented
    )


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        return None
    return user


async def create_session(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    ip: str | None,
    user_agent: str | None,
) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_absolute_hours),
            ip=ip,
            user_agent=(user_agent or "")[:512],
        )
    )
    user.last_login_at = now
    await session.flush()
    return token


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: object
    token: str


async def resolve_session(
    session: AsyncSession, settings: Settings, token: str | None
) -> Principal | None:
    if not token:
        return None
    row = await session.scalar(
        select(UserSession).where(UserSession.token_hash == _token_hash(token))
    )
    now = utcnow()
    if (
        row is None
        or row.revoked_at is not None
        or row.expires_at <= now
        or row.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= now
    ):
        return None
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    if now - row.last_seen_at > timedelta(minutes=1):
        row.last_seen_at = now
    return Principal(user=user, session_id=row.id, token=token)


async def revoke_session(session: AsyncSession, token: str) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.token_hash == _token_hash(token), UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


class LoginThrottle:
    """Sliding-window limits on failed logins per client IP and per account.

    In-memory: correct for the single API process of the MVP. A multi-instance deployment
    must move this to the database (tracked for Sprint 6).
    """

    def __init__(
        self,
        *,
        per_ip: int = 10,
        per_account: int = 5,
        window_seconds: float = 15 * 60,
    ) -> None:
        self._limits = {"ip": per_ip, "account": per_account}
        self._window = window_seconds
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _recent(self, key: tuple[str, str]) -> deque[float]:
        q = self._failures[key]
        cutoff = time.monotonic() - self._window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, ip: str, account: str) -> bool:
        return (
            len(self._recent(("ip", ip))) >= self._limits["ip"]
            or len(self._recent(("account", account.lower()))) >= self._limits["account"]
        )

    def record_failure(self, ip: str, account: str) -> None:
        now = time.monotonic()
        self._failures[("ip", ip)].append(now)
        self._failures[("account", account.lower())].append(now)

    def reset(self, account: str) -> None:
        self._failures.pop(("account", account.lower()), None)
