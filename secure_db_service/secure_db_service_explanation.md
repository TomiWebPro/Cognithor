# SecureDbService Explanation

The `secure_db_service` package provides a deterministic, non-blocking SQLite database access layer with optional keyring-backed encryption. It is designed to work with any SQLite database file and is used by the endpoint module's `Tracker` for all database operations.

The package is split into two source files:

## File: key_manager.py

Provides utilities for managing a database encryption key in the system keyring. This mirrors the approach used in the `Backend_w._DB` project, where the production database uses SQLCipher with a key stored in the keyring.

**Module-level constants**:
- `SERVICE_NAME = "Cognithor"`: The keyring service name.
- `KEY_NAME = "db_key"`: The keyring key name.
- `FALLBACK_KEY = "debug_key_please_change_me"`: Development fallback used when no key is found in keyring and no env var is set.

**`_keyring_available()`**: Checks whether the `keyring` library is installed. If not, all keyring functions degrade gracefully (returning `None` or `False`) — no import errors are raised at module level.

**`get_key(service_name, key_name)`**: Retrieves the encryption key from the system keyring. Returns `None` if the keyring is unavailable, the key doesn't exist, or any error occurs. This is intentionally silent — the caller decides what fallback to use.

**`set_key(key, service_name, key_name)`**: Stores a key in the system keyring. Returns `True` on success, `False` if the keyring is unavailable or writing fails.

**`has_key(service_name, key_name)`**: Returns `True` if a key exists in the keyring for the given service and key name.

**`get_or_create_key(service_name, key_name, length)`**: Retrieves the existing key from the keyring, or generates a new random key using `secrets.token_hex(length)` (default 32 bytes = 64 hex chars) and stores it. This is useful for initial setup — run once to create a key, and subsequent calls will reuse it.

**`resolve_key(use_encryption, service_name, key_name, env_var)`**: The central key resolution function. Given a `use_encryption` flag, it resolves the actual encryption key in this priority order:
1. If `use_encryption` is `False`, returns `None` (no encryption).
2. If `env_var` is provided and that environment variable is set, uses its value.
3. Attempts to retrieve the key from the system keyring via `get_key()`.
4. Falls back to `FALLBACK_KEY` (`"debug_key_please_change_me"`).

This three-tier fallback (env var → keyring → hardcoded) matches the pattern used in `Backend_w._DB`, where production uses keyring, CI/testing uses env vars, and local development uses a debug key.

## File: service.py

Provides `SecureDbService`, a deterministic non-blocking wrapper around `sqlite3` (and optionally `pysqlcipher3`/`sqlcipher3` for encryption).

**Constructor parameters**:
- `db_path`: Path to the SQLite database file. The parent directory is created automatically if it does not exist.
- `use_encryption`: If `True`, attempts to use `pysqlcipher3` (or `sqlcipher3`) for SQLCipher encryption. Falls back to plain `sqlite3` if neither is installed.
- `wal_mode`: Enables WAL (Write-Ahead Logging) for better concurrent read performance. Default `True`.
- `retry_attempts`: Number of times to retry if the database is locked. Default `5`.
- `retry_delay_seconds`: Delay between retry attempts. Default `0.1`.
- `service_name`, `key_name`, `key_env_var`: Passed through to `resolve_key()` for encryption key resolution.

**`_get_driver()`**: Returns the appropriate database driver module. If `use_encryption` is `False`, returns standard `sqlite3`. If encryption is requested, tries to import `pysqlcipher3.dbapi2`, then `sqlcipher3.dbapi2`, and falls back to `sqlite3` with a warning log if neither is installed. The module is cached in `_cipher_module` after the first successful import.

**`connect()`**: Opens a new database connection with the following deterministic setup:
1. Resolves the encryption key via `resolve_key()`.
2. Connects using the appropriate driver.
3. If an encryption key is provided, executes `PRAGMA key = '<key>'` to unlock the database.
4. Enables WAL mode via `PRAGMA journal_mode=WAL`.
5. Enables foreign keys via `PRAGMA foreign_keys=ON`.
6. Sets `row_factory = sqlite3.Row` for dict-style column access.
7. Implements retry logic: if a `"database is locked"` OperationalError occurs, it waits `retry_delay_seconds` and retries up to `retry_attempts` times.

**`connection()`** (context manager): Opens a connection via `connect()`, yields it, commits on success, rolls back on exception, and always closes the connection in the `finally` block. This is the recommended way to perform multiple operations atomically.

**`transaction()`** (context manager): Identical to `connection()` — yields a connection with auto-commit/rollback. Provided as a semantic alias for readability.

**`run_transaction(fn)`**: Executes a callable `fn(conn)` inside a transaction context, returning the callable's result. Useful for running arbitrary code against the database with automatic commit/rollback.

**`execute(sql, params)`**: Executes a single SQL statement with optional parameters. Uses the connection context manager (auto-commit). Returns the cursor.

**`execute_many(sql, params_list)`**: Executes the same SQL statement against each parameter set in the list. Uses a single transaction for all executions.

**`execute_script(sql)`**: Executes a multi-statement SQL script (e.g., table creation statements separated by semicolons). Uses the connection context manager.

**`query(sql, params)`**: Executes a SELECT and returns all result rows as a list of `sqlite3.Row` objects. Each row supports both index access (`row[0]`) and dict-style access (`row["column_name"]`).

**`query_one(sql, params)`**: Executes a SELECT and returns the first row, or `None` if no rows match.

**`insert(sql, params)`**: Executes an INSERT and returns the `lastrowid` of the inserted row.

**`table_info(table_name)`**: Returns the column metadata for a table via `PRAGMA table_info`. Each row contains `cid`, `name`, `type`, `notnull`, `dflt_value`, and `pk`.

**`table_exists(table_name)`**: Returns `True` if a table with the given name exists in the database.

**`vacuum()`**: Reclaims unused space and defragments the database file by running `VACUUM`. Useful after bulk deletions.

**`backup(target_path)`**: Creates a point-in-time backup of the database using SQLite's online backup API (`src_conn.backup(dst_conn)`). The source database can remain in use during the backup — reads and writes can proceed concurrently. The target file's parent directory is created automatically.

**`toggle_encryption(enable)`**: Converts an existing database between plain-text and encrypted (SQLCipher) format, or vice versa. Works by:
1. Connecting to the source database with the current encryption setting.
2. If enabling encryption, ensuring a key exists in the keyring (via `get_or_create_key`).
3. Creating a temporary database with the target driver and encryption key.
4. Using `src_conn.iterdump()` to dump all data and `dst_conn.executescript()` to recreate it.
5. Renaming the original to `.bak`, the temp to the original path, then deleting the `.bak`.

Returns `True` if a conversion was performed, `False` if already in the requested state. The original database is preserved as a backup until the operation completes successfully.

## File: __init__.py

Exports the public API: `SecureDbService`, `SERVICE_NAME`, `KEY_NAME`, `FALLBACK_KEY`, `get_key`, `set_key`, `has_key`, `get_or_create_key`, `resolve_key`.

## How `SecureDbService` is deterministic and non-blocking

| Property | Mechanism |
|----------|-----------|
| **Deterministic** | WAL mode ensures consistent read behavior. `row_factory` is always set. Foreign keys are always enabled. Every connection has the same PRAGMAs applied in the same order. |
| **Non-blocking reads** | WAL mode allows concurrent reads while a write transaction is in progress. Readers do not block writers and writers do not block readers. |
| **Non-blocking writes (retry)** | If a `database is locked` error occurs (e.g., another process is writing), the service retries with a configurable delay instead of immediately failing. |
| **Auto-cleanup** | Connections are always closed (via context manager `finally`). Transactions are always committed or rolled back. No dangling connections. |
| **Online backup** | `backup()` uses SQLite's built-in online backup API, allowing the database to remain in use during the backup process. |
| **Encryption toggle** | `toggle_encryption()` converts between plain-text and encrypted SQLCipher using `iterdump()` + recreate, with automatic key management. |

## Encryption key resolution order

```
use_encryption=True?
    │
    ├── No  → return None (plain SQLite)
    │
    └── Yes → try in order:
             1. env_var (e.g. COGNITHOR_DB_KEY)
             2. system keyring (service="Cognithor", key="db_key")
             3. fallback key "debug_key_please_change_me"
```

## Usage example

```python
from secure_db_service import SecureDbService

# Plain database (default)
svc = SecureDbService("data/my_app.db")
svc.execute_script("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
svc.execute("INSERT INTO items (name) VALUES (?)", ("hello",))
rows = svc.query("SELECT * FROM items")

# Encrypted database (requires pysqlcipher3)
enc_svc = SecureDbService("data/secure.db", use_encryption=True)
enc_svc.execute("CREATE TABLE IF NOT EXISTS secrets (id INTEGER PRIMARY KEY, value TEXT)")

# Transaction with rollback on error
def insert_items(conn):
    conn.execute("INSERT INTO items (name) VALUES (?)", ("a",))
    conn.execute("INSERT INTO items (name) VALUES (?)", ("b",))
    return "done"

svc.run_transaction(insert_items)

# Online backup
svc.backup("data/my_app_backup.db")
```
