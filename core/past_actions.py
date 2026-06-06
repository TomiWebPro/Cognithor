from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from secure_db_service import SecureDbService

if TYPE_CHECKING:
    from core.time import TimeService


@dataclass
class PastActionRecord:
    id: Optional[int] = None
    agent_id: str = ""
    role: str = ""
    content: str = ""
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
                created_at    TEXT DEFAULT (datetime('now')),
                bot_timestamp TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_past_actions_agent
                ON past_actions(agent_id, created_at);
        """)
        try:
            self._svc.execute(
                "ALTER TABLE past_actions ADD COLUMN bot_timestamp TEXT"
            )
        except Exception:
            pass

    def record_action(
        self,
        agent_id: str,
        role: str,
        content: str,
        time_svc: Optional[TimeService] = None,
    ) -> PastActionRecord:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        bot_ts = time_svc.now().isoformat() if time_svc else None
        cur = self._svc.execute(
            """INSERT INTO past_actions (agent_id, role, content, created_at, bot_timestamp)
             VALUES (?, ?, ?, ?, ?)""",
            (agent_id, role, content, now, bot_ts),
        )
        return PastActionRecord(
            id=cur.lastrowid,
            agent_id=agent_id,
            role=role,
            content=content,
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
    ) -> Optional[str]:
        actions = self.get_recent_actions(agent_id, max_count)
        if not actions:
            return None

        lines = ["[Past Actions]"]
        lines.append("  Status: Open")
        lines.append("")
        for a in actions:
            role_label = a.role.upper() if a.role.lower() in (
                "user", "assistant", "system", "agent"
            ) else a.role
            content = a.content
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    content = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass
            ts = ""
            if a.bot_timestamp:
                try:
                    dt = datetime.datetime.fromisoformat(a.bot_timestamp)
                    ts = dt.strftime("[%Y-%m-%d %H:%M:%S] ")
                except Exception:
                    pass
            lines.append(f"  {ts}{role_label}: {content}")

        return "\n".join(lines)

    def _row_to_record(self, row) -> PastActionRecord:
        try:
            bt = row["bot_timestamp"]
        except (IndexError, KeyError, TypeError):
            bt = None
        return PastActionRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            bot_timestamp=bt,
        )
