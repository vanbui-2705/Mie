"""Fernet-based encryption/decryption for sensitive DB fields."""
from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    key = os.environ.get("FERNET_KEY", "")
    if not key:
        # In production this MUST be set; for dev we generate a volatile one.
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token_str: str) -> str:
    if not token_str:
        return ""
    try:
        return _get_fernet().decrypt(token_str.encode()).decode()
    except Exception:
        return ""


def mask(value: str) -> str:
    """Show first 4 and last 4 chars; mask the middle."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}***{value[-4:]}"
