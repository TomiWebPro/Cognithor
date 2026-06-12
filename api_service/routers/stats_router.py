from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request

from endpoint import EndpointManager

from ..auth import get_current_user
from ..dependencies import get_endpoint_mgr

router = APIRouter(tags=["stats"])

DEFAULT_PERIODS = ["1h", "3h", "12h", "24h", "7d", "all"]


@router.get("/stats/tokens")
async def get_token_usage(
    request: Request = None,
    periods: str = "",
    agent_id: Optional[str] = None,
    endpoint_mgr: EndpointManager = Depends(get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    period_list = [p.strip() for p in periods.split(",") if p.strip()] if periods else DEFAULT_PERIODS
    data = endpoint_mgr.tracker.get_token_usage_by_period(period_list, agent_id=agent_id)
    return {"periods": data}


@router.get("/stats/tokens/by-agent")
async def get_token_usage_by_agent(
    request: Request = None,
    periods: str = "",
    endpoint_mgr: EndpointManager = Depends(get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    period_list = [p.strip() for p in periods.split(",") if p.strip()] if periods else DEFAULT_PERIODS
    agents = endpoint_mgr.tracker.get_token_usage_by_agent_periods(period_list)
    return {"agents": agents}


@router.get("/stats/timing")
async def get_timing(
    request: Request = None,
    periods: str = "",
    agent_id: Optional[str] = None,
    endpoint_mgr: EndpointManager = Depends(get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    period_list = [p.strip() for p in periods.split(",") if p.strip()] if periods else DEFAULT_PERIODS
    timing = endpoint_mgr.tracker.get_timing_by_period(period_list, agent_id=agent_id)
    first_hours = endpoint_mgr.tracker._period_to_hours(period_list[0]) if period_list else None
    idle = endpoint_mgr.tracker.get_idle_breakdown(
        period_hours=first_hours,
        agent_id=agent_id,
    )
    return {"periods": timing, "idle": idle}


@router.get("/stats/timing/by-agent")
async def get_timing_by_agent(
    request: Request = None,
    periods: str = "",
    endpoint_mgr: EndpointManager = Depends(get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    period_list = [p.strip() for p in periods.split(",") if p.strip()] if periods else DEFAULT_PERIODS
    data = endpoint_mgr.tracker.get_timing_by_agent_periods(period_list)
    return {"agents": data}
