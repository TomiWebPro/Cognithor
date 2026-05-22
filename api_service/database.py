from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

import bcrypt
from secure_db_service import SecureDbService


DB_DIR = Path("data")
DB_NAME = "cognithor.db"
DB_PATH = DB_DIR / DB_NAME

DEFAULT_CONFIG: dict[str, Optional[str]] = {
    "api_host": "0.0.0.0",
    "api_port": "4464",
    "secret_key": None,
    "algorithm": "HS256",
    "access_token_expire_minutes": "60",
    "app_name": "Cognithor",
    "app_version": "0.1.0",
    "encryption_key": None,
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


class ApiConfigManager:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        use_encryption: bool = False,
        service_name: str = "Cognithor",
        key_name: str = "api_config_key",
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
        self._init_tables()
        self._seed_defaults()

    def _init_tables(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS api_config (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                key   TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                created_at      TEXT DEFAULT (datetime('now'))
            );
        """)

    def _seed_defaults(self) -> None:
        for key, default_value in DEFAULT_CONFIG.items():
            existing = self._svc.query_one(
                "SELECT value FROM api_config WHERE key = ?", (key,)
            )
            if existing is not None:
                continue
            if default_value is None:
                value = secrets.token_hex(32)
            else:
                value = default_value
            self._svc.execute(
                "INSERT INTO api_config (key, value) VALUES (?, ?)",
                (key, value),
            )

        admin = self._svc.query_one(
            "SELECT id FROM api_users WHERE username = ?", ("admin",)
        )
        if admin is None:
            self.create_user("admin", "admin")

    def get_config(self, key: str) -> Optional[str]:
        row = self._svc.query_one(
            "SELECT value FROM api_config WHERE key = ?", (key,)
        )
        return row["value"] if row else None

    def set_config(self, key: str, value: str) -> None:
        self._svc.execute(
            "INSERT OR REPLACE INTO api_config (key, value) VALUES (?, ?)",
            (key, value),
        )

    def get_all_config(self) -> dict[str, str]:
        rows = self._svc.query("SELECT key, value FROM api_config")
        return {r["key"]: r["value"] for r in rows}

    def create_user(self, username: str, password: str) -> bool:
        try:
            hashed = hash_password(password)
            self._svc.execute(
                "INSERT INTO api_users (username, hashed_password) VALUES (?, ?)",
                (username, hashed),
            )
            return True
        except Exception:
            return False

    def verify_user(self, username: str, password: str) -> bool:
        row = self._svc.query_one(
            "SELECT hashed_password FROM api_users WHERE username = ?",
            (username,),
        )
        if row is None:
            return False
        return verify_password(password, row["hashed_password"])

    def user_exists(self, username: str) -> bool:
        row = self._svc.query_one(
            "SELECT id FROM api_users WHERE username = ?", (username,)
        )
        return row is not None
