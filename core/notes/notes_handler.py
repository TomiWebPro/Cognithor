from __future__ import annotations

import datetime
import logging
from typing import Optional

from secure_db_service import SecureDbService
from core.app.app_manager import AppHandler

logger = logging.getLogger(__name__)


class NotesHandler(AppHandler):
    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS agent_notes (
                agent_id          TEXT PRIMARY KEY,
                content           TEXT DEFAULT '',
                max_interactions  INTEGER DEFAULT 10,
                interaction_count INTEGER DEFAULT 0,
                created_at        TEXT DEFAULT (datetime('now')),
                updated_at        TEXT DEFAULT (datetime('now'))
            );
        """)
        for col, ctype in (("max_interactions", "INTEGER"), ("interaction_count", "INTEGER"), ("created_at", "TEXT")):
            try:
                self._svc.execute(
                    f"ALTER TABLE agent_notes ADD COLUMN {col} {ctype}"
                )
            except Exception:
                pass

    def _get_row(self, agent_id: str):
        return self._svc.query_one(
            "SELECT * FROM agent_notes WHERE agent_id = ?", (agent_id,)
        )

    def get_notes(self, agent_id: str) -> str:
        row = self._get_row(agent_id)
        return row["content"] if row else ""

    def set_notes(self, agent_id: str, content: str, max_interactions: int = 10) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            """INSERT INTO agent_notes (agent_id, content, max_interactions, interaction_count, created_at, updated_at)
             VALUES (?, ?, ?, 0, ?, ?)
             ON CONFLICT(agent_id) DO UPDATE SET content = ?, max_interactions = ?, interaction_count = 0, created_at = ?, updated_at = ?""",
            (agent_id, content, max_interactions, now, now, content, max_interactions, now, now),
        )

    def extend_note(self, agent_id: str, max_interactions: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            "UPDATE agent_notes SET max_interactions = ?, interaction_count = 0, created_at = ?, updated_at = ? WHERE agent_id = ?",
            (max_interactions, now, now, agent_id),
        )

    def _increment_count(self, agent_id: str) -> None:
        row = self._get_row(agent_id)
        if row is None or not row["content"]:
            return
        current = int(row["interaction_count"] or 0)
        self._svc.execute(
            "UPDATE agent_notes SET interaction_count = ? WHERE agent_id = ?",
            (current + 1, agent_id),
        )

    def _check_expired(self, agent_id: str) -> bool:
        row = self._get_row(agent_id)
        if row is None or not row["content"]:
            return True
        max_int = int(row["max_interactions"] or 10)
        count = int(row["interaction_count"] or 0)
        if count >= max_int:
            self._svc.execute(
                "UPDATE agent_notes SET content = '', interaction_count = 0 WHERE agent_id = ?",
                (agent_id,),
            )
            return True
        return False

    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        agent_id = params.get("agent_id", "")
        self._increment_count(agent_id)
        expired = self._check_expired(agent_id)
        row = self._get_row(agent_id)

        label = f" ({tab_label})" if tab_label else ""
        lines = [
            f"[Notes]{label}",
            "  Status: Open",
            "",
        ]

        if row and row["content"]:
            content = row["content"]
            max_int = int(row["max_interactions"] or 10)
            count = int(row["interaction_count"] or 0)
            remaining = max_int - count
            created = row["created_at"] or ""
            if created:
                try:
                    dt = datetime.datetime.fromisoformat(created)
                    created_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    created_str = created
            else:
                created_str = ""
            lines.append(f"  {content}")
            if created_str:
                lines.append(f"  (created {created_str}, expires in {remaining} interactions)")
            if remaining == 1:
                lines.append("  \u26a0\ufe0f Will expire in 1 interaction. Use extend_note.")
        else:
            lines.append("  (empty \u2014 use write_note to record plans)")

        lines.append("")
        lines.append('  To write:  {"command": "write_note", "content": "..."}')
        lines.append('  To extend: {"command": "extend_note", "max_interactions": <number>}')
        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        content = params.get("content", "")
        max_int = params.get("max_interactions", 10)
        if content:
            self.set_notes(agent_id, content, max_interactions=max_int)
        return {
            "success": True,
            "type": "notes",
        }
