# Core Module — Architecture & Vision

The `core` package provides the runtime services that drive agent conversations: context window management, open-app tab system, past-action tracking with structured summaries, configurable time progression, alarm scheduling, and a background daemon scheduler for waking idle agents.

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
  notes/
    __init__.py
    notes_handler.py            NotesHandler (system persistent tab)
  diary/
    __init__.py
    diary_service.py            DiaryService, DiaryEntry
    diary_handler.py            DiaryHandler (system persistent tab)
  agent/
    __init__.py
    runner.py                   AgentRunner — production agent loop
  time/
    __init__.py
    time_service.py             TimeService, TimeConfig
    time_handler.py             TimeHandler (system persistent tab — [Time])
    alarm_service.py            AlarmService — agent_alarms CRUD + trigger
    scheduler.py                AlarmScheduler — background daemon thread
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

Accepts flags: `show_context_window`, `show_notes`, `show_diary`, `show_time`.

1. Ensure persistent system tabs exist — deletes tabs for disabled features, creates ones for enabled.
2. Refresh all tab interfaces — each handler re-reads from its DB table.
3. Sort tabs: **all persistent tabs first** (by `opened_at`), then non-persistent tabs (also by `opened_at`).
4. Iterate tabs in order, numbering them `[tab 1]`, `[tab 2]`, etc.
5. For each tab, if `is_persistent=True`, auto-append `"  (persistent tab)"` — no hardcoded text in handlers.
6. Context window tab is always rendered last (after all other tabs).
7. Count tokens for the context window tab and update its params.
8. Return concatenated string.

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

Five system persistent tabs provide the agent's workspace context. Each can be toggled per-agent via boolean flags on the `agents` record:

| App ID | Handler | Toggle Flag | Purpose |
|--------|---------|-------------|---------|
| `__list_apps__` | `ListAppsHandler` | always on | Lists available apps with `{open_app:"..."}` commands |
| `__past_actions__` | `PastActionsHandler` | always on | Shows recent action history with summaries |
| `__context_window__` | `ContextWindowHandler` | `show_context_window` | Shows token usage (`Tokens: N / M, Usage: X%`) |
| `__notes__` | `NotesHandler` | `show_notes` | Temporal memory — overwritable note with interaction-based expiry |
| `__diary__` | `DiaryHandler` | `show_diary` | Long-term memory — today's append-only diary entry, dated by simulated clock |
| `__time__` | `TimeHandler` | `show_time` | Displays agent simulated time, UTC time, ratio, pending alarms, and command docs |

Opened automatically by `ensure_persistent_tabs()`, configured via `AppTabManager._SYSTEM_PERSISTENT_APPS = ["__list_apps__", "__past_actions__", "__context_window__", "__notes__", "__diary__", "__time__"]`.

---

## Notes — Temporal Memory (`notes/notes_handler.py`)

The Notes tab gives the agent a short-term, overwritable scratchpad. It sits in the context window whenever `show_notes` is enabled, and auto-expires after a configurable number of context renders.

### Agent commands

| Command | Effect |
|---------|--------|
| `{"command": "write_note", "content": "..."}` | Overwrites the entire note |
| `{"command": "write_note", "content": "...", "max_interactions": 5}` | Same, but sets a custom expiry (default 10) |
| `{"command": "extend_note", "max_interactions": 10}` | Resets the interaction counter to 0, updates expiry limit |

### Expiry lifecycle

1. On `write_note`, the note stores `content`, `max_interactions` (default 10), and `interaction_count = 0`.
2. Each call to `generate_interface()` (triggered by every context assembly) increments `interaction_count`.
3. When `interaction_count >= max_interactions`, the content is auto-cleared — the tab shows the empty placeholder.
4. When `interaction_count == max_interactions - 1`, an expiry warning is appended to the interface: `⚠️ Will expire in 1 interaction. Use extend_note.`
5. `extend_note` resets `interaction_count` to 0 and updates the `max_interactions` threshold.

### Tab rendering

```
[Notes]
  Status: Open

  my plan here
  (created 2026-06-08 12:22:00, expires in 8 interactions)
  ⚠️ Will expire in 1 interaction. Use extend_note.

  To write:  {"command": "write_note", "content": "..."}
  To extend: {"command": "extend_note", "max_interactions": <number>}
  (persistent tab)
```

### Past-actions exclusion

`write_note` and `extend_note` commands are **never recorded** in the past actions tab. The dispatch layer (simulator and runner) silently executes them and strips them from the response before anything reaches `PastActionsService`. This keeps the action history clean of transient scratchpad writes.

### Per-agent toggle

Controlled by the boolean `show_notes` field on the `agents` record (default `true`). When toggled off, the `__notes__` tab is deleted from `agent_open_apps`.

---

## Diary — Long-Term Memory (`diary/diary_service.py`, `diary/diary_handler.py`)

The Diary tab provides append-only, date-stamped long-term storage. Each simulated day (from `TimeService.now()`) gets one entry that accumulates all writes. Past entries can be listed but never modified.

### Agent commands

| Command | Effect |
|---------|--------|
| `{"command": "write_diary", "content": "..."}` | Appends to today's entry (creates if first write today) |
| `{"command": "list_diary"}` | Lists all past diary entries as JSON |
| `{"command": "list_diary", "date": "2026-06-08"}` | Lists entries for a specific date |

### Append-only semantics

1. `DiaryService.append_diary()` reads `TimeService.now()` to determine today's date (`YYYY-MM-DD`).
2. If no entry exists for today → creates a new row with the given content.
3. If an entry already exists → appends `"\n" + new content` to the existing content.
4. There is **no** update or delete exposed to the agent. Past entries are immutable.
5. The simulated clock is used — if time passes (via `TimeService` ratio/epoch config), "today" changes and a new diary day begins.

### Tab rendering

```
[Diary]
  Status: Open

  Today: 2026-06-08
  Entry:
  first diary entry
  second line

  To write today: {"command": "write_diary", "content": "..."}
  To list past:   {"command": "list_diary"} or {"command": "list_diary", "date": "YYYY-MM-DD"}
  (persistent tab)
```

### Per-agent toggle

Controlled by the boolean `show_diary` field on the `agents` record (default `true`). When toggled off, the `__diary__` tab is deleted from `agent_open_apps`.

---

## Time — Simulated Clock & Alarm System (`time/`)

The time system provides three components: a configurable simulated clock, a persistent `[Time]` tab, and a full alarm/wait system with background daemon scheduling.

### TimeService — Simulated Clock (`time/time_service.py`)

Maps real-world UTC time to agent-simulated time via epoch mapping and ratio:

| Config | Default | Description |
|--------|---------|-------------|
| `real_epoch` | `1970-01-01T00:00:00+00:00` | Real-world reference datetime |
| `agent_epoch` | `1970-01-01T00:00:00+00:00` | Agent-world reference datetime |
| `ratio` | `1.0` | Multiplier (1 real second = N agent seconds) |

**Example**: `real_epoch=2000-01-01`, `agent_epoch=2025-01-01`, `ratio=60.0` → each real second advances the agent clock by 1 minute. A query at real `2026-06-09` would return agent time ~2026-06-09 + 60× elapsed from 2000.

### TimeHandler — The `[Time]` Tab (`time/time_handler.py`)

A system persistent tab (`__time__`) that shows:
- Agent simulated time
- Human (UTC) time
- Ratio and epoch configuration
- Pending alarms list
- Command documentation for alarms and wait

**Tab rendering:**
```
[Time]
  Status: Open

  Agent Simulated Time:  2026-06-09 05:15:27 UTC
  Human (UTC) Time:      2026-06-09 05:15:27 UTC
  Ratio:                 1.0x
  Agent Epoch:           1970-01-01T00:00:00+00:00
  Real Epoch:            1970-01-01T00:00:00+00:00

  Commands:
    Set alarm:   {"command": "set_alarm", "time": "<ISO datetime>", "message": "..."}
    With type:   {"command": "set_alarm", "time": "...", "time_type": "agent|real", "message": "..."}
    Acknowledge: {"command": "acknowledge_alarm", "alarm_id": "..."}
    Wait:        {"command": "wait", "duration": <seconds>, "time_type": "agent|real"}
    Wait until:  {"command": "wait_until", "time": "<ISO datetime>", "time_type": "agent|real"}
  (persistent tab)
```

Toggled via the boolean `show_time` field on the `agents` record (default `true`).

### AlarmService — Alarm CRUD (`time/alarm_service.py`)

| Method | Description |
|--------|-------------|
| `set_alarm(agent_id, alarm_time, time_type, message)` | Create alarm; if `time_type="real"`, converts to agent time via ratio |
| `check_alarms(agent_id)` | Returns all due+non-triggered alarms, marks them triggered |
| `get_triggered_alarms(agent_id)` | Returns all triggered+unacknowledged alarms |
| `get_pending_alarms(agent_id)` | Returns future non-triggered alarms (for Time tab display) |
| `acknowledge_alarm(alarm_id)` | Deletes the alarm |
| `cancel_alarm(alarm_id)` | Deletes only if not yet triggered |
| `list_alarms(agent_id)` | Returns all alarms regardless of state |

When `time_type="real"`, the alarm time is converted to agent time by:
```
elapsed_real = alarm_time - real_now
agent_offset = elapsed_real * ratio
converted = agent_now + agent_offset
```

### AlarmScheduler — Background Daemon (`time/scheduler.py`)

A daemon thread that runs at a configurable interval (default 1s):

1. Queries `agent_alarms` for non-triggered alarms where `alarm_time <= now`
2. Atomically marks each as `triggered=1` (with `rowcount` guard for race safety)
3. If `agent.status == "idle"`, sets it to `"active"` (wakes the agent)
4. Logs all events

The scheduler is started in:
- **API**: FastAPI lifespan (`startup` event)
- **CLI**: `_init_services()` on interactive launch
- **Simulator**: `_init_services()` on startup

### Alarm Notification in Context

When `AgentRunner.run()` is called:
1. It calls both `check_alarms(agent_id)` (catches edge-case alarms the scheduler hasn't seen yet) and `get_triggered_alarms(agent_id)` (picks up scheduler-triggered alarms)
2. Merges and deduplicates by alarm ID
3. If any triggered alarms exist, injects an `[Alarm Ringing!]` block at the **top** of the context:

```
[Alarm Ringing!]
  time to check! (id=m61amau0)
  Acknowledge: {"command": "acknowledge_alarm", "alarm_id": "..."}
```

4. The agent can acknowledge via `{"command": "acknowledge_alarm", "alarm_id": "..."}`, which deletes the alarm from the DB.

### Agent Commands (Parsed in `AgentRunner._handle_alarm_wait_commands`)

| Command | Effect |
|---------|--------|
| `{"command": "set_alarm", "time": "...", "message": "..."}` | Sets an agent-time alarm |
| `{"command": "set_alarm", "time": "...", "time_type": "real", "message": "..."}` | Sets a real-time alarm (converted via ratio) |
| `{"command": "acknowledge_alarm", "alarm_id": "..."}` | Acknowledges a triggered alarm (deletes it) |
| `{"command": "wait", "duration": <seconds>}` | Returns `{"response": ..., "wait": N}` — caller sleeps N seconds |
| `{"command": "wait_until", "time": "...", "time_type": "agent\|real"}` | Returns `{"response": ..., "wait": N}` — caller calculates sleep |

The `wait` commands return the duration in the result dict. The caller (simulator or future production loop) is responsible for sleeping. The simulator implements this with `time.sleep()`.

### Wake-on-Alarm Flow

```
Scheduler ticks → finds due alarm → marks triggered → agent status=idle?
                                                          │
                                                     ┌─────┴──────┐
                                                     yes          no
                                                       │            │
                                                  set active     (agent is
                                                       │        already running)
                                                  next loop     next run()
                                                  picks up         │
                                                  agent now    triggered alarms
                                                  active       injected in ctx
```

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
       │       ├── get_agent_context(
       │       │     show_notes, show_diary)    →  builds context string
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
       ├── NotesHandler (notes/notes_handler.py)
       │       │
       │       ├── set_notes() / extend_note()  →  agent_notes table
       │       ├── generate_interface()         →  checks expiry, increments counter
       │       └── execute()                    →  handles write_note command
       │
       ├── DiaryService (diary/diary_service.py)
       │       │
       │       ├── append_diary()               →  agent_diary table (append-only)
       │       └── list_entries()               →  past entries, filterable by date
       │
       ├── DiaryHandler (diary/diary_handler.py)
       │       └── generate_interface()         →  reads today's entry from DiaryService
       │
       ├── ListAppsHandler (app/list_apps.py)
       │       └── persistent tab listing available apps
       │
        ├── TimeService (time/time_service.py)
        │       └── now()                        →  provides simulated clock for diary dating, alarm comparison, and time tab display
        │
        ├── TimeHandler (time/time_handler.py)
        │       └── [Time] persistent tab showing agent time, UTC, ratio, alarm commands
        │
        ├── AlarmService (time/alarm_service.py)
        │       │
        │       ├── set_alarm()                  →  agent_alarms table (supports agent/real time types)
        │       ├── check_alarms()               →  marks due alarms as triggered
        │       ├── get_triggered_alarms()       →  returns triggered + unacknowledged alarms
        │       ├── acknowledge_alarm()          →  deletes alarm from DB
        │       ├── cancel_alarm()               →  deletes non-triggered alarm
        │       └── get_pending_alarms()         →  returns non-triggered alarms for display in Time tab
        │
        ├── AlarmScheduler (time/scheduler.py)
        │       │
        │       ├── daemon thread polling every ~1s
        │       ├── marks triggered alarms atomically
        │       └── wakes idle agents (status idle → active)
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

**`agent_notes`** — Notes (temporal memory):
| Column | Type | Description |
|--------|------|-------------|
| `agent_id` | TEXT PK | FK to agents |
| `content` | TEXT | Note body (cleared on expiry) |
| `max_interactions` | INTEGER | Lifespan in context renders (default 10) |
| `interaction_count` | INTEGER | Times `generate_interface()` has been called |
| `created_at` | TEXT | Timestamp of last write |
| `updated_at` | TEXT | Timestamp of last update |

**`agent_diary`** — Diary (long-term memory):
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `agent_id` | TEXT NOT NULL | FK to agents |
| `date` | TEXT NOT NULL | Simulated date (`YYYY-MM-DD`) |
| `content` | TEXT NOT NULL | Accumulated entry for that day |
| `created_at` | TEXT | Timestamp of first write |
| `updated_at` | TEXT | Timestamp of last append |

**`agent_alarms`** — Alarms:
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | 8-char unique alarm ID |
| `agent_id` | TEXT NOT NULL | FK to agents |
| `alarm_time` | TEXT NOT NULL | ISO datetime (converted to agent time if `time_type="real"`) |
| `time_type` | TEXT | `"agent"` or `"real"` — how the time was specified |
| `message` | TEXT | Optional alarm message |
| `triggered` | INTEGER | 0 = pending, 1 = fired |
| `created_at` | TEXT | UTC timestamp of creation |

The agents table also has two additional columns for time/alarm support:
| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `show_time` | INTEGER | 1 | Whether to show the `[Time]` tab in context |
| `status` | TEXT | `"active"` | `"active"` = running, `"idle"` = sleeping (woken by scheduler) |

---

## Design Principles (Don't Lose These)

1. **Core provides mechanism, not content.** No core-level handler per content type. `AppHandler` and the `_open_tabs`/`_update_tabs` contract are generic — apps decide what to display and when to create tabs.

2. **Past actions are structured, not flat.** `app_id` + `summary` separate human-readable display from machine-readable payload. The tab renders summaries, preserving JSON for debugging.

3. **Persistence comes from DB, not from code.** The `"(persistent tab)"` label is auto-appended by context builder based on `is_persistent` column. Handlers never hardcode it.

4. **Tabs are the agent's workspace.** Like browser tabs: tool tabs show commands, content tabs show results, the agent opens/closes/updates them as it works.

5. **No special cases in dispatch.** Past actions are a tab like any other. The dispatch doesn't need to know about past actions — the handler encapsulates it.
