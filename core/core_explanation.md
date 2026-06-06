# Core Module Explanation

The `core` package provides the runtime services that drive agent conversations: context window management, configurable time progression, and past-action tracking for memory.

The package is split across four service files plus system app handlers:

## File: core/app_manager.py

Defines the context window management layer — how tabs are opened, closed, and assembled into a single context string that the agent sees.

**`AppHandler`**: Abstract base class for app tab handlers. Subclasses must implement:
- `generate_interface(params, tab_label)` — Returns a string describing the app's current state for the context window.
- `execute(params)` — Runs the app's core action and returns a result dict.

**`AgentOpenAppRecord`**: Dataclass mirroring the `agent_open_apps` table. Each row is a single open tab for an agent:
- `id`: 6-char unique tab ID (e.g. `"a1b2c3"`)
- `agent_id`: Which agent owns this tab
- `app_id`: Which app this tab represents (or `"__system__"` for system tabs)
- `tab_label`: Optional user-facing label
- `params`: JSON string of parameters the app was opened with
- `interface_text`: The rendered display text shown in context
- `is_persistent`: If True, the tab cannot be closed (e.g. `__list_apps__`)
- `opened_at` / `updated_at`: Timestamps

**`AppTabManager`**: The central class that manages open tabs and context assembly.

Key methods:
- `open_app(agent_id, app_id, tab_label, params, is_persistent)` — Opens a new tab. Generates a unique ID, calls the app handler's `generate_interface()`, persists to DB. Returns `(tab_id, interface_text)`.
- `close_tab(tab_id)` — Closes a non-persistent tab. Raises `ValueError` if persistent.
- `close_tabs_by_app(agent_id, app_id)` — Closes all non-persistent tabs for a given app.
- `close_all_tabs(agent_id)` — Closes all non-persistent tabs.
- `list_open_apps(agent_id)` — Returns all open tabs ordered by opened_at.
- `get_open_app(tab_id)` — Returns a single tab by ID.
- `ensure_persistent_tabs(agent_id)` — Creates or upgrades the `__list_apps__` system tab.
- `refresh_interface(tab_id)` — Re-generates interface text for a single tab.
- `refresh_interfaces(agent_id)` — Re-generates interface for all tabs of an agent.
- `get_agent_context(agent_id, past_actions_svc, max_past_actions)` — Assembles the complete context window. Returns a string with all tabs numbered `[tab 1]`, `[tab 2]`, etc. If a `PastActionsService` is provided, past actions are prepended as a `[tab 1]` section.
- `register_handler(app_id, handler)` — Registers an `AppHandler` subclass for a given `app_id` (called at startup for built-in apps like `list_directory` and `__list_apps__`).

**Context assembly flow** (`get_agent_context`):
1. Ensure persistent tabs exist (`__list_apps__`).
2. Refresh all tab interfaces.
3. If `past_actions_svc` is provided and has entries, prepend `[tab 1] [Past Actions]` section.
4. Number remaining open tabs starting from the next available number.
5. Return concatenated string.

Handler registration happens at application startup:
- `api_service/main.py` — registers `list_directory` and `__list_apps__` handlers.
- `sim_agent_service/simulator.py` — same registration for simulator mode.

---

## File: core/app/list_apps.py

**`ListAppsHandler`**: A system `AppHandler` that shows the available apps in the context window. It is registered as a persistent tab (`__list_apps__`) that cannot be closed.

The `generate_interface()` method:
1. Lists all available apps from `AppRegistry`.
2. Formats each app with its `app_id`, `name`, description, and an `{open_app:"..."}` invocation hint.
3. Returns the formatted text for display in the context window.

The `execute()` method returns a success response with the app count.

---

## File: core/time/time_service.py

**`TimeService`**: Configurable time progression that maps a real-world epoch to an agent-world epoch with a speed ratio.

**`TimeConfig`**: Dataclass holding the three configuration values:
- `real_epoch`: ISO datetime — the real-world moment that corresponds to...
- `agent_epoch`: ISO datetime — ...this agent-world moment.
- `ratio`: Float multiplier — how many agent-seconds pass per real second.

Example: `real_epoch = 1999-05-21`, `agent_epoch = 2024-06-15`, `ratio = 3.0` means that at real time 2026-06-06, the agent's clock shows approximately 2032-09-XX (27 real years × 3 = 81 agent years after 2024).

Time data is stored in the `time_config` key-value table in `cognithor.db` and persists across restarts.

Key methods:
- `get_config()` — Returns the current `TimeConfig`.
- `set_config(real_epoch, agent_epoch, ratio)` — Updates one or more config values.
- `now()` — Returns the current agent time as a `datetime.datetime`.
- `now_timestamp()` — Returns the current agent time as a Unix timestamp.

---

## File: core/past_actions.py

**`PastActionsService`**: Tracks a rolling window of past interactions (user inputs and system responses). Past actions are stored in the `past_actions` table in `cognithor.db` and persist across restarts.

**`PastActionRecord`**: Dataclass mirroring the `past_actions` table:
- `id`: Auto-increment primary key
- `agent_id`: Which agent this action belongs to
- `role`: `"user"`, `"assistant"`, `"system"`, or `"agent"`
- `content`: The action content (raw text or JSON)
- `created_at`: UTC timestamp when recorded
- `bot_timestamp`: Agent-local time (from `TimeService.now()`) when recorded

Key methods:
- `record_action(agent_id, role, content, time_svc)` — Inserts a new action. If `time_svc` is provided, the agent's current time is stored as `bot_timestamp`.
- `trim_actions(agent_id, max_count)` — Deletes the oldest actions for an agent until only `max_count` remain. Called after each batch of recordings.
- `get_recent_actions(agent_id, max_count)` — Returns the most recent `max_count` actions (oldest first).
- `count_actions(agent_id)` — Total actions stored for an agent.
- `clear_actions(agent_id)` — Deletes all actions for an agent.
- `generate_tab_interface(agent_id, max_count)` — Produces a formatted tab string for the context window. Returns `None` if no actions exist. Each action is shown as:
  ```
  [2024-06-15 14:30:00] USER: {"command": "open", ...}
  [2024-06-15 14:30:01] ASSISTANT: {"tab_id": "abc123", "status": "opened"}
  ```
  Parseable JSON content is pretty-printed with 2-space indent for readability.

The `max_past_actions` limit (default 15) is stored per-agent in the `agents.max_past_actions` column. It can be changed:
- Via the CLI (`Agent Management > Edit past actions limit`)
- Via the API (`PUT /agents/{agent_id}`)
- Programmatically through `AgentManager.update_agent()`

In the simulator (`-s` mode), every interaction is recorded as a past action — including malformed input, unknown commands, open/close operations, and plain-text messages. After each batch, `trim_actions()` keeps the total under the agent's configured limit.

**Important ordering rule**: When a command both records an assistant action AND refreshes the context window (e.g. `open`, `close`), the `record_action()` call **must** happen **before** `get_agent_context()` / `_ctx()`. This ensures the just-recorded assistant response is included in the Past Actions section of the refreshed context. Violating this order causes the agent to see stale past actions that end with its own input but lack the system's response.

---

## How the Files Work Together

```
 CLI / API / Simulator
       │
       ├── AppTabManager (app_manager.py)
       │       │
       │       ├── open_app() / close_tab()  →  agent_open_apps table
       │       ├── get_agent_context()       →  builds the context string
       │       │       │
       │       │       ├── [tab 1] Past Actions    ← PastActionsService.generate_tab_interface()
       │       │       ├── [tab 2] Available Apps  ← ListAppsHandler (persistent)
       │       │       └── [tab 3..N] Other tabs   ← registered AppHandlers
       │       │
       │       └── register_handler(app_id, handler)
       │
       ├── PastActionsService (past_actions.py)
       │       │
       │       ├── record_action()  →  past_actions table
       │       ├── generate_tab_interface()  →  formatted string for context
       │       └── trim_actions()  →  enforces max_past_actions limit
       │
       └── TimeService (time/time_service.py)
               │
               ├── now()  →  agent-local datetime
               └── PastActionsService uses this to timestamp actions
```

All services share the same `SecureDbService` instance, operating on the same `cognithor.db` file.

---

## Database Tables

**`agent_open_apps` table** — Open tabs (managed by `AppTabManager`):
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | 6-char unique tab ID |
| `agent_id` | TEXT NOT NULL | FK to agents |
| `app_id` | TEXT NOT NULL | App identifier |
| `tab_label` | TEXT | Optional user label |
| `params` | TEXT JSON | App parameters |
| `interface_text` | TEXT | Cached rendered display |
| `is_persistent` | INTEGER | 1 = cannot be closed (default 0) |
| `opened_at` / `updated_at` | TEXT | Timestamps |

**`time_config` table** — Time service config (managed by `TimeService`):
| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PK | Config key (e.g. `"real_epoch"`) |
| `value` | TEXT | Config value (ISO datetime or float string) |

**`past_actions` table** — Action history (managed by `PastActionsService`):
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `agent_id` | TEXT NOT NULL | FK to agents |
| `role` | TEXT NOT NULL | `"user"`, `"assistant"`, `"system"`, `"agent"` |
| `content` | TEXT NOT NULL | Full action content |
| `created_at` | TEXT | UTC timestamp (auto-set) |
| `bot_timestamp` | TEXT | Agent-local time (from TimeService) |

---

## Usage Example

```python
from core import AppTabManager, PastActionsService, TimeService

# Initialize with shared SecureDbService
app_tab_mgr = AppTabManager(svc=svc, app_registry=registry)
time_svc = TimeService(svc=svc)
past_actions_svc = PastActionsService(svc=svc)

# Record an interaction
past_actions_svc.record_action(
    agent_id="abc123",
    role="user",
    content='{"open_app": "list_directory"}',
    time_svc=time_svc,
)
past_actions_svc.record_action(
    agent_id="abc123",
    role="assistant",
    content='{"tab_id": "xyz789", "status": "opened"}',
    time_svc=time_svc,
)
past_actions_svc.trim_actions("abc123", max_count=15)

# Build the full context window
agent = agent_mgr.get_agent("abc123")
ctx = app_tab_mgr.get_agent_context(
    "abc123",
    past_actions_svc=past_actions_svc,
    max_past_actions=agent.max_past_actions,
)
print(ctx)
# [tab 1] [Past Actions]
#   Status: Open
#
#   [2024-06-15 14:30:00] USER: {"open_app": "list_directory"}
#   [2024-06-15 14:30:01] ASSISTANT: {"tab_id": "xyz789", "status": "opened"}
#
# [tab 2] [Available Apps] (Available Apps)
#   ...
```

---

## Adding a New System App Handler

To add a new system tab (like `__list_apps__`):

1. Create a handler class extending `AppHandler` with `generate_interface()` and `execute()`.
2. Register it at startup:
```python
app_tab_mgr.register_handler("my_system_app", MyHandler())
```
3. Open it as a persistent tab:
```python
app_tab_mgr.open_app(agent_id, "my_system_app", is_persistent=True)
```
