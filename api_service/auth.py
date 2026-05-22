from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from .database import ApiConfigManager

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def get_secret_key(config_mgr: ApiConfigManager) -> str:
    key = config_mgr.get_config("secret_key")
    if not key:
        raise RuntimeError("secret_key not configured in database")
    return key


def get_algorithm(config_mgr: ApiConfigManager) -> str:
    alg = config_mgr.get_config("algorithm")
    return alg or "HS256"


def get_expire_minutes(config_mgr: ApiConfigManager) -> int:
    val = config_mgr.get_config("access_token_expire_minutes")
    try:
        return int(val) if val else 60
    except (ValueError, TypeError):
        return 60


def create_access_token(
    data: dict,
    config_mgr: ApiConfigManager,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=get_expire_minutes(config_mgr)
        )
    to_encode.update({"exp": expire})
    secret = get_secret_key(config_mgr)
    algorithm = get_algorithm(config_mgr)
    return jwt.encode(to_encode, secret, algorithm=algorithm)


def authenticate_user(
    config_mgr: ApiConfigManager,
    username: str,
    password: str,
) -> bool:
    return config_mgr.verify_user(username, password)


def _get_config_mgr(request: Request) -> ApiConfigManager:
    return request.app.state.config_mgr


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    config_mgr: ApiConfigManager = Depends(_get_config_mgr),
) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    auth_token = getattr(request.state, "auth_token", None)
    if auth_token:
        token = auth_token

    try:
        secret = get_secret_key(config_mgr)
        algorithm = get_algorithm(config_mgr)
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    if not config_mgr.user_exists(username):
        raise credentials_exception

    return username
