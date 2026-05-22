from __future__ import annotations

from fastapi import Request
from endpoint import EndpointManager

from .database import ApiConfigManager


def get_config_mgr(request: Request) -> ApiConfigManager:
    return request.app.state.config_mgr


def get_endpoint_mgr(request: Request) -> EndpointManager:
    return request.app.state.endpoint_mgr
