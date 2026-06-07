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
    from core import AppTabManager, ListAppsHandler, PastActionsService, PastActionsHandler, TimeService
    from core.context_window import ContextWindowHandler
    from apps.list_directory.handler import ListDirectoryHandler

    log_db = LogDatabase(
        db_path=str(DATA_DIR / "cognithor_logs.db"),
        use_encryption=use_encryption,
    )
    log_svc = LogService(database=log_db)

    import logging
    from log_service import DbLogHandler
    logging.getLogger().addHandler(DbLogHandler(log_svc))

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

    past_actions_svc = PastActionsService(svc=svc)

    app_tab_mgr = AppTabManager(svc=svc, app_registry=app_registry)
    app_tab_mgr.register_handler("list_directory", ListDirectoryHandler())
    app_tab_mgr.register_handler("__list_apps__", ListAppsHandler(app_registry, agent_app_mgr))
    app_tab_mgr.register_handler("__past_actions__", PastActionsHandler(past_actions_svc))
    app_tab_mgr.register_handler("__context_window__", ContextWindowHandler())

    time_svc = TimeService(svc=svc)

    return {
        "svc": svc,
        "config_mgr": config_mgr,
        "agent_mgr": agent_mgr,
        "app_registry": app_registry,
        "agent_app_mgr": agent_app_mgr,
        "app_tab_mgr": app_tab_mgr,
        "time_svc": time_svc,
        "past_actions_svc": past_actions_svc,
    }


def _oj(data: dict, indent: Optional[int] = None) -> str:
    return json.dumps(data, indent=indent)


def _context(
    agent_id: str,
    app_tab_mgr,
    max_past_actions=15,
    show_context_window=False,
    context_window=4096,
    agent_can_change_max_past_actions=False,
) -> str:
    return app_tab_mgr.get_agent_context(
        agent_id,
        max_past_actions=max_past_actions,
        show_context_window=show_context_window,
        context_window=context_window,
        agent_can_change_max_past_actions=agent_can_change_max_past_actions,
    )


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


def _process_tab_operations(result: dict, services: dict, agent_id: str) -> None:
    app_tab_mgr = services["app_tab_mgr"]
    for tab_spec in result.get("_open_tabs", []):
        app_tab_mgr.open_app(
            agent_id=agent_id,
            app_id=tab_spec.get("app_id", ""),
            tab_label=tab_spec.get("tab_label"),
            params=tab_spec.get("params"),
        )
    for tab_spec in result.get("_update_tabs", []):
        existing = app_tab_mgr._find_tab_by_app_and_label(
            agent_id,
            tab_spec.get("app_id", ""),
            tab_spec.get("tab_label", ""),
        )
        if existing is not None:
            app_tab_mgr.update_tab_params(existing.id, tab_spec.get("params", {}))
            app_tab_mgr.refresh_interface(existing.id)


def _handle_input(
    content: str,
    services: dict,
    agent_id: str,
    agent: Optional[object] = None,
) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"raw": content}

    app_tab_mgr = services["app_tab_mgr"]
    max_pa = getattr(agent, "max_past_actions", 15) if agent else 15
    scw = getattr(agent, "show_context_window", False) if agent else False
    cw = getattr(agent, "context_window", 4096) if agent else 4096
    acc = getattr(agent, "agent_can_change_max_past_actions", False) if agent else False

    app_tab_mgr.refresh_interfaces(agent_id)
    ctx = _context(
        agent_id, app_tab_mgr,
        max_past_actions=max_pa,
        show_context_window=scw,
        context_window=cw,
        agent_can_change_max_past_actions=acc,
    )

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


def _dispatch(
    raw: str,
    services: dict,
    agent_id: str,
    agent: Optional[object] = None,
) -> list[dict]:
    results = []
    raw = raw.strip()

    if not raw:
        return results

    time_svc = services.get("time_svc")
    past_actions_svc = services.get("past_actions_svc")
    max_pa = getattr(agent, "max_past_actions", 15) if agent else 15
    scw = getattr(agent, "show_context_window", False) if agent else False
    cw = getattr(agent, "context_window", 4096) if agent else 4096
    acc = getattr(agent, "agent_can_change_max_past_actions", False) if agent else False

    def _ctx() -> str:
        return _context(
            agent_id, services["app_tab_mgr"],
            max_past_actions=max_pa,
            show_context_window=scw,
            context_window=cw,
            agent_can_change_max_past_actions=acc,
        )

    clean = raw.replace('\\"', '"')
    clean = _fix_json_keys(clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        err = {"error": "Nothing matched with the available command", "raw_input": raw}
        if past_actions_svc:
            past_actions_svc.record_action(agent_id, "user", raw, time_svc=time_svc)
            past_actions_svc.record_action(
                agent_id, "assistant", json.dumps(err), time_svc=time_svc,
            )
            past_actions_svc.trim_actions(agent_id, max_pa)
        results.append({"type": "context", "content": _ctx()})
        return results

    items = parsed if isinstance(parsed, list) else [parsed]

    for item in items:
        item_raw = json.dumps(item) if isinstance(item, dict) else str(item)

        if not isinstance(item, dict):
            err = {"error": "Each item must be a JSON object", "raw": str(item)}
            if past_actions_svc:
                past_actions_svc.record_action(
                    agent_id, "user", item_raw, time_svc=time_svc,
                )
                past_actions_svc.record_action(
                    agent_id, "assistant", json.dumps(err), time_svc=time_svc,
                )
            continue

        item = _normalize(item)
        command = item.get("command", "").lower().lstrip("/")

        if past_actions_svc:
            past_actions_svc.record_action(
                agent_id, "user", item_raw, time_svc=time_svc,
            )

        if not command:
            handler_result = _handle_input(json.dumps(item), services, agent_id, agent=agent)
            results.append(handler_result)
            if past_actions_svc:
                pa_record = {k: v for k, v in handler_result.items()
                             if k not in ("context", "combined_payload")}
                past_actions_svc.record_action(
                    agent_id, "assistant", json.dumps(pa_record), time_svc=time_svc,
                )
            continue

        if command in ("open",):
            result = _handle_open(item, services, agent_id)
            if result:
                results.append({"type": "result", "command": "open", "data": result})
                if past_actions_svc:
                    pa = {k: v for k, v in result.items() if k != "interface"}
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(pa), time_svc=time_svc,
                    )
                results.append({"type": "context", "content": _ctx()})
        elif command in ("close",):
            result = _handle_close(item, services, agent_id)
            if result:
                results.append({"type": "result", "command": "close", "data": result})
                if past_actions_svc:
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(result), time_svc=time_svc,
                    )
                results.append({"type": "context", "content": _ctx()})
        elif command in ("context",):
            content = _ctx()
            results.append({"type": "context", "content": content})
            if past_actions_svc:
                past_actions_svc.record_action(
                    agent_id, "assistant", json.dumps({"context": content}), time_svc=time_svc,
                )
        elif command in ("tabs",):
            tabs = services["app_tab_mgr"].list_open_apps(agent_id)
            data = [
                {"tab_id": t.id, "app_id": t.app_id, "tab_label": t.tab_label,
                 "is_persistent": t.is_persistent}
                for t in tabs
            ]
            results.append({"type": "result", "command": "tabs", "data": data})
            if past_actions_svc:
                past_actions_svc.record_action(
                    agent_id, "assistant", json.dumps({"tabs": data}), time_svc=time_svc,
                )
        elif command in ("apps",):
            apps = services["app_registry"].list_available_apps()
            data = [
                {"app_id": a.app_id, "name": a.name, "description": a.description, "icon": a.icon}
                for a in apps
            ]
            results.append({"type": "result", "command": "apps", "data": data})
            if past_actions_svc:
                past_actions_svc.record_action(
                    agent_id, "assistant", json.dumps({"apps": data}), time_svc=time_svc,
                )
        elif command in ("execute", "run"):
            app_id = item.get("app_id", "")
            action = item.get("action", item.get("params", {}))
            handler = services["app_tab_mgr"]._handlers.get(app_id)
            if handler is None:
                err = {"error": f"No handler registered for app: {app_id}"}
                results.append({"type": "error", "data": err})
                if past_actions_svc:
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(err), app_id=app_id,
                        time_svc=time_svc,
                    )
            else:
                result = handler.execute(action if isinstance(action, dict) else {})
                results.append({"type": "result", "command": "execute", "data": result, "app_id": app_id})
                _process_tab_operations(result, services, agent_id)
                if past_actions_svc:
                    summary = result.get("past_action_summary")
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(result),
                        app_id=app_id, summary=summary, time_svc=time_svc,
                    )
                results.append({"type": "context", "content": _ctx()})
        elif command in ("config",):
            new_max = item.get("max_past_actions")
            if new_max is None:
                err = {"error": "max_past_actions required for config command"}
                results.append({"type": "error", "data": err})
                if past_actions_svc:
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(err), time_svc=time_svc,
                    )
            else:
                try:
                    new_max = int(new_max)
                except (ValueError, TypeError):
                    new_max = -1
                if new_max < 3:
                    err = {"error": f"max_past_actions must be at least 3, got {new_max}"}
                    results.append({"type": "error", "data": err})
                    if past_actions_svc:
                        past_actions_svc.record_action(
                            agent_id, "assistant", json.dumps(err), time_svc=time_svc,
                        )
                elif not acc:
                    err = {"error": "Agent not allowed to change max_past_actions"}
                    results.append({"type": "error", "data": err})
                    if past_actions_svc:
                        past_actions_svc.record_action(
                            agent_id, "assistant", json.dumps(err), time_svc=time_svc,
                        )
                else:
                    services["agent_mgr"].update_agent(agent_id, max_past_actions=new_max)
                    if agent is not None:
                        agent.max_past_actions = new_max
                    max_pa = new_max
                    result = {"status": "updated", "max_past_actions": new_max}
                    results.append({"type": "result", "command": "config", "data": result})
                    if past_actions_svc:
                        past_actions_svc.record_action(
                            agent_id, "assistant", json.dumps(result), time_svc=time_svc,
                        )
                    results.append({"type": "context", "content": _ctx()})
        elif command in ("help",):
            help_data = {
                "open": {"usage": '{"command": "open", "app_id": "...", "tab_label": "...", "params": {...}}', "description": "Open an app tab"},
                "close": {"usage": '{"command": "close", "tab_id": "..."}', "description": "Close a non-persistent tab"},
                "context": {"usage": '{"command": "context"}', "description": "Show current context window"},
                "tabs": {"usage": '{"command": "tabs"}', "description": "List open tabs"},
                "apps": {"usage": '{"command": "apps"}', "description": "List available apps"},
                "execute": {"usage": '{"command": "execute", "app_id": "...", "action": {...}}', "description": "Execute an action on an app"},
                "config": {"usage": '{"command": "config", "max_past_actions": <number>}', "description": "Change agent's max past actions limit (min 3)"},
                "help": {"usage": '{"command": "help"}', "description": "Show this help"},
                "quit": {"usage": '{"command": "quit"}', "description": "Exit simulator"},
                "input": {"usage": '{"input": "..."} or plain text', "description": "Simulate agent receiving input"},
                "batch": {"usage": '[{...}, {...}]', "description": "Multiple commands at once"},
            }
            results.append({"type": "help", "commands": help_data})
            if past_actions_svc:
                past_actions_svc.record_action(
                    agent_id, "assistant", json.dumps({"help": help_data}), time_svc=time_svc,
                )
        elif command in ("quit", "exit"):
            results.append({"type": "quit"})
        else:
            err = {"error": f"Unknown command: {command}", "type": "error"}
            if past_actions_svc:
                past_actions_svc.record_action(
                    agent_id, "assistant", json.dumps(err), time_svc=time_svc,
                )

    if past_actions_svc:
        past_actions_svc.trim_actions(agent_id, max_pa)

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

    max_pa = agent.max_past_actions if hasattr(agent, "max_past_actions") else 15
    scw = agent.show_context_window if hasattr(agent, "show_context_window") else False
    cw = agent.context_window if hasattr(agent, "context_window") else 4096
    acc = agent.agent_can_change_max_past_actions if hasattr(agent, "agent_can_change_max_past_actions") else False
    ctx = _context(
        agent_id, app_tab_mgr,
        max_past_actions=max_pa,
        show_context_window=scw,
        context_window=cw,
        agent_can_change_max_past_actions=acc,
    )
    agent_info = _oj({
        "type": "session",
        "agent": {"name": agent.name, "agent_id": agent.agent_id, "context_window": agent.context_window},
    }, indent=2)
    panel = Panel(
        Text(agent_info + "\n\n" + ctx),
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

        results = _dispatch(raw, services, agent_id, agent=agent)

        for r in results:
            if r.get("type") == "quit":
                return
            rtype = r.get("type", "")
            if rtype == "context":
                panel = Panel(
                    Text(r.get("content", "")),
                    title="[bold green]Context Window[/bold green]",
                    box=rich_box.ROUNDED,
                    border_style="green",
                    padding=(1, 2),
                )
            elif rtype == "help":
                text = _oj(r, indent=2).replace("\\n", "\n").replace('\\"', '"')
                panel = Panel(
                    Text(text),
                    title="[bold yellow]Help[/bold yellow]",
                    box=rich_box.ROUNDED,
                    border_style="yellow",
                    padding=(1, 2),
                )
            elif r.get("error"):
                text = _oj(r, indent=2).replace("\\n", "\n").replace('\\"', '"')
                panel = Panel(
                    Text(text),
                    title="[bold red]Error[/bold red]",
                    box=rich_box.ROUNDED,
                    border_style="red",
                    padding=(1, 2),
                )
            else:
                text = _oj(r, indent=2).replace("\\n", "\n").replace('\\"', '"')
                panel = Panel(
                    Text(text),
                    title="[bold cyan]Response[/bold cyan]",
                    box=rich_box.ROUNDED,
                    border_style="cyan",
                    padding=(1, 2),
                )
            console.print(panel)
