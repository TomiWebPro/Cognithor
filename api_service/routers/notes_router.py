from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agents_service import AgentManager
from core import NotesManager

from ..auth import get_current_user

router = APIRouter(tags=["notes"])


def _get_notes_manager(request: Request) -> NotesManager:
    return request.app.state.notes_manager


def _get_agent_mgr(request: Request) -> AgentManager:
    return request.app.state.agent_mgr


@router.get("/agents/{agent_id}/notes")
async def list_notes(
    agent_id: str,
    notes_manager: NotesManager = Depends(_get_notes_manager),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    notes = notes_manager.list_notes(agent_id)
    return {
        "agent_id": agent_id,
        "notes": [
            {
                "note_id": n["id"],
                "title": n["title"],
                "content": n["content"],
                "max_interactions": n["max_interactions"],
                "interaction_count": n["interaction_count"],
                "created_at": n["created_at"],
                "updated_at": n["updated_at"],
            }
            for n in notes
        ],
    }


@router.post("/agents/{agent_id}/notes")
async def create_note(
    agent_id: str,
    payload: dict,
    notes_manager: NotesManager = Depends(_get_notes_manager),
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agent = agent_mgr.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    title = payload.get("title", "")
    content = payload.get("content", "")
    max_interactions = payload.get("max_interactions", 10)
    note_id = notes_manager.create_note(agent_id, title=title, content=content, max_interactions=max_interactions)
    return {"agent_id": agent_id, "note_id": note_id, "title": title, "content": content}


@router.get("/notes/{note_id}")
async def get_note(
    note_id: str,
    notes_manager: NotesManager = Depends(_get_notes_manager),
    _: str = Depends(get_current_user),
):
    note = notes_manager.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return {
        "note_id": note["id"],
        "agent_id": note["agent_id"],
        "title": note["title"],
        "content": note["content"],
        "max_interactions": note["max_interactions"],
        "interaction_count": note["interaction_count"],
        "created_at": note["created_at"],
        "updated_at": note["updated_at"],
    }


@router.put("/notes/{note_id}")
async def update_note(
    note_id: str,
    payload: dict,
    notes_manager: NotesManager = Depends(_get_notes_manager),
    _: str = Depends(get_current_user),
):
    note = notes_manager.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    content = payload.get("content", "")
    title = payload.get("title")
    notes_manager.update_note(note_id, content=content, title=title)
    return {"note_id": note_id, "content": content, "title": title}


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: str,
    notes_manager: NotesManager = Depends(_get_notes_manager),
    _: str = Depends(get_current_user),
):
    note = notes_manager.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    notes_manager.delete_note(note_id)
    return {"note_id": note_id, "status": "deleted"}


@router.post("/notes/{note_id}/extend")
async def extend_note(
    note_id: str,
    payload: dict,
    notes_manager: NotesManager = Depends(_get_notes_manager),
    _: str = Depends(get_current_user),
):
    note = notes_manager.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    max_interactions = payload.get("max_interactions", 10)
    notes_manager.extend_note(note_id, max_interactions=max_interactions)
    return {"note_id": note_id, "max_interactions": max_interactions, "status": "extended"}
