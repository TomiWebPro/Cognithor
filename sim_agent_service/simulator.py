"""Agent Simulation CLI — JSON protocol for testing agent context coherence.

All output is JSON-wrapped. Input accepts plain text (treated as agent
input) or JSON objects/arrays (commands or batched commands).

Usage: python main.py -s
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich.text import Text
from rich import box as rich_box
from cli_service.display import console, print_banner, print_error, print_warning, print_hint

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "cognithor.db"
APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

PYSQLCIPHER_AVAILABLE = False
try:
    from pysqlcipher3 import dbapi2 as _pysqlcipher
    PYSQLCIPHER_AVAILABLE = True
except ImportError:
    pass


def _detect_encryption() -> bool:
    if not DB_PATH.exists():
        return PYSQLCIPHER_AVAILABLE
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
        return False
    except sqlite3.DatabaseError:
        pass
    try:
        from secure_db_service import SecureDbService
        svc = SecureDbService(db_path=DB_PATH, use_encryption=True)
        svc.query_one("SELECT 1")
        return True
    except Exception:
        pass
    return False


def _init_services(use_encryption: bool = False) -> dict:
    from secure_db_service import SecureDbService
    from log_service import LogDatabase, LogService
    from endpoint.database import Tracker
    from api_service.database import ApiConfigManager
    from agents_service.database import AgentManager
    from apps_service.database import AppRegistry, AgentAppManager
    from core import AppTabManager, ListAppsHandler
    from apps.list_directory.handler import ListDirectoryHandler

    log_db = LogDatabase(
        db_path=str(DATA_DIR / "cognithor_logs.db"),
        use_encryption=use_encryption,
    )
    log_svc = LogService(database=log_db)

    svc = SecureDbService(
        db_path=DB_PATH,
        use_encryption=use_encryption,
        wal_mode=True,
        retry_attempts=5,
        retry_delay_seconds=0.1,
        service_name="Cognithor",
        key_name="db_key",
    )

    tracker = Tracker(db_path=str(DB_PATH), svc=svc, log_service=log_svc)
    config_mgr = ApiConfigManager(db_path=str(DB_PATH), svc=svc, key_name="db_key")
    agent_mgr = AgentManager(svc=svc)

    app_registry = AppRegistry(svc=svc)
    app_registry.scan_apps_directory(str(APPS_DIR))
    agent_app_mgr = AgentAppManager(svc=svc)

    app_tab_mgr = AppTabManager(svc=svc, app_registry=app_registry)
    app_tab_mgr.register_handler("list_directory", ListDirectoryHandler())
    app_tab_mgr.register_handler("__list_apps__", ListAppsHandler(app_registry))

    return {
        "svc": svc,
        "config_mgr": config_mgr,
        "agent_mgr": agent_mgr,
        "app_registry": app_registry,
        "agent_app_mgr": agent_app_mgr,
        "app_tab_mgr": app_tab_mgr,
    }


def _oj(data: dict, indent: Optional[int] = None) -> str:
    return json.dumps(data, indent=indent)


def _context(agent_id: str, app_tab_mgr) -> str:
    return app_tab_mgr.get_agent_context(agent_id)


def _handle_open(args: dict, services: dict, agent_id: str) -> Optional[dict]:
    app_id = args.get("app_id") or args.get("_raw")
    tab_label = args.get("tab_label")
    params = args.get("params")

    app_tab_mgr = services["app_tab_mgr"]
    app_registry = services["app_registry"]

    app = app_registry.get_app(app_id) if app_id and not app_id.startswith("__") else None
    if app is None and not (app_id and app_id.startswith("__")):
        return {"error": f"App '{app_id}' not found"}

    try:
        tab_id, interface = app_tab_mgr.open_app(
            agent_id=agent_id,
            app_id=app_id,
            tab_label=tab_label,
            params=params,
        )
        return {"tab_id": tab_id, "app_id": app_id, "status": "opened", "interface": interface}
    except ValueError as e:
        return {"error": str(e)}


def _handle_close(args: dict, services: dict, agent_id: str) -> Optional[dict]:
    tab_id = args.get("tab_id") or args.get("_raw", "").strip()
    if not tab_id:
        return {"error": "tab_id required"}

    app_tab_mgr = services["app_tab_mgr"]
    try:
        if app_tab_mgr.close_tab(tab_id):
            return {"tab_id": tab_id, "status": "closed"}
        return {"error": f"Tab '{tab_id}' not found"}
    except ValueError as e:
        return {"error": str(e)}


def _handle_input(
    content: str,
    services: dict,
    agent_id: str,
) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"raw": content}

    app_tab_mgr = services["app_tab_mgr"]
    app_tab_mgr.refresh_interfaces(agent_id)
    ctx = _context(agent_id, app_tab_mgr)

    combined = ctx + "\n\n" + content if ctx else content
    return {
        "status": "received",
        "input": parsed,
        "context": ctx,
        "combined_payload": combined,
    }


_SHORTCUTS = {
    "open_app": ("open", "app_id"),
    "close_tab": ("close", "tab_id"),
    "list_apps": ("apps", None),
    "list_tabs": ("tabs", None),
    "context": ("context", None),
    "help": ("help", None),
    "quit": ("quit", None),
    "exit": ("quit", None),
}


def _normalize(item: dict) -> dict:
    for key, (cmd, prop) in _SHORTCUTS.items():
        if key in item:
            normalized = {"command": cmd}
            val = item[key]
            if isinstance(val, dict):
                normalized.update(val)
            if prop and val and not isinstance(val, dict):
                normalized[prop] = val
            for k, v in item.items():
                if k != key:
                    normalized[k] = v
            return normalized
    return item


def _fix_json_keys(raw: str) -> str:
    return re.sub(r'(\{|\,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', raw)


def _dispatch(raw: str, services: dict, agent_id: str) -> list[dict]:
    results = []
    raw = raw.strip()

    if not raw:
        return results

    clean = raw.replace('\\"', '"')
    clean = _fix_json_keys(clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        parsed = {"input": raw}

    items = parsed if isinstance(parsed, list) else [parsed]

    for item in items:
        if not isinstance(item, dict):
            results.append({"error": "Each item must be a JSON object", "raw": str(item)})
            continue

        item = _normalize(item)

        command = item.get("command", "").lower().lstrip("/")
        if not command:
            results.append(_handle_input(json.dumps(item), services, agent_id))
            continue

        if command in ("open",):
            result = _handle_open(item, services, agent_id)
            if result:
                results.append({"type": "result", "command": "open", "data": result})
                results.append({"type": "context", "content": _context(agent_id, services["app_tab_mgr"])})
        elif command in ("close",):
            result = _handle_close(item, services, agent_id)
            if result:
                results.append({"type": "result", "command": "close", "data": result})
                results.append({"type": "context", "content": _context(agent_id, services["app_tab_mgr"])})
        elif command in ("context",):
            results.append({"type": "context", "content": _context(agent_id, services["app_tab_mgr"])})
        elif command in ("tabs",):
            tabs = services["app_tab_mgr"].list_open_apps(agent_id)
            results.append({
                "type": "result",
                "command": "tabs",
                "data": [
                    {"tab_id": t.id, "app_id": t.app_id, "tab_label": t.tab_label,
                     "is_persistent": t.is_persistent}
                    for t in tabs
                ],
            })
        elif command in ("apps",):
            apps = services["app_registry"].list_available_apps()
            results.append({
                "type": "result",
                "command": "apps",
                "data": [
                    {"app_id": a.app_id, "name": a.name, "description": a.description, "icon": a.icon}
                    for a in apps
                ],
            })
        elif command in ("help",):
            results.append({
                "type": "help",
                "commands": {
                    "open": {"usage": '{"command": "open", "app_id": "...", "tab_label": "...", "params": {...}}', "description": "Open an app tab"},
                    "close": {"usage": '{"command": "close", "tab_id": "..."}', "description": "Close a non-persistent tab"},
                    "context": {"usage": '{"command": "context"}', "description": "Show current context window"},
                    "tabs": {"usage": '{"command": "tabs"}', "description": "List open tabs"},
                    "apps": {"usage": '{"command": "apps"}', "description": "List available apps"},
                    "help": {"usage": '{"command": "help"}', "description": "Show this help"},
                    "quit": {"usage": '{"command": "quit"}', "description": "Exit simulator"},
                    "input": {"usage": '{"input": "..."} or plain text', "description": "Simulate agent receiving input"},
                    "batch": {"usage": '[{...}, {...}]', "description": "Multiple commands at once"},
                },
            })
        elif command in ("quit", "exit"):
            results.append({"type": "quit"})
        else:
            results.append({"error": f"Unknown command: {command}", "type": "error"})

    return results


def simulation_main() -> None:
    use_encryption = _detect_encryption()
    if use_encryption and not PYSQLCIPHER_AVAILABLE:
        print("Database appears encrypted but pysqlcipher3 is not installed.")
        print("Falling back to plain-text (will likely fail).")
        use_encryption = False

    if not DB_PATH.exists():
        print("No database found. Run 'python main.py -i' and initialize first.")
        sys.exit(1)

    services = _init_services(use_encryption=use_encryption)
    agent_mgr = services["agent_mgr"]
    app_tab_mgr = services["app_tab_mgr"]

    agents = agent_mgr.list_agents()
    if not agents:
        print("No agents found. Create one through the interactive CLI (-i).")
        sys.exit(1)

    print()
    print_banner(subtitle="Agent Simulator")
    print()

    agent = None
    while agent is None:
        try:
            for i, a in enumerate(agents):
                ref = a.model_ref or "no model"
                cw = a.context_window
                print(f"  {i+1}. {a.name} ({a.agent_id}, cw={cw}, model={ref})")

            choice = input("\nSelect agent (number): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(agents):
                agent = agents[idx]
            else:
                print("Invalid selection.")
        except (ValueError, EOFError, KeyboardInterrupt):
            print("Aborted.")
            sys.exit(1)

    agent_id = agent.agent_id
    print()
    print(f"Selected: {agent.name} ({agent_id})")
    print()

    ctx = _context(agent_id, app_tab_mgr)
    session = {
        "type": "session",
        "agent": {"name": agent.name, "agent_id": agent.agent_id, "context_window": agent.context_window},
        "context": ctx,
    }
    session_json = _oj(session, indent=2).replace("\\n", "\n").replace('\\"', '"')
    panel = Panel(
        Text(session_json),
        title="[bold cyan]Context Window[/bold cyan]",
        box=rich_box.ROUNDED,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)

    while True:
        try:
            raw = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        results = _dispatch(raw, services, agent_id)

        for r in results:
            if r.get("type") == "quit":
                return
            text = _oj(r, indent=2).replace("\\n", "\n").replace('\\"', '"')
            panel = Panel(
                Text(text),
                title="[bold cyan]Response[/bold cyan]",
                box=rich_box.ROUNDED,
                border_style="cyan",
                padding=(1, 2),
            )
            console.print(panel)
