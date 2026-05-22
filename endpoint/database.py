from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from log_service import LogService
from secure_db_service import SecureDbService

from .models import ProviderRecord


DB_DIR = Path("data")
DB_NAME = "cognithor.db"
DB_PATH = DB_DIR / DB_NAME


DEFAULT_PROVIDERS: list[ProviderRecord] = [
    ProviderRecord(
        name="openai",
        base_url="https://api.openai.com/v1",
        endpoint_path="/chat/completions",
        default_model="gpt-4o",
        models={"low": "gpt-4o-mini", "high": "gpt-4o", "image": "gpt-4o", "embedding": "text-embedding-3-small"},
        headers_template={},
        auth_type="bearer",
        body_template='{"model": "${model}", "messages": ${messages_json}, "temperature": ${temperature}, "max_tokens": ${max_tokens}}',
        response_content_path="choices.0.message.content",
        response_usage_input_path="usage.prompt_tokens",
        response_usage_output_path="usage.completion_tokens",
        is_active=True,
    ),
    ProviderRecord(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        endpoint_path="/chat/completions",
        default_model="anthropic/claude-3.5-sonnet",
        models={"low": "openai/gpt-4o-mini", "high": "anthropic/claude-3.5-sonnet", "image": "openai/gpt-4o"},
        headers_template={"HTTP-Referer": "https://github.com/tomi/cognithor"},
        auth_type="bearer",
        body_template='{"model": "${model}", "messages": ${messages_json}, "temperature": ${temperature}, "max_tokens": ${max_tokens}}',
        response_content_path="choices.0.message.content",
        response_usage_input_path="usage.prompt_tokens",
        response_usage_output_path="usage.completion_tokens",
    ),
    ProviderRecord(
        name="ollama",
        base_url="http://localhost:11434",
        endpoint_path="/api/chat",
        default_model="llama3",
        models={"low": "llama3", "high": "llama3", "image": "llava"},
        headers_template={},
        auth_type="none",
        body_template='{"model": "${model}", "messages": ${messages_json}, "options": {"temperature": ${temperature}, "num_predict": ${max_tokens}}}',
        response_content_path="message.content",
        response_usage_input_path="",
        response_usage_output_path="eval_count",
        is_streaming=True,
    ),
    ProviderRecord(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        endpoint_path="/messages",
        default_model="claude-sonnet-4-20250514",
        models={"low": "claude-haiku-3-5-20241022", "high": "claude-sonnet-4-20250514", "image": "claude-sonnet-4-20250514"},
        headers_template={"anthropic-version": "2023-06-01"},
        auth_type="header",
        auth_header_name="x-api-key",
        body_template='{"model": "${model}", "messages": ${messages_json}, "temperature": ${temperature}, "max_tokens": ${max_tokens}, "system": "${system_prompt}"}',
        response_content_path="content.0.text",
        response_usage_input_path="usage.input_tokens",
        response_usage_output_path="usage.output_tokens",
    ),
]


class Tracker:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        use_encryption: bool = False,
        service_name: str = "Cognithor",
        key_name: str = "db_key",
        key_env_var: Optional[str] = None,
        log_service: Optional[LogService] = None,
    ):
        self.log = log_service or LogService()
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
            CREATE TABLE IF NOT EXISTS providers (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                name                    TEXT NOT NULL UNIQUE,
                api_key                 TEXT,
                base_url                TEXT NOT NULL,
                endpoint_path           TEXT DEFAULT '/chat/completions',
                default_model           TEXT,
                models                  TEXT,
                headers_template        TEXT DEFAULT '{}',
                auth_type               TEXT DEFAULT 'bearer',
                auth_header_name        TEXT,
                body_template           TEXT NOT NULL,
                response_content_path   TEXT DEFAULT 'choices.0.message.content',
                response_usage_input_path  TEXT DEFAULT 'usage.prompt_tokens',
                response_usage_output_path TEXT DEFAULT 'usage.completion_tokens',
                response_usage_cost_path   TEXT,
                is_streaming            INTEGER DEFAULT 0,
                is_active               INTEGER DEFAULT 0,
                max_retries             INTEGER DEFAULT 3,
                timeout_seconds         INTEGER DEFAULT 60,
                max_concurrent          INTEGER DEFAULT 5,
                created_at              TEXT DEFAULT (datetime('now')),
                updated_at              TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS usage_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                provider        TEXT NOT NULL,
                model           TEXT NOT NULL,
                input_tokens    INTEGER DEFAULT 0,
                output_tokens   INTEGER DEFAULT 0,
                cost            REAL DEFAULT 0.0,
                duration_ms     REAL,
                status          TEXT DEFAULT 'completed',
                context         TEXT,
                timestamp       TEXT DEFAULT (datetime('now')),
                metadata        TEXT
            );

            CREATE TABLE IF NOT EXISTS health_checks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                provider    TEXT NOT NULL,
                available   INTEGER NOT NULL,
                latency_ms  REAL,
                error       TEXT,
                checked_at  TEXT DEFAULT (datetime('now'))
            );
        """)

        for rec in DEFAULT_PROVIDERS:
            existing = self._svc.query_one(
                "SELECT id FROM providers WHERE name = ?", (rec.name,)
            )
            if existing:
                continue
            self._insert_provider(rec)
            self.log.notify(
                f"Seeded default provider: {rec.name}",
                folder="endpoint/database", file=__file__,
            )

    def _insert_provider(self, rec: ProviderRecord) -> None:
        self._svc.execute(
            """INSERT INTO providers
                (name, api_key, base_url, endpoint_path, default_model, models,
                 headers_template, auth_type, auth_header_name, body_template,
                 response_content_path, response_usage_input_path,
                 response_usage_output_path, response_usage_cost_path,
                 is_streaming, is_active, max_retries, timeout_seconds, max_concurrent)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.name, rec.api_key, rec.base_url, rec.endpoint_path,
                rec.default_model, json.dumps(rec.models),
                json.dumps(rec.headers_template), rec.auth_type,
                rec.auth_header_name, rec.body_template,
                rec.response_content_path, rec.response_usage_input_path,
                rec.response_usage_output_path, rec.response_usage_cost_path,
                int(rec.is_streaming), int(rec.is_active),
                rec.max_retries, rec.timeout_seconds, rec.max_concurrent,
            ),
        )

    def get_provider(self, name: str) -> Optional[ProviderRecord]:
        row = self._svc.query_one(
            "SELECT * FROM providers WHERE name = ?", (name,)
        )
        if row is None:
            return None
        return self._row_to_record(row)

    def get_active_provider(self) -> Optional[ProviderRecord]:
        row = self._svc.query_one(
            "SELECT * FROM providers WHERE is_active = 1 LIMIT 1"
        )
        if row is None:
            return None
        return self._row_to_record(row)

    def list_providers(self) -> list[ProviderRecord]:
        rows = self._svc.query("SELECT * FROM providers ORDER BY name")
        return [self._row_to_record(r) for r in rows]

    def save_provider(self, rec: ProviderRecord) -> ProviderRecord:
        existing = self._svc.query_one(
            "SELECT id FROM providers WHERE name = ?", (rec.name,)
        )
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if existing:
            self._svc.execute(
                """UPDATE providers SET
                    api_key = COALESCE(?, api_key),
                    base_url = COALESCE(?, base_url),
                    endpoint_path = COALESCE(?, endpoint_path),
                    default_model = COALESCE(?, default_model),
                    models = COALESCE(?, models),
                    headers_template = COALESCE(?, headers_template),
                    auth_type = COALESCE(?, auth_type),
                    auth_header_name = COALESCE(?, auth_header_name),
                    body_template = COALESCE(?, body_template),
                    response_content_path = COALESCE(?, response_content_path),
                    response_usage_input_path = COALESCE(?, response_usage_input_path),
                    response_usage_output_path = COALESCE(?, response_usage_output_path),
                    response_usage_cost_path = COALESCE(?, response_usage_cost_path),
                    is_streaming = ?,
                    is_active = ?,
                    max_retries = ?,
                    timeout_seconds = ?,
                    max_concurrent = ?,
                    updated_at = ?
                WHERE name = ?""",
                (
                    rec.api_key, rec.base_url, rec.endpoint_path,
                    rec.default_model, json.dumps(rec.models),
                    json.dumps(rec.headers_template), rec.auth_type,
                    rec.auth_header_name, rec.body_template,
                    rec.response_content_path, rec.response_usage_input_path,
                    rec.response_usage_output_path, rec.response_usage_cost_path,
                    int(rec.is_streaming), int(rec.is_active),
                    rec.max_retries, rec.timeout_seconds, rec.max_concurrent,
                    now, rec.name,
                ),
            )
            rec.id = existing["id"]
        else:
            self._insert_provider(rec)
            row = self._svc.query_one(
                "SELECT id FROM providers WHERE name = ?", (rec.name,)
            )
            rec.id = row["id"] if row else None

        return rec

    def set_active(self, name: str) -> None:
        self._svc.execute("UPDATE providers SET is_active = 0")
        self._svc.execute(
            "UPDATE providers SET is_active = 1 WHERE name = ?", (name,)
        )

    def _row_to_record(self, row) -> ProviderRecord:
        def _j(val):
            if val is None:
                return {}
            return json.loads(val) if isinstance(val, str) and val.strip() else {}
        return ProviderRecord(
            id=row["id"],
            name=row["name"],
            api_key=row["api_key"],
            base_url=row["base_url"],
            endpoint_path=row["endpoint_path"],
            default_model=row["default_model"],
            models=_j(row["models"]),
            headers_template=_j(row["headers_template"]),
            auth_type=row["auth_type"],
            auth_header_name=row["auth_header_name"],
            body_template=row["body_template"],
            response_content_path=row["response_content_path"],
            response_usage_input_path=row["response_usage_input_path"],
            response_usage_output_path=row["response_usage_output_path"],
            response_usage_cost_path=row["response_usage_cost_path"],
            is_streaming=bool(row["is_streaming"]),
            is_active=bool(row["is_active"]),
            max_retries=row["max_retries"],
            timeout_seconds=row["timeout_seconds"],
            max_concurrent=row["max_concurrent"],
        )

    def record_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        duration_ms: Optional[float] = None,
        status: str = "completed",
        context: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        if status == "failed":
            self.log.error(
                f"Usage failure provider={provider} model={model} context={context}",
                folder="endpoint/database", file=__file__,
            )
        return self._svc.insert(
            """INSERT INTO usage_log
               (provider, model, input_tokens, output_tokens, cost, duration_ms, status, context, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, model, input_tokens, output_tokens, cost, duration_ms, status, context,
             json.dumps(metadata) if metadata else None),
        )

    def record_health(
        self,
        provider: str,
        available: bool,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        self._svc.execute(
            "INSERT INTO health_checks (provider, available, latency_ms, error) VALUES (?, ?, ?, ?)",
            (provider, int(available), latency_ms, error),
        )
        if not available:
            self.log.warning(
                f"Health check unavailable provider={provider} error={error}",
                folder="endpoint/database", file=__file__,
            )

    def get_total_cost(self, provider: Optional[str] = None) -> float:
        if provider:
            row = self._svc.query_one(
                "SELECT COALESCE(SUM(cost), 0) FROM usage_log WHERE provider = ?",
                (provider,),
            )
        else:
            row = self._svc.query_one(
                "SELECT COALESCE(SUM(cost), 0) FROM usage_log"
            )
        return row[0] if row else 0.0

    def get_recent_usage(self, limit: int = 20):
        return self._svc.query(
            "SELECT * FROM usage_log ORDER BY id DESC LIMIT ?", (limit,)
        )

    def get_health_history(self, provider: Optional[str] = None, limit: int = 10):
        if provider:
            return self._svc.query(
                "SELECT * FROM health_checks WHERE provider = ? ORDER BY id DESC LIMIT ?",
                (provider, limit),
            )
        return self._svc.query(
            "SELECT * FROM health_checks ORDER BY id DESC LIMIT ?", (limit,)
        )

    def backup(self, target_path: str | Path) -> None:
        self._svc.backup(target_path)

    def vacuum(self) -> None:
        self._svc.vacuum()
