# Developer Log: Encryption Toggle Bug (toggle ON → set_config crash)

## Bug Report

When toggling database encryption **OFF** then **ON** via the security settings UI, the second toggle (encrypt ON) succeeds for the main DB and log DB but crashes when the subsequent `config_mgr.set_config()` call tries to write to the main DB:

```
pysqlcipher3.dbapi2.DatabaseError: file is not a database
```

Error at `service.py:151` — `conn.execute("PRAGMA journal_mode=WAL")`

## Root Cause Analysis

### Problem 1: Key inconsistency between encryption and read

The `toggle_encryption(enable=True)` flow did:

1. `delete_key(...)` — delete old key from keyring
2. `get_or_create_key(...)` — generates **new random key**, stores it in keyring, returns it
3. `dst_key = self._get_encryption_key()` — **re-reads** from keyring via `resolve_key()`
4. `_transfer(..., dst_key)` — encrypts temp DB with `dst_key`
5. File swap
6. `config_mgr.set_config()` → `connect()` calls `resolve_key()` again to get the key

The vulnerability: if `resolve_key()` fails to read from keyring (transient Secret Service daemon delay, keyring backend not actually usable despite being importable), it returned `FALLBACK_KEY`. But `get_or_create_key()` had returned a different random key. The DB was encrypted with that random key, but `connect()` tried to open with `FALLBACK_KEY` → **"file is not a database"**.

### Problem 2: `_keyring_available()` was too permissive

```python
def _keyring_available():
    try:
        import keyring
        return True
    except ImportError:
        return False
```

Only checked if the `keyring` **package** is importable — not whether a working **backend** exists. The package can be importable even when no Secret Service / KWallet daemon is running. This meant:
- `_keyring_available()` → `True`
- `set_key()` → `keyring.set_password()` fails (no backend) → bare `except` swallows error → returns `False`
- `get_or_create_key()` gets `False` from `set_key()` but **ignores the return value** and still returns the random key
- `resolve_key()` → `get_key()` → `keyring.get_password()` also fails → caught by bare `except` → returns `None` → `resolve_key()` returns `FALLBACK_KEY`
- **Mismatch**: generated random key vs `FALLBACK_KEY`

### Problem 3: Silent error handling in key_manager

All `get_key`, `set_key`, `delete_key` used bare `except: return None/False` with no logging — making keyring failures invisible.

### Problem 4: Stale WAL/SHM journal files

After file swap in `toggle_encryption`, stale `-wal` / `-shm` files from the old (decrypted) database could remain alongside the new encrypted database file. SQLCipher would attempt to read these files for un-checkpointed journal data, potentially causing conflicts.

## Changes Made

### `secure_db_service/key_manager.py`

| Change | Line(s) | Purpose |
|--------|---------|---------|
| `_keyring_available()` now calls `keyring.get_keyring()` | 15-22 | Verifies a working backend, not just package import |
| Added `logger.error()` to bare `except` in `get_key` | 35-36 | Keyring failures now visible in logs |
| Added `logger.error()` to bare `except` in `set_key` | 52-53 | Keyring failures now visible in logs |
| Added `logger.error()` to bare `except` in `delete_key` | 69-70 | Keyring failures now visible in logs |
| `get_or_create_key()` checks `set_key()` return value | 89-97 | Returns `FALLBACK_KEY` if storage fails — consistent with `resolve_key()` |

### `secure_db_service/service.py`

| Change | Line(s) | Purpose |
|--------|---------|---------|
| Import `FALLBACK_KEY` | 12 | Needed for fallback logic |
| `self._cached_key` attribute | 90 | Cache encryption key after toggle |
| `_get_encryption_key()` falls back to cached key | 130-141 | If `resolve_key` returns `FALLBACK_KEY` but we have a cached key, use it |
| Capture `get_or_create_key()` return value as `generated_key` | 288-297 | Avoid re-reading from keyring |
| Use `generated_key` if `resolve_key` returns `FALLBACK_KEY` | 311-314 | Handle transient keyring read failure |
| Cache `dst_key` in `self._cached_key` | 318 | Persist for subsequent `connect()` calls |
| Clear `_cached_key` on exception rollback | 325 | Prevent stale cache after failed toggle |
| Clean stale `-wal`/`-shm` files after file swap | 335-338 | Prevent SQLCipher journal conflicts |

## Verification

All tests pass:
- `tests/test_key_manager.py` — 32/32 passed (keyring-enabled environment)
- `tests/test_secure_db.py` — 38/38 passed
- Comprehensive toggle flow reproduction test — 15/15 passed
- Edge case: simulated `set_key` failure confirms `get_or_create_key` + `resolve_key` now return consistent `FALLBACK_KEY`

## Key Design Decision

Rather than relying on keyring for every `connect()` call (which is vulnerable to transient Secret Service daemon delays), the fix **caches the encryption key** in memory after a successful `toggle_encryption`. The cached key is used as a fallback if the keyring read fails. This eliminates the race window between `set_key` (write to keyring) and `get_key` (read from keyring) during the same request.
