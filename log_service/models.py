from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


class LogLevel:
    CODE_ERROR = "code-error"
    WARNING = "warning"
    NOTIFY = "notify"
    NORMAL_OPERATION = "normal-operation"


@dataclass
class LogEntry:
    id: Optional[int] = None
    timestamp: str = ""
    level: str = LogLevel.NORMAL_OPERATION
    folder: str = ""
    file: str = ""
    line: Optional[int] = None
    raw_error: str = ""
    message: str = ""
