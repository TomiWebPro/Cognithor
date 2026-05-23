# Cognithor — API Documentation

## Overview

REST API for the Cognithor autonomous agent system. Built with FastAPI.

## Security Model (Three-Tier)

```
 Tier 1 — Public (plain HTTP)
   GET  /                        → server info
   GET  /health                  → health check
   GET  /onboarding/passkey      → onboarding passkey

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

The plaintext inside the envelope is JSON. For requests, the inner structure is:
```json
{
  "_token": "optional JWT for redundancy",
  "_body": { ... original request body ... }
}
```

The middleware (`api_service/middleware.py`) transparently encrypts/decrypts — route handlers never see encrypted data.

## Excluded Routes (No Encryption)

| Route | Reason |
|---|---|
| `GET /` | Public server info |
| `GET /health` | Public health check |
| `POST /token` | Login — credentials sent in plaintext, JWT returned |
| `GET /onboarding/passkey` | Onboarding passkey (public) |
| `GET /onboarding/passkey.qr` | Onboarding QR image (public) |
| `/docs`, `/redoc` | OpenAPI documentation |
| `/openapi.json` | OpenAPI schema |

## Base URL

Defaults to `http://localhost:8000`. Configurable via `api_host` and `api_port` in the `api_config` database table.

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
| `POST` | `/providers/{name}/activate` | Set provider as active |
| `POST` | `/providers/{name}/test` | Test provider connectivity |

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
| `GET` | `/settings/security` | Get security config |
| `PUT` | `/settings/security` | Update security config |
| `POST` | `/settings/token/refresh` | Refresh JWT token |

## Key Implementation Files

| File | Purpose |
|---|---|
| `api_service/encryption.py` | `derive_key()`, `encrypt_payload()`, `decrypt_payload()` |
| `api_service/middleware.py` | `EncryptionMiddleware` — transparent encryption/decryption |
| `api_service/auth.py` | JWT creation, validation, TTL (float, supports sub-minute) |
| `api_service/database.py` | DB schema, user management, config storage |
| `api_service/routers/security_router.py` | TTL validation (0.5–10 min range) |

## Error Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad request (invalid TTL, malformed encrypted payload) |
| 401 | Unauthorized — `"Could not validate credentials"` (missing/invalid/expired JWT) |
| 401 | Unauthorized — `"Token superseded by another login"` (version mismatch) |
| 404 | Resource not found |
| 409 | Conflict (duplicate, encryption in progress) |
| 422 | Invalid input |
| 500 | Server error |

## Quickstart

```bash
cd cognithor/
python onboarding/setup.py init --no-encrypt
python -m api_service.main

# Health check (public)
curl http://localhost:8000/health

# Login (plain)
curl -X POST http://localhost:8000/token \
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
| Token TTL | 30s–10min, configurable in DB |
| Token refresh | Available, keeps same token version |
| Single-session | Enforced via `ver` claim in JWT, incremented on each login |
| Onboarding passkey | Base64-encoded, carries host+credentials |
| DB encryption | Optional SQLCipher (separate from API encryption) |
