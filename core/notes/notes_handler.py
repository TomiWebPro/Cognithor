from __future__ import annotations

import datetime
import json
import logging
from typing import Optional

from secure_db_service import SecureDbService
from core.app.app_manager import AppHandler

logger = logging.getLogger(__name__)


class NotesManager:
    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS agent_notes (
                id                TEXT PRIMARY KEY,
                agent_id          TEXT NOT NULL,
                title             TEXT DEFAULT '',
                content           TEXT DEFAULT '',
                max_interactions  INTEGER DEFAULT 10,
                interaction_count INTEGER DEFAULT 0,
                created_at        TEXT DEFAULT (datetime('now')),
                updated_at        TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_agent_notes_agent
                ON agent_notes(agent_id);
        """)

    def _generate_note_id(self) -> str:
        import random
        import string
        chars = string.ascii_lowercase + string.digits
        for _ in range(100):
            nid = ''.join(random.choices(chars, k=8))
            existing = self._svc.query_one(
                "SELECT id FROM agent_notes WHERE id = ?", (nid,)
            )
            if not existing:
                return nid
        raise RuntimeError("Failed to generate unique note ID")

    def create_note(
        self,
        agent_id: str,
        title: str = "",
        content: str = "",
        max_interactions: int = 10,
    ) -> str:
        note_id = self._generate_note_id()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            """INSERT INTO agent_notes
               (id, agent_id, title, content, max_interactions, interaction_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
            (note_id, agent_id, title, content, max_interactions, now, now),
        )
        return note_id

    def get_note(self, note_id: str):
        return self._svc.query_one(
            "SELECT * FROM agent_notes WHERE id = ?", (note_id,)
        )

    def list_notes(self, agent_id: str) -> list:
        return self._svc.query(
            "SELECT * FROM agent_notes WHERE agent_id = ? ORDER BY created_at",
            (agent_id,),
        )

    def update_note(
        self, note_id: str, content: str, title: Optional[str] = None
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if title is not None:
            self._svc.execute(
                "UPDATE agent_notes SET content = ?, title = ?, updated_at = ? WHERE id = ?",
                (content, title, now, note_id),
            )
        else:
            self._svc.execute(
                "UPDATE agent_notes SET content = ?, updated_at = ? WHERE id = ?",
                (content, now, note_id),
            )

    def delete_note(self, note_id: str) -> None:
        self._svc.execute("DELETE FROM agent_notes WHERE id = ?", (note_id,))

    def extend_note(self, note_id: str, max_interactions: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            "UPDATE agent_notes SET max_interactions = ?, interaction_count = 0, updated_at = ? WHERE id = ?",
            (max_interactions, now, note_id),
        )

    def _increment_count(self, note_id: str) -> None:
        row = self.get_note(note_id)
        if row is None:
            return
        current = int(row["interaction_count"] or 0)
        self._svc.execute(
            "UPDATE agent_notes SET interaction_count = ? WHERE id = ?",
            (current + 1, note_id),
        )

    def _check_and_delete_expired(self, note_id: str) -> bool:
        row = self.get_note(note_id)
        if row is None:
            return True
        max_int = int(row["max_interactions"] or 10)
        count = int(row["interaction_count"] or 0)
        if count >= max_int:
            self._svc.execute("DELETE FROM agent_notes WHERE id = ?", (note_id,))
            return True
        return False

    def cleanup_expired(self, agent_id: str) -> list[str]:
        rows = self._svc.query(
            "SELECT id FROM agent_notes WHERE agent_id = ? AND interaction_count >= max_interactions",
            (agent_id,),
        )
        deleted = []
        for row in rows:
            nid = row["id"]
            self._svc.execute("DELETE FROM agent_notes WHERE id = ?", (nid,))
            deleted.append(nid)
        return deleted


class NotesCommandHandler(AppHandler):
    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        label = f" ({tab_label})" if tab_label else ""
        lines = [
            f"[Notes]{label}",
            "  Status: Open",
            "",
            "  Use notes to keep important context and plan your upcoming actions. Notes automatically run down from 10 interactions and are removed from context. For important notes you can reset note lifetime to a larger amount. You are suggested to not keep irrelevant notes and log long term accomplishments in diary.",
            "",
            "  Manage your notes with these commands:",
            "",
            '    {"command": "create_note", "title": "...", "content": "..."}',
            '    {"command": "edit_note", "note_id": "...", "content": "..."}',
            '    {"command": "reset_note_lifetime", "note_id": "...", "max_interactions": <number>}',
            '    {"command": "delete_note", "note_id": "..."}',
        ]
        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        return {"success": True, "type": "notes_command"}


class NoteTabHandler(AppHandler):
    def __init__(self, notes_manager: NotesManager):
        self._notes_manager = notes_manager

    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        note_id = params.get("note_id", "")
        if not note_id:
            return "[Note]\n  Status: Open\n\n  (no note specified)"

        row = self._notes_manager.get_note(note_id)
        if row is None:
            return "[Note]\n  Status: Open\n\n  (this note has been removed)"

        title = row["title"] or "untitled"
        content = row["content"] or "(empty)"
        max_int = int(row["max_interactions"] or 10)
        count = int(row["interaction_count"] or 0)
        remaining = max_int - count

        lines = [
            f"[Note: {title}]",
            "  Status: Open",
            f"  ID: {note_id}",
            "",
            f"  {content}",
            "",
            f"  \u23f3 Auto deletes in {remaining} interactions, use command to extend it if you still need this note in memory.",
            "  Closing this tab deletes the note.",
            "",
            "  Commands:",
            f'    {{"command": "edit_note", "note_id": "{note_id}", "content": "..."}}',
            f'    {{"command": "reset_note_lifetime", "note_id": "{note_id}", "max_interactions": <number>}}',
            f'    {{"command": "delete_note", "note_id": "{note_id}"}}',
        ]

        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        return {"success": True, "type": "note_tab"}
