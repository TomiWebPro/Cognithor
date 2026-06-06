from __future__ import annotations

import logging
import traceback as tb_module
from pathlib import Path

from .models import LogLevel
from .service import LogService


class DbLogHandler(logging.Handler):
    def __init__(self, log_service: LogService):
        super().__init__()
        self._svc = log_service

    def emit(self, record: logging.LogRecord) -> None:
        level_map = {
            logging.CRITICAL: LogLevel.CODE_ERROR,
            logging.ERROR: LogLevel.CODE_ERROR,
            logging.WARNING: LogLevel.WARNING,
            logging.INFO: LogLevel.NOTIFY,
            logging.DEBUG: LogLevel.NORMAL_OPERATION,
        }
        db_level = level_map.get(record.levelno, LogLevel.NOTIFY)

        folder = Path(record.pathname).parent.name
        file = record.pathname
        line = record.lineno
        msg = record.getMessage()
        raw_error = ""
        if record.exc_info and record.exc_info[0] is not None:
            raw_error = "".join(tb_module.format_exception(*record.exc_info))

        if db_level == LogLevel.CODE_ERROR:
            self._svc.error(raw_error=raw_error, folder=folder, file=file, line=line, message=msg)
        elif db_level == LogLevel.WARNING:
            self._svc.warning(raw_error=raw_error, folder=folder, file=file, line=line, message=msg)
        elif db_level == LogLevel.NOTIFY:
            self._svc.notify(raw_error=raw_error, folder=folder, file=file, line=line, message=msg)
        else:
            self._svc.normal_operation(message=msg, folder=folder, file=file, line=line)
