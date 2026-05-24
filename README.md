# Cognithor

Backend API server and CLI for managing and routing requests to multiple LLM providers (OpenAI, Anthropic, OpenRouter, Ollama, and custom endpoints). Provides a unified gateway with encrypted payloads, JWT authentication, and optional SQLCipher-encrypted databases.

This project is an independent re-implementation of the concepts from the original [Cognithor project](https://github.com/Alex8791-cyber/cognithor), built from a different architecture. No code/implementations were cloned from the original project.

## Features

- **FastAPI REST server** with JWT authentication (OAuth2 password bearer)
- **Transparent AES-256-GCM payload encryption** — key derived from JWT via SHA-256
- **Data-driven LLM provider configuration** — add new providers via DB insert, no code changes
- **Multi-provider routing** — single, fallback chain, or round-robin
- **Model testing & health monitoring** — per-model availability tracking
- **Optional SQLCipher-encrypted SQLite databases** — key from env var → OS keyring → fallback
- **Structured logging** to SQLite (error/warning/notify/normal-operation levels)
- **Interactive CLI** for provider CRUD, model management, and connection info
- **Onboarding passkey** with QR code for frontend setup
- **Single-session enforcement** — each login bumps a token version, superseding old sessions

## Quickstart

```bash
python onboarding/setup.py init --no-encrypt   # create DBs & seed defaults
python -m api_service.main                      # start API server on 0.0.0.0:4464
# or
python -m api_service.main -i                   # interactive CLI menu
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  api_service/  — FastAPI server, JWT auth, encryption MW   │
│    ├── main.py           — App creation, CLI entry point   │
│    ├── auth.py           — JWT create/validate, OAuth2     │
│    ├── middleware.py     — Transparent AES-GCM encryption  │
│    ├── encryption.py     — derive_key, encrypt/decrypt     │
│    ├── database.py       — ApiConfigManager (config+users) │
│    ├── cli_launcher.py   — Interactive management CLI      │
│    └── routers/          — Endpoints for all CRUD ops      │
├─────────────────────────────────────────────────────────────┤
│  endpoint/  — LLM provider configuration & HTTP client     │
│    ├── models.py         — ProviderRecord, Message, etc.   │
│    ├── database.py       — Tracker (provider+usage DB)     │
│    ├── config.py         — Env var / JSON config loading   │
│    ├── providers.py      — HttpProvider (generic LLM call) │
│    └── manager.py        — EndpointManager (chat, fallback)│
├─────────────────────────────────────────────────────────────┤
│  secure_db_service/  — SQLite wrapper with encryption      │
│    ├── service.py        — SecureDbService (WAL, retry)    │
│    └── key_manager.py    — Keyring-based encryption key mgt│
├─────────────────────────────────────────────────────────────┤
│  log_service/  — Structured SQLite logging                 │
│    ├── database.py       — LogDatabase (log_entries table) │
│    ├── models.py         — LogLevel, LogEntry              │
│    └── service.py        — LogService (auto caller detect) │
└─────────────────────────────────────────────────────────────┘
```

## License

This project is licensed under the **MIT License with Geographic Use Restriction Addendum v1.0 (MIT + GURAv1)**.

The MIT base license grants standard permissions, including the rights to use, copy, modify, merge, publish, distribute, sublicense, and sell the software. However, the GURAv1 addendum revokes these permissions for any individual or entity residing in, incorporated in, or operating within:

- **Brazil**
- States of **California**, **Texas**, **Utah**, **Louisiana**, **Colorado**, **Illinois**, **New York** (USA)

See the [LICENSE](./LICENSE) file for full terms. The original Cognithor project is fully open source.
