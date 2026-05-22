# Cognithor Onboarding

## Overview

The onboarding script (`setup.py`) initialises the three Cognithor services that
rely on local SQLite databases.  Before first use — or after a `clear` — no
database files exist and none of the services can operate.  This script creates
them, builds the schema, and seeds default data so everything is ready to run.

## Services & databases

| Service | DB file | Tables |
|---|---|---|
| `secure_db_service` | — | No tables of its own. Provides the shared `SecureDbService` wrapper (connection pooling, encryption, retry logic) used by the other two. |
| `log_service` | `data/cognithor_logs.db` | `log_entries` — structured error/warning/notify/operation log |
| `endpoint` | `data/cognithor.db` | `providers` — LLM endpoint configs (API keys, URLs, models, templates); `usage_log` — token/cost tracking; `health_checks` — availability history |

On `init` the script:

1. Creates `data/` if it doesn't exist.
2. Ensures an encryption key exists in the system keyring (`get_or_create_key`).
3. Instantiates `LogDatabase(use_encryption=…)` — creates `cognithor_logs.db`
   and the `log_entries` table.
4. Instantiates `Tracker(use_encryption=…)` — creates `cognithor.db` and the
   `providers`, `usage_log`, `health_checks` tables, then seeds four default
   providers (OpenAI, OpenRouter, Ollama, Anthropic).

## Encryption

By default databases are created with **SQLCipher encryption** via
`pysqlcipher3`.  The encryption key is resolved in this order:

1. `COGNITHOR_DB_KEY` environment variable
2. System keyring (service=`Cognithor`, key=`db_key`)
3. Hard-coded fallback (`debug_key_please_change_me`)

Pass `--no-encrypt` to create plain SQLite databases instead.

## Commands

```
python onboarding/setup.py init               # encrypted DBs (default)
python onboarding/setup.py init --no-encrypt   # plain-text DBs
python onboarding/setup.py status              # show DB files & row counts
python onboarding/setup.py clear               # delete all DB files (with confirmation)
python onboarding/setup.py clear -f            # delete without prompting
python onboarding/setup.py reset               # clear + init (needs -f to skip prompt)
python onboarding/setup.py reset -f            # atomic destroy & recreate
```

## Dev mode

`reset -f` is the dev-mode entry point.  It:

- Deletes every database file (including WAL / SHM sidecars)
- Removes the `data/` directory if empty
- Re-runs full initialisation

This gives a clean slate identical to a first-time install.

## Notes

- The script must be run from the project root (`cognithor/`) because services
  expect `data/` as a relative path.
- `httpx` must be installed for the endpoint service at runtime, but it is not
  required for onboarding itself.
- `pysqlcipher3` requires the system library `libsqlcipher`.  If it is missing,
  `SecureDbService` falls back to plain `sqlite3` and logs a warning.
