from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..auth import get_current_user

router = APIRouter()


@router.get("/")
async def read_root():
    return {
        "message": "Cognithor API",
        "status": "running",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
    }


@router.get("/health/secured")
async def health_secured(
    _: str = Depends(get_current_user),
):
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "authenticated": True,
    }
