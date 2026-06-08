from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agents_service import AgentManager
from core import NotesHandler

from ..auth import get_current_user

router = APIRouter(tags=["notes"])


def _get_notes_handler(request: Request) -> NotesHandler:
    return request.app.state.notes_handler


def _get_agent_mgr(request: Request) -> AgentManager:
    return request.app.state.agent_mgr


@router.get("/agents/{agent_id}/notes")
async def get_notes(
    agent_id: str,
    notes_handler: NotesHandler = Depends(_get_notes_handler),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    content = notes_handler.get_notes(agent_id)
    return {"agent_id": agent_id, "notes": content}


@router.put("/agents/{agent_id}/notes")
async def set_notes(
    agent_id: str,
    payload: dict,
    notes_handler: NotesHandler = Depends(_get_notes_handler),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    content = payload.get("content", "")
    notes_handler.set_notes(agent_id, content)
    return {"agent_id": agent_id, "notes": content}
