from __future__ import annotations

import datetime
import importlib.util
import json
import logging
import random
import string
from pathlib import Path
from typing import Optional

from secure_db_service import SecureDbService

from .models import AppManifest, AppParameter, AppRecord, AgentAppRecord

logger = logging.getLogger(__name__)


def validate_icon(icon: str) -> bool:
    if not icon:
        return False
    if icon.strip() != icon:
        return False
    return 1 <= len(icon) <= 2


def generate_app_id() -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))


def _manifest_from_module(module) -> AppManifest:
    raw = module.MANIFEST
    if isinstance(raw, dict):
        raw = AppManifest(
            app_id=raw.get("app_id", raw.get("name", "")),
            name=raw.get("name", raw.get("app_id", "")),
            description=raw.get("description", ""),
            version=raw.get("version", "1.0.0"),
            author=raw.get("author", "system"),
            icon=raw.get("icon", "extension"),
            parameters=[AppParameter(**p) if isinstance(p, dict) else p for p in raw.get("parameters", [])],
            outputs=[AppParameter(**o) if isinstance(o, dict) else o for o in raw.get("outputs", [])],
            requires_confirmation=raw.get("requires_confirmation", False),
            timeout_seconds=raw.get("timeout_seconds", 30),
        )
    return raw


def _manifest_to_json(manifest: AppManifest) -> str:
    return json.dumps({
        "app_id": manifest.app_id,
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "author": manifest.author,
        "icon": manifest.icon,
        "parameters": [vars(p) for p in manifest.parameters],
        "outputs": [vars(o) for o in manifest.outputs],
        "requires_confirmation": manifest.requires_confirmation,
        "timeout_seconds": manifest.timeout_seconds,
    })


class AppRegistry:
    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS apps (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id                TEXT NOT NULL UNIQUE,
                name                  TEXT NOT NULL,
                description           TEXT DEFAULT '',
                version               TEXT DEFAULT '1.0.0',
                author                TEXT DEFAULT 'system',
                type                  TEXT DEFAULT 'builtin',
                icon                  TEXT DEFAULT '◆',
                manifest              TEXT,
                directory             TEXT,
                is_available          INTEGER DEFAULT 1,
                requires_confirmation INTEGER DEFAULT 0,
                timeout_seconds       INTEGER DEFAULT 30,
                created_at            TEXT DEFAULT (datetime('now')),
                updated_at            TEXT DEFAULT (datetime('now'))
            );
        """)

    def _ensure_unique_app_id(self) -> str:
        for _ in range(100):
            aid = generate_app_id()
            existing = self._svc.query_one(
                "SELECT id FROM apps WHERE app_id = ?", (aid,)
            )
            if not existing:
                return aid
        raise RuntimeError("Failed to generate unique app ID")

    def register_app(self, manifest: AppManifest, directory: Optional[str] = None) -> AppRecord:
        if manifest.icon and not validate_icon(manifest.icon):
            raise ValueError(f"Invalid icon '{manifest.icon}': must be 1-2 unicode code points")
        app_id = manifest.app_id or self._ensure_unique_app_id()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        manifest_json = _manifest_to_json(manifest)
        self._svc.execute(
            """INSERT INTO apps
                (app_id, name, description, version, author, type, icon,
                 manifest, directory, is_available, requires_confirmation,
                 timeout_seconds, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                app_id, manifest.name, manifest.description, manifest.version,
                manifest.author, manifest.type if hasattr(manifest, 'type') and manifest.type else 'builtin',
                manifest.icon, manifest_json, directory,
                1, manifest.requires_confirmation, manifest.timeout_seconds,
                now, now,
            ),
        )
        row = self._svc.query_one("SELECT * FROM apps WHERE app_id = ?", (app_id,))
        return self._row_to_record(row)

    def unregister_app(self, app_id: str) -> bool:
        existing = self.get_app(app_id)
        if existing is None:
            return False
        self._svc.execute("DELETE FROM apps WHERE app_id = ?", (app_id,))
        return True

    def get_app(self, app_id: str) -> Optional[AppRecord]:
        row = self._svc.query_one(
            "SELECT * FROM apps WHERE app_id = ?", (app_id,)
        )
        if row is None:
            return None
        return self._row_to_record(row)

    def list_apps(self) -> list[AppRecord]:
        rows = self._svc.query("SELECT * FROM apps ORDER BY name")
        return [self._row_to_record(r) for r in rows]

    def list_available_apps(self) -> list[AppRecord]:
        rows = self._svc.query(
            "SELECT * FROM apps WHERE is_available = 1 ORDER BY name"
        )
        return [self._row_to_record(r) for r in rows]

    def update_app(
        self,
        app_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        icon: Optional[str] = None,
        is_available: Optional[bool] = None,
        manifest: Optional[str] = None,
        requires_confirmation: Optional[bool] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Optional[AppRecord]:
        existing = self.get_app(app_id)
        if existing is None:
            return None
        if icon is not None and not validate_icon(icon):
            raise ValueError(f"Invalid icon '{icon}': must be 1-2 unicode code points")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            """UPDATE apps SET
                name = COALESCE(?, name),
                description = COALESCE(?, description),
                version = COALESCE(?, version),
                icon = COALESCE(?, icon),
                is_available = COALESCE(?, is_available),
                manifest = COALESCE(?, manifest),
                requires_confirmation = COALESCE(?, requires_confirmation),
                timeout_seconds = COALESCE(?, timeout_seconds),
                updated_at = ?
             WHERE app_id = ?""",
            (name, description, version, icon,
             int(is_available) if is_available is not None else None,
             manifest,
             int(requires_confirmation) if requires_confirmation is not None else None,
             timeout_seconds, now, app_id),
        )
        return self.get_app(app_id)

    def scan_apps_directory(self, apps_dir: str) -> list[AppRecord]:
        registered: list[AppRecord] = []
        apps_path = Path(apps_dir)
        if not apps_path.is_dir():
            return registered

        for entry in sorted(apps_path.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "manifest.py"
            if not manifest_path.exists():
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"{entry.name}.manifest", str(manifest_path)
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if not hasattr(module, "MANIFEST"):
                    continue
                manifest = _manifest_from_module(module)
                manifest.type = "builtin"
                existing = self.get_app(manifest.app_id)
                if existing is not None:
                    self.update_app(
                        app_id=existing.app_id,
                        name=manifest.name,
                        description=manifest.description,
                        version=manifest.version,
                        icon=manifest.icon,
                        is_available=True,
                        manifest=_manifest_to_json(manifest),
                        requires_confirmation=manifest.requires_confirmation,
                        timeout_seconds=manifest.timeout_seconds,
                    )
                    registered.append(existing)
                else:
                    record = self.register_app(manifest, directory=str(entry))
                    registered.append(record)
            except Exception:
                logger.error("Failed to load app from %s", entry, exc_info=True)
                continue

        return registered

    def _manifest_to_record(self, manifest: AppManifest, directory: Optional[str] = None) -> AppRecord:
        return AppRecord(
            app_id=manifest.app_id,
            name=manifest.name,
            description=manifest.description,
            version=manifest.version,
            author=manifest.author,
            type="builtin",
            icon=manifest.icon,
            manifest=json.dumps({
                "app_id": manifest.app_id,
                "name": manifest.name,
                "description": manifest.description,
                "version": manifest.version,
                "author": manifest.author,
                "icon": manifest.icon,
                "parameters": [vars(p) for p in manifest.parameters],
                "outputs": [vars(o) for o in manifest.outputs],
                "requires_confirmation": manifest.requires_confirmation,
                "timeout_seconds": manifest.timeout_seconds,
            }),
            directory=directory,
            is_available=True,
            requires_confirmation=manifest.requires_confirmation,
            timeout_seconds=manifest.timeout_seconds,
        )

    def _row_to_record(self, row) -> AppRecord:
        return AppRecord(
            id=row["id"],
            app_id=row["app_id"],
            name=row["name"],
            description=row["description"],
            version=row["version"],
            author=row["author"],
            type=row["type"],
            icon=row["icon"],
            manifest=row["manifest"],
            directory=row["directory"],
            is_available=bool(row["is_available"]),
            requires_confirmation=bool(row["requires_confirmation"]),
            timeout_seconds=row["timeout_seconds"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class AgentAppManager:
    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS agent_apps (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id      TEXT NOT NULL,
                app_id        TEXT NOT NULL,
                is_enabled    INTEGER DEFAULT 1,
                config        TEXT,
                installed_at  TEXT DEFAULT (datetime('now')),
                updated_at    TEXT DEFAULT (datetime('now')),
                UNIQUE(agent_id, app_id)
            );
        """)

    def install_app(
        self,
        agent_id: str,
        app_id: str,
        config: Optional[str] = None,
    ) -> Optional[AgentAppRecord]:
        existing = self._svc.query_one(
            "SELECT id FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        if existing is not None:
            return None
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            """INSERT INTO agent_apps
                (agent_id, app_id, is_enabled, config, installed_at, updated_at)
             VALUES (?, ?, 1, ?, ?, ?)""",
            (agent_id, app_id, config, now, now),
        )
        row = self._svc.query_one(
            "SELECT * FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        return self._row_to_record(row)

    def uninstall_app(self, agent_id: str, app_id: str) -> bool:
        existing = self._svc.query_one(
            "SELECT id FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        if existing is None:
            return False
        self._svc.execute(
            "DELETE FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        return True

    def enable_app(self, agent_id: str, app_id: str) -> Optional[AgentAppRecord]:
        existing = self._svc.query_one(
            "SELECT id FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        if existing is None:
            return None
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            "UPDATE agent_apps SET is_enabled = 1, updated_at = ? WHERE agent_id = ? AND app_id = ?",
            (now, agent_id, app_id),
        )
        return self.get_agent_app(agent_id, app_id)

    def disable_app(self, agent_id: str, app_id: str) -> Optional[AgentAppRecord]:
        existing = self._svc.query_one(
            "SELECT id FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        if existing is None:
            return None
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            "UPDATE agent_apps SET is_enabled = 0, updated_at = ? WHERE agent_id = ? AND app_id = ?",
            (now, agent_id, app_id),
        )
        return self.get_agent_app(agent_id, app_id)

    def get_agent_app(self, agent_id: str, app_id: str) -> Optional[AgentAppRecord]:
        row = self._svc.query_one(
            "SELECT * FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        if row is None:
            return None
        return self._row_to_record(row)

    def list_agent_apps(self, agent_id: str) -> list[AgentAppRecord]:
        rows = self._svc.query(
            "SELECT * FROM agent_apps WHERE agent_id = ? ORDER BY app_id",
            (agent_id,),
        )
        return [self._row_to_record(r) for r in rows]

    def list_enabled_agent_apps(self, agent_id: str) -> list[AgentAppRecord]:
        rows = self._svc.query(
            "SELECT * FROM agent_apps WHERE agent_id = ? AND is_enabled = 1 ORDER BY app_id",
            (agent_id,),
        )
        return [self._row_to_record(r) for r in rows]

    def set_app_config(self, agent_id: str, app_id: str, config: str) -> Optional[AgentAppRecord]:
        existing = self._svc.query_one(
            "SELECT id FROM agent_apps WHERE agent_id = ? AND app_id = ?",
            (agent_id, app_id),
        )
        if existing is None:
            return None
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            "UPDATE agent_apps SET config = ?, updated_at = ? WHERE agent_id = ? AND app_id = ?",
            (config, now, agent_id, app_id),
        )
        return self.get_agent_app(agent_id, app_id)

    def uninstall_all_for_agent(self, agent_id: str) -> int:
        self._svc.execute(
            "DELETE FROM agent_apps WHERE agent_id = ?",
            (agent_id,),
        )
        return self._svc.changes if hasattr(self._svc, 'changes') else 0

    def _row_to_record(self, row) -> AgentAppRecord:
        return AgentAppRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            app_id=row["app_id"],
            is_enabled=bool(row["is_enabled"]),
            config=row["config"],
            installed_at=row["installed_at"],
            updated_at=row["updated_at"],
        )
