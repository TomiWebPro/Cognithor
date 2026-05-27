from __future__ import annotations

from fastapi import Request
from agents_service import AgentManager
from endpoint import EndpointManager

from .database import ApiConfigManager


def get_config_mgr(request: Request) -> ApiConfigManager:
    return request.app.state.config_mgr


def get_endpoint_mgr(request: Request) -> EndpointManager:
    return request.app.state.endpoint_mgr


def get_agent_mgr(request: Request) -> AgentManager:
    return request.app.state.agent_mgr
