# Creating Apps for Cognithor

Apps are the tool-use layer that extends what agents can do. Each app is a
self-contained directory inside `apps/` with two required files. No core
code needs to be modified — discovery is automatic.

---

## File Structure

Every app lives in its own directory under `apps/`:

```
apps/
├── my_app/
│   ├── manifest.py          # Required: metadata and parameter schema
│   └── handler.py           # Required: logic (AppHandler subclass)
├── list_directory/
│   ├── manifest.py
│   └── handler.py
├── read_from_file/
│   ├── manifest.py
│   └── handler.py
├── terminal/
│   ├── manifest.py
│   └── handler.py
└── write_to_file/
    ├── manifest.py
    └── handler.py
```

---

## 1. `manifest.py` — App Metadata

Export a `MANIFEST` dictionary describing the app's identity, parameters,
and outputs:

```python
MANIFEST = {
    "app_id": "my_app",                    # unique ID (matches directory name)
    "name": "My App",                      # human-readable name
    "description": "What this app does.",  # shown in the agent's context
    "version": "1.0.0",
    "author": "your_name",
    "icon": "🔧",                           # single character or emoji (1-2 code points)
    "parameters": [                        # what the agent must/can pass
        {
            "name": "inputText",
            "type": "string",
            "description": "Text to process",
            "required": True,
        },
        {
            "name": "option",
            "type": "string",
            "description": "Optional setting",
            "required": False,
            "default": "default_value",
        },
    ],
    "outputs": [                           # what the execute() returns
        {
            "name": "result",
            "type": "string",
            "description": "Processed result",
            "required": True,
        },
    ],
}
```

### Field Reference

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `app_id` | `str` | (required) | Must be unique; use the directory name |
| `name` | `str` | (required) | Display name |
| `description` | `str` | `""` | Shown in app listings and tab interface |
| `version` | `str` | `"1.0.0"` | Semantic version |
| `author` | `str` | `"system"` | Who created this |
| `icon` | `str` | `"◆"` | Single character or emoji only |
| `parameters` | `list[dict]` | `[]` | Each param has: `name` (str), `type` (str), `description` (str), `required` (bool), `default` (any, optional), `enum` (list[str], optional) |
| `outputs` | `list[dict]` | `[]` | Same shape as parameters |
| `requires_confirmation` | `bool` | `False` | Reserved for future safety checks |
| `timeout_seconds` | `int` | `30` | Reserved for future execution timeout |
| `config_schema` | `list[dict]` | `[]` | Declares per-agent configuration fields. Each entry: `name` (str), `type` (str: `string`/`password`/`integer`/`boolean`), `label` (str), `description` (str), `required` (bool), `default` (any). Used by the CLI configuration form. |

---

## 2. `handler.py` — App Logic

Export a class that extends `AppHandler` and implements two methods:

```python
from typing import Optional
from core.app.app_manager import AppHandler

class MyAppHandler(AppHandler):
    def generate_interface(self, params: dict, tab_label: Optional[str] = None) -> str:
        """Return a text UI shown in the agent's context window."""
        return "\n".join([
            f"[my_app]{' (' + tab_label + ')' if tab_label else ''}",
            "  Status: Open",
            "",
            f"  Input: {params.get('inputText', '')}",
        ])

    def execute(self, params: dict) -> dict:
        """Perform the app action and return results."""
        text = params.get("inputText", "")
        result = text.upper()
        return {
            "success": True,
            "result": result,
            "bytes_processed": len(text),
        }
```

### `generate_interface(params, tab_label) -> str`

Build the text that the agent sees in its context window. The first line
should follow the convention `[app_id] (label)` so the agent knows which
tab it's looking at. A close-tag `{close_tab:"abc123"}` is appended
automatically for non-persistent tabs.

### `execute(params) -> dict`

The actual tool execution. Accept the parameters from the manifest, perform
the action, and return a dict. Always include `"success": True/False` in
the return value.

### `get_action_summary(params, result) -> Optional[str]` (optional)

Override to provide a short summary string for the past-actions log.
If not overridden, the default reads `result.get("past_action_summary")`.

### Side Effects — Opening / Updating Other Tabs

Your `execute()` can signal the system to open or update other tabs by
including special keys in the return dict. This works in both the
simulator and the production runner:

```python
{
    "success": True,
    "_open_tabs": [
        {"app_id": "read_from_file", "params": {"filePath": "/tmp/data.txt"}},
    ],
    "_update_tabs": [
        {"app_id": "notes", "tab_label": "Summary", "params": {"content": "...", "agent_id": agent_id}},
    ],
}
```

### `get_config_schema() -> list[dict]` (optional static method)

Override to declare what per-agent configuration your app accepts. This is
an alternative to `config_schema` in the manifest dict — the handler-level
version can compute the schema dynamically:

```python
class MyAppHandler(AppHandler):
    @staticmethod
    def get_config_schema() -> list[dict]:
        return [
            {"name": "api_key", "type": "password", "label": "API Key",
             "description": "Provider API key", "required": True},
            {"name": "max_results", "type": "integer", "label": "Max Results",
             "required": False, "default": 10},
        ]
```

The CLI reads this schema when the user opens the "Configure app for agent"
menu, and renders a form for each field.

---

## How the System Works

### Discovery

At startup, two scans happen automatically:

1. `AppRegistry.scan_apps_directory()` iterates `apps/`, reads each
   `manifest.py`, and registers the app in the database.
2. `AppTabManager.scan_app_handlers()` iterates the same directories,
   finds `handler.py`, dynamically imports it, locates the `AppHandler`
   subclass, and registers it.

No imports or registration calls in core code are needed for user-facing
apps. System apps (IDs prefixed `__`) are registered manually since they
need service injection.

### Agent ID Awareness

Every handler automatically receives `agent_id` in its `params` dict.
This is injected by `AppTabManager.open_app()` and `AgentRunner._do_execute()`
— you don't need to pass it explicitly. Your handler can use it for
per-agent state isolation:

```python
def execute(self, params: dict) -> dict:
    agent_id = params.get("agent_id")
    # ... do something specific to this agent
```

### Per-Agent App Configuration

Apps can declare a `config_schema` in `manifest.py` (see field reference).
The admin sets per-agent values via the CLI "Configure app for agent" menu
or the `PUT /agents/{id}/apps/{id}/config` API.

Your handler can access the config in two ways:

**1. During `execute()`** — the config is automatically injected into
params as `_app_config`:

```python
def execute(self, params: dict) -> dict:
    config = params.get("_app_config", {})
    api_key = config.get("api_key", "")
```

**2. Anywhere in the handler** — via `self.ctx.get_app_config()`:

```python
class MyAppHandler(AppHandler):
    def generate_interface(self, params: dict, tab_label=None) -> str:
        agent_id = params.get("agent_id", "")
        config = self.ctx.get_app_config(agent_id, "my_app")
        # ...
```

The `AppHandlerContext` object (`self.ctx`) is injected automatically when
the handler is instantiated by `scan_app_handlers()`. It provides
controlled access to core services without coupling your app to the
internals of Cognithor.

### Tab Lifecycle

- **Opening**: The agent sends `{"command": "open_app", "app_id": "...",
  "params": {...}}`. A tab is created in the DB with a unique 6-char ID.
- **Closing**: The agent sends `{"command": "close_tab", "tab_id": "..."}`.
  Non-persistent tabs are deleted.
- **Persistence**: System tabs (notes, diary, time) are persistent and
  cannot be closed by the agent.
- **Context**: On each turn, `get_agent_context()` rebuilds the full text
  view by calling `generate_interface()` on every open tab.

### Execution Flow

The production runner (`AgentRunner`) intercepts commands embedded in the
LLM's response text using JSON brace-matching:

```
I'll look that up for you.
{"command": "execute", "app_id": "list_directory", "action": {"path": "/tmp"}}
Here are the results...
```

The command block is removed from the response, the handler's `execute()`
is called, and the result is recorded in the agent's past actions.

Before executing, the system checks that the app is installed AND enabled
for the calling agent via `AgentAppManager`.

### Non-Blocking / Deferred Execution

All app execution is synchronous from the runner's perspective — the
handler's `execute()` runs to completion before the agent loop continues.
However, because tabs persist between turns, you can build a
"deferred-result" pattern:

1. Your `execute()` performs kick-off work, stores a reference in a tab,
   and returns immediately.
2. On the next turn, the agent sees the tab (via context rebuild) and
   can check the result or run a follow-up command.

```python
def execute(self, params: dict) -> dict:
    job_id = start_background_job(params.get("input", ""))
    return {
        "success": True,
        "job_id": job_id,
        "past_action_summary": f"Started job {job_id}",
        "_open_tabs": [
            {"app_id": "my_app", "tab_label": f"Job {job_id}",
             "params": {"job_id": job_id, "status": "running", "agent_id": params["agent_id"]}},
        ],
    }
```

If your app needs the runner to pause before the next LLM call (e.g.,
waiting for an external condition), include `_wait_seconds` in the result:

```python
return {
    "success": True,
    "status": "waiting_for_data",
    "_wait_seconds": 5,
}
```

This is the same mechanism used by the `wait` command.

---

## Testing with the Simulator

Cognithor includes an interactive simulator that lets you test your app
without starting the full API server.

### Launch

```bash
python main.py -s
```

This opens a JSON-protocol REPL where you can send commands and see the
agent's context window update in real time.

### Simulator Commands

| Command | Example | Description |
|---------|---------|-------------|
| `open_app` | `{"open_app": "my_app", "params": {"inputText": "hello"}}` | Open a tab for your app |
| `execute` | `{"command": "execute", "app_id": "my_app", "action": {"inputText": "hello"}}` | Run your app's handler |
| `close_tab` | `{"close_tab": "abc123"}` | Close a tab by ID |
| `list_apps` | `{"list_apps": true}` | Show available apps |
| `list_tabs` | `{"list_tabs": true}` | Show open tabs |
| `context` | `{"context": true}` | Show the full agent context |

### Quick Test Workflow

1. Start the simulator: `python main.py -s`
2. Select or create an agent in the simulator's agent menu
3. Install your app via the `App Management` menu (or use the API)
4. Test the flow:
   ```
   {"open_app": "my_app", "params": {"inputText": "hello"}}
   {"command": "execute", "app_id": "my_app", "action": {"inputText": "hello"}}
   ```
5. Watch the context update with your app's interface

The simulator behaves identically to the production runner for app
execution, so once it works here it will work in production.

---

## Configuring Apps via the CLI

The CLI provides a "Configure app for agent" menu under App Management.
When selected, it reads the app's `config_schema` (from `manifest.py`)
and renders a dynamic form for each field.

### Supported Field Types

| Type | CLI Input | Example |
|------|-----------|---------|
| `string` | Text prompt with default | `API Key [sk-...]:` |
| `password` | Text prompt (echo visible) | `Secret Key:` |
| `integer` | Numeric input | `Max Results [10]:` |
| `boolean` | Confirm prompt | `Enable logging? [y/N]:` |

### Example `config_schema` in `manifest.py`

```python
MANIFEST = {
    ...
    "config_schema": [
        {"name": "api_key", "type": "password", "label": "API Key",
         "description": "Provider API key", "required": True},
        {"name": "max_results", "type": "integer", "label": "Max Results",
         "required": False, "default": 10},
        {"name": "verbose", "type": "boolean", "label": "Verbose Logging",
         "required": False, "default": False},
    ],
}
```

The configured values are stored per-agent in the `agent_apps.config`
column and injected into `execute()` params as `_app_config`.

---

## Checklist for a Working App

- [ ] Directory created at `apps/<app_id>/`
- [ ] `manifest.py` exports `MANIFEST` dict
- [ ] `handler.py` exports an `AppHandler` subclass
- [ ] The directory name matches `manifest["app_id"]`
- [ ] `generate_interface()` returns a string the agent can read
- [ ] `execute()` returns a dict with `"success": bool`
- [ ] Tested in simulator: `python main.py -s`
- [ ] App installed for the target agent via CLI or API
