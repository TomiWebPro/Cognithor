from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt(plaintext: str, key_hex: str) -> dict[str, str]:
    key = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return {
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(ciphertext).decode(),
    }


def decrypt(payload: dict[str, str], key_hex: str) -> str:
    key = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key)
    iv = base64.b64decode(payload["iv"])
    ciphertext = base64.b64decode(payload["data"])
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    return plaintext.decode("utf-8")


def encrypt_json(data: dict, key_hex: str) -> dict[str, str]:
    return encrypt(json.dumps(data, separators=(",", ":")), key_hex)


def decrypt_json(payload: dict[str, str], key_hex: str) -> dict:
    return json.loads(decrypt(payload, key_hex))
