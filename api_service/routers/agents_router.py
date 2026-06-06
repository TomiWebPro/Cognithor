from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agents_service import AgentManager

from ..auth import get_current_user

router = APIRouter(tags=["agents"])


def _get_agent_mgr(request: Request) -> AgentManager:
    return request.app.state.agent_mgr


@router.get("/agents")
async def list_agents(
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    agents = agent_mgr.list_agents()
    return [vars(a) for a in agents]


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    record = agent_mgr.get_agent(agent_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return vars(record)


@router.post("/agents")
async def create_agent(
    payload: dict,
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=422, detail="Field 'name' is required")
    context_window = payload.get("context_window", 4096)
    try:
        context_window = int(context_window)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="'context_window' must be an integer")
    max_past_actions = payload.get("max_past_actions", 15)
    try:
        max_past_actions = int(max_past_actions)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="'max_past_actions' must be an integer")
    record = agent_mgr.create_agent(
        name=name,
        context_window=context_window,
        model_ref=payload.get("model_ref"),
        backup_model_ref=payload.get("backup_model_ref"),
        max_past_actions=max_past_actions,
    )
    return vars(record)


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    payload: dict,
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    existing = agent_mgr.get_agent(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    context_window = payload.get("context_window")
    if context_window is not None:
        try:
            context_window = int(context_window)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="'context_window' must be an integer")
    max_past_actions = payload.get("max_past_actions")
    if max_past_actions is not None:
        try:
            max_past_actions = int(max_past_actions)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="'max_past_actions' must be an integer")
    record = agent_mgr.update_agent(
        agent_id=agent_id,
        name=payload.get("name"),
        context_window=context_window,
        model_ref=payload.get("model_ref"),
        backup_model_ref=payload.get("backup_model_ref"),
        max_past_actions=max_past_actions,
    )
    return vars(record)


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    request: Request = None,
    _: str = Depends(get_current_user),
):
    existing = agent_mgr.get_agent(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_mgr.delete_agent(agent_id)
    if request is not None and hasattr(request.app.state, "agent_app_mgr"):
        request.app.state.agent_app_mgr.uninstall_all_for_agent(agent_id)
    return {"deleted": True}
