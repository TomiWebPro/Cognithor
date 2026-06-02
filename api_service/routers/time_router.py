from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from core import TimeService, TimeConfig

from ..auth import get_current_user

router = APIRouter(tags=["time"])


def _get_time_svc(request: Request) -> TimeService:
    return request.app.state.time_svc


@router.get("/time/config")
async def get_time_config(
    time_svc: TimeService = Depends(_get_time_svc),
    _: str = Depends(get_current_user),
):
    cfg = time_svc.get_config()
    return {
        "real_epoch": cfg.real_epoch,
        "agent_epoch": cfg.agent_epoch,
        "ratio": cfg.ratio,
    }


@router.put("/time/config")
async def set_time_config(
    payload: dict,
    time_svc: TimeService = Depends(_get_time_svc),
    _: str = Depends(get_current_user),
):
    real_epoch = payload.get("real_epoch")
    agent_epoch = payload.get("agent_epoch")
    ratio = payload.get("ratio")

    if not real_epoch and not agent_epoch and ratio is None:
        raise HTTPException(status_code=422, detail="At least one field required: real_epoch, agent_epoch, ratio")

    try:
        cfg = time_svc.set_config(
            real_epoch=real_epoch,
            agent_epoch=agent_epoch,
            ratio=float(ratio) if ratio is not None else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "real_epoch": cfg.real_epoch,
        "agent_epoch": cfg.agent_epoch,
        "ratio": cfg.ratio,
    }
