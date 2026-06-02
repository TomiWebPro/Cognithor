from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppParameter:
    name: str = ""
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Optional[str] = None
    enum: list[str] = field(default_factory=list)


@dataclass
class AppManifest:
    app_id: str = ""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = "system"
    icon: str = "◆"
    parameters: list[AppParameter] = field(default_factory=list)
    outputs: list[AppParameter] = field(default_factory=list)
    requires_confirmation: bool = False
    timeout_seconds: int = 30


@dataclass
class AppRecord:
    id: Optional[int] = None
    app_id: str = ""
    name: str = ""
    description: str = ""
    version: str = ""
    author: str = ""
    type: str = "builtin"
    icon: str = "◆"
    manifest: Optional[str] = None
    directory: Optional[str] = None
    is_available: bool = True
    requires_confirmation: bool = False
    timeout_seconds: int = 30
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class AgentAppRecord:
    id: Optional[int] = None
    agent_id: str = ""
    app_id: str = ""
    is_enabled: bool = True
    config: Optional[str] = None
    installed_at: Optional[str] = None
    updated_at: Optional[str] = None
