from __future__ import annotations

import base64
import io
import json
import secrets

import qrcode
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..dependencies import get_config_mgr
from ..database import ApiConfigManager

router = APIRouter(tags=["onboarding"])


def _get_passkey_data(config_mgr: ApiConfigManager) -> dict:
    config = config_mgr.get_all_config()
    host = config.get("api_host", "0.0.0.0")
    port = config.get("api_port", "8000")

    encryption_key = config_mgr.get_config("encryption_key")
    if not encryption_key:
        encryption_key = secrets.token_hex(32)
        config_mgr.set_config("encryption_key", encryption_key)

    return {
        "host": host,
        "port": int(port),
        "username": "admin",
        "password": "admin",
        "encryption_key": encryption_key,
    }


def _encode_passkey(data: dict) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode()


def _generate_qr(text: str) -> bytes:
    qr = qrcode.make(text)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/onboarding/passkey")
async def get_onboarding_passkey(
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
):
    data = _get_passkey_data(config_mgr)
    passkey = _encode_passkey(data)
    qr_bytes = _generate_qr(passkey)
    return {
        "passkey": passkey,
        "qr_code": base64.b64encode(qr_bytes).decode(),
    }


@router.get("/onboarding/passkey.qr", response_class=Response)
async def get_onboarding_passkey_qr(
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
):
    data = _get_passkey_data(config_mgr)
    passkey = _encode_passkey(data)
    qr_bytes = _generate_qr(passkey)
    return Response(content=qr_bytes, media_type="image/png")
