from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from secure_db_service import SecureDbService

from .models import LogEntry, LogLevel


DB_DIR = Path("data")
DB_NAME = "cognithor_logs.db"
DB_PATH = DB_DIR / DB_NAME


class LogDatabase:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        use_encryption: bool = False,
        service_name: str = "Cognithor",
        key_name: str = "log_db_key",
        key_env_var: Optional[str] = None,
    ):
        self.db_path = db_path or DB_PATH
        self._svc = SecureDbService(
            db_path=self.db_path,
            use_encryption=use_encryption,
            wal_mode=True,
            retry_attempts=5,
            retry_delay_seconds=0.1,
            service_name=service_name,
            key_name=key_name,
            key_env_var=key_env_var,
        )
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS log_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                level       TEXT NOT NULL,
                folder      TEXT NOT NULL,
                file        TEXT NOT NULL,
                line        INTEGER,
                raw_error   TEXT,
                message     TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_log_entries_level
                ON log_entries(level);
            CREATE INDEX IF NOT EXISTS idx_log_entries_folder
                ON log_entries(folder);
            CREATE INDEX IF NOT EXISTS idx_log_entries_timestamp
                ON log_entries(timestamp);
        """)

    def insert(self, entry: LogEntry) -> int:
        return self._svc.insert(
            """INSERT INTO log_entries
               (timestamp, level, folder, file, line, raw_error, message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.timestamp,
                entry.level,
                entry.folder,
                entry.file,
                entry.line,
                entry.raw_error,
                entry.message,
            ),
        )

    def query(
        self,
        level: Optional[str] = None,
        folder: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        conditions = []
        params = []

        if level:
            conditions.append("level = ?")
            params.append(level)
        if folder:
            conditions.append("folder = ?")
            params.append(folder)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = self._svc.query(
            f"SELECT * FROM log_entries WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params,
        )
        return [dict(r) for r in rows]

    def count_by_level(self, folder: Optional[str] = None) -> list[dict]:
        where = "WHERE folder = ?" if folder else ""
        params = (folder,) if folder else ()
        rows = self._svc.query(
            f"SELECT level, COUNT(*) as count FROM log_entries {where} GROUP BY level",
            params,
        )
        return [dict(r) for r in rows]

    def count_by_folder(self, level: Optional[str] = None) -> list[dict]:
        where = "WHERE level = ?" if level else ""
        params = (level,) if level else ()
        rows = self._svc.query(
            f"SELECT folder, COUNT(*) as count FROM log_entries {where} GROUP BY folder",
            params,
        )
        return [dict(r) for r in rows]

    def delete_older_than(self, days: int) -> int:
        cur = self._svc.execute(
            "DELETE FROM log_entries WHERE timestamp < datetime('now', ?)",
            (f"-{days} days",),
        )
        return cur.rowcount

    def vacuum(self) -> None:
        self._svc.vacuum()

    def backup(self, target_path: str | Path) -> None:
        self._svc.backup(target_path)
