from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import get_current_user
from ..database import ApiConfigManager, hash_password
from ..dependencies import get_config_mgr

router = APIRouter(tags=["settings"])


def _validate_password(password: str) -> None:
    # Password is auto-generated for frontend-backend communication, not a
    # human-chosen password. The checks below guard against leaving the
    # default "admin" credential in place after deployment. Auto-generated
    # tokens naturally satisfy all constraints (≥8 chars, upper, lower, digit).
    if len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters"
        )
    if not any(c.isupper() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one uppercase letter"
        )
    if not any(c.islower() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one lowercase letter"
        )
    if not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one digit"
        )


@router.get("/settings")
async def get_settings(
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    return config_mgr.get_all_config()


@router.put("/settings")
async def update_settings(
    payload: dict[str, str],
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    for key, value in payload.items():
        config_mgr.set_config(key, value)
    return config_mgr.get_all_config()


@router.get("/settings/users")
async def list_users(
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    rows = config_mgr._svc.query(
        "SELECT username, created_at FROM api_users ORDER BY username"
    )
    return [{"username": r["username"], "created_at": r["created_at"]} for r in rows]


@router.post("/settings/users")
async def create_user(
    payload: dict[str, str],
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    _: str = Depends(get_current_user),
):
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")
    _validate_password(password)
    if config_mgr.user_exists(username):
        raise HTTPException(status_code=409, detail="User already exists")
    config_mgr.create_user(username, password)
    return {"username": username, "created": True}


@router.put("/settings/users/me/password")
async def change_password(
    payload: dict[str, str],
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
    current_user: str = Depends(get_current_user),
):
    old_password = payload.get("old_password")
    new_password = payload.get("new_password")
    if not old_password or not new_password:
        raise HTTPException(status_code=400, detail="old_password and new_password are required")
    _validate_password(new_password)
    if not config_mgr.verify_user(current_user, old_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    config_mgr._svc.execute(
        "UPDATE api_users SET hashed_password = ? WHERE username = ?",
        (hash_password(new_password), current_user),
    )
    return {"updated": True}
