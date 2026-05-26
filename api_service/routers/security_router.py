from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import create_access_token, get_current_user
from ..dependencies import get_config_mgr
from ..database import ApiConfigManager
from secure_db_service.key_manager import _keyring_available

router = APIRouter(tags=["security"])

MIN_TOKEN_TTL = 0.5
MAX_TOKEN_TTL = 10.0


@router.get("/settings/security")
async def get_security_settings(
    request: Request,
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    config = config_mgr.get_all_config()
    svc = config_mgr._svc

    return {
        "access_token_expire_minutes": config.get("access_token_expire_minutes", "10"),
        "database_encryption_enabled": svc.use_encryption,
        "database_encryption_available": svc._cipher_available,
        "keyring_available": _keyring_available(),
        "keyring_service_name": svc.service_name,
        "keyring_key_name": svc.key_name,
    }


@router.put("/settings/security")
async def update_security_settings(
    payload: dict[str, str],
    request: Request,
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    allowed_keys = {"access_token_expire_minutes", "database_encryption_enabled"}

    if "access_token_expire_minutes" in payload:
        try:
            ttl = float(payload["access_token_expire_minutes"])
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid token expiry value")
        if ttl < MIN_TOKEN_TTL or ttl > MAX_TOKEN_TTL:
            raise HTTPException(
                status_code=400,
                detail=f"Token expiry must be between {MIN_TOKEN_TTL} and {MAX_TOKEN_TTL} minutes",
            )

    if "database_encryption_enabled" in payload:
        if request.app.state.encryption_in_progress:
            raise HTTPException(status_code=409, detail="Encryption change already in progress")

        request.app.state.encryption_in_progress = True
        try:
            enable = payload["database_encryption_enabled"].lower() in ("true", "1", "yes")
            config_mgr.toggle_encryption(enable)

            endpoint_mgr = request.app.state.endpoint_mgr
            endpoint_mgr.log.db.toggle_encryption(enable)

            config_mgr.set_config(
                "database_encryption_enabled", str(enable).lower(),
            )
        finally:
            request.app.state.encryption_in_progress = False

    for key, value in payload.items():
        if key in allowed_keys:
            config_mgr.set_config(key, value)
    return {"updated": True}


@router.post("/settings/token/refresh")
async def refresh_token(
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    current_user: str = Depends(get_current_user),
):
    version = config_mgr.get_token_version(current_user)
    new_token = create_access_token(
        data={"sub": current_user},
        config_mgr=config_mgr,
        token_version=version,
    )
    from ..auth import get_expire_minutes
    ttl = get_expire_minutes(config_mgr)
    return {"access_token": new_token, "token_type": "bearer", "expires_in_minutes": ttl}
