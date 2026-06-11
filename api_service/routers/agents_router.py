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


@router.get("/agents/runtime")
async def list_agents_runtime(
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    request: Request = None,
    _: str = Depends(get_current_user),
):
    agents = agent_mgr.list_agents()
    results = []
    for a in agents:
        results.append(_build_runtime(a, agent_mgr, request))
    return results


@router.get("/agents/{agent_id}/runtime")
async def get_agent_runtime(
    agent_id: str,
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    request: Request = None,
    _: str = Depends(get_current_user),
):
    existing = agent_mgr.get_agent(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _build_runtime(existing, agent_mgr, request)


@router.get("/agents/{agent_id}/context")
async def get_agent_context(
    agent_id: str,
    agent_mgr: AgentManager = Depends(_get_agent_mgr),
    _: str = Depends(get_current_user),
):
    existing = agent_mgr.get_agent(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "context": existing.last_context or "",
        "last_updated": existing.last_context_updated_at,
    }


def _build_runtime(agent, agent_mgr: AgentManager, request: Request) -> dict:
    result = {"agent": vars(agent)}

    past_actions_svc = getattr(request.app.state, "past_actions_svc", None) if request else None
    if past_actions_svc is not None:
        records = past_actions_svc.get_recent_actions(agent.agent_id, max_count=5)
        result["recent_actions"] = [
            {"role": r.role, "summary": r.summary, "content": (r.content or "")[:200], "created_at": r.created_at}
            for r in records
        ]
    else:
        result["recent_actions"] = []

    notes_mgr = getattr(request.app.state, "notes_manager", None) if request else None
    if notes_mgr is not None:
        notes = notes_mgr.list_notes(agent.agent_id)
        result["notes"] = [
            {"id": n["id"], "title": n["title"], "content": (n["content"] or "")[:200], "created_at": n["created_at"]}
            for n in (notes or [])
        ]
        result["notes_count"] = len(result["notes"])
    else:
        result["notes"] = []
        result["notes_count"] = 0

    diary_svc = getattr(request.app.state, "diary_svc", None) if request else None
    if diary_svc is not None:
        entries = diary_svc.list_entries(agent.agent_id)
        result["diary_count"] = len(entries) if entries else 0
        result["latest_diary"] = entries[0].content[:200] if entries else None
    else:
        result["diary_count"] = 0
        result["latest_diary"] = None

    alarm_svc = getattr(request.app.state, "alarm_service", None) if request else None
    if alarm_svc is not None:
        alarms = alarm_svc.list_alarms(agent.agent_id)
        result["alarms"] = alarms or []
        result["alarms_count"] = len(result["alarms"])
    else:
        result["alarms"] = []
        result["alarms_count"] = 0

    app_tab_mgr = getattr(request.app.state, "app_tab_mgr", None) if request else None
    if app_tab_mgr is not None:
        tabs = app_tab_mgr.list_open_apps(agent.agent_id)
        result["open_tabs"] = [
            {"tab_id": t.id, "app_id": t.app_id, "label": t.tab_label, "persistent": t.is_persistent}
            for t in (tabs or [])
        ]
    else:
        result["open_tabs"] = []

    agent_app_mgr = getattr(request.app.state, "agent_app_mgr", None) if request else None
    if agent_app_mgr is not None:
        apps = agent_app_mgr.list_agent_apps(agent.agent_id)
        result["installed_apps_count"] = len(apps) if apps else 0
        result["enabled_apps_count"] = sum(1 for a in (apps or []) if a.is_enabled)
    else:
        result["installed_apps_count"] = 0
        result["enabled_apps_count"] = 0

    result["context_window"] = agent.context_window

    return result


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
    if max_past_actions < 3:
        raise HTTPException(status_code=422, detail="'max_past_actions' must be at least 3")
    agent_can_change = payload.get("agent_can_change_max_past_actions", False)
    show_time = payload.get("show_time", True)
    record = agent_mgr.create_agent(
        name=name,
        context_window=context_window,
        model_ref=payload.get("model_ref"),
        backup_model_ref=payload.get("backup_model_ref"),
        max_past_actions=max_past_actions,
        agent_can_change_max_past_actions=agent_can_change,
        show_time=show_time,
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
        if max_past_actions < 3:
            raise HTTPException(status_code=422, detail="'max_past_actions' must be at least 3")
    agent_can_change = payload.get("agent_can_change_max_past_actions")
    show_time = payload.get("show_time")
    status = payload.get("status")
    record = agent_mgr.update_agent(
        agent_id=agent_id,
        name=payload.get("name"),
        context_window=context_window,
        model_ref=payload.get("model_ref"),
        backup_model_ref=payload.get("backup_model_ref"),
        max_past_actions=max_past_actions,
        agent_can_change_max_past_actions=agent_can_change,
        show_time=show_time,
        status=status,
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
