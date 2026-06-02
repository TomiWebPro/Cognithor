from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from apps_service import AppRegistry, AgentAppManager, validate_icon

from ..auth import get_current_user

router = APIRouter(tags=["apps"])


def _get_app_registry(request: Request) -> AppRegistry:
    return request.app.state.app_registry


def _get_agent_app_mgr(request: Request) -> AgentAppManager:
    return request.app.state.agent_app_mgr


@router.get("/apps")
async def list_apps(
    app_registry: AppRegistry = Depends(_get_app_registry),
    _: str = Depends(get_current_user),
):
    apps = app_registry.list_available_apps()
    return [vars(a) for a in apps]


@router.get("/apps/all")
async def list_all_apps(
    app_registry: AppRegistry = Depends(_get_app_registry),
    _: str = Depends(get_current_user),
):
    apps = app_registry.list_apps()
    return [vars(a) for a in apps]


@router.get("/apps/{app_id}")
async def get_app(
    app_id: str,
    app_registry: AppRegistry = Depends(_get_app_registry),
    _: str = Depends(get_current_user),
):
    record = app_registry.get_app(app_id)
    if record is None:
        raise HTTPException(status_code=404, detail="App not found")
    return vars(record)


@router.post("/apps")
async def register_app(
    payload: dict,
    app_registry: AppRegistry = Depends(_get_app_registry),
    _: str = Depends(get_current_user),
):
    from apps_service import AppManifest, AppParameter

    manifest = AppManifest(
        app_id=payload.get("app_id", ""),
        name=payload.get("name", ""),
        description=payload.get("description", ""),
        version=payload.get("version", "1.0.0"),
        author=payload.get("author", "custom"),
        icon=payload.get("icon", "◆"),
        parameters=[
            AppParameter(**p) if isinstance(p, dict) else p
            for p in payload.get("parameters", [])
        ],
        outputs=[
            AppParameter(**o) if isinstance(o, dict) else o
            for o in payload.get("outputs", [])
        ],
        requires_confirmation=payload.get("requires_confirmation", False),
        timeout_seconds=payload.get("timeout_seconds", 30),
    )
    manifest.type = "custom"
    if not manifest.name:
        raise HTTPException(status_code=422, detail="Field 'name' is required")
    if not manifest.app_id:
        manifest.app_id = manifest.name.lower().replace(" ", "_")
    if manifest.icon and not validate_icon(manifest.icon):
        raise HTTPException(status_code=422, detail="Field 'icon' must be a single character or emoji (1-2 unicode code points)")
    record = app_registry.register_app(
        manifest,
        directory=payload.get("directory"),
    )
    return vars(record)


@router.delete("/apps/{app_id}")
async def unregister_app(
    app_id: str,
    app_registry: AppRegistry = Depends(_get_app_registry),
    _: str = Depends(get_current_user),
):
    existing = app_registry.get_app(app_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="App not found")
    app_registry.unregister_app(app_id)
    return {"deleted": True}


@router.put("/apps/{app_id}")
async def update_app(
    app_id: str,
    payload: dict,
    app_registry: AppRegistry = Depends(_get_app_registry),
    _: str = Depends(get_current_user),
):
    existing = app_registry.get_app(app_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="App not found")
    icon = payload.get("icon")
    if icon is not None and not validate_icon(icon):
        raise HTTPException(status_code=422, detail="Field 'icon' must be a single character or emoji (1-2 unicode code points)")
    record = app_registry.update_app(
        app_id=app_id,
        name=payload.get("name"),
        description=payload.get("description"),
        version=payload.get("version"),
        icon=icon,
        is_available=payload.get("is_available"),
        requires_confirmation=payload.get("requires_confirmation"),
        timeout_seconds=payload.get("timeout_seconds"),
    )
    return vars(record)


@router.get("/agents/{agent_id}/apps")
async def list_agent_apps(
    agent_id: str,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    _: str = Depends(get_current_user),
):
    apps = agent_app_mgr.list_agent_apps(agent_id)
    return [vars(a) for a in apps]


@router.get("/agents/{agent_id}/apps/enabled")
async def list_enabled_agent_apps(
    agent_id: str,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    _: str = Depends(get_current_user),
):
    apps = agent_app_mgr.list_enabled_agent_apps(agent_id)
    return [vars(a) for a in apps]


@router.post("/agents/{agent_id}/apps")
async def install_app(
    agent_id: str,
    payload: dict,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    app_registry: AppRegistry = Depends(_get_app_registry),
    _: str = Depends(get_current_user),
):
    app_id = payload.get("app_id")
    if not app_id:
        raise HTTPException(status_code=422, detail="Field 'app_id' is required")

    app = app_registry.get_app(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="App not found in registry")
    if not app.is_available:
        raise HTTPException(status_code=400, detail="App is not available")

    result = agent_app_mgr.install_app(
        agent_id=agent_id,
        app_id=app_id,
        config=payload.get("config"),
    )
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"App '{app_id}' is already installed for agent '{agent_id}'",
        )
    return vars(result)


@router.get("/agents/{agent_id}/apps/{app_id}")
async def get_agent_app(
    agent_id: str,
    app_id: str,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    _: str = Depends(get_current_user),
):
    record = agent_app_mgr.get_agent_app(agent_id, app_id)
    if record is None:
        raise HTTPException(status_code=404, detail="App installation not found")
    return vars(record)


@router.delete("/agents/{agent_id}/apps/{app_id}")
async def uninstall_app(
    agent_id: str,
    app_id: str,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    _: str = Depends(get_current_user),
):
    result = agent_app_mgr.uninstall_app(agent_id, app_id)
    if not result:
        raise HTTPException(status_code=404, detail="App installation not found")
    return {"deleted": True}


@router.put("/agents/{agent_id}/apps/{app_id}/enable")
async def enable_app(
    agent_id: str,
    app_id: str,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    _: str = Depends(get_current_user),
):
    record = agent_app_mgr.enable_app(agent_id, app_id)
    if record is None:
        raise HTTPException(status_code=404, detail="App installation not found")
    return vars(record)


@router.put("/agents/{agent_id}/apps/{app_id}/disable")
async def disable_app(
    agent_id: str,
    app_id: str,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    _: str = Depends(get_current_user),
):
    record = agent_app_mgr.disable_app(agent_id, app_id)
    if record is None:
        raise HTTPException(status_code=404, detail="App installation not found")
    return vars(record)


@router.put("/agents/{agent_id}/apps/{app_id}/config")
async def set_app_config(
    agent_id: str,
    app_id: str,
    payload: dict,
    agent_app_mgr: AgentAppManager = Depends(_get_agent_app_mgr),
    _: str = Depends(get_current_user),
):
    import json
    config = payload.get("config")
    config_json = json.dumps(config) if config is not None and not isinstance(config, str) else config
    record = agent_app_mgr.set_app_config(agent_id, app_id, config_json)
    if record is None:
        raise HTTPException(status_code=404, detail="App installation not found")
    return vars(record)
