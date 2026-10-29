import pyotp
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from agent_hq.config import Settings
from agent_hq.models import User, utcnow
from agent_hq.security import totp
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]

SECRET = pyotp.random_base32()


async def _enroll(h: Harness) -> None:
    async with h.app.state.sessionmaker() as session:
        user = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert user is not None
        user.totp_secret_encrypted = totp.encrypt_secret(h.settings, SECRET)
        user.totp_enabled_at = utcnow()
        await session.commit()


async def _login(h: Harness, otp: str | None = None) -> tuple[int, str]:
    body = {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    if otp is not None:
        body["otp"] = otp
    r = await h.client.post("/auth/login", json=body)
    return r.status_code, r.json().get("detail", "")


async def test_enrolled_admin_needs_a_valid_single_use_code(harness: Harness) -> None:
    await _enroll(harness)
    assert await _login(harness) == (401, "otp_required")
    wrong = "000000" if pyotp.TOTP(SECRET).now() != "000000" else "111111"
    assert await _login(harness, wrong) == (401, "invalid credentials")

    code = pyotp.TOTP(SECRET).now()
    status, _ = await _login(harness, code)
    assert status == 200
    # The same code cannot be replayed.
    assert await _login(harness, code) == (401, "invalid credentials")


async def test_wrong_password_never_reveals_the_second_factor(harness: Harness) -> None:
    await _enroll(harness)
    r = await harness.client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": "not-the-password"}
    )
    assert r.status_code == 401 and r.json()["detail"] == "invalid credentials"


async def test_production_requires_two_factor(harness: Harness) -> None:
    harness.app.state.settings = harness.settings.model_copy(update={"environment": "production"})
    status, detail = await _login(harness)
    assert status == 403 and "two-factor" in detail
    await _enroll(harness)
    harness.app.state.settings = harness.settings.model_copy(update={"environment": "production"})
    assert (await _login(harness, pyotp.TOTP(SECRET).now()))[0] == 200


def test_secret_is_encrypted_and_bound_to_the_session_secret(settings: Settings) -> None:
    token = totp.encrypt_secret(settings, SECRET)
    assert SECRET not in token
    assert totp.decrypt_secret(settings, token) == SECRET
    rotated = settings.model_copy(update={"session_secret": SecretStr("r" * 48)})
    with pytest.raises(RuntimeError, match="rotated"):
        totp.decrypt_secret(rotated, token)


def test_codes_from_adjacent_steps_are_accepted() -> None:
    now = 1_900_000_000.0
    previous = pyotp.TOTP(SECRET).at(int(now) - 30)
    assert totp.matching_step(SECRET, previous, at=now) == int((now - 30) // 30)
    far = pyotp.TOTP(SECRET).at(int(now) - 120)
    assert totp.matching_step(SECRET, far, at=now) is None
