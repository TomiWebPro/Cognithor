from __future__ import annotations
import os
import secrets
from typing import Optional


SERVICE_NAME = "Cognithor"
KEY_NAME = "db_key"
FALLBACK_KEY = "debug_key_please_change_me"


def _keyring_available() -> bool:
    try:
        import keyring
        return True
    except ImportError:
        return False


def get_key(
    service_name: str = SERVICE_NAME,
    key_name: str = KEY_NAME,
) -> Optional[str]:
    if not _keyring_available():
        return None
    import keyring
    try:
        val = keyring.get_password(service_name, key_name)
        return val if val else None
    except Exception:
        return None


def set_key(
    key: str,
    service_name: str = SERVICE_NAME,
    key_name: str = KEY_NAME,
) -> bool:
    if not _keyring_available():
        return False
    import keyring
    try:
        keyring.set_password(service_name, key_name, key)
        return True
    except Exception:
        return False


def has_key(
    service_name: str = SERVICE_NAME,
    key_name: str = KEY_NAME,
) -> bool:
    return get_key(service_name, key_name) is not None


def get_or_create_key(
    service_name: str = SERVICE_NAME,
    key_name: str = KEY_NAME,
    length: int = 32,
) -> str:
    existing = get_key(service_name, key_name)
    if existing:
        return existing
    new_key = secrets.token_hex(length)
    set_key(new_key, service_name, key_name)
    return new_key


def resolve_key(
    use_encryption: bool,
    service_name: str = SERVICE_NAME,
    key_name: str = KEY_NAME,
    env_var: Optional[str] = None,
) -> Optional[str]:
    if not use_encryption:
        return None

    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val

    val = get_key(service_name, key_name)
    if val:
        return val

    return FALLBACK_KEY
