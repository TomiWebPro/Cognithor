from __future__ import annotations

import datetime
import json
import random
import string
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from secure_db_service import SecureDbService
from apps_service import AppRegistry, AppRecord

if TYPE_CHECKING:
    from core.past_actions import PastActionsService


def generate_tab_id() -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=6))


class AppHandler:
    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        raise NotImplementedError

    def execute(self, params: dict) -> dict:
        raise NotImplementedError


@dataclass
class AgentOpenAppRecord:
    id: Optional[str] = None
    agent_id: str = ""
    app_id: str = ""
    tab_label: Optional[str] = None
    params: Optional[str] = None
    interface_text: Optional[str] = None
    is_persistent: bool = False
    opened_at: Optional[str] = None
    updated_at: Optional[str] = None


class AppTabManager:
    def __init__(self, svc: SecureDbService, app_registry: AppRegistry):
        self._svc = svc
        self._app_registry = app_registry
        self._handlers: dict[str, AppHandler] = {}
        self._init_db()

    def register_handler(self, app_id: str, handler: AppHandler) -> None:
        self._handlers[app_id] = handler

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS agent_open_apps (
                id              TEXT PRIMARY KEY,
                agent_id        TEXT NOT NULL,
                app_id          TEXT NOT NULL,
                tab_label       TEXT,
                params          TEXT,
                interface_text  TEXT,
                is_persistent   INTEGER DEFAULT 0,
                opened_at       TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_agent_open_apps_agent
                ON agent_open_apps(agent_id);
        """)
        try:
            self._svc.execute(
                "ALTER TABLE agent_open_apps ADD COLUMN is_persistent INTEGER DEFAULT 0"
            )
        except Exception:
            pass

    def _ensure_unique_tab_id(self) -> str:
        for _ in range(100):
            tid = generate_tab_id()
            existing = self._svc.query_one(
                "SELECT id FROM agent_open_apps WHERE id = ?", (tid,)
            )
            if not existing:
                return tid
        raise RuntimeError("Failed to generate unique tab ID")

    def _get_params_dict(self, params: Optional[str]) -> dict:
        if not params:
            return {}
        try:
            return json.loads(params) if isinstance(params, str) else params
        except (json.JSONDecodeError, TypeError):
            return {}

    def _generate_interface(
        self,
        app_id: str,
        params: dict,
        tab_label: Optional[str] = None,
        app_record: Optional[AppRecord] = None,
        tab_id: Optional[str] = None,
        is_persistent: bool = False,
    ) -> str:
        handler = self._handlers.get(app_id)
        interface = ""
        if handler is not None:
            interface = handler.generate_interface(params, tab_label=tab_label)
        elif app_record is not None:
            icon = app_record.icon or "\u25c6"
            label = f" ({tab_label})" if tab_label else ""
            lines = [
                f"[{app_record.app_id}]{label}",
                "  Status: Open",
            ]
            if app_record.description:
                lines.append("")
                lines.append(f"  {app_record.description}")
            interface = "\n".join(lines)

        if tab_id and not is_persistent:
            close_tag = f'{{close_tab:"{tab_id}"}}'
            idx = interface.find('\n')
            if idx == -1:
                interface = f"{interface} {close_tag}"
            else:
                interface = f"{interface[:idx]} {close_tag}{interface[idx:]}"

        return interface

    def _is_system_app(self, app_id: str) -> bool:
        return app_id.startswith("__")

    def open_app(
        self,
        agent_id: str,
        app_id: str,
        tab_label: Optional[str] = None,
        params: Optional[dict] = None,
        is_persistent: bool = False,
    ) -> tuple[str, str]:
        is_system = self._is_system_app(app_id)

        if is_system:
            app_record = None
        else:
            app_record = self._app_registry.get_app(app_id)
            if app_record is None:
                raise ValueError(f"App '{app_id}' not found in registry")

        tab_id = self._ensure_unique_tab_id()
        params_json = json.dumps(params) if params else None
        params_dict = params or {}

        interface = self._generate_interface(
            app_id, params_dict, tab_label=tab_label, app_record=app_record,
            tab_id=tab_id, is_persistent=is_persistent,
        )
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        self._svc.execute(
            """INSERT INTO agent_open_apps
                (id, agent_id, app_id, tab_label, params, interface_text,
                 is_persistent, opened_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tab_id, agent_id, app_id, tab_label, params_json, interface,
             int(is_persistent), now, now),
        )

        return tab_id, interface

    def close_tab(self, tab_id: str) -> bool:
        existing = self._svc.query_one(
            "SELECT id, is_persistent FROM agent_open_apps WHERE id = ?", (tab_id,)
        )
        if existing is None:
            return False
        if existing["is_persistent"]:
            raise ValueError("Cannot close a persistent tab")
        self._svc.execute("DELETE FROM agent_open_apps WHERE id = ?", (tab_id,))
        return True

    def close_tabs_by_app(self, agent_id: str, app_id: str) -> int:
        self._svc.execute(
            "DELETE FROM agent_open_apps WHERE agent_id = ? AND app_id = ? AND is_persistent = 0",
            (agent_id, app_id),
        )
        return self._svc.changes if hasattr(self._svc, 'changes') else 0

    def close_all_tabs(self, agent_id: str) -> int:
        self._svc.execute(
            "DELETE FROM agent_open_apps WHERE agent_id = ? AND is_persistent = 0",
            (agent_id,),
        )
        return self._svc.changes if hasattr(self._svc, 'changes') else 0

    def list_open_apps(self, agent_id: str) -> list[AgentOpenAppRecord]:
        rows = self._svc.query(
            "SELECT * FROM agent_open_apps WHERE agent_id = ? ORDER BY opened_at",
            (agent_id,),
        )
        return [self._row_to_record(r) for r in rows]

    def get_open_app(self, tab_id: str) -> Optional[AgentOpenAppRecord]:
        row = self._svc.query_one(
            "SELECT * FROM agent_open_apps WHERE id = ?", (tab_id,)
        )
        if row is None:
            return None
        return self._row_to_record(row)

    def ensure_persistent_tabs(self, agent_id: str) -> None:
        existing = self._svc.query_one(
            "SELECT id, is_persistent FROM agent_open_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, "__list_apps__"),
        )
        if existing is not None:
            if not existing["is_persistent"]:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self._svc.execute(
                    "UPDATE agent_open_apps SET is_persistent = 1, updated_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
            return
        self.open_app(
            agent_id,
            "__list_apps__",
            is_persistent=True,
        )

    def refresh_interface(self, tab_id: str) -> Optional[str]:
        record = self.get_open_app(tab_id)
        if record is None:
            return None

        is_system = self._is_system_app(record.app_id)
        app_record = None if is_system else self._app_registry.get_app(record.app_id)

        params = self._get_params_dict(record.params)
        new_interface = self._generate_interface(
            record.app_id, params, tab_label=record.tab_label, app_record=app_record,
            tab_id=tab_id, is_persistent=record.is_persistent,
        )
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        self._svc.execute(
            "UPDATE agent_open_apps SET interface_text = ?, updated_at = ? WHERE id = ?",
            (new_interface, now, tab_id),
        )

        return new_interface

    def refresh_interfaces(self, agent_id: str) -> None:
        for rec in self.list_open_apps(agent_id):
            self.refresh_interface(rec.id)

    def get_agent_context(
        self,
        agent_id: str,
        past_actions_svc: Optional[PastActionsService] = None,
        max_past_actions: int = 15,
    ) -> str:
        self.ensure_persistent_tabs(agent_id)
        self.refresh_interfaces(agent_id)
        records = self.list_open_apps(agent_id)

        if not records and past_actions_svc is None:
            return ""

        sections: list[str] = []
        tab_num = 1

        if past_actions_svc is not None:
            past_interface = past_actions_svc.generate_tab_interface(
                agent_id, max_past_actions,
            )
            if past_interface:
                sections.append(f"[tab {tab_num}] {past_interface}")
                tab_num += 1

        for rec in records:
            if rec.interface_text:
                if sections:
                    sections.append("")
                text = rec.interface_text
                idx = text.find('\n')
                if idx == -1:
                    text = f"[tab {tab_num}] {text}"
                else:
                    text = f"[tab {tab_num}] {text[:idx]}{text[idx:]}"
                sections.append(text)
                tab_num += 1

        return "\n".join(sections)

    def _row_to_record(self, row) -> AgentOpenAppRecord:
        return AgentOpenAppRecord(
            id=str(row["id"]),
            agent_id=row["agent_id"],
            app_id=row["app_id"],
            tab_label=row["tab_label"],
            params=row["params"],
            interface_text=row["interface_text"],
            is_persistent=bool(row["is_persistent"]),
            opened_at=row["opened_at"],
            updated_at=row["updated_at"],
        )
