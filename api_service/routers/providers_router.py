from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from endpoint import EndpointManager, ProviderRecord

from ..auth import get_current_user

router = APIRouter(tags=["providers"])


def _get_endpoint_mgr(request: Request) -> EndpointManager:
    return request.app.state.endpoint_mgr


@router.get("/providers")
async def list_providers(
    endpoint_mgr: EndpointManager = Depends(_get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    providers = endpoint_mgr.tracker.list_providers()
    return [vars(p) for p in providers]


@router.get("/providers/{name}")
async def get_provider(
    name: str,
    endpoint_mgr: EndpointManager = Depends(_get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    record = endpoint_mgr.tracker.get_provider(name)
    if record is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return vars(record)


@router.post("/providers")
async def create_provider(
    payload: dict,
    endpoint_mgr: EndpointManager = Depends(_get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=422, detail="Field 'name' is required")
    existing = endpoint_mgr.tracker.get_provider(name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Provider already exists")
    record = ProviderRecord(
        name=name,
        api_key=payload.get("api_key"),
        base_url=payload.get("base_url", ""),
        endpoint_path=payload.get("endpoint_path", "/chat/completions"),
        models=payload.get("models", {}),
        active_models=payload.get("active_models", {}),
        headers_template=payload.get("headers_template", {}),
        auth_type=payload.get("auth_type", "bearer"),
        auth_header_name=payload.get("auth_header_name"),
        body_template=payload.get("body_template", ""),
        response_content_path=payload.get("response_content_path", "choices.0.message.content"),
        response_usage_input_path=payload.get("response_usage_input_path", "usage.prompt_tokens"),
        response_usage_output_path=payload.get("response_usage_output_path", "usage.completion_tokens"),
        response_usage_cost_path=payload.get("response_usage_cost_path"),
        is_streaming=payload.get("is_streaming", False),
        is_active=payload.get("is_active", False),
        max_retries=payload.get("max_retries", 3),
        timeout_seconds=payload.get("timeout_seconds", 60),
        max_concurrent=payload.get("max_concurrent", 5),
    )
    endpoint_mgr.register_provider(record)
    return vars(record)


@router.put("/providers/{name}")
async def update_provider(
    name: str,
    payload: dict,
    endpoint_mgr: EndpointManager = Depends(_get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    existing = endpoint_mgr.tracker.get_provider(name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    record = ProviderRecord(
        id=existing.id,
        name=name,
        api_key=payload.get("api_key", existing.api_key),
        base_url=payload.get("base_url", existing.base_url),
        endpoint_path=payload.get("endpoint_path", existing.endpoint_path),
        models=payload.get("models", existing.models),
        active_models=payload.get("active_models", existing.active_models),
        headers_template=payload.get("headers_template", existing.headers_template),
        auth_type=payload.get("auth_type", existing.auth_type),
        auth_header_name=payload.get("auth_header_name", existing.auth_header_name),
        body_template=payload.get("body_template", existing.body_template),
        response_content_path=payload.get("response_content_path", existing.response_content_path),
        response_usage_input_path=payload.get("response_usage_input_path", existing.response_usage_input_path),
        response_usage_output_path=payload.get("response_usage_output_path", existing.response_usage_output_path),
        response_usage_cost_path=payload.get("response_usage_cost_path", existing.response_usage_cost_path),
        is_streaming=payload.get("is_streaming", existing.is_streaming),
        is_active=payload.get("is_active", existing.is_active),
        max_retries=payload.get("max_retries", existing.max_retries),
        timeout_seconds=payload.get("timeout_seconds", existing.timeout_seconds),
        max_concurrent=payload.get("max_concurrent", existing.max_concurrent),
    )
    endpoint_mgr.register_provider(record)
    return vars(record)


@router.delete("/providers/{name}")
async def delete_provider(
    name: str,
    endpoint_mgr: EndpointManager = Depends(_get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    existing = endpoint_mgr.tracker.get_provider(name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    endpoint_mgr.tracker._svc.execute(
        "DELETE FROM providers WHERE name = ?", (name,)
    )
    return {"deleted": True}


@router.post("/providers/{name}/test")
async def test_provider(
    name: str,
    payload: dict,
    endpoint_mgr: EndpointManager = Depends(_get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    existing = endpoint_mgr.tracker.get_provider(name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    model_name = payload.get("model")
    if model_name:
        try:
            result = endpoint_mgr.test_model(name, model_name)
            return {"provider": name, "model": model_name, **result}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            return {"provider": name, "model": model_name, "available": False, "latency_ms": None, "error": str(e), "last_checked": None}

    try:
        status_result = endpoint_mgr.check_status(name)
        return {
            "provider": name,
            "available": status_result.available,
            "latency_ms": status_result.latency_ms,
            "error": status_result.error,
            "last_checked": status_result.last_checked,
        }
    except Exception as e:
        return {
            "provider": name,
            "available": False,
            "latency_ms": None,
            "error": str(e),
            "last_checked": None,
        }


@router.post("/providers/{name}/test-model/{model}")
async def test_model(
    name: str,
    model: str,
    endpoint_mgr: EndpointManager = Depends(_get_endpoint_mgr),
    _: str = Depends(get_current_user),
):
    existing = endpoint_mgr.tracker.get_provider(name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        result = endpoint_mgr.test_model(name, model)
        return {"provider": name, "model": model, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return {"provider": name, "model": model, "available": False, "latency_ms": None, "error": str(e), "last_checked": None}
