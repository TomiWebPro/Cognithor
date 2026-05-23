from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ProviderRecord:
    id: Optional[int] = None
    name: str = ""
    api_key: Optional[str] = None
    base_url: str = ""
    endpoint_path: str = "/chat/completions"
    models: list[str] = field(default_factory=list)
    headers_template: dict[str, str] = field(default_factory=dict)
    auth_type: str = "bearer"
    auth_header_name: Optional[str] = None
    body_template: str = ""
    response_content_path: str = "choices.0.message.content"
    response_usage_input_path: str = "usage.prompt_tokens"
    response_usage_output_path: str = "usage.completion_tokens"
    response_usage_cost_path: Optional[str] = None
    is_streaming: bool = False
    is_active: bool = False
    max_retries: int = 3
    timeout_seconds: int = 60
    max_concurrent: int = 5


@dataclass
class EndpointStatus:
    provider: str
    available: bool = False
    latency_ms: Optional[float] = None
    last_checked: Optional[str] = None
    error: Optional[str] = None


@dataclass
class UsageRecord:
    id: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: Optional[float] = None
    status: str = "completed"
    timestamp: Optional[str] = None
    context: Optional[str] = None
