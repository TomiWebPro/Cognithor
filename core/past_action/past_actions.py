from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from secure_db_service import SecureDbService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.time import TimeService


@dataclass
class PastActionRecord:
    id: Optional[int] = None
    agent_id: str = ""
    role: str = ""
    content: str = ""
    app_id: Optional[str] = None
    summary: Optional[str] = None
    created_at: Optional[str] = None
    bot_timestamp: Optional[str] = None


class PastActionsService:
    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS past_actions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id      TEXT NOT NULL,
                role          TEXT NOT NULL,
                content       TEXT NOT NULL,
                app_id        TEXT,
                summary       TEXT,
                created_at    TEXT DEFAULT (datetime('now')),
                bot_timestamp TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_past_actions_agent
                ON past_actions(agent_id, created_at);
        """)
        for col in ("bot_timestamp", "app_id", "summary"):
            try:
                self._svc.execute(
                    f"ALTER TABLE past_actions ADD COLUMN {col} TEXT"
                )
            except Exception:
                pass

    def record_action(
        self,
        agent_id: str,
        role: str,
        content: str,
        *,
        app_id: Optional[str] = None,
        summary: Optional[str] = None,
        time_svc: Optional[TimeService] = None,
    ) -> PastActionRecord:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        bot_ts = time_svc.now().isoformat() if time_svc else None
        cur = self._svc.execute(
            """INSERT INTO past_actions (agent_id, role, content, app_id, summary, created_at, bot_timestamp)
             VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, role, content, app_id, summary, now, bot_ts),
        )
        return PastActionRecord(
            id=cur.lastrowid,
            agent_id=agent_id,
            role=role,
            content=content,
            app_id=app_id,
            summary=summary,
            created_at=now,
            bot_timestamp=bot_ts,
        )

    def trim_actions(self, agent_id: str, max_count: int) -> int:
        total = self.count_actions(agent_id)
        if total <= max_count:
            return 0
        to_delete = total - max_count
        self._svc.execute(
            """DELETE FROM past_actions
             WHERE id IN (
                 SELECT id FROM past_actions
                 WHERE agent_id = ?
                 ORDER BY created_at ASC
                 LIMIT ?
             )""",
            (agent_id, to_delete),
        )
        return to_delete

    def get_recent_actions(
        self,
        agent_id: str,
        max_count: int = 15,
    ) -> list[PastActionRecord]:
        rows = self._svc.query(
            """SELECT * FROM past_actions
             WHERE agent_id = ?
             ORDER BY created_at DESC
             LIMIT ?""",
            (agent_id, max_count),
        )
        return [self._row_to_record(r) for r in reversed(rows)]

    def count_actions(self, agent_id: str) -> int:
        row = self._svc.query_one(
            "SELECT COUNT(*) AS cnt FROM past_actions WHERE agent_id = ?",
            (agent_id,),
        )
        return row["cnt"] if row else 0

    def clear_actions(self, agent_id: str) -> int:
        self._svc.execute(
            "DELETE FROM past_actions WHERE agent_id = ?",
            (agent_id,),
        )
        return self._svc.changes if hasattr(self._svc, 'changes') else 0

    def generate_tab_interface(
        self,
        agent_id: str,
        max_count: int = 15,
        agent_can_change: bool = False,
    ) -> Optional[str]:
        actions = self.get_recent_actions(agent_id, max_count)
        if not actions:
            return None

        lines = ["[Past Actions]"]
        lines.append("  Status: Open")
        lines.append("")
        lines.append(f"  Your past actions will be truncated after {max_count} interactions and will be moved out of the window.")
        lines.append("  You will no longer be able to see or know that action.")
        if agent_can_change:
            lines.append('  To change: {"command": "config", "max_past_actions": <number>}')
        lines.append("")
        for a in actions:
            raw_role = a.role.lower()
            if raw_role == "user":
                role_label = "YOU"
            elif raw_role == "assistant":
                role_label = "HARNESS"
            else:
                role_label = a.role.upper() if raw_role in ("system", "agent") else a.role
            display = a.summary if a.summary else a.content
            if len(display) > 100:
                display = display[:97] + "..."
            if a.app_id:
                role_label = f"{role_label} [{a.app_id}]"
            ts = ""
            if a.bot_timestamp:
                try:
                    dt = datetime.datetime.fromisoformat(a.bot_timestamp)
                    ts = dt.strftime("[%Y-%m-%d %H:%M:%S] ")
                except Exception:
                    pass
            lines.append(f"  {ts}{role_label}: {display}")

        return "\n".join(lines)

    def _row_to_record(self, row) -> PastActionRecord:
        try:
            bt = row["bot_timestamp"]
        except (IndexError, KeyError, TypeError):
            bt = None
        try:
            ai = row["app_id"]
        except (IndexError, KeyError, TypeError):
            ai = None
        try:
            sm = row["summary"]
        except (IndexError, KeyError, TypeError):
            sm = None
        return PastActionRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            role=row["role"],
            content=row["content"],
            app_id=ai,
            summary=sm,
            created_at=row["created_at"],
            bot_timestamp=bt,
        )
