from __future__ import annotations
import datetime
import logging
import random
import string
from typing import Optional

from secure_db_service import SecureDbService

logger = logging.getLogger(__name__)

from .models import AgentRecord


def generate_agent_id() -> str:
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=6))


class AgentManager:
    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS agents (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id          TEXT NOT NULL UNIQUE,
                name              TEXT NOT NULL,
                context_window    INTEGER DEFAULT 4096,
                model_ref         TEXT,
                backup_model_ref  TEXT,
                max_past_actions  INTEGER DEFAULT 15,
                created_at        TEXT DEFAULT (datetime('now')),
                updated_at        TEXT DEFAULT (datetime('now'))
            );
        """)
        try:
            self._svc.execute(
                "ALTER TABLE agents ADD COLUMN max_past_actions INTEGER DEFAULT 15"
            )
        except Exception:
            logger.info("Column max_past_actions already exists or could not be added", exc_info=True)

    def _ensure_unique_id(self) -> str:
        for _ in range(100):
            aid = generate_agent_id()
            existing = self._svc.query_one(
                "SELECT id FROM agents WHERE agent_id = ?", (aid,)
            )
            if not existing:
                return aid
        raise RuntimeError("Failed to generate unique agent ID")

    def create_agent(
        self,
        name: str,
        context_window: int = 4096,
        model_ref: Optional[str] = None,
        backup_model_ref: Optional[str] = None,
        max_past_actions: int = 15,
    ) -> AgentRecord:
        agent_id = self._ensure_unique_id()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            """INSERT INTO agents
                (agent_id, name, context_window, model_ref, backup_model_ref, max_past_actions, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, name, context_window, model_ref, backup_model_ref, max_past_actions, now, now),
        )
        row = self._svc.query_one("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        return self._row_to_record(row)

    def get_agent(self, agent_id: str) -> Optional[AgentRecord]:
        row = self._svc.query_one(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        )
        if row is None:
            return None
        return self._row_to_record(row)

    def list_agents(self) -> list[AgentRecord]:
        rows = self._svc.query("SELECT * FROM agents ORDER BY name")
        return [self._row_to_record(r) for r in rows]

    def update_agent(
        self,
        agent_id: str,
        name: Optional[str] = None,
        context_window: Optional[int] = None,
        model_ref: Optional[str] = None,
        backup_model_ref: Optional[str] = None,
        max_past_actions: Optional[int] = None,
    ) -> Optional[AgentRecord]:
        existing = self.get_agent(agent_id)
        if existing is None:
            return None
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            """UPDATE agents SET
                name = COALESCE(?, name),
                context_window = COALESCE(?, context_window),
                model_ref = COALESCE(?, model_ref),
                backup_model_ref = COALESCE(?, backup_model_ref),
                max_past_actions = COALESCE(?, max_past_actions),
                updated_at = ?
             WHERE agent_id = ?""",
            (name, context_window, model_ref, backup_model_ref, max_past_actions, now, agent_id),
        )
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        existing = self.get_agent(agent_id)
        if existing is None:
            return False
        self._svc.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        return True

    def _row_to_record(self, row) -> AgentRecord:
        try:
            mpa = row["max_past_actions"] or 15
        except (IndexError, KeyError, TypeError):
            mpa = 15
        return AgentRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            name=row["name"],
            context_window=row["context_window"],
            model_ref=row["model_ref"],
            backup_model_ref=row["backup_model_ref"],
            max_past_actions=mpa,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
