from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agents_service import AgentManager
from core import DiaryService

from ..auth import get_current_user

router = APIRouter(tags=["diary"])


def _get_diary_svc(request: Request) -> DiaryService:
    return request.app.state.diary_svc


def _get_agent_mgr(request: Request) -> AgentManager:
    return request.app.state.agent_mgr


@router.post("/agents/{agent_id}/diary")
async def append_diary(
    agent_id: str,
    payload: dict,
    diary_svc: DiaryService = Depends(_get_diary_svc),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    content = payload.get("content", "")
    if not content:
        raise HTTPException(status_code=422, detail="Field 'content' is required")
    result = diary_svc.append_diary(agent_id, content)
    return result


@router.get("/agents/{agent_id}/diary")
async def list_diary(
    agent_id: str,
    date: str = Query(None, description="Optional date filter (YYYY-MM-DD)"),
    diary_svc: DiaryService = Depends(_get_diary_svc),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    entries = diary_svc.list_entries(agent_id, date=date)
    return {
        "agent_id": agent_id,
        "entries": [
            {
                "date": e.date,
                "content": e.content,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for e in entries
        ],
    }
