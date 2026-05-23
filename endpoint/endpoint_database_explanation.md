# Endpoint Database Explanation

This document provides a natural language explanation of the database schema used in the Cognithor endpoint module.

The database is an optionally encrypted SQLite database (`data/cognithor.db`) managed via the `Tracker` class, which delegates all low-level access to `SecureDbService` (from the `secure_db_service` package). It is created automatically on first use. It contains three tables, each serving a specific purpose:

## 1. providers

Stores configuration for each LLM API provider. This is the core table that makes the system data-driven rather than code-driven. Adding a new provider means inserting a row, not writing a new Python class.

Columns include:

- **id**: Primary key for each provider record (integer, auto-incremented).
- **name**: Unique identifier for the provider, e.g. "openai", "openrouter", "ollama", "anthropic" (text, unique, not null).
- **api_key**: API key for authentication (text, nullable). Stored here so it can be set via environment variables or config file, rather than hardcoded.
- **base_url**: Base URL for the provider's API, e.g. "https://api.openai.com/v1" (text, not null). Swappable without modifying code.
- **endpoint_path**: The path appended to base_url for chat completions, e.g. "/chat/completions", "/api/chat", "/messages" (text, default "/chat/completions").
- **models**: JSON array of model names available for this provider, e.g. `["gpt-4o", "gpt-4o-mini", "text-embedding-3-small"]` (text, nullable).
- **headers_template**: JSON string of extra HTTP headers to send with every request, e.g. `{"HTTP-Referer": "https://github.com/tomi/cognithor"}` (text, default "{}").
- **auth_type**: Authentication method. One of "bearer" (sends `Authorization: Bearer <api_key>`), "header" (sends `<auth_header_name>: <api_key>`), or "none" (no auth) (text, default "bearer").
- **auth_header_name**: Header name used when `auth_type` is "header", e.g. "x-api-key" for Anthropic (text, nullable).
- **body_template**: JSON template string with placeholders for dynamic values (text, not null). Placeholders:
  - `${model}` — the model name
  - `${messages_json}` — pre-rendered JSON array of message objects
  - `${temperature}` — temperature as a string number
  - `${max_tokens}` — max tokens as a string number
  - `${system_prompt}` — system prompt text (only used if the template contains this placeholder; the system message is then extracted from the messages array)
- **response_content_path**: Dot-notation path to extract the response text from the API JSON response, e.g. "choices.0.message.content", "content.0.text", "message.content" (text, default "choices.0.message.content").
- **response_usage_input_path**: Dot-notation path to extract input token count from the response, e.g. "usage.prompt_tokens", "usage.input_tokens" (text, default "usage.prompt_tokens"). Leave empty if not provided.
- **response_usage_output_path**: Dot-notation path to extract output token count, e.g. "usage.completion_tokens", "usage.output_tokens", "eval_count" (text, default "usage.completion_tokens").
- **response_usage_cost_path**: Dot-notation path to extract cost directly from the API response, if the provider includes it (text, nullable).
- **is_streaming**: Boolean flag. If 1, the response is treated as newline-delimited JSON (NDJSON), and content is concatenated across lines. Used for Ollama's streaming API (integer, default 0).
- **is_active**: Boolean flag. If 1, this provider is the default active provider used when no provider is explicitly specified (integer, default 0).
- **max_retries**: Maximum number of retry attempts for failed requests (integer, default 3).
- **timeout_seconds**: Request timeout in seconds (integer, default 60).
- **max_concurrent**: Maximum number of concurrent requests allowed for this provider (integer, default 5).
- **created_at**: Timestamp when the record was created (text, default current datetime).
- **updated_at**: Timestamp when the record was last updated (text, default current datetime).

### Default providers seeded on init

On first database creation, four providers are automatically seeded:

| name | base_url | auth_type | endpoint_path | models |
|------|----------|-----------|---------------|--------|
| openai | https://api.openai.com/v1 | bearer | /chat/completions | gpt-4o, gpt-4o-mini, text-embedding-3-small |
| openrouter | https://openrouter.ai/api/v1 | bearer | /chat/completions | openai/gpt-4o-mini, anthropic/claude-3.5-sonnet, openai/gpt-4o |
| ollama | http://localhost:11434 | none | /api/chat | llama3, llava |
| anthropic | https://api.anthropic.com/v1 | header | /messages | claude-haiku-3-5-20241022, claude-sonnet-4-20250514 |

These defaults are only inserted if no provider with that name already exists, so they do not overwrite existing configurations.

### How the body template works

The `body_template` uses Python's `string.Template` syntax. Before substitution, messages are pre-processed:

1. **System prompt extraction**: If the template contains `${system_prompt}`, the first system-role message is extracted from the messages array and placed into the `system_prompt` variable. That message is then excluded from the rendered `messages_json`. This handles Anthropic's API which expects `system` as a top-level field, not inside the messages array.

2. **Standard rendering**: Otherwise, all messages are rendered as-is into `messages_json`.

Example — OpenAI template:
```
{"model": "${model}", "messages": ${messages_json}, "temperature": ${temperature}, "max_tokens": ${max_tokens}}
```

Example — Anthropic template (system prompt extracted from messages):
```
{"model": "${model}", "messages": ${messages_json}, "temperature": ${temperature}, "max_tokens": ${max_tokens}, "system": "${system_prompt}"}
```

Example — Ollama template (streaming, options nested):
```
{"model": "${model}", "messages": ${messages_json}, "options": {"temperature": ${temperature}, "num_predict": ${max_tokens}}}
```

### Response path navigation

The dot-notation path is resolved by splitting on `.` and traversing the JSON response. Array indices are specified as integers in the path:

- `choices.0.message.content` → `response["choices"][0]["message"]["content"]`
- `content.0.text` → `response["content"][0]["text"]`
- `usage.prompt_tokens` → `response["usage"]["prompt_tokens"]`

## 2. usage_log

Tracks detailed information about each LLM API call. Designed to log every interaction with language model providers, capturing tokens, costs, timing, and context.

Columns include:

- **id**: Primary key for each usage record (integer, auto-incremented).
- **provider**: Name of the provider used, e.g. "openai", "ollama", "openrouter" (text, not null).
- **model**: The specific model used for this call, e.g. "gpt-4o", "llama3" (text, not null).
- **input_tokens**: Number of input (prompt) tokens consumed (integer, default 0).
- **output_tokens**: Number of output (completion) tokens generated (integer, default 0).
- **cost**: Calculated cost for this API call in USD (real, default 0.0). This can be populated by the caller based on token counts and known pricing, or by the `response_usage_cost_path` if the API returns it directly.
- **duration_ms**: Round-trip duration of the API call in milliseconds (real, nullable).
- **status**: Processing status of the record (text, default "completed"). Possible values:
  - "completed": The API call finished successfully.
  - "failed": The API call encountered an error.
  - Custom status values can be assigned for in-progress tracking.
- **context**: Optional string identifier linking this usage to a broader context, e.g. a conversation ID, file being processed, or agent task (text, nullable).
- **timestamp**: Datetime when the usage was recorded (text, default current datetime).
- **metadata**: Optional JSON string for arbitrary additional data (text, nullable).

### Usage notes

- Each API call creates one row — there is no cumulative accumulation across rows. For cumulative cost tracking, use `get_total_cost()` which sums the `cost` column across all records.
- The `context` field is intended to group related calls together (e.g., all calls made during the processing of a single file).
- Unlike the Backend_w._DB `usage` table, this table tracks individual calls rather than conversations, keeping the schema simple and generic.

## 3. health_checks

Stores the results of periodic health/latency checks performed against configured providers. Used to determine provider availability for fallback logic.

Columns include:

- **id**: Primary key for each health check record (integer, auto-incremented).
- **provider**: Name of the provider that was checked (text, not null).
- **available**: Boolean flag. 1 if the provider responded successfully, 0 if it failed (integer, not null).
- **latency_ms**: Response time in milliseconds for the check request (real, nullable).
- **error**: Error message if the check failed, typically describing the connection issue or exception (text, nullable).
- **checked_at**: Timestamp when the check was performed (text, default current datetime).

### How health checks work

The `check_status()` method in `EndpointManager` sends a minimal chat request ("Respond with only the word: ok" with max_tokens=10) to the provider. If it succeeds, the provider is marked available with the measured latency. If it raises any exception, the provider is marked unavailable with the error message stored.

## How the tables relate

```
providers (configuration)
    │
    ├── usage_log (tracks each API call)
    │     provider → providers.name
    │
    └── health_checks (tracks availability)
          provider → providers.name
```

`usage_log` and `health_checks` reference `providers` by name. There is no formal foreign key constraint (to keep schema flexible for dynamic provider names), but the application code maintains consistency.

## SecureDbService layer

All database access goes through `SecureDbService` (from the `secure_db_service` package), which provides:

- **WAL mode**: Write-Ahead Logging enables concurrent reads while a write is in progress, preventing most "database is locked" errors.
- **Retry logic**: If a "database is locked" error occurs, the service retries up to 5 times with a 0.1 second delay between attempts.
- **Auto-commit**: Connections opened via the context manager (`with svc.connection() as conn:`) automatically commit on success and rollback on exception.
- **Optional encryption**: If `use_encryption=True` is passed, the service attempts to use `pysqlcipher3` (or `sqlcipher3`) to create an encrypted database. The encryption key is resolved in this order:
  1. An environment variable (default: `COGNITHOR_DB_KEY`).
  2. The system keyring (service: `"Cognithor"`, key: `"db_key"`) via the `keyring` library.
  3. A fallback development key (`"debug_key_please_change_me"`).

This mirrors the approach used in the `Backend_w._DB` project, where the production database uses SQLCipher with a key stored in the system keyring.

## Keyring management

The `secure_db_service.key_manager` module provides utilities for managing the encryption key:

- `get_key(service_name, key_name)`: Retrieves the key from the system keyring.
- `set_key(key, service_name, key_name)`: Stores a key in the system keyring. Returns `False` if the `keyring` library is not installed.
- `has_key(service_name, key_name)`: Checks if a key exists in the keyring.
- `get_or_create_key(service_name, key_name, length)`: Retrieves the existing key, or generates a new random key (using `secrets.token_hex(length)`) and stores it in the keyring.

If the `keyring` library is not installed, all these functions gracefully return `None` or `False` — no errors are raised.

## Database initialization

The database is created at `data/cognithor.db` relative to the project root (customizable via the `db_path` parameter). On creation:

1. All three tables are created if they do not exist.
2. WAL mode is enabled for better concurrent read performance.
3. Foreign keys pragma is enabled for data integrity.
4. The four default providers are seeded only if no provider with that name exists.

When `use_encryption=True`, the database file is created as a SQLCipher-encrypted database using the resolved encryption key.

## Backups and maintenance

The `Tracker` class exposes two database maintenance methods:

- `backup(target_path)`: Creates a point-in-time backup of the database to the specified path. Uses SQLite's built-in online backup API, so the source database can remain in use during the backup.
- `vacuum()`: Reclaims unused space and defragments the database file. Useful after many deletions or updates.

## Adding a new provider

To add a new LLM provider, insert a row into the `providers` table with the appropriate configuration values. No code changes are needed.

Example — adding Google Gemini via the `Tracker` API:

```python
from endpoint.database import Tracker
from endpoint.models import ProviderRecord

tracker = Tracker()  # or Tracker(use_encryption=True) for encrypted DB
tracker.save_provider(ProviderRecord(
    name="gemini",
    base_url="https://generativelanguage.googleapis.com/v1beta",
    endpoint_path="/models/gemini-pro:generateContent",
    models=["gemini-pro"],
    auth_type="header",
    auth_header_name="x-goog-api-key",
    body_template='{"contents": ${messages_json}, "generationConfig": {"temperature": ${temperature}, "maxOutputTokens": ${max_tokens}}}',
    response_content_path="candidates.0.content.parts.0.text",
    response_usage_input_path="",
    response_usage_output_path="",
    is_active=False,
))
```

After saving, the provider is immediately available via the `EndpointManager` for chat, fallback, and round-robin operations.
