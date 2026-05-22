from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import create_access_token, get_current_user
from ..dependencies import get_config_mgr
from ..database import ApiConfigManager
from secure_db_service.key_manager import _keyring_available

router = APIRouter(tags=["security"])


@router.get("/settings/security")
async def get_security_settings(
    request: Request,
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    config = config_mgr.get_all_config()
    svc = config_mgr._svc

    return {
        "access_token_expire_minutes": config.get("access_token_expire_minutes", "60"),
        "database_encryption_enabled": svc.use_encryption,
        "database_encryption_available": svc._cipher_module is not None,
        "keyring_available": _keyring_available(),
        "keyring_service_name": svc.service_name,
        "keyring_key_name": svc.key_name,
        "communication_encryption": request.url.scheme == "https",
        "communication_protocol": request.url.scheme,
    }


@router.put("/settings/security")
async def update_security_settings(
    payload: dict[str, str],
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    allowed_keys = {"access_token_expire_minutes"}
    for key, value in payload.items():
        if key in allowed_keys:
            config_mgr.set_config(key, value)
    return {"updated": True}


@router.post("/settings/token/refresh")
async def refresh_token(
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    current_user: str = Depends(get_current_user),
):
    new_token = create_access_token(
        data={"sub": current_user},
        config_mgr=config_mgr,
    )
    return {"access_token": new_token, "token_type": "bearer"}
