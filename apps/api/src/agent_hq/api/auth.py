from fastapi import APIRouter, HTTPException, Request, Response, status

from agent_hq.api.deps import DbDep, PrincipalDep, SettingsDep, check_origin
from agent_hq.api.schemas import LoginIn, LoginOut, UserOut
from agent_hq.config import Settings
from agent_hq.events import record_audit
from agent_hq.security.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    LoginThrottle,
    authenticate,
    create_session,
    csrf_token_for,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookies(response: Response, settings: Settings, token: str) -> str:
    secure = settings.environment not in ("local", "test")
    max_age = settings.session_absolute_hours * 3600
    csrf = csrf_token_for(settings, token)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=secure, samesite="lax"
    )
    # Readable by the web app so it can echo it in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure, samesite="lax"
    )
    return csrf


@router.post("/login")
async def login(
    body: LoginIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> LoginOut:
    check_origin(request, settings)
    throttle: LoginThrottle = request.app.state.login_throttle
    ip = _client_ip(request)
    if throttle.blocked(ip, body.email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, try later")
    user = await authenticate(db, body.email, body.password)
    if user is None:
        throttle.record_failure(ip, body.email)
        await record_audit(
            db,
            actor_type="system",
            actor_id=None,
            action="auth.login_failed",
            details={"ip": ip},
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    throttle.reset(body.email)
    token = await create_session(
        db, settings, user, ip=ip, user_agent=request.headers.get("user-agent")
    )
    await record_audit(
        db, actor_type="user", actor_id=str(user.id), action="auth.login", details={"ip": ip}
    )
    await db.commit()
    csrf = _set_cookies(response, settings, token)
    return LoginOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: PrincipalDep, response: Response, db: DbDep) -> None:
    await revoke_session(db, principal.token)
    await record_audit(db, actor_type="user", actor_id=str(principal.user.id), action="auth.logout")
    await db.commit()
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)


@router.get("/me")
async def me(principal: PrincipalDep, settings: SettingsDep) -> LoginOut:
    return LoginOut(
        user=UserOut.model_validate(principal.user),
        csrf_token=csrf_token_for(settings, principal.token),
    )
