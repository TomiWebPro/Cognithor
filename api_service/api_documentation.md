# Cognithor — API Documentation

## Overview

REST API for the Cognithor autonomous agent system. Built with FastAPI.

## Security Model (Three-Tier)

```
 Tier 1 — Public (plain HTTP)
   GET  /                        → server info
   GET  /health                  → health check
   GET  /onboarding/passkey      → onboarding passkey
   GET  /onboarding/passkey.qr   → onboarding QR image

 Tier 2 — Login (plain HTTP, credentials in body)
   POST /token                   → username + password → JWT

 Tier 3 — Encrypted (AES-256-GCM, key derived from JWT)
   All other endpoints           → request/response payloads encrypted
                                    key = SHA-256(JWT)
                                    JWT in Authorization: Bearer header
```

## Encryption Detail

Once a JWT is obtained, all authenticated API communication uses payload-level encryption:

- **Algorithm**: AES-256-GCM
- **Key derivation**: `SHA-256(JWT)` → 32 bytes (256 bits)
- **IV**: 12 random bytes, generated per-request
- **Tag**: 128-bit GCM authentication tag (included in ciphertext)
- **AAD**: none

**Request format** (client → server):
```json
{
  "iv": "base64-encoded 12-byte IV",
  "data": "base64-encoded ciphertext + auth tag"
}
```

**Response format** (server → client):
```json
{
  "iv": "base64-encoded 12-byte IV",
  "data": "base64-encoded ciphertext + auth tag"
}
```

The plaintext inside the envelope is the original JSON body. The middleware (`api_service/middleware.py`) transparently encrypts/decrypts — route handlers never see encrypted data. The JWT is read from the `Authorization: Bearer` header (not from inside the encrypted payload).

## Excluded Routes (No Encryption)

All routes under these prefixes bypass encryption:

| Prefix | Reason |
|---|---|
| `/` | Public server info |
| `/health` | Public health check |
| `/token` | Login — credentials sent in plaintext, JWT returned |
| `/onboarding` | Onboarding passkey + QR (public) |
| `/docs` | OpenAPI documentation |
| `/redoc` | OpenAPI documentation |
| `/openapi.json` | OpenAPI schema |

## Base URL

Defaults to `http://0.0.0.0:4464`. Configurable via `api_host` and `api_port` in the `api_config` database table.

## Authentication

### Obtaining a Token

```
POST /token
Content-Type: application/json

{"username": "admin", "password": "admin"}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

### Token Expiry

- **Range**: 30 seconds (0.5 min) to 10 minutes
- **Default**: 10 minutes
- **Configurable via**: `PUT /settings/security` with `access_token_expire_minutes`

Once expired, the backend returns 401. The client must re-authenticate.

### Single-Session Enforcement

Only one active session per user. Each successful `POST /token` increments a `token_version` counter in the database for that user. The version is embedded in the JWT as the `ver` claim.

Every authenticated request (via `get_current_user`) compares the JWT's `ver` against the DB. If they differ, the backend returns `401 Token superseded by another login`.

```
Alice logs in  → token_version=2, JWT has ver=2
Bob logs in    → token_version=3, JWT has ver=3
Alice's next request → ver=2 != 3 → 401, connection dropped
```

The frontend health monitor detects the 401 and transitions to the reconnect screen automatically.

### Token Refresh

```
POST /settings/token/refresh
Authorization: Bearer <current_token>
```

Returns a new JWT with a fresh expiry **and the same token version** (no increment — same session).

## Onboarding Passkey

The passkey endpoint provides initial connection credentials to avoid the chicken-and-egg problem (needing credentials to get credentials).

```
GET /onboarding/passkey
```

**Response:**
```json
{
  "passkey": "<base64-encoded JSON>",
  "qr_code": "<base64-encoded PNG>"
}
```

The decoded passkey contains:
```json
{
  "host": "0.0.0.0",
  "port": 8000,
  "username": "admin",
  "password": "admin",
  "encryption_available": true
}
```

The frontend uses these credentials to call `POST /token`, then derives the encryption key from the returned JWT.

## API Endpoints

### Root

```
GET /
```

No auth. Returns server identity.

```json
{
  "message": "Cognithor API",
  "status": "running",
  "version": "0.1.0",
  "timestamp": "2026-05-22T22:00:00Z"
}
```

### Health Check

```
GET /health
```

No auth. Returns operational status.

```json
{
  "status": "healthy",
  "timestamp": "2026-05-22T22:00:00Z",
  "version": "0.1.0"
}
```

### Current User

```
GET /users/me
Authorization: Bearer <jwt>
```

Returns authenticated username. Encrypted response.

### Providers

All provider endpoints require authentication and use encrypted payloads.

| Method | Path | Description |
|---|---|---|
| `GET` | `/providers` | List all providers |
| `GET` | `/providers/{name}` | Get provider by name |
| `POST` | `/providers` | Create provider |
| `PUT` | `/providers/{name}` | Update provider |
| `DELETE` | `/providers/{name}` | Delete provider |
| `POST` | `/providers/{name}/test` | Test provider connectivity (or specific model if `model` in body) |
| `POST` | `/providers/{name}/test-model/{model}` | Test a specific model by name |

### Agents

All agent endpoints require authentication and use encrypted payloads. Each agent is identified by a unique 6-character alphanumeric ID (`agent_id`). Models are linked via `model_ref` in the format `provider::model_name` (e.g. `openai::gpt-4o`).

| Method | Path | Description |
|---|---|---|
| `GET` | `/agents` | List all agents |
| `GET` | `/agents/{agent_id}` | Get agent by 6-char ID |
| `POST` | `/agents` | Create agent |
| `PUT` | `/agents/{agent_id}` | Update agent (context window, model refs, name, toggles) |
| `DELETE` | `/agents/{agent_id}` | Delete agent |

**Create agent:**
```json
{
  "name": "MyAgent",
  "context_window": 8192,
  "model_ref": "openai::gpt-4o",
  "backup_model_ref": "anthropic::claude-sonnet-4-20250514",
  "show_notes": true,
  "show_diary": true
}
```

**Response:**
```json
{
  "id": 1,
  "agent_id": "aB3xK9",
  "name": "MyAgent",
  "context_window": 8192,
  "model_ref": "openai::gpt-4o",
  "backup_model_ref": "anthropic::claude-sonnet-4-20250514",
  "show_notes": true,
  "show_diary": true,
  "created_at": "...",
  "updated_at": "..."
}
```

### Agent fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Friendly agent name |
| `context_window` | int | 4096 | Max token limit for context |
| `model_ref` | string | null | Primary model in `provider::model` format |
| `backup_model_ref` | string | null | Fallback model |
| `max_past_actions` | int | 15 | Number of past actions in context (min 3) |
| `agent_can_change_max_past_actions` | bool | false | Whether agent can self-adjust past action limit |
| `show_context_window` | bool | true | Show token usage tab |
| `show_notes` | bool | true | Show Notes tab (temporal memory, overwritable, auto-expires) |
| `show_diary` | bool | true | Show Diary tab (long-term memory, append-only) |

### Notes

| Method | Path | Description |
|---|---|---|
| `GET` | `/agents/{agent_id}/notes` | Get current note content |
| `PUT` | `/agents/{agent_id}/notes` | Overwrite note content |

**Read notes:**
```json
GET /agents/{agent_id}/notes

Response:
{
  "agent_id": "aB3xK9",
  "notes": "current plan here"
}
```

**Write notes:**
```json
PUT /agents/{agent_id}/notes
{
  "content": "new plan here"
}

Response:
{
  "agent_id": "aB3xK9",
  "notes": "new plan here"
}
```

### Diary

| Method | Path | Description |
|---|---|---|
| `POST` | `/agents/{agent_id}/diary` | Append to today's diary entry |
| `GET` | `/agents/{agent_id}/diary` | List diary entries (optional `?date=YYYY-MM-DD`) |

**Append to diary:**
```json
POST /agents/{agent_id}/diary
{
  "content": "Accomplished X, Y, Z"
}

Response:
{
  "success": true,
  "date": "2026-06-08",
  "type": "diary"
}
```

**List diary entries:**
```json
GET /agents/{agent_id}/diary

Response:
{
  "agent_id": "aB3xK9",
  "entries": [
    {
      "date": "2026-06-08",
      "content": "Accomplished X, Y, Z",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### Settings

All settings endpoints require authentication and use encrypted payloads.

| Method | Path | Description |
|---|---|---|
| `GET` | `/settings` | Get all settings |
| `PUT` | `/settings` | Update settings |
| `GET` | `/settings/users` | List users |
| `POST` | `/settings/users` | Create user |
| `PUT` | `/settings/users/me/password` | Change own password |

### Security Settings

| Method | Path | Description |
|---|---|---|
| `GET` | `/settings/security` | Get security config (TTL, DB encryption status, keyring status) |
| `PUT` | `/settings/security` | Update security config — TTL (0.5–10 min) or toggle DB encryption |
| `POST` | `/settings/token/refresh` | Refresh JWT token (same session, version preserved) |

When toggling database encryption, all three databases (`cognithor.db`, `cognithor_logs.db`) are converted via SQLite `iterdump` + recreate. The operation sets `encryption_in_progress` to prevent concurrent toggles (409 if attempted).

### Settings (General)

| Method | Path | Description |
|---|---|---|
| `GET` | `/settings` | Get all config key-values |
| `PUT` | `/settings` | Update config key-value pairs |
| `GET` | `/settings/users` | List users and creation dates |
| `POST` | `/settings/users` | Create new user |
| `PUT` | `/settings/users/me/password` | Change own password (requires `old_password` + `new_password`) |

## Key Implementation Files

| File | Purpose |
|---|---|
| `api_service/encryption.py` | `derive_key()`, `encrypt_payload()`, `decrypt_payload()` |
| `api_service/middleware.py` | `EncryptionMiddleware` — transparent encryption/decryption |
| `api_service/auth.py` | JWT creation, validation, TTL (float, supports sub-minute), token version enforcement |
| `api_service/database.py` | `ApiConfigManager` — DB schema, user management, config storage, password hashing |
| `api_service/main.py` | FastAPI app entry point, CLI (`-i` for interactive menu, `--encrypt`/`--no-encrypt`), DB encryption auto-detect |
| `api_service/cli_launcher.py` | Interactive CLI menu — status, provider CRUD, model management, connection info + passkey generation |
| `api_service/routers/base.py` | Root (`GET /`) and health (`GET /health`) endpoints |
| `api_service/routers/auth_router.py` | Login (`POST /token`) and current user (`GET /users/me`) |
| `api_service/routers/providers_router.py` | Full provider CRUD + test endpoints |
| `api_service/routers/security_router.py` | TTL validation (0.5–10 min range), DB encryption toggle, token refresh |
| `api_service/routers/settings_router.py` | General settings CRUD, user management |
| `api_service/routers/onboarding_router.py` | Passkey + QR code generation for frontend onboarding |
| `api_service/routers/notes_router.py` | Notes CRUD (`GET/PUT /agents/{id}/notes`) |
| `api_service/routers/diary_router.py` | Diary append + list (`POST/GET /agents/{id}/diary`) |

## Error Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad request (invalid TTL range, malformed encrypted payload, missing fields) |
| 401 | Unauthorized — `"Could not validate credentials"` (missing/invalid/expired JWT) |
| 401 | Unauthorized — `"Token superseded by another login"` (version mismatch) |
| 403 | Forbidden — wrong current password on password change |
| 404 | Resource not found |
| 409 | Conflict (duplicate provider, duplicate user, encryption toggle already in progress) |
| 422 | Invalid input (missing required fields) |
| 500 | Server error |

## Quickstart

```bash
cd cognithor/
python onboarding/setup.py init --no-encrypt
python -m api_service.main              # starts uvicorn server
# or
python -m api_service.main -i           # interactive CLI menu (no server)

# Health check (public)
curl http://localhost:4464/health

# Login (plain)
curl -X POST http://localhost:4464/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'

# Authenticated request (encrypted)
# From the frontend — handles encryption automatically
```

## Security Summary

| Aspect | Status |
|---|---|
| Public endpoints | Plain HTTP, no auth |
| Login | Plain HTTP, credentials in body |
| Authenticated payloads | AES-256-GCM encrypted, key = SHA-256(JWT) |
| Key derivation | SHA-256 of the JWT (stateless, no storage) |
| Token TTL | 30s–10min (0.5–10), configurable in DB via `access_token_expire_minutes` |
| Token refresh | Available, keeps same token version |
| Single-session | Enforced via `ver` claim in JWT, incremented on each login |
| Onboarding passkey | Base64-encoded, carries host+credentials |
| DB encryption | Optional SQLCipher via `pysqlcipher3`/`sqlcipher3`, key from env var → keyring → fallback |
| Keyring | OS keyring (via `keyring` lib) stores DB encryption key |
| CLI | Interactive menu for provider CRUD, model testing, passkey generation |
| Password storage | bcrypt-hashed in `api_users` table |
