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
    from core import AppTabManager, ListAppsHandler, PastActionsService, PastActionsHandler, TimeService, TimeHandler, AlarmService, AlarmScheduler, NotesManager, NotesCommandHandler, NoteTabHandler, DiaryService, DiaryHandler
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
    notes_manager = NotesManager(svc=svc)
    app_tab_mgr.register_handler("list_directory", ListDirectoryHandler())
    app_tab_mgr.register_handler("__list_apps__", ListAppsHandler(app_registry, agent_app_mgr))
    app_tab_mgr.register_handler("__past_actions__", PastActionsHandler(past_actions_svc))
    app_tab_mgr.register_handler("__context_window__", ContextWindowHandler())
    app_tab_mgr.register_handler("__notes__", NotesCommandHandler())
    app_tab_mgr.register_handler("__note__", NoteTabHandler(notes_manager))

    diary_svc = DiaryService(svc=svc)
    time_svc = TimeService(svc=svc)
    alarm_svc = AlarmService(svc=svc, time_svc=time_svc)
    alarm_scheduler = AlarmScheduler(svc=svc, time_svc=time_svc, agent_mgr=agent_mgr)
    alarm_scheduler.start()
    app_tab_mgr.register_handler("__diary__", DiaryHandler(diary_svc, time_svc))
    app_tab_mgr.register_handler("__time__", TimeHandler(time_svc, alarm_svc))

    return {
        "svc": svc,
        "config_mgr": config_mgr,
        "agent_mgr": agent_mgr,
        "app_registry": app_registry,
        "agent_app_mgr": agent_app_mgr,
        "app_tab_mgr": app_tab_mgr,
        "time_svc": time_svc,
        "alarm_svc": alarm_svc,
        "alarm_scheduler": alarm_scheduler,
        "past_actions_svc": past_actions_svc,
        "notes_manager": notes_manager,
        "diary_svc": diary_svc,
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
    show_notes=True,
    show_diary=True,
    show_time=True,
    notes_manager=None,
) -> str:
    return app_tab_mgr.get_agent_context(
        agent_id,
        max_past_actions=max_past_actions,
        show_context_window=show_context_window,
        context_window=context_window,
        agent_can_change_max_past_actions=agent_can_change_max_past_actions,
        show_notes=show_notes,
        show_diary=show_diary,
        show_time=show_time,
        notes_manager=notes_manager,
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
    st = getattr(agent, "show_time", True) if agent else True

    app_tab_mgr.refresh_interfaces(agent_id)
    ctx = _context(
        agent_id, app_tab_mgr,
        max_past_actions=max_pa,
        show_context_window=scw,
        context_window=cw,
        agent_can_change_max_past_actions=acc,
        show_time=st,
        notes_manager=services.get("notes_manager"),
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
    "create_note": ("create_note", None),
    "edit_note": ("edit_note", None),
    "reset_note_lifetime": ("reset_note_lifetime", None),
    "delete_note": ("delete_note", None),
    "write_diary": ("write_diary", None),
    "list_diary": ("list_diary", None),
    "set_alarm": ("set_alarm", None),
    "acknowledge_alarm": ("acknowledge_alarm", None),
    "wait": ("wait", None),
    "wait_until": ("wait_until", None),
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
    alarm_svc = services.get("alarm_svc")
    past_actions_svc = services.get("past_actions_svc")
    notes_manager = services.get("notes_manager")
    diary_svc = services.get("diary_svc")
    max_pa = getattr(agent, "max_past_actions", 15) if agent else 15
    scw = getattr(agent, "show_context_window", False) if agent else False
    cw = getattr(agent, "context_window", 4096) if agent else 4096
    acc = getattr(agent, "agent_can_change_max_past_actions", False) if agent else False
    sn = getattr(agent, "show_notes", True) if agent else True
    sd = getattr(agent, "show_diary", True) if agent else True
    st = getattr(agent, "show_time", True) if agent else True

    def _ctx() -> str:
        return _context(
            agent_id, services["app_tab_mgr"],
            max_past_actions=max_pa,
            show_context_window=scw,
            context_window=cw,
            agent_can_change_max_past_actions=acc,
            show_notes=sn,
            show_diary=sd,
            show_time=st,
            notes_manager=notes_manager,
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
        elif command in ("create_note",):
            if not notes_manager:
                err = {"error": "Notes manager not available"}
                results.append({"type": "error", "data": err})
            else:
                title = item.get("title", "")
                content = item.get("content", "")
                max_int = item.get("max_interactions", 10)
                note_id = notes_manager.create_note(agent_id, title=title, content=content, max_interactions=max_int)
                services["app_tab_mgr"].open_app(
                    agent_id, "__note__",
                    tab_label=title or "untitled",
                    params={"note_id": note_id, "agent_id": agent_id},
                    is_persistent=False,
                )
                result = {"success": True, "type": "notes", "action": "created", "note_id": note_id}
                results.append({"type": "result", "command": "create_note", "data": result})
                if past_actions_svc:
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(result),
                        summary="SUCCESS: Note created", time_svc=time_svc,
                    )
                results.append({"type": "context", "content": _ctx()})
        elif command in ("edit_note",):
            if not notes_manager:
                err = {"error": "Notes manager not available"}
                results.append({"type": "error", "data": err})
            else:
                note_id = item.get("note_id", "")
                content = item.get("content", "")
                title = item.get("title")
                if not note_id:
                    err = {"error": "note_id required for edit_note"}
                    results.append({"type": "error", "data": err})
                else:
                    note = notes_manager.get_note(note_id)
                    if note is None:
                        err = {"error": f"Note '{note_id}' not found"}
                        results.append({"type": "error", "data": err})
                    else:
                        notes_manager.update_note(note_id, content=content, title=title)
                        result = {"success": True, "type": "notes", "action": "updated", "note_id": note_id}
                        results.append({"type": "result", "command": "edit_note", "data": result})
                        if past_actions_svc:
                            past_actions_svc.record_action(
                                agent_id, "assistant", json.dumps(result),
                                summary="SUCCESS: Note edited", time_svc=time_svc,
                            )
                        results.append({"type": "context", "content": _ctx()})
        elif command in ("reset_note_lifetime",):
            if not notes_manager:
                err = {"error": "Notes manager not available"}
                results.append({"type": "error", "data": err})
            else:
                note_id = item.get("note_id", "")
                max_int = item.get("max_interactions", 10)
                if not note_id:
                    err = {"error": "note_id required for reset_note_lifetime"}
                    results.append({"type": "error", "data": err})
                else:
                    note = notes_manager.get_note(note_id)
                    if note is None:
                        err = {"error": f"Note '{note_id}' not found"}
                        results.append({"type": "error", "data": err})
                    else:
                        notes_manager.extend_note(note_id, max_interactions=max_int)
                        result = {"success": True, "type": "notes", "action": "extended", "note_id": note_id, "max_interactions": max_int}
                        results.append({"type": "result", "command": "reset_note_lifetime", "data": result})
                        if past_actions_svc:
                            past_actions_svc.record_action(
                                agent_id, "assistant", json.dumps(result),
                                summary="SUCCESS: Note lifetime reset", time_svc=time_svc,
                            )
                        results.append({"type": "context", "content": _ctx()})
        elif command in ("delete_note",):
            if not notes_manager:
                err = {"error": "Notes manager not available"}
                results.append({"type": "error", "data": err})
            else:
                note_id = item.get("note_id", "")
                if not note_id:
                    err = {"error": "note_id required for delete_note"}
                    results.append({"type": "error", "data": err})
                else:
                    note = notes_manager.get_note(note_id)
                    if note is None:
                        err = {"error": f"Note '{note_id}' not found"}
                        results.append({"type": "error", "data": err})
                    else:
                        notes_manager.delete_note(note_id)
                        for tab in services["app_tab_mgr"].list_open_apps(agent_id):
                            if tab.app_id == "__note__":
                                import json as _j
                                tp = _j.loads(tab.params) if tab.params else {}
                                if tp.get("note_id") == note_id:
                                    try:
                                        services["app_tab_mgr"].close_tab(tab.id)
                                    except ValueError:
                                        pass
                        result = {"success": True, "type": "notes", "action": "deleted", "note_id": note_id}
                        results.append({"type": "result", "command": "delete_note", "data": result})
                        if past_actions_svc:
                            past_actions_svc.record_action(
                                agent_id, "assistant", json.dumps(result),
                                summary="SUCCESS: Note deleted", time_svc=time_svc,
                            )
                        results.append({"type": "context", "content": _ctx()})
        elif command in ("write_diary",):
            if not diary_svc:
                err = {"error": "Diary service not available"}
                results.append({"type": "error", "data": err})
            else:
                content = item.get("content", "")
                result = diary_svc.append_diary(agent_id, content, time_svc=time_svc)
                results.append({"type": "result", "command": "write_diary", "data": result})
                if past_actions_svc:
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(result), time_svc=time_svc,
                    )
                results.append({"type": "context", "content": _ctx()})
        elif command in ("list_diary",):
            if not diary_svc:
                err = {"error": "Diary service not available"}
                results.append({"type": "error", "data": err})
            else:
                date = item.get("date")
                entries = diary_svc.list_entries(agent_id, date=date)
                data = [
                    {"date": e.date, "content": e.content, "created_at": e.created_at, "updated_at": e.updated_at}
                    for e in entries
                ]
                result = {"entries": data}
                results.append({"type": "result", "command": "list_diary", "data": result})
                if past_actions_svc:
                    past_actions_svc.record_action(
                        agent_id, "assistant", json.dumps(result), time_svc=time_svc,
                    )
                results.append({"type": "context", "content": _ctx()})
        elif command in ("set_alarm",):
            if not alarm_svc:
                err = {"error": "Alarm service not available"}
                results.append({"type": "error", "data": err})
            else:
                alarm_time = item.get("time", "")
                message = item.get("message", "")
                time_type = item.get("time_type", "agent")
                if not alarm_time:
                    err = {"error": "time required for set_alarm"}
                    results.append({"type": "error", "data": err})
                else:
                    alarm_id = alarm_svc.set_alarm(agent_id, alarm_time, time_type=time_type, message=message)
                    if alarm_id:
                        result = {"success": True, "alarm_id": alarm_id, "time": alarm_time, "message": message}
                        results.append({"type": "result", "command": "set_alarm", "data": result})
                    else:
                        err = {"error": "Alarm time is in the past"}
                        results.append({"type": "error", "data": err})
                    if past_actions_svc:
                        past_actions_svc.record_action(agent_id, "assistant", json.dumps(result if alarm_id else err), time_svc=time_svc)
                    results.append({"type": "context", "content": _ctx()})
        elif command in ("acknowledge_alarm",):
            if not alarm_svc:
                err = {"error": "Alarm service not available"}
                results.append({"type": "error", "data": err})
            else:
                alarm_id = item.get("alarm_id", "")
                if not alarm_id:
                    err = {"error": "alarm_id required"}
                    results.append({"type": "error", "data": err})
                elif alarm_svc.acknowledge_alarm(alarm_id):
                    result = {"success": True, "alarm_id": alarm_id, "status": "acknowledged"}
                    results.append({"type": "result", "command": "acknowledge_alarm", "data": result})
                else:
                    err = {"error": f"Alarm '{alarm_id}' not found"}
                    results.append({"type": "error", "data": err})
                if past_actions_svc:
                    past_actions_svc.record_action(agent_id, "assistant", json.dumps(result if result.get("success") else err), time_svc=time_svc)
                results.append({"type": "context", "content": _ctx()})
        elif command in ("wait",):
            duration = item.get("duration", 0)
            try:
                duration = float(duration)
            except (ValueError, TypeError):
                duration = 0
            if duration <= 0:
                err = {"error": "duration must be a positive number"}
                results.append({"type": "error", "data": err})
            else:
                result = {"status": "waiting", "duration_seconds": duration}
                results.append({"type": "result", "command": "wait", "data": result})
                if past_actions_svc:
                    past_actions_svc.record_action(agent_id, "assistant", json.dumps(result), time_svc=time_svc)
        elif command in ("wait_until",):
            target = item.get("time", "")
            if not target:
                err = {"error": "time required for wait_until"}
                results.append({"type": "error", "data": err})
            else:
                try:
                    target_dt = __import__('datetime').datetime.fromisoformat(target)
                    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                    if target_dt.tzinfo is None:
                        target_dt = target_dt.replace(tzinfo=__import__('datetime').timezone.utc)
                    diff = (target_dt - now).total_seconds()
                    if diff > 0:
                        result = {"status": "waiting", "duration_seconds": diff, "until": target}
                        results.append({"type": "result", "command": "wait_until", "data": result})
                    else:
                        err = {"error": "Target time is in the past"}
                        results.append({"type": "error", "data": err})
                except Exception:
                    err = {"error": f"Invalid time format: {target}"}
                    results.append({"type": "error", "data": err})
                if past_actions_svc:
                    past_actions_svc.record_action(agent_id, "assistant", json.dumps(result if diff > 0 else err), time_svc=time_svc)
        elif command in ("help",):
            help_data = {
                "open": {"usage": '{"command": "open", "app_id": "...", "tab_label": "...", "params": {...}}', "description": "Open an app tab"},
                "close": {"usage": '{"command": "close", "tab_id": "..."}', "description": "Close a non-persistent tab"},
                "context": {"usage": '{"command": "context"}', "description": "Show current context window"},
                "tabs": {"usage": '{"command": "tabs"}', "description": "List open tabs"},
                "apps": {"usage": '{"command": "apps"}', "description": "List available apps"},
                "execute": {"usage": '{"command": "execute", "app_id": "...", "action": {...}}', "description": "Execute an action on an app"},
                "config": {"usage": '{"command": "config", "max_past_actions": <number>}', "description": "Change agent's max past actions limit (min 3)"},
                "create_note": {"usage": '{"command": "create_note", "title": "...", "content": "..."}', "description": "Create a new note"},
                "edit_note": {"usage": '{"command": "edit_note", "note_id": "...", "content": "..."}', "description": "Edit note content"},
                "reset_note_lifetime": {"usage": '{"command": "reset_note_lifetime", "note_id": "...", "max_interactions": <number>}', "description": "Reset note lifetime (resets counter)"},
                "delete_note": {"usage": '{"command": "delete_note", "note_id": "..."}', "description": "Delete a note and close its tab"},
                "write_diary": {"usage": '{"command": "write_diary", "content": "..."}', "description": "Append to today's diary entry"},
                "list_diary": {"usage": '{"command": "list_diary", "date": "YYYY-MM-DD"}', "description": "List diary entries (omit date for all)"},
                "set_alarm": {"usage": '{"command": "set_alarm", "time": "<ISO datetime>", "message": "...", "time_type": "agent|real"}', "description": "Set an alarm"},
                "acknowledge_alarm": {"usage": '{"command": "acknowledge_alarm", "alarm_id": "..."}', "description": "Acknowledge a ringing alarm"},
                "wait": {"usage": '{"command": "wait", "duration": <seconds>}', "description": "Wait before next interaction"},
                "wait_until": {"usage": '{"command": "wait_until", "time": "<ISO datetime>"}', "description": "Wait until a specific time"},
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
    sn = agent.show_notes if hasattr(agent, "show_notes") else True
    sd = agent.show_diary if hasattr(agent, "show_diary") else True
    st = agent.show_time if hasattr(agent, "show_time") else True
    ctx = _context(
        agent_id, app_tab_mgr,
        max_past_actions=max_pa,
        show_context_window=scw,
        context_window=cw,
        agent_can_change_max_past_actions=acc,
        show_notes=sn,
        show_diary=sd,
        show_time=st,
        notes_manager=services.get("notes_manager"),
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
            if r.get("command") in ("wait", "wait_until") and r.get("data", {}).get("status") == "waiting":
                duration = r["data"].get("duration_seconds", 0)
                if duration > 0:
                    import time as _time
                    from cli_service.display import print_info
                    print_info(f"Waiting {duration:.0f} seconds...")
                    _time.sleep(duration)
                continue
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
