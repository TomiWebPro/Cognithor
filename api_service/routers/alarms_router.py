from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agents_service import AgentManager
from core import AlarmService

from ..auth import get_current_user

router = APIRouter(tags=["alarms"])


def _get_alarm_svc(request: Request) -> AlarmService:
    return request.app.state.alarm_svc


def _get_agent_mgr(request: Request) -> AgentManager:
    return request.app.state.agent_mgr


@router.get("/agents/{agent_id}/alarms")
async def list_alarms(
    agent_id: str,
    alarm_svc: AlarmService = Depends(_get_alarm_svc),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    alarms = alarm_svc.list_alarms(agent_id)
    return {"agent_id": agent_id, "alarms": alarms}


@router.post("/agents/{agent_id}/alarms")
async def create_alarm(
    agent_id: str,
    payload: dict,
    alarm_svc: AlarmService = Depends(_get_alarm_svc),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    alarm_time = payload.get("time")
    if not alarm_time:
        raise HTTPException(status_code=422, detail="Field 'time' is required")
    message = payload.get("message", "")
    time_type = payload.get("time_type", "agent")
    alarm_id = alarm_svc.set_alarm(agent_id, alarm_time, time_type=time_type, message=message)
    if alarm_id is None:
        raise HTTPException(status_code=422, detail="Alarm time is in the past")
    return {"agent_id": agent_id, "alarm_id": alarm_id, "time": alarm_time, "message": message}


@router.delete("/alarms/{alarm_id}")
async def cancel_alarm(
    alarm_id: str,
    alarm_svc: AlarmService = Depends(_get_alarm_svc),
    _: str = Depends(get_current_user),
):
    if not alarm_svc.cancel_alarm(alarm_id):
        raise HTTPException(status_code=404, detail="Alarm not found or already triggered")
    return {"alarm_id": alarm_id, "status": "cancelled"}
