from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Callable, Optional

ProgressCallback = Callable[[int, int], None]

from log_service import LogService
from log_service.database import LogDatabase
from secure_db_service import SecureDbService

from .models import ProviderRecord


DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_NAME = "cognithor.db"
DB_PATH = DB_DIR / DB_NAME


DEFAULT_PROVIDERS: list[ProviderRecord] = [
    ProviderRecord(
        name="openai",
        base_url="https://api.openai.com/v1",
        endpoint_path="/chat/completions",
        models={"gpt-4o": "gpt-4o", "gpt-4o-mini": "gpt-4o-mini", "text-embedding-3-small": "text-embedding-3-small"},
        headers_template={},
        auth_type="bearer",
        body_template='{"model": "${model}", "messages": ${messages_json}, "temperature": ${temperature}, "max_tokens": ${max_tokens}}',
        response_content_path="choices.0.message.content",
        response_usage_input_path="usage.prompt_tokens",
        response_usage_output_path="usage.completion_tokens",
    ),
    ProviderRecord(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        endpoint_path="/chat/completions",
        models={"openai/gpt-4o-mini": "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet": "anthropic/claude-3.5-sonnet", "openai/gpt-4o": "openai/gpt-4o"},
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
        models={"llama3": "llama3", "llava": "llava"},
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
        models={"claude-haiku-3-5-20241022": "claude-haiku-3-5-20241022", "claude-sonnet-4-20250514": "claude-sonnet-4-20250514"},
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
        use_encryption: bool = True,
        service_name: str = "Cognithor",
        key_name: str = "db_key",
        key_env_var: Optional[str] = None,
        log_service: Optional[LogService] = None,
        svc: Optional[SecureDbService] = None,
    ):
        self.db_path = db_path or DB_PATH
        self._svc = svc or SecureDbService(
            db_path=self.db_path,
            use_encryption=use_encryption,
            wal_mode=True,
            retry_attempts=5,
            retry_delay_seconds=0.1,
            service_name=service_name,
            key_name=key_name,
            key_env_var=key_env_var,
        )

        if log_service is not None:
            self.log = log_service
        elif svc is not None:
            self.log = LogService(
                database=LogDatabase(
                    use_encryption=self._svc.use_encryption,
                    key_name=key_name,
                ),
            )
        else:
            self.log = LogService(
                database=LogDatabase(
                    use_encryption=use_encryption,
                    key_name=key_name,
                ),
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
                models                  TEXT,
                active_models           TEXT DEFAULT '{}',
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

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
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

        self._migrate_db()

    def _migrate_db(self) -> None:
        row = self._svc.query_one("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        version = row["version"] if row else 0

        if version < 1:
            rows = self._svc.query("SELECT id, models FROM providers WHERE models IS NOT NULL")
            for r in rows:
                try:
                    parsed = json.loads(r["models"])
                    if isinstance(parsed, list):
                        migrated = {m: m for m in parsed}
                        self._svc.execute(
                            "UPDATE providers SET models = ? WHERE id = ?",
                            (json.dumps(migrated), r["id"]),
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

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

            self._svc.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (1)")

    def _insert_provider(self, rec: ProviderRecord) -> None:
        self._svc.execute(
            """INSERT INTO providers
                (name, api_key, base_url, endpoint_path, models, active_models,
                 headers_template, auth_type, auth_header_name, body_template,
                 response_content_path, response_usage_input_path,
                 response_usage_output_path, response_usage_cost_path,
                 is_streaming, is_active, max_retries, timeout_seconds, max_concurrent)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.name, rec.api_key, rec.base_url, rec.endpoint_path,
                json.dumps(rec.models), json.dumps(rec.active_models),
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
        rows = list(self._svc.query("SELECT * FROM providers ORDER BY name"))
        for row in rows:
            rec = self._row_to_record(row)
            if any(rec.active_models.values()):
                return rec
        for row in rows:
            rec = self._row_to_record(row)
            if rec.is_active:
                return rec
        return None

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
                    models = COALESCE(?, models),
                    active_models = COALESCE(?, active_models),
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
                    json.dumps(rec.models), json.dumps(rec.active_models),
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

    def _row_to_record(self, row) -> ProviderRecord:
        def _j(val):
            if val is None:
                return {}
            return json.loads(val) if isinstance(val, str) and val.strip() else {}
        def _jd(val):
            if val is None:
                return {}
            if isinstance(val, str) and val.strip():
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return {m: m for m in parsed}
                if isinstance(parsed, dict):
                    return {str(k): str(v) for k, v in parsed.items()}
            return {}
        def _jb(val):
            if val is None:
                return {}
            if isinstance(val, str) and val.strip():
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict):
                        return {str(k): bool(v) for k, v in parsed.items()}
                except (json.JSONDecodeError, TypeError):
                    pass
            return {}
        try:
            _active = _jb(row["active_models"])
        except (KeyError, IndexError):
            _active = {}
        return ProviderRecord(
            id=row["id"],
            name=row["name"],
            api_key=row["api_key"],
            base_url=row["base_url"],
            endpoint_path=row["endpoint_path"],
            models=_jd(row["models"]),
            active_models=_active,
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

    def toggle_encryption(
        self,
        enable: bool,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> bool:
        return self._svc.toggle_encryption(enable, progress_callback)

    def backup(self, target_path: str | Path) -> None:
        self._svc.backup(target_path)

    def vacuum(self) -> None:
        self._svc.vacuum()
