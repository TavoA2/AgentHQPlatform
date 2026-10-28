"""Time-ordered UUIDv7 identifiers (RFC 9562). Python 3.13 has no stdlib uuid7."""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76 | rand_a << 64
    value |= 0b10 << 62 | rand_b
    return uuid.UUID(int=value)
