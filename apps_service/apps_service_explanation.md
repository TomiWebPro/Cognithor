# Apps Service Explanation

The `apps_service` package provides a management layer for agent applications (tools). It enables a many-to-many relationship between agents and apps: any agent can have any subset of available apps installed, and each installation can be individually enabled or disabled with per-agent configuration. Adding a new app requires only a manifest file in the `apps/` directory — no new service code is needed.

The package is split into three files:

## File: apps_service/models.py

Defines the data structures used throughout the module.

**`AppParameter`**: Describes a single input or output parameter for an app. Each parameter has a `name`, `type` (e.g. "string", "integer", "boolean"), `description`, `required` flag, optional `default` value, and optional `enum` list of valid values.

**`AppManifest`**: The full definition of an app. Contains:
- `app_id`: Unique identifier (e.g. `"read_from_file"`)
- `name`, `description`: Human-readable metadata
- `version`: Semantic version string
- `author`: Creator name (`"system"` for built-in apps)
- `icon`: Single unicode character or emoji for UI display (e.g. `"📄"`, `"⌨️"`, `"◆"`)
- `parameters`: List of `AppParameter` that the app accepts as input
- `outputs`: List of `AppParameter` that the app returns
- `requires_confirmation`: Whether the agent should ask user before executing
- `timeout_seconds`: Maximum execution time before the app is killed

On-disk `manifest.py` files use only the basic fields (`app_id`, `name`, `description`, `version`, `author`, `icon`). Extended fields (`parameters`, `outputs`, `requires_confirmation`, `timeout_seconds`) are available via the API for custom app registration.

**`AppRecord`**: Mirrors the `apps` database table. Adds database fields (`id`, `created_at`, `updated_at`, `is_available`, `directory`, `type`) plus the full `manifest` stored as a JSON string for introspection without re-parsing source code.

**`AgentAppRecord`**: Mirrors the `agent_apps` junction table. Holds `agent_id`, `app_id`, `is_enabled` toggle, and an optional per-installation `config` JSON string.

## File: apps_service/database.py

Provides two classes that handle all database operations via `SecureDbService`.

### AppRegistry

Manages the global app catalog (the `apps` table). Apps are the available tools in the system — independently of any agent.

**Key methods:**
- `register_app(manifest, directory)` — Registers a new app in the catalog from an `AppManifest`. Generates a unique `app_id` if not provided. Serializes the manifest to JSON for storage.
- `unregister_app(app_id)` — Removes an app from the catalog. Returns `False` if the app does not exist.
- `get_app(app_id)` — Retrieves a single app by ID, or `None`.
- `list_apps()` — Returns all registered apps (available and unavailable).
- `list_available_apps()` — Returns only apps where `is_available = 1`.
- `update_app(app_id, ...)` — Partially updates app metadata. Uses `COALESCE` in SQL, so only provided fields are changed. Does not allow changing `app_id`.
- `scan_apps_directory(apps_dir)` — Scans a directory on disk and auto-discovers built-in apps. For each subdirectory containing a `manifest.py` with a `MANIFEST` variable, it imports the module and registers (or updates) the app. This is called automatically at server startup and CLI initialization.

**App discovery**: The `scan_apps_directory` method uses Python's `importlib.util` to dynamically load manifest modules from disk. If an app with the same `app_id` already exists in the database, it updates the existing record (name, version, description, etc.) rather than creating a duplicate. This means built-in app manifests can be updated on disk and the changes will be picked up on next startup.

### AgentAppManager

Manages the many-to-many relationship between agents and apps (the `agent_apps` table). Each row represents an app installation for a specific agent.

**Key methods:**
- `install_app(agent_id, app_id, config)` — Installs an app for an agent. Returns `None` if already installed (unique constraint), otherwise returns the new `AgentAppRecord`.
- `uninstall_app(agent_id, app_id)` — Removes an app installation. Returns `False` if the installation does not exist.
- `enable_app(agent_id, app_id)` / `disable_app(agent_id, app_id)` — Toggles the `is_enabled` flag. Returns `None` if the installation does not exist.
- `get_agent_app(agent_id, app_id)` — Retrieves a single installation record, or `None`.
- `list_agent_apps(agent_id)` — Lists all apps installed for an agent.
- `list_enabled_agent_apps(agent_id)` — Lists only the enabled apps (useful for runtime filtering).
- `set_app_config(agent_id, app_id, config)` — Updates the per-agent configuration JSON for an installed app.
- `uninstall_all_for_agent(agent_id)` — Removes all app installations for an agent. Called when an agent is deleted to maintain referential integrity.

## File: apps_service/__init__.py

Exports the public API: `AppRegistry`, `AgentAppManager`, `AppRecord`, `AgentAppRecord`, `AppManifest`, `AppParameter`, `generate_app_id`.

## How the Files Work Together

```
 apps/ directory (on disk)
       │
       │  scan_apps_directory()
       ▼
  AppRegistry (database.py)     ← global app catalog (apps table)
       │
       │  get_app(), list_apps()
       ▼
  Application / CLI / API
       │
       │  install_app(), enable_app(), etc.
       ▼
  AgentAppManager (database.py) ← per-agent installations (agent_apps table)
       │
       ├── install_app()     → creates binding
       ├── uninstall_app()   → removes binding
       ├── enable_app()      → sets is_enabled=1
       ├── disable_app()     → sets is_enabled=0
       └── set_app_config()  → updates per-agent config
```

Both classes delegate database access to `SecureDbService`, sharing the same `cognithor.db` file used by the rest of the system.

## App Requirements and Validation

Every app registered in the system must satisfy these rules:

### Icon
- Must be 1-2 Unicode code points (a single character or emoji).
- Examples: `"◆"`, `"📄"`, `"✏️"`, `"⌨️"`.
- Rejected: empty string, whitespace, multi-character strings like `"terminal"`, `"extension"`, `"abc"`.
- Enforced by `validate_icon()` in `database.py` and `apps_router.py` (returns `ValueError` or `422`).

### app_id
- Must be unique across the entire registry (database `UNIQUE` constraint).
- Auto-generated if not provided in the manifest.

### Name
- Required for all apps (enforced by `apps_router.py` — `422` if missing).
- Used as the display name in CLI and frontend.

### agent_apps uniqueness
- An app can be installed for a given agent only once (`UNIQUE(agent_id, app_id)` constraint).
- Attempting to re-install returns `None` (service layer) or `409 Conflict` (API).

### Availability gate
- Only apps with `is_available = true` can be installed.
- The API `POST /agents/{id}/apps` checks this and returns `400` if the app is unavailable.

### On-disk manifests vs API
- Manifests in `apps/*/manifest.py` support only basic fields (`app_id`, `name`, `description`, `version`, `author`, `icon`).
- Extended fields (`parameters`, `outputs`, `requires_confirmation`, `timeout_seconds`) are accepted only through the API `POST /apps` endpoint.
- The `scan_apps_directory()` method silently skips directories without a valid `manifest.py`.

## Database Tables

**`apps` table** — Global app registry (managed by `AppRegistry`):
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing ID |
| `app_id` | TEXT UNIQUE | Human-readable identifier (e.g. `"read_from_file"`) |
| `name` | TEXT | Display name |
| `description` | TEXT | What the app does |
| `version` | TEXT | Semantic version |
| `author` | TEXT | Creator |
| `type` | TEXT | `"builtin"` or `"custom"` |
| `icon` | TEXT | Single unicode character or emoji |
| `manifest` | TEXT JSON | Full app definition (parameters, outputs, settings) |
| `directory` | TEXT | Path to the app module on disk |
| `is_available` | INTEGER | Whether the app can be installed |
| `requires_confirmation` | INTEGER | Safety flag |
| `timeout_seconds` | INTEGER | Max execution time |
| `created_at` / `updated_at` | TEXT | Timestamps |

**`agent_apps` table** — Junction table (managed by `AgentAppManager`):
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing ID |
| `agent_id` | TEXT FK→agents | Which agent this belongs to |
| `app_id` | TEXT FK→apps | Which app is installed |
| `is_enabled` | INTEGER | Toggle (1=enabled, 0=disabled) |
| `config` | TEXT JSON | Per-agent configuration for this app |
| `installed_at` / `updated_at` | TEXT | Timestamps |
| UNIQUE(agent_id, app_id) | | Prevents duplicate installations |

## Adding a New Built-in App

Create a directory under `apps/` with a `manifest.py` file. On-disk manifests use only basic metadata:

```python
# apps/my_tool/manifest.py
MANIFEST = {
    "app_id": "my_tool",
    "name": "My Custom Tool",
    "description": "Does something useful for agents",
    "version": "1.0.0",
    "author": "system",
    "icon": "🛠️",
}
```

On next server startup (or "Rescan apps directory" in the CLI), `scan_apps_directory()` will find it and register it automatically. No Python code changes are needed.

## Adding a Custom App via API

Custom apps can be registered at runtime through the API without creating files on disk:

```python
from apps_service import AppRegistry, AppManifest, AppParameter

registry = AppRegistry(svc)
registry.register_app(AppManifest(
    app_id="web_search",
    name="Web Search",
    description="Search the web for information",
    version="1.0.0",
    author="user123",
    icon="🔍",
    parameters=[
        AppParameter(name="query", type="string", description="Search query", required=True),
    ],
    outputs=[
        AppParameter(name="results", type="string", description="Search results"),
    ],
))
```

## Usage Example (Python)

```python
from apps_service import AppRegistry, AgentAppManager

# Initialize (service auto-creates tables)
registry = AppRegistry(svc)
agent_app_mgr = AgentAppManager(svc)

# Auto-discover built-in apps from disk
registry.scan_apps_directory("apps/")

# Install an app for an agent
agent_app_mgr.install_app(agent_id="abc123", app_id="read_from_file")

# Disable it (agent can still see it, but it won't execute)
agent_app_mgr.disable_app("abc123", "read_from_file")

# Re-enable
agent_app_mgr.enable_app("abc123", "read_from_file")

# List what's installed
for app in agent_app_mgr.list_agent_apps("abc123"):
    print(f"{app.app_id}: {'enabled' if app.is_enabled else 'disabled'}")

# Uninstall
agent_app_mgr.uninstall_app("abc123", "read_from_file")
```
