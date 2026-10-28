from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.config import Settings
from agent_hq.security.auth import (
    CSRF_HEADER,
    SESSION_COOKIE,
    Principal,
    csrf_valid,
    resolve_session,
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def check_origin(request: Request, settings: Settings) -> None:
    """Reject cross-site state changes. Browsers always send Origin on such requests."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin not allowed")


async def get_principal(request: Request, db: DbDep, settings: SettingsDep) -> Principal:
    principal = await resolve_session(db, settings, request.cookies.get(SESSION_COOKIE))
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    if request.method not in SAFE_METHODS:
        check_origin(request, settings)
        if not csrf_valid(settings, principal.token, request.headers.get(CSRF_HEADER)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid CSRF token")
    await db.commit()  # persists the sliding last_seen_at update
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]
