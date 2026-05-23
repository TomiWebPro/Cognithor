from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def derive_key(jwt: str) -> bytes:
    return hashlib.sha256(jwt.encode()).digest()


def encrypt_payload(plaintext: str, key: bytes) -> dict:
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ct = aesgcm.encrypt(iv, plaintext.encode(), None)
    return {
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(ct).decode(),
    }


def decrypt_payload(payload: dict, key: bytes) -> str:
    aesgcm = AESGCM(key)
    iv = base64.b64decode(payload["iv"])
    ct = base64.b64decode(payload["data"])
    return aesgcm.decrypt(iv, ct, None).decode()
