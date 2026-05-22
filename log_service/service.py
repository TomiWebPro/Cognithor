from __future__ import annotations
import datetime
import inspect
import traceback
from pathlib import Path
from typing import Optional

from .database import LogDatabase
from .models import LogEntry, LogLevel


class LogService:
    def __init__(self, database: Optional[LogDatabase] = None):
        self.db = database or LogDatabase()

    def _make_entry(
        self,
        level: str,
        raw_error: str,
        folder: str,
        file: Optional[str] = None,
        line: Optional[int] = None,
        message: str = "",
    ) -> LogEntry:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not file or not line:
            stack = inspect.stack()
            for frame_info in stack:
                caller_path = Path(frame_info.filename)
                if "log_service" not in caller_path.parts:
                    file = str(caller_path)
                    line = frame_info.lineno
                    break

        return LogEntry(
            timestamp=timestamp,
            level=level,
            folder=folder,
            file=file or "",
            line=line,
            raw_error=raw_error,
            message=message,
        )

    def error(
        self,
        raw_error: str,
        folder: str = "",
        file: Optional[str] = None,
        line: Optional[int] = None,
        message: str = "",
    ) -> int:
        entry = self._make_entry(LogLevel.CODE_ERROR, raw_error, folder, file, line, message)
        return self.db.insert(entry)

    def warning(
        self,
        raw_error: str,
        folder: str = "",
        file: Optional[str] = None,
        line: Optional[int] = None,
        message: str = "",
    ) -> int:
        entry = self._make_entry(LogLevel.WARNING, raw_error, folder, file, line, message)
        return self.db.insert(entry)

    def notify(
        self,
        message: str,
        folder: str = "",
        file: Optional[str] = None,
        line: Optional[int] = None,
        raw_error: str = "",
    ) -> int:
        entry = self._make_entry(LogLevel.NOTIFY, raw_error, folder, file, line, message)
        return self.db.insert(entry)

    def normal_operation(
        self,
        message: str,
        folder: str = "",
        file: Optional[str] = None,
        line: Optional[int] = None,
    ) -> int:
        entry = self._make_entry(LogLevel.NORMAL_OPERATION, "", folder, file, line, message)
        return self.db.insert(entry)

    def log_exception(
        self,
        exc: BaseException,
        folder: str = "",
        file: Optional[str] = None,
        line: Optional[int] = None,
        message: str = "",
    ) -> int:
        tb = traceback.format_exc()
        raw_error = f"{type(exc).__name__}: {exc}\n{tb}"
        return self.error(raw_error, folder, file, line, message)

    def query(
        self,
        level: Optional[str] = None,
        folder: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        return self.db.query(level, folder, limit, offset)

    def count_by_level(self, folder: Optional[str] = None) -> list[dict]:
        return self.db.count_by_level(folder)

    def count_by_folder(self, level: Optional[str] = None) -> list[dict]:
        return self.db.count_by_folder(level)
