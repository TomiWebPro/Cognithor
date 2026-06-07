from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


def parse_model_ref(model_ref: str) -> tuple[str, str]:
    provider, _, model = model_ref.partition("::")
    return provider, model


def build_model_ref(provider: str, model: str) -> str:
    return f"{provider}::{model}"


@dataclass
class AgentRecord:
    id: Optional[int] = None
    agent_id: str = ""
    name: str = ""
    context_window: int = 4096
    model_ref: Optional[str] = None
    backup_model_ref: Optional[str] = None
    max_past_actions: int = 15
    show_context_window: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
