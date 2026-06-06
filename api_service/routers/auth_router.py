from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth import authenticate_user, create_access_token, get_current_user
from ..dependencies import get_config_mgr
from ..database import ApiConfigManager

router = APIRouter()

_login_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_RATE_LIMIT = 5
_LOGIN_RATE_WINDOW = 60


def _check_login_rate(ip: str) -> None:
    now = time.time()
    attempts = _login_attempts[ip]
    cutoff = now - _LOGIN_RATE_WINDOW
    _login_attempts[ip] = [t for t in attempts if t > cutoff]
    if len(_login_attempts[ip]) >= _LOGIN_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )


@router.post("/token")
async def login(
    request: Request,
    config_mgr: ApiConfigManager = Depends(get_config_mgr),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_login_rate(client_ip)

    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")

    _login_attempts[client_ip].append(time.time())

    if not authenticate_user(config_mgr, username, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    version = config_mgr.increment_token_version(username)
    access_token = create_access_token(
        data={"sub": username},
        config_mgr=config_mgr,
        token_version=version,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me")
async def read_users_me(
    username: str = Depends(get_current_user),
):
    return {"username": username}
