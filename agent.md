# Cognithor Agent System

This project provides a backend API and CLI for creating an autonomous agent system by routing LLM requests through multiple providers.

## Current State

- **endpoint/** — Fully implemented. Universal LLM provider configuration via `endpoint/database.py` (Tracker), `endpoint/providers.py` (HttpProvider), `endpoint/manager.py` (EndpointManager), `endpoint/config.py` (env var / JSON config).
- **api_service/** — Fully implemented. FastAPI server with JWT auth, AES-256-GCM payload encryption, full CRUD for providers/settings/users, interactive CLI.
- **secure_db_service/** — Fully implemented. SQLite wrapper with WAL mode, retry logic, optional SQLCipher encryption, keyring-backed key management.
- **log_service/** — Fully implemented. Structured logging to SQLite with four levels, auto caller detection.
- **onboarding/** — Fully implemented. `setup.py` initialises all three service databases and seeds defaults.
- **agents/** — Empty (placeholder for future agent implementations).
- **apps/** — Empty (placeholder for future app modules).
- **core/** — Empty (placeholder for core agent logic).

## Next Steps

The following areas are planned but not yet implemented:

- **core/** — Rolling context window management for agent conversations.
- **agents/** — Agent implementations (e.g. `agent_jason/` directory exists but is empty).
- **apps/** — Application modules: read_from_file, write_to_file, terminal, time_service. 

