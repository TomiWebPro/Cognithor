from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from secure_db_service import SecureDbService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.time import TimeService


@dataclass
class DiaryEntry:
    id: Optional[int] = None
    agent_id: str = ""
    date: str = ""
    content: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DiaryService:
    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS agent_diary (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id   TEXT NOT NULL,
                date       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(agent_id, date)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_diary_agent
                ON agent_diary(agent_id, date);
        """)

    def _today(self, time_svc: Optional[TimeService] = None) -> str:
        if time_svc:
            return time_svc.now().strftime("%Y-%m-%d")
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def append_diary(
        self,
        agent_id: str,
        content: str,
        time_svc: Optional[TimeService] = None,
    ) -> dict:
        today = self._today(time_svc)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        existing = self._svc.query_one(
            "SELECT content FROM agent_diary WHERE agent_id = ? AND date = ?",
            (agent_id, today),
        )

        if existing:
            new_content = existing["content"] + "\n" + content
            self._svc.execute(
                "UPDATE agent_diary SET content = ?, updated_at = ? WHERE agent_id = ? AND date = ?",
                (new_content, now, agent_id, today),
            )
        else:
            self._svc.execute(
                """INSERT INTO agent_diary (agent_id, date, content, created_at, updated_at)
                 VALUES (?, ?, ?, ?, ?)""",
                (agent_id, today, content, now, now),
            )

        return {
            "success": True,
            "date": today,
            "type": "diary",
            "past_action_summary": f"Appended to diary ({today})",
        }

    def get_entry(self, agent_id: str, date: str) -> Optional[DiaryEntry]:
        row = self._svc.query_one(
            "SELECT * FROM agent_diary WHERE agent_id = ? AND date = ?",
            (agent_id, date),
        )
        if row is None:
            return None
        return self._row_to_entry(row)

    def list_entries(
        self,
        agent_id: str,
        date: Optional[str] = None,
    ) -> list[DiaryEntry]:
        if date:
            rows = self._svc.query(
                "SELECT * FROM agent_diary WHERE agent_id = ? AND date = ? ORDER BY date DESC",
                (agent_id, date),
            )
        else:
            rows = self._svc.query(
                "SELECT * FROM agent_diary WHERE agent_id = ? ORDER BY date DESC",
                (agent_id,),
            )
        return [self._row_to_entry(r) for r in rows]

    def batch_list_entries(self, agent_ids: list[str]) -> dict[str, list[DiaryEntry]]:
        if not agent_ids:
            return {}
        placeholders = ",".join("?" for _ in agent_ids)
        rows = self._svc.query(
            f"SELECT * FROM agent_diary WHERE agent_id IN ({placeholders}) ORDER BY date DESC",
            agent_ids,
        )
        grouped: dict[str, list] = {aid: [] for aid in agent_ids}
        for r in rows:
            aid = r["agent_id"]
            if aid in grouped:
                grouped[aid].append(self._row_to_entry(r))
        return grouped

    def _row_to_entry(self, row) -> DiaryEntry:
        return DiaryEntry(
            id=row["id"],
            agent_id=row["agent_id"],
            date=row["date"],
            content=row["content"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
