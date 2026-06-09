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
including special keys in the return dict:

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
This is injected by `AppTabManager.open_app()` — you don't need to pass
it explicitly. Your handler can use it for per-agent state isolation:

```python
def execute(self, params: dict) -> dict:
    agent_id = params.get("agent_id")
    # ... do something specific to this agent
```

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

## Checklist for a Working App

- [ ] Directory created at `apps/<app_id>/`
- [ ] `manifest.py` exports `MANIFEST` dict
- [ ] `handler.py` exports an `AppHandler` subclass
- [ ] The directory name matches `manifest["app_id"]`
- [ ] `generate_interface()` returns a string the agent can read
- [ ] `execute()` returns a dict with `"success": bool`
- [ ] Tested in simulator: `python main.py -s`
- [ ] App installed for the target agent via CLI or API
