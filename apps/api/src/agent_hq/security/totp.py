"""TOTP two-factor authentication for the admin (ADR-0007, ADR-0014).

The shared secret is stored encrypted (Fernet, key derived from AGENT_HQ_SESSION_SECRET),
codes are accepted within one 30-second step of drift, and a code can be used only once.
"""

import base64
import hashlib
import time
from datetime import UTC, datetime

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from agent_hq.config import Settings
from agent_hq.models import User

STEP_SECONDS = 30


def _fernet(settings: Settings) -> Fernet:
    secret = settings.session_secret.get_secret_value()
    if len(secret) < 32:
        raise RuntimeError("AGENT_HQ_SESSION_SECRET must be set to use two-factor authentication")
    key = hashlib.sha256(f"agent-hq-totp|{secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(settings: Settings, secret: str) -> str:
    return _fernet(settings).encrypt(secret.encode()).decode()


def decrypt_secret(settings: Settings, token: str) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("cannot decrypt 2FA secret (was the session secret rotated?)") from exc


def provisioning_uri(secret: str, email: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=f"{issuer} Agent HQ")


def matching_step(secret: str, code: str, at: float | None = None) -> int | None:
    """The time step a code belongs to (current ±1), or None if it does not match."""
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = time.time() if at is None else at
    for offset in (0, -1, 1):
        moment = now + offset * STEP_SECONDS
        if totp.verify(code, for_time=datetime.fromtimestamp(moment, UTC), valid_window=0):
            return int(moment // STEP_SECONDS)
    return None


def verify_and_consume(settings: Settings, user: User, code: str, at: float | None = None) -> bool:
    """Check a code for `user` and reject replays of the same or an older step."""
    if not user.totp_secret_encrypted:
        return False
    step = matching_step(decrypt_secret(settings, user.totp_secret_encrypted), code, at)
    if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
        return False
    user.totp_last_step = step
    return True
