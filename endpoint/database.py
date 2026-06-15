from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Callable, Optional

ProgressCallback = Callable[[int, int], None]

from log_service import LogService
from log_service.database import LogDatabase
from secure_db_service import SecureDbService

from secure_db_service.cache import TtlCache

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
        provider_cache_ttl: float = 30.0,
    ):
        self.db_path = db_path or DB_PATH
        self._cache = TtlCache(ttl_seconds=provider_cache_ttl)
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
                metadata        TEXT,
                agent_id        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_usage_log_agent ON usage_log(agent_id);
            CREATE INDEX IF NOT EXISTS idx_usage_log_timestamp ON usage_log(timestamp);

            CREATE TABLE IF NOT EXISTS health_checks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                provider    TEXT NOT NULL,
                available   INTEGER NOT NULL,
                latency_ms  REAL,
                error       TEXT,
                checked_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id            TEXT NOT NULL,
                agent_name          TEXT,
                model               TEXT,
                provider            TEXT,
                input_tokens        INTEGER DEFAULT 0,
                output_tokens       INTEGER DEFAULT 0,
                cost                REAL DEFAULT 0.0,
                total_duration_ms   REAL,
                llm_duration_ms     REAL,
                harness_duration_ms REAL,
                wait_requested_ms   REAL,
                status              TEXT DEFAULT 'completed',
                error               TEXT,
                started_at          TEXT,
                completed_at        TEXT
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

        if version < 2:
            try:
                self._svc.execute("ALTER TABLE usage_log ADD COLUMN agent_id TEXT")
                self.log.notify("Added agent_id column to usage_log", folder="endpoint/database", file=__file__)
            except Exception:
                self.log.normal_operation("agent_id column already exists on usage_log", folder="endpoint/database", file=__file__)

            self._svc.execute("UPDATE usage_log SET agent_id = context WHERE agent_id IS NULL AND context IS NOT NULL AND context != ''")

            self._svc.execute_script("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id            TEXT NOT NULL,
                    agent_name          TEXT,
                    model               TEXT,
                    provider            TEXT,
                    input_tokens        INTEGER DEFAULT 0,
                    output_tokens       INTEGER DEFAULT 0,
                    cost                REAL DEFAULT 0.0,
                    total_duration_ms   REAL,
                    llm_duration_ms     REAL,
                    harness_duration_ms REAL,
                    wait_requested_ms   REAL,
                    status              TEXT DEFAULT 'completed',
                    error               TEXT,
                    started_at          TEXT,
                    completed_at        TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_id);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs(started_at);
            """)
            self.log.notify("Created agent_runs table", folder="endpoint/database", file=__file__)

            self._svc.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (2)")

    def _insert_provider(self, rec: ProviderRecord) -> int:
        cur = self._svc.execute(
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
                rec.is_streaming if rec.is_streaming is not None else 0,
                rec.is_active if rec.is_active is not None else 0,
                rec.max_retries, rec.timeout_seconds, rec.max_concurrent,
            ),
        )
        return cur.lastrowid

    def get_provider(self, name: str, use_cache: bool = True) -> Optional[ProviderRecord]:
        if use_cache:
            cached = self._cache.get(f"provider:{name}")
            if cached is not None:
                return cached
        row = self._svc.query_one(
            "SELECT * FROM providers WHERE name = ?", (name,)
        )
        if row is None:
            return None
        rec = self._row_to_record(row)
        if use_cache:
            self._cache.set(f"provider:{name}", rec)
        return rec

    def get_active_provider(self, use_cache: bool = True) -> Optional[ProviderRecord]:
        if use_cache:
            cached = self._cache.get("provider:active")
            if cached is not None:
                return cached
        row = self._svc.query_one(
            """SELECT * FROM providers WHERE active_models IS NOT NULL
               AND active_models != '' AND active_models != '{}'
               AND json_valid(active_models)
               AND (SELECT value FROM json_each(active_models) WHERE value = 1 LIMIT 1) IS NOT NULL
               ORDER BY name LIMIT 1"""
        )
        if row is not None:
            rec = self._row_to_record(row)
            if use_cache:
                self._cache.set("provider:active", rec)
            return rec
        row = self._svc.query_one(
            "SELECT * FROM providers WHERE is_active = 1 ORDER BY name LIMIT 1"
        )
        if row is not None:
            rec = self._row_to_record(row)
            if use_cache:
                self._cache.set("provider:active", rec)
            return rec
        return None

    def list_providers(self, use_cache: bool = True) -> list[ProviderRecord]:
        if use_cache:
            cached = self._cache.get("providers:all")
            if cached is not None:
                return cached
        rows = self._svc.query("SELECT * FROM providers ORDER BY name")
        result = [self._row_to_record(r) for r in rows]
        if use_cache:
            self._cache.set("providers:all", result)
        return result

    def _invalidate_provider_cache(self, name: Optional[str] = None) -> None:
        self._cache.invalidate("providers:all")
        self._cache.invalidate("provider:active")
        if name:
            self._cache.invalidate(f"provider:{name}")

    def delete_provider(self, name: str) -> bool:
        existing = self._svc.query_one(
            "SELECT id FROM providers WHERE name = ?", (name,)
        )
        if existing is None:
            return False
        self._svc.execute("DELETE FROM providers WHERE name = ?", (name,))
        self._invalidate_provider_cache(name)
        return True

    def save_provider(self, rec: ProviderRecord) -> ProviderRecord:
        self._invalidate_provider_cache(rec.name)
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
                    is_streaming = COALESCE(?, is_streaming),
                    is_active = COALESCE(?, is_active),
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
                    int(rec.is_streaming) if rec.is_streaming is not None else None,
                    int(rec.is_active) if rec.is_active is not None else None,
                    rec.max_retries, rec.timeout_seconds, rec.max_concurrent,
                    now, rec.name,
                ),
            )
            rec.id = existing["id"]
        else:
            rec.id = self._insert_provider(rec)

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
        agent_id: Optional[str] = None,
    ) -> int:
        if status == "failed":
            self.log.error(
                f"Usage failure provider={provider} model={model} context={context}",
                folder="endpoint/database", file=__file__,
            )
        return self._svc.insert(
            """INSERT INTO usage_log
               (provider, model, input_tokens, output_tokens, cost, duration_ms, status, context, metadata, agent_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, model, input_tokens, output_tokens, cost, duration_ms, status, context,
             json.dumps(metadata) if metadata else None, agent_id),
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

    def record_run(
        self,
        agent_id: str,
        agent_name: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        total_duration_ms: Optional[float] = None,
        llm_duration_ms: Optional[float] = None,
        harness_duration_ms: Optional[float] = None,
        wait_requested_ms: Optional[float] = None,
        status: str = "completed",
        error: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> int:
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        return self._svc.insert(
            """INSERT INTO agent_runs
               (agent_id, agent_name, model, provider,
                input_tokens, output_tokens, cost,
                total_duration_ms, llm_duration_ms, harness_duration_ms,
                wait_requested_ms, status, error, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, agent_name, model, provider,
             input_tokens, output_tokens, cost,
             total_duration_ms, llm_duration_ms, harness_duration_ms,
             wait_requested_ms, status, error,
             started_at or now, completed_at or now),
        )

    def get_token_usage(
        self,
        period_hours: Optional[float] = None,
        agent_id: Optional[str] = None,
    ) -> dict:
        if period_hours is not None:
            where = "WHERE timestamp >= datetime('now', ?)"
            params: list = [f'-{period_hours} hours']
        else:
            where = ""
            params = []
        if agent_id:
            where += " AND agent_id = ?" if where else "WHERE agent_id = ?"
            params.append(agent_id)
        row = self._svc.query_one(
            f"SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
            f"COALESCE(SUM(cost), 0.0), COUNT(*) FROM usage_log {where}",
            tuple(params),
        )
        return {
            "input_tokens": int(row[0]) if row else 0,
            "output_tokens": int(row[1]) if row else 0,
            "cost": float(row[2]) if row else 0.0,
            "runs": int(row[3]) if row else 0,
        }

    def get_token_usage_by_agent(
        self,
        period_hours: Optional[float] = None,
    ) -> list[dict]:
        if period_hours is not None:
            where = "WHERE timestamp >= datetime('now', ?)"
            params: list = [f'-{period_hours} hours']
        else:
            where = ""
            params = []
        rows = self._svc.query(
            f"SELECT agent_id, COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
            f"COALESCE(SUM(cost), 0.0), COUNT(*) FROM usage_log {where} "
            f"GROUP BY agent_id ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC",
            tuple(params),
        )
        return [
            {
                "agent_id": r[0] or "unknown",
                "input_tokens": int(r[1]),
                "output_tokens": int(r[2]),
                "cost": float(r[3]),
                "runs": int(r[4]),
            }
            for r in rows
        ]

    @staticmethod
    def _period_to_hours(p: str) -> Optional[float]:
        if p == "all":
            return None
        p = p.strip()
        if p.endswith("d"):
            try:
                return float(p[:-1]) * 24
            except (ValueError, AttributeError):
                return None
        elif p.endswith("h"):
            try:
                return float(p[:-1])
            except (ValueError, AttributeError):
                return None
        return None

    def get_token_usage_by_period(
        self,
        periods: list[str],
        agent_id: Optional[str] = None,
    ) -> dict:
        result = {}
        for p in periods:
            h = self._period_to_hours(p)
            result[p] = self.get_token_usage(period_hours=h, agent_id=agent_id)
        return result

    def get_token_usage_by_agent_periods(
        self,
        periods: list[str],
    ) -> dict:
        all_agents = self._svc.query(
            "SELECT DISTINCT agent_id FROM usage_log WHERE agent_id IS NOT NULL AND agent_id != ''"
        )
        if not all_agents:
            return {}
        agent_ids = [r[0] for r in all_agents]

        agent_names = {}
        if agent_ids:
            ph = ",".join("?" for _ in agent_ids)
            name_rows = self._svc.query(
                f"SELECT agent_id, agent_name FROM agent_runs "
                f"WHERE agent_id IN ({ph}) AND agent_name IS NOT NULL "
                f"GROUP BY agent_id",
                agent_ids,
            )
            for nr in name_rows:
                agent_names[nr["agent_id"]] = nr["agent_name"]

        result = {}
        for p in periods:
            h = self._period_to_hours(p)
            if h is not None:
                rows = self._svc.query(
                    f"SELECT agent_id, COALESCE(SUM(input_tokens), 0), "
                    f"COALESCE(SUM(output_tokens), 0), COALESCE(SUM(cost), 0.0), COUNT(*) "
                    f"FROM usage_log WHERE agent_id IN ({ph}) "
                    f"AND timestamp >= datetime('now', ?) "
                    f"GROUP BY agent_id",
                    [*agent_ids, f'-{h} hours'],
                )
            else:
                rows = self._svc.query(
                    f"SELECT agent_id, COALESCE(SUM(input_tokens), 0), "
                    f"COALESCE(SUM(output_tokens), 0), COALESCE(SUM(cost), 0.0), COUNT(*) "
                    f"FROM usage_log WHERE agent_id IN ({ph}) "
                    f"GROUP BY agent_id",
                    agent_ids,
                )
            by_aid = {}
            for r in rows:
                by_aid[r[0]] = {
                    "input_tokens": int(r[1]),
                    "output_tokens": int(r[2]),
                    "cost": float(r[3]),
                    "runs": int(r[4]),
                }
            for aid in agent_ids:
                if aid not in result:
                    result[aid] = {}
                result[aid][p] = by_aid.get(aid, {
                    "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "runs": 0,
                })

        for aid in agent_ids:
            result[aid]["_name"] = agent_names.get(aid, aid)
        return result

    def get_timing_stats(
        self,
        period_hours: Optional[float] = None,
        agent_id: Optional[str] = None,
    ) -> dict:
        if period_hours is not None:
            where = "WHERE started_at >= datetime('now', ?)"
            params: list = [f'-{period_hours} hours']
        else:
            where = ""
            params = []
        if agent_id:
            where += " AND agent_id = ?" if where else "WHERE agent_id = ?"
            params.append(agent_id)
        row = self._svc.query_one(
            f"SELECT COALESCE(SUM(llm_duration_ms), 0), COALESCE(SUM(harness_duration_ms), 0), "
            f"COALESCE(SUM(wait_requested_ms), 0), COALESCE(SUM(total_duration_ms), 0), COUNT(*) "
            f"FROM agent_runs {where}",
            tuple(params),
        )
        return {
            "generating_ms": float(row[0]) if row else 0.0,
            "harness_ms": float(row[1]) if row else 0.0,
            "wait_requested_ms": float(row[2]) if row else 0.0,
            "total_ms": float(row[3]) if row else 0.0,
            "runs": int(row[4]) if row else 0,
        }

    def get_timing_by_period(
        self,
        periods: list[str],
        agent_id: Optional[str] = None,
    ) -> dict:
        result = {}
        for p in periods:
            h = self._period_to_hours(p)
            result[p] = self.get_timing_stats(period_hours=h, agent_id=agent_id)
        return result

    def get_timing_by_agent_periods(
        self,
        periods: list[str],
    ) -> dict:
        all_agents = self._svc.query(
            "SELECT DISTINCT agent_id FROM agent_runs WHERE agent_id IS NOT NULL AND agent_id != ''"
        )
        if not all_agents:
            return {}
        agent_ids = [r[0] for r in all_agents]

        agent_names = {}
        if agent_ids:
            ph = ",".join("?" for _ in agent_ids)
            name_rows = self._svc.query(
                f"SELECT agent_id, agent_name FROM agent_runs "
                f"WHERE agent_id IN ({ph}) AND agent_name IS NOT NULL "
                f"GROUP BY agent_id",
                agent_ids,
            )
            for nr in name_rows:
                agent_names[nr["agent_id"]] = nr["agent_name"]

        result = {}
        for p in periods:
            h = self._period_to_hours(p)
            if h is not None:
                rows = self._svc.query(
                    f"SELECT agent_id, "
                    f"COALESCE(SUM(llm_duration_ms), 0), "
                    f"COALESCE(SUM(harness_duration_ms), 0), "
                    f"COALESCE(SUM(wait_requested_ms), 0), "
                    f"COALESCE(SUM(total_duration_ms), 0), COUNT(*) "
                    f"FROM agent_runs WHERE agent_id IN ({ph}) "
                    f"AND started_at >= datetime('now', ?) "
                    f"GROUP BY agent_id",
                    [*agent_ids, f'-{h} hours'],
                )
            else:
                rows = self._svc.query(
                    f"SELECT agent_id, "
                    f"COALESCE(SUM(llm_duration_ms), 0), "
                    f"COALESCE(SUM(harness_duration_ms), 0), "
                    f"COALESCE(SUM(wait_requested_ms), 0), "
                    f"COALESCE(SUM(total_duration_ms), 0), COUNT(*) "
                    f"FROM agent_runs WHERE agent_id IN ({ph}) "
                    f"GROUP BY agent_id",
                    agent_ids,
                )
            by_aid = {}
            for r in rows:
                by_aid[r[0]] = {
                    "generating_ms": float(r[1]),
                    "harness_ms": float(r[2]),
                    "wait_requested_ms": float(r[3]),
                    "total_ms": float(r[4]),
                    "runs": int(r[5]),
                }
            for aid in agent_ids:
                if aid not in result:
                    result[aid] = {}
                result[aid][p] = by_aid.get(aid, {
                    "generating_ms": 0.0, "harness_ms": 0.0,
                    "wait_requested_ms": 0.0, "total_ms": 0.0, "runs": 0,
                })

        for aid in agent_ids:
            result[aid]["_name"] = agent_names.get(aid, aid)
        return result

    def get_idle_breakdown(
        self,
        period_hours: Optional[float] = None,
        agent_id: Optional[str] = None,
    ) -> dict:
        if period_hours is not None:
            where = "WHERE started_at >= datetime('now', ?)"
            params: list = [f'-{period_hours} hours']
        else:
            where = ""
            params = []
        if agent_id:
            where += " AND agent_id = ?" if where else "WHERE agent_id = ?"
            params.append(agent_id)

        row = self._svc.query_one(
            f"""SELECT
               COALESCE(SUM(COALESCE(wait_requested_ms, 0)), 0),
               COALESCE(SUM(
                 CASE WHEN prev_completed IS NOT NULL AND started_at IS NOT NULL
                   THEN MAX(0, (julianday(started_at) - julianday(prev_completed)) * 86400000.0)
                   ELSE 0 END
               ), 0)
             FROM (
               SELECT started_at, completed_at, wait_requested_ms,
                 LAG(completed_at) OVER (
                   PARTITION BY agent_id ORDER BY started_at
                 ) AS prev_completed
               FROM agent_runs {where}
             ) sub""",
            tuple(params),
        )

        total_gap_ms = float(row[1]) if row else 0.0
        waiting_ms = float(row[0]) if row else 0.0
        idle_ms = max(0.0, total_gap_ms - waiting_ms)

        return {
            "idle_ms": idle_ms,
            "waiting_ms": waiting_ms,
            "total_gap_ms": total_gap_ms,
        }

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
