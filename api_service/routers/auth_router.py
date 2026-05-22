from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth import authenticate_user, create_access_token, get_current_user
from ..dependencies import get_config_mgr
from ..database import ApiConfigManager

router = APIRouter()


@router.post("/token")
async def login(
    request: Request,
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
):
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")

    if not authenticate_user(config_mgr, username, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": username},
        config_mgr=config_mgr,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me")
async def read_users_me(
    username: str = Depends(get_current_user),
):
    return {"username": username}
