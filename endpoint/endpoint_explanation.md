# Endpoint Module Explanation

The endpoint module provides a universal configuration layer for LLM API providers (OpenAI, OpenRouter, Ollama, Anthropic, etc.). It is designed to be data-driven: adding a new provider requires only a database insert, not new Python code.

The module is split into six files:

## File: endpoint/models.py

Defines the data structures used throughout the module.

**`Message`**: A single chat message with a `role` (e.g. "user", "assistant", "system") and `content` string. This is the input unit for all chat calls.

**`ProviderRecord`**: The central configuration object. It mirrors the `providers` database table and holds everything needed to talk to an LLM API:
- `name`: Provider identifier like "openai", "ollama"
- `base_url`, `endpoint_path`: Where to send HTTP requests
- `api_key`: Authentication credential (stored in DB, not code)
- `auth_type`: "bearer", "header", or "none"
- `body_template`: A JSON template with `${model}`, `${messages_json}`, `${temperature}`, `${max_tokens}`, `${system_prompt}` placeholders. This is what makes the system data-driven — each provider has a different template stored in the DB row.
- `response_content_path`, `response_usage_input_path`, `response_usage_output_path`: Dot-notation paths to extract the response text and token counts from the API's JSON response.
- `models`: A list of model names available for this provider.
- `is_streaming`: Whether the API returns newline-delimited JSON (Ollama).
- `max_retries`, `timeout_seconds`, `max_concurrent`: Connection settings.

**`EndpointStatus`**: Holds the result of a health check — whether a provider is reachable, its latency, and any error message.

**`UsageRecord`**: A dataclass for usage data (tokens, cost, duration) that mirrors the `usage_log` table.

## File: endpoint/database.py

Provides the `Tracker` class, which handles all database operations. It delegates low-level database access to `SecureDbService` (from the `secure_db_service` package), which provides deterministic non-blocking access with WAL mode, retry logic for locked databases, and optional keyring-backed encryption.

`Tracker` manages three tables:
- **`providers`**: Stores all provider configurations (rows are self-contained — no code changes needed to add a new provider).
- **`usage_log`**: Records every API call with token counts, cost, duration, status, and context.
- **`health_checks`**: Stores results of periodic provider availability checks.

Key methods:
- `get_provider(name)`, `get_active_provider()`, `list_providers()`, `save_provider(rec)`, `set_active(name)` — CRUD for providers.
- `record_usage(...)`, `record_health(...)` — Logging.
- `get_total_cost(provider)`, `get_recent_usage(limit)`, `get_health_history(provider, limit)` — Querying.
- `backup(target_path)`, `vacuum()` — Database maintenance.

On first initialization, `Tracker` seeds four default providers (openai, openrouter, ollama, anthropic) with pre-configured body templates, response paths, and auth settings. These are only inserted if no provider with that name already exists.

## File: endpoint/config.py

Provides `EndpointSettings`, which bootstraps provider configurations from environment variables or a JSON file into the database.

**Environment variable loading**: Reads all `COGNITHOR_*` environment variables. For example:
- `COGNITHOR_OPENAI_API_KEY=sk-...` sets the API key for the "openai" provider.
- `COGNITHOR_OLLAMA_BASE_URL=http://localhost:11434` overrides the base URL.
- `COGNITHOR_ACTIVE_PROVIDER=ollama` sets the default active provider.

**JSON file loading**: If `endpoint_config.json` exists, it parses the file and merges the settings into the database. The expected format is:
```json
{
    "active_provider": "openai",
    "endpoints": {
        "openai": {
            "api_key": "sk-...",
            "base_url": "https://api.openai.com/v1",
            "models": ["gpt-4o", "gpt-4o-mini"],
            "body_template": "{\"model\": \"${model}\", \"messages\": ${messages_json}}"
        }
    }
}
```

This approach means configuration can come from environment variables (for quick dev setup), a JSON file (for repeatable configs), or programmatically via `Tracker.save_provider()`.

## File: endpoint/providers.py

Contains the HTTP client layer for talking to LLM APIs. Unlike traditional designs that have one class per provider, this module uses a single generic `HttpProvider` class that reads all its behavior from a `ProviderRecord`.

**`UsageInfo`**: A simple data class that holds the result of a chat call — input/output token counts, cost, duration, and model name.

**`_navigate(obj, path)`**: A utility that extracts values from nested JSON using dot-notation paths. For example, `_navigate(data, "choices.0.message.content")` resolves to `data["choices"][0]["message"]["content"]`. This is how the same provider code works with OpenAI's response format (`choices.0.message.content`), Anthropic's (`content.0.text`), and Ollama's (`message.content`).

**`_prepare_messages(messages, body_template)`**: Pre-processes the message list before template substitution. If the body template contains `${system_prompt}`, the first system-role message is extracted and set aside (for Anthropic's API which puts system at the top level). Otherwise all messages are rendered as-is into `messages_json`.

**`HttpProvider`**: The single generic provider class.
- `__init__(record)`: Takes a `ProviderRecord` that defines all behavior.
- `chat(messages, model, temperature, max_tokens)`: The core method.
  1. Resolves the model name from the record or argument.
  2. Calls `_prepare_messages` to handle system prompt extraction.
  3. Substitutes placeholders into the `body_template` using Python's `string.Template`.
  4. Builds HTTP headers based on `auth_type` ("bearer" sends `Authorization: Bearer <key>`, "header" sends a custom header like `x-api-key`, "none" sends no auth).
  5. Sends the POST request via `httpx` and measures duration.
  6. If `is_streaming` is True, parses newline-delimited JSON (Ollama's format) and concatenates content across lines.
  7. If not streaming, parses the JSON response using `_navigate` to extract the response text.
  8. Extracts token counts using the configured `response_usage_input_path` and `response_usage_output_path`.
  9. Returns the response text and a `UsageInfo` object.

Because all variability is in the `ProviderRecord` (stored in the database), this single class handles OpenAI, OpenRouter, Ollama, Anthropic, and any future OpenAI-compatible API without code changes.

## File: endpoint/manager.py

Provides `EndpointManager`, the high-level interface that most application code interacts with. It ties together the database (`Tracker`), configuration (`EndpointSettings`), and HTTP clients (`HttpProvider`).

**EndpointManager**:
- `chat(messages, provider, model, temperature, max_tokens, context)`: Sends a chat request to the specified provider (or the active provider if none specified). Automatically records usage to `usage_log` after each call.
- `chat_with_fallback(messages, preferred, ...)`: Tries providers in order. If the preferred provider fails, it falls through to the next available provider. Raises an error if all fail.
- `chat_with_round_robin(messages, ...)`: Randomly selects a provider from all configured ones. Useful for load distribution.
- `check_status(name)`: Sends a minimal "ok" prompt to a provider and measures latency. Returns an `EndpointStatus` with availability, latency, and error info. Exceptions are caught gracefully.
- `check_all()`: Checks all configured providers in sequence.
- `register_provider(record)`: Saves a new provider record to the database and clears the cached HTTP client so it gets recreated on next use.

Provider instances are cached internally (in `_instances`) so that the HTTP client is created once per provider and reused across calls.

## File: endpoint/__init__.py

Exports the public API: `EndpointSettings`, `Tracker`, `EndpointManager`, `EndpointStatus`, `Message`, `ProviderRecord`, `UsageRecord`, `HttpProvider`, `UsageInfo`.

## How the Files Work Together

```
Application code
      │
      ▼
 EndpointManager (manager.py)      ← high-level chat/fallback/health API
      │
      ├── Tracker (database.py)    ← stores/loads provider configs, logs usage
      │       │
      │       └── SecureDbService  ← deterministic non-blocking DB access
      │                              (WAL mode, retry, optional encryption)
      │
      └── HttpProvider (providers.py) ← generic HTTP client driven by ProviderRecord
              │
              └── httpx → LLM API (OpenAI, Ollama, etc.)
```

An application importing this module would typically:

1. Create or reuse a `Tracker` (which auto-initializes the DB and seeds defaults).
2. Optionally run `EndpointSettings` to merge env vars or a JSON config file.
3. Create an `EndpointManager` that ties everything together.
4. Call `manager.chat([Message(role="user", content="Hello")])` to send a message to the active provider.

## Adding a New Provider

Adding a new LLM provider (e.g., Groq, Together AI, DeepSeek) requires zero code changes:

```python
from endpoint import Tracker, ProviderRecord

tracker = Tracker()
tracker.save_provider(ProviderRecord(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    endpoint_path="/chat/completions",
    models=["llama3-70b-8192", "llama3-8b-8192"],
    auth_type="bearer",
    body_template='{"model": "${model}", "messages": ${messages_json}, "temperature": ${temperature}}',
    response_content_path="choices.0.message.content",
    response_usage_input_path="usage.prompt_tokens",
    response_usage_output_path="usage.completion_tokens",
    api_key="gsk_...",
))
```

After saving, the provider is immediately available via `EndpointManager` for chat, fallback, and round-robin operations.

## Supported Environment Variables

| Variable | Effect |
|----------|--------|
| `COGNITHOR_OPENAI_API_KEY` | Sets API key for the "openai" provider |
| `COGNITHOR_OPENAI_BASE_URL` | Overrides base URL for OpenAI |
| `COGNITHOR_OPENROUTER_API_KEY` | Sets API key for OpenRouter |
| `COGNITHOR_OLLAMA_BASE_URL` | Overrides Ollama base URL |
| `COGNITHOR_ANTHROPIC_API_KEY` | Sets API key for Anthropic |
| `COGNITHOR_ACTIVE_PROVIDER` | Sets the active (default) provider by name |

Any provider can be configured this way — just match the prefix to the provider's `name` in the database.
