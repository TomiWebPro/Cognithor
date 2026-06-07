# Core Module — Architecture & Vision

The `core` package provides the runtime services that drive agent conversations: context window management, open-app tab system, past-action tracking with structured summaries, and configurable time progression.

The goal is a **tab-based context workspace** that the agent manages like a human manages browser tabs — each app opens a tab, user/agent actions are tracked as structured past actions, and apps can create or update tabs as part of their execution lifecycle.

---

## Directory Structure

```
core/
  __init__.py                   Re-exports all public symbols
  app/
    __init__.py
    app_manager.py              AppHandler, AppTabManager, AgentOpenAppRecord
    list_apps.py                ListAppsHandler (system persistent tab)
  past_action/
    __init__.py
    past_actions.py             PastActionsService, PastActionRecord
    handler.py                  PastActionsHandler (system persistent tab)
  agent/
    __init__.py
    runner.py                   AgentRunner — production agent loop
  time/
    __init__.py
    time_service.py             TimeService, TimeConfig
```

---

## The Tab System (`app/app_manager.py`)

### AppHandler — abstract base for all app tabs

```python
class AppHandler:
    def generate_interface(self, params: dict, tab_label: str | None = None) -> str: ...
    def execute(self, params: dict) -> dict: ...
    def get_action_summary(self, params: dict, result: dict) -> str | None:
        return result.get("past_action_summary")
```

Every app that wants to appear as a tab registers an `AppHandler`. The handler controls what the agent sees (`generate_interface`) and what happens when the agent sends an action (`execute`).

`get_action_summary()` lets the app provide a human-readable string describing what `execute()` did. This feeds into the Past Actions tab so the agent sees clean summaries like `"Edited lines 345-432 in main.py"` instead of raw JSON.

### AppTabManager — tab lifecycle

| Method | Purpose |
|--------|---------|
| `open_app(agent_id, app_id, tab_label, params, is_persistent)` | Create a new tab → returns `(tab_id, interface_text)` |
| `close_tab(tab_id)` | Close a non-persistent tab |
| `close_tabs_by_app(agent_id, app_id)` | Close all non-persistent tabs for an app |
| `close_all_tabs(agent_id)` | Close all non-persistent tabs |
| `list_open_apps(agent_id)` | List tabs ordered by opened_at |
| `get_open_app(tab_id)` | Get a single tab by ID |
| `update_tab_params(tab_id, params)` | Update stored params of a tab → re-rendered on next refresh |
| `refresh_interface(tab_id)` | Re-generate interface text |
| `refresh_interfaces(agent_id)` | Re-generate all tab interfaces |
| `ensure_persistent_tabs(agent_id, max_past_actions)` | Auto-open system persistent tabs |
| `get_agent_context(agent_id, max_past_actions)` | Assemble the full context window string |
| `set_tab_persistence(tab_id, persistent)` | Toggle whether a tab can be closed |
| `register_handler(app_id, handler)` | Register an AppHandler for an app ID |

### Context Assembly Flow (`get_agent_context`)

1. Ensure persistent system tabs exist (`__list_apps__`, `__past_actions__`).
2. Refresh all tab interfaces.
3. Iterate tabs in order, numbering them `[tab 1]`, `[tab 2]`, etc.
4. For each tab, if `is_persistent=True`, auto-append `"  (persistent tab)"` — no hardcoded text in handlers.
5. Return concatenated string.

### Persistence Toggle

Any tab's persistence can be toggled:
- **API**: `PATCH /tabs/{tab_id}/persist` with `{"persistent": true/false}`
- **CLI**: Apps menu → "Toggle tab persistence"
- **Programmatic**: `app_tab_mgr.set_tab_persistence(tab_id, bool)`

Persistent tabs cannot be closed (raises `ValueError`).

---

## The Past Actions System (`past_action/past_actions.py`)

### PastActionRecord — structured history

| Field | Type | Purpose |
|-------|------|---------|
| `id` | int | Auto-increment PK |
| `agent_id` | str | FK to agents |
| `role` | str | `"user"`, `"assistant"`, `"system"`, `"agent"` |
| `content` | str | Full JSON payload (preserved for replay/debug) |
| `app_id` | str or None | Which app produced this action |
| `summary` | str or None | Human-readable summary from the app |
| `created_at` | str | UTC timestamp |
| `bot_timestamp` | str | Agent-local time from TimeService |

### How recording works

```python
# Legacy — raw content
pas.record_action(agent_id, "user", '{"command": "read", "path": "main.py"}')

# Structured — with app context
pas.record_action(agent_id, "assistant", '{"success": true, ...}',
                  app_id="read_from_file",
                  summary="Read main.py (145 lines)")
```

### Tab rendering

The past actions tab renders using `summary` if available, falling back to `content`. If `app_id` is set, it shows as a prefix:

```
YOU: read file main.py
HARNESS [read_from_file]: Read main.py (145 lines)
HARNESS [edit]: Edited lines 345-432 in main.py
```

---

## The `_open_tabs` / `_update_tabs` Contract

When an app's `execute()` returns a result dict, it can include instructions for the tab system:

```python
{
    "success": True,
    "past_action_summary": "Listed 42 entries in /home",
    "_open_tabs": [
        {"app_id": "list_directory", "tab_label": "/home", "params": {"entries": [...]}}
    ],
    "_update_tabs": [
        {"app_id": "list_directory", "tab_label": "/home", "params": {"entries": [...]}}
    ],
}
```

The dispatch layer (in `sim_agent_service/simulator.py` and future agent runners) processes these:

1. `_open_tabs` → calls `app_tab_mgr.open_app()` to create new content tabs
2. `_update_tabs` → finds existing tab by `app_id` + `tab_label`, updates its params, refreshes interface

This is how an agent's workflow works in practice:

```
Tab 3: [read_from_file] — shows "Commands: read <path>"
Agent sends: {"command": "execute", "app_id": "read_from_file", "action": {"path": "main.py"}}

ReadFileHandler.execute() returns:
  { success: true, _open_tabs: [{app_id: "read_from_file", tab_label: "main.py",
     params: {lines: [...], path: "main.py"}}],
     past_action_summary: "Read main.py (145 lines)" }

Tab 3: [read_from_file] — still shows commands
Tab 4: [main.py] — shows file content line by line ← NEW TAB

Agent sends: {"command": "execute", "app_id": "edit", "action": {"path": "main.py", "lines": "345-432"}}

EditHandler.execute() returns:
  { success: true, _update_tabs: [{app_id: "read_from_file", tab_label: "main.py",
     params: {lines: [edited...], path: "main.py"}}],
     past_action_summary: "Edited lines 345-432 in main.py" }

Tab 4: [main.py] — now shows EDITED content ← UPDATED

Agent closes tab: Tab 4 gone.
```

The key principle: **core provides the mechanism, apps own their display**. No core-level handler per content type exists. Each app's `generate_interface()` decides what its tab looks like, and each app's `execute()` decides what tabs to create or update.

---

## System Persistent Tabs

Two tabs are always open and cannot be closed:

| App ID | Handler | Purpose |
|--------|---------|---------|
| `__list_apps__` | `ListAppsHandler` | Lists available apps with `{open_app:"..."}` commands |
| `__past_actions__` | `PastActionsHandler` | Shows recent action history with summaries |

Opened automatically by `ensure_persistent_tabs()`, configured via `AppTabManager._SYSTEM_PERSISTENT_APPS`.

---

## Agent Runner (`agent/runner.py`)

The production `AgentRunner`:
1. Builds context window via `app_tab_mgr.get_agent_context(agent_id)`
2. Sends context + system prompt to the LLM endpoint
3. Records the assistant response as a past action

It does NOT parse agent responses for commands (that's the simulator layer). For production, command parsing and `_open_tabs`/`_update_tabs` processing belong in a higher-level agent loop.

---

## How the Files Work Together

```
 CLI / API / Simulator
       │
       ├── AppTabManager (app/app_manager.py)
       │       │
       │       ├── open_app() / close_tab()     →  agent_open_apps table
       │       ├── get_agent_context()          →  builds context string
       │       ├── update_tab_params()          →  update tab content
       │       └── _find_tab_by_app_and_label() →  update existing tabs
       │
       ├── PastActionsService (past_action/past_actions.py)
       │       │
       │       ├── record_action(agent_id, role, content, app_id, summary)
       │       ├── generate_tab_interface()     →  renders with app_id/summary
       │       └── trim_actions()               →  enforces max_past_actions
       │
       ├── PastActionsHandler (past_action/handler.py)
       │       └── wraps above as a persistent tab
       │
       ├── ListAppsHandler (app/list_apps.py)
       │       └── persistent tab listing available apps
       │
       └── AppHandler.execute() contract
               │
               ├── past_action_summary  →  clean entry in Past Actions tab
               ├── _open_tabs           →  creates new content tabs
               └── _update_tabs         →  updates existing content tabs
```

---

## Database Tables

**`agent_open_apps`** — Open tabs:
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | 6-char unique tab ID |
| `agent_id` | TEXT NOT NULL | FK to agents |
| `app_id` | TEXT NOT NULL | App identifier |
| `tab_label` | TEXT | Optional user label |
| `params` | TEXT JSON | App parameters |
| `interface_text` | TEXT | Cached rendered display |
| `is_persistent` | INTEGER | 1 = cannot be closed |
| `opened_at` / `updated_at` | TEXT | Timestamps |

**`past_actions`** — Structured action history:
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `agent_id` | TEXT NOT NULL | FK to agents |
| `role` | TEXT NOT NULL | `"user"`, `"assistant"`, `"system"`, `"agent"` |
| `content` | TEXT NOT NULL | Full payload (preserved) |
| `app_id` | TEXT | Which app produced this |
| `summary` | TEXT | Human-readable summary |
| `created_at` | TEXT | UTC timestamp |
| `bot_timestamp` | TEXT | Agent-local time |

---

## Design Principles (Don't Lose These)

1. **Core provides mechanism, not content.** No core-level handler per content type. `AppHandler` and the `_open_tabs`/`_update_tabs` contract are generic — apps decide what to display and when to create tabs.

2. **Past actions are structured, not flat.** `app_id` + `summary` separate human-readable display from machine-readable payload. The tab renders summaries, preserving JSON for debugging.

3. **Persistence comes from DB, not from code.** The `"(persistent tab)"` label is auto-appended by context builder based on `is_persistent` column. Handlers never hardcode it.

4. **Tabs are the agent's workspace.** Like browser tabs: tool tabs show commands, content tabs show results, the agent opens/closes/updates them as it works.

5. **No special cases in dispatch.** Past actions are a tab like any other. The dispatch doesn't need to know about past actions — the handler encapsulates it.
