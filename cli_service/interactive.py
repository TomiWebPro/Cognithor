"""Interactive CLI menu — refactored from api_service/cli_launcher.py.

Uses rich for colorful rendering, panels, tables, and spinners.
Breadcrumb navigation, step guidance, and context-sensitive hints.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from rich.cells import cell_len
from rich.text import Text
from rich.panel import Panel
from rich.live import Live
from rich import box as rich_box

from cli_service.display import (
    console,
    print_banner,
    print_header,
    print_section,
    print_step,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_dim,
    print_hint,
    print_table,
    print_credentials_box,
    print_passkey_box,
    print_status_panel,
    print_encryption_status_panel,
    spinner,
    print_empty,
)
from cli_service.prompts import ask, ask_secret, confirm, choose, pause
from cli_service.server import detect_db_encryption
from cli_service.onboarding import cmd_init

def db_exists() -> bool:
    return DB_PATH.exists()


PYSQLCIPHER_AVAILABLE = False
try:
    from pysqlcipher3 import dbapi2 as _pysqlcipher
    PYSQLCIPHER_AVAILABLE = True
except ImportError:
    pass

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "cognithor.db"
APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

CONFIG: dict = {
    "config_mgr": None,
    "tracker": None,
    "agent_mgr": None,
    "app_registry": None,
    "agent_app_mgr": None,
    "use_encryption": False,
}


def _init_services(use_encryption: bool = False) -> None:
    if CONFIG["config_mgr"] is not None:
        return

    CONFIG["use_encryption"] = use_encryption

    from log_service import LogDatabase, LogService
    from endpoint.database import Tracker
    from api_service.database import ApiConfigManager
    from agents_service.database import AgentManager
    from apps_service.database import AppRegistry, AgentAppManager
    from core import TimeService
    from secure_db_service import SecureDbService

    log_db = LogDatabase(
        db_path=DATA_DIR / "cognithor_logs.db",
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

    CONFIG["tracker"] = Tracker(
        db_path=DB_PATH,
        svc=svc,
        log_service=log_svc,
    )

    CONFIG["config_mgr"] = ApiConfigManager(
        db_path=DB_PATH,
        svc=svc,
        key_name="db_key",
    )

    CONFIG["agent_mgr"] = AgentManager(svc=svc)

    app_registry = AppRegistry(svc=svc)
    app_registry.scan_apps_directory(str(APPS_DIR))
    CONFIG["app_registry"] = app_registry
    CONFIG["agent_app_mgr"] = AgentAppManager(svc=svc)

    from core import AppTabManager, TimeService, DiaryService, AlarmService, AlarmScheduler

    app_tab_mgr = AppTabManager(svc=svc, app_registry=app_registry, agent_app_mgr=CONFIG["agent_app_mgr"])
    app_tab_mgr.scan_app_handlers(str(APPS_DIR))
    CONFIG["app_tab_mgr"] = app_tab_mgr
    CONFIG["time_svc"] = TimeService(svc=svc)
    CONFIG["diary_svc"] = DiaryService(svc=svc)
    CONFIG["alarm_svc"] = AlarmService(svc=svc, time_svc=CONFIG["time_svc"])
    alarm_scheduler = AlarmScheduler(
        svc=svc,
        time_svc=CONFIG["time_svc"],
        agent_mgr=CONFIG["agent_mgr"],
    )
    alarm_scheduler.start()
    CONFIG["alarm_scheduler"] = alarm_scheduler

    print_empty()
    print_step(3, 3, "Initialization complete")
    enc_label = "encrypted" if use_encryption else "plain-text"
    print_success(f"Database initialized ({enc_label})")
    print_hint("Next: Set up providers with API keys in 'Provider management'")


def cmd_status() -> None:
    config_mgr = CONFIG["config_mgr"]
    tracker = CONFIG["tracker"]

    config = config_mgr.get_all_config()
    providers = tracker.list_providers()
    active = [p.name for p in providers if any(p.active_models.values()) or p.is_active]

    print_empty()
    print_status_panel([
        ("Database", str(DB_PATH)),
        ("Encryption", "ENCRYPTED" if CONFIG["use_encryption"] else "plain-text"),
        ("API Host", f"{config.get('api_host', '0.0.0.0')}:{config.get('api_port', '4464')}"),
        ("Providers", str(len(providers))),
        ("Active", active[0] if active else "(none)"),
    ])

    if providers:
        rows = []
        for p in providers:
            status = "●" if (any(p.active_models.values()) or p.is_active) else "○"
            key = "✓ SET" if p.api_key else "✗ NOT SET"
            active_m = ', '.join(m for m, ok in p.active_models.items() if ok) if p.active_models else ''
            models_info = active_m if active_m else (', '.join(p.models) if p.models else '-')
            rows.append([status, p.name, models_info, key])
        status_w = max(cell_len(r[0]) for r in rows)
        print_table(
            ["", "Provider", "Active Models", "API Key"],
            rows,
            title="Providers",
            col_widths=[status_w],
            justify=["center"],
        )

    print_empty()
    print_info("Auth: POST /token with username + password to receive JWT")


def _pick_provider(tracker, title: str = "Select provider") -> tuple:
    providers = tracker.list_providers()
    if not providers:
        print_warning("No providers configured")
        pause()
        return None, None
    names = [p.name for p in providers]
    idx = choose(names, title=title)
    return providers[idx], names[idx]


def cmd_providers_menu() -> None:
    tracker = CONFIG["tracker"]

    while True:
        print_header("Provider Management", "Main > Providers")

        providers = tracker.list_providers()
        if providers:
            rows = []
            for p in providers:
                status = "●" if (any(p.active_models.values()) or p.is_active) else "○"
                key = "SET" if p.api_key else "NO KEY"
                rows.append([status, p.name, key])
            status_w = max(cell_len(r[0]) for r in rows)
            print_table(
                ["", "Provider", "API Key"],
                rows,
                col_widths=[status_w],
                justify=["center"],
            )
        else:
            print_warning("No providers configured")
            print_hint("Run 'Initialize database' from main menu first")

        print_empty()
        choice = choose(
            [
                "Show details",
                "Set API key",
                "Manage models",
                "Test model",
                "Delete provider",
                "Back to main menu",
            ],
            title="Select an action",
            default=5,
            hint="Manage or configure providers for LLM access",
        )

        if choice == 5:
            return

        if choice == 0:
            p, _ = _pick_provider(tracker, "Select provider to inspect")
            if not p:
                continue

            active_m = ', '.join(m for m, ok in p.active_models.items() if ok) if p.active_models else 'none'
            console.print(Panel(
                Text(f"  URL:            {p.base_url}{p.endpoint_path}\n"
                     f"  Auth type:      {p.auth_type}\n"
                     f"  API key set:    {'Yes' if p.api_key else 'No'}\n"
                     f"  Registered:     {', '.join(p.models) if p.models else 'none'}\n"
                     f"  Active models:  {active_m}\n"
                     f"  Streaming:      {'Yes' if p.is_streaming else 'No'}\n"
                     f"  Active:         {'Yes' if p.is_active else 'No'}"),
                title=f"[bold cyan]{p.name}[/bold cyan]",
                box=rich_box.ROUNDED,
                border_style="cyan",
                padding=(1, 2),
            ))
            pause()

        elif choice == 1:
            p, name = _pick_provider(tracker, "Select provider to set API key")
            if not p:
                continue

            key = ask_secret("API Key", hint="This key is stored in the database")
            if not key:
                print_warning("Cancelled")
                continue
            p.api_key = key
            tracker.save_provider(p)
            print_success(f"API key set for {name}")

        elif choice == 2:
            p, name = _pick_provider(tracker, "Select provider to manage models")
            if not p:
                continue
            cmd_models_menu(tracker, p)

        elif choice == 3:
            p, name = _pick_provider(tracker, "Select provider to test")
            if not p:
                continue

            if not p.models:
                print_warning("No models configured for this provider")
                pause()
                continue

            model_list = list(p.models.items())
            model_choices = [
                f"{mname} ({mid}){' [active]' if p.active_models.get(mname) else ''}"
                for mname, mid in model_list
            ]
            idx = choose(
                model_choices,
                title=f"Models for {name}",
                hint="Select a model to run a test request",
            )

            test_name, test_id = model_list[idx]
            print_empty()
            print_info(f"Testing {name}/{test_name}...")

            from endpoint.manager import EndpointManager
            mgr = EndpointManager(tracker=tracker)

            with spinner("Testing model") as progress:
                task = progress.add_task("", total=None)
                try:
                    result = mgr.test_model(name, test_name)
                    progress.stop()
                    if result["available"]:
                        print_success(
                            f"PASSED  latency={result['latency_ms']:.0f}ms  "
                            f"output_tokens={result['output_tokens']}"
                        )
                    else:
                        print_error(f"FAILED: {result.get('error')}")
                except Exception as e:
                    progress.stop()
                    print_error(f"Error: {e}")

            pause()

        elif choice == 4:
            p, name = _pick_provider(tracker, "Select provider to DELETE")
            if not p:
                continue

            if confirm(f"DELETE '{name}' permanently?", default=False):
                tracker._svc.execute(
                    "DELETE FROM providers WHERE name = ?", (name,)
                )
                print_success(f"Deleted provider: {name}")
            else:
                print_warning("Cancelled")
            pause()


def cmd_agents_menu() -> None:
    agent_mgr = CONFIG["agent_mgr"]
    tracker = CONFIG["tracker"]
    from agents_service import build_model_ref, parse_model_ref

    def _pick_model_ref(prompt_title: str = "Select model") -> Optional[str]:
        providers = tracker.list_providers()
        if not providers:
            print_warning("No providers configured")
            pause()
            return None
        pnames = [p.name for p in providers]
        pidx = choose(pnames, title=f"{prompt_title} — Provider")
        provider = providers[pidx]
        if not provider.models:
            print_warning(f"No models for {provider.name}")
            pause()
            return None
        mlist = list(provider.models.keys())
        midx = choose(mlist, title=f"{prompt_title} — Model for {provider.name}")
        return build_model_ref(provider.name, mlist[midx])

    while True:
        print_header("Agent Management", "Main > Agents")

        agents = agent_mgr.list_agents()
        if agents:
            rows = []
            agent_app_mgr = CONFIG.get("agent_app_mgr")
            for a in agents:
                primary = a.model_ref or "-"
                backup = a.backup_model_ref or "-"
                cw_flag = "On" if a.show_context_window else "Off"
                can_change = "Allowed" if a.agent_can_change_max_past_actions else "Disallowed"
                notes_flag = "On" if a.show_notes else "Off"
                diary_flag = "On" if a.show_diary else "Off"
                time_flag = "On" if getattr(a, "show_time", True) else "Off"
                rows.append([a.agent_id, a.name, str(a.context_window), str(a.max_past_actions), can_change, cw_flag, notes_flag, diary_flag, time_flag, primary, backup])
            print_table(
                ["ID", "Name", "Context Window", "Past Actions", "Agent Edit PA", "CW Tab", "Notes", "Diary", "Time", "Model Ref", "Backup Ref"],
                rows,
            )
            if agent_app_mgr:
                for a in agents:
                    if not agent_app_mgr.list_enabled_agent_apps(a.agent_id):
                        print_warning(f"Agent '{a.name}' has no apps configured — its tools are extremely limited")
                    if (a.context_window or 0) < 16384:
                        print_warning(f"Agent '{a.name}' context window is {a.context_window} — too small for complex tasks")
        else:
            print_warning("No agents configured")

        print_empty()
        choice = choose(
            [
                "Add agent",
                "Edit context window",
                "Edit past actions limit",
                "Toggle context window tab",
                "Toggle agent can change past actions limit",
                "Toggle notes tab",
                "Toggle diary feature",
                "Toggle time tab",
                "View diary entries",
                "Link primary model",
                "Link backup model",
                "Delete agent",
                "Back to main menu",
            ],
            title="Select an action",
            default=12,
            hint="Manage autonomous agents",
        )

        if choice == 12:
            return

        if choice == 0:
            name = ask("Agent name", hint="A friendly name for this agent")
            if not name:
                print_warning("Cancelled")
                continue
            cw_input = ask("Context window", default="4096", hint="Max tokens for context")
            try:
                cw = int(cw_input)
            except ValueError:
                print_error("Invalid number, using 4096")
                cw = 4096
            mpa_input = ask(
                "Past actions limit",
                default="15",
                hint="Number of past actions to keep in context (minimum 3)",
            )
            try:
                mpa = int(mpa_input)
            except ValueError:
                print_error("Invalid number, using 15")
                mpa = 15
            if mpa < 3:
                print_warning("Minimum is 3, using 3")
                mpa = 3
            agent = agent_mgr.create_agent(name=name, context_window=cw, max_past_actions=mpa)
            print_success(f"Created agent {agent.agent_id} ({name})")

        elif choice == 1:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name} (cw={a.context_window})" for a in agents]
            aidx = choose(alist, title="Select agent to edit context window")
            agent = agents[aidx]
            cw_input = ask(
                "Context window",
                default=str(agent.context_window),
                hint="Max tokens for this agent's context",
            )
            try:
                cw = int(cw_input)
            except ValueError:
                print_error("Invalid number")
                continue
            agent_mgr.update_agent(agent.agent_id, context_window=cw)
            print_success(f"Updated {agent.agent_id} context window → {cw}")

        elif choice == 2:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name} (past_actions={a.max_past_actions})" for a in agents]
            aidx = choose(alist, title="Select agent to edit past actions limit")
            agent = agents[aidx]
            mpa_input = ask(
                "Past actions limit",
                default=str(agent.max_past_actions),
                hint="Number of past actions kept in context (minimum 3)",
            )
            try:
                mpa = int(mpa_input)
            except ValueError:
                print_error("Invalid number")
                continue
            if mpa < 3:
                print_warning("Minimum is 3, using 3")
                mpa = 3
            agent_mgr.update_agent(agent.agent_id, max_past_actions=mpa)
            print_success(f"Updated {agent.agent_id} past actions limit → {mpa}")

        elif choice == 3:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name} (tab={'ON' if a.show_context_window else 'OFF'})" for a in agents]
            aidx = choose(alist, title="Select agent to toggle context window tab")
            agent = agents[aidx]
            new_val = not agent.show_context_window
            agent_mgr.update_agent(agent.agent_id, show_context_window=new_val)
            status = "ON" if new_val else "OFF"
            print_success(f"Context window tab for '{agent.name}' → {status}")

        elif choice == 4:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name} (edit={'YES' if a.agent_can_change_max_past_actions else 'no'})" for a in agents]
            aidx = choose(alist, title="Select agent to toggle can change past actions")
            agent = agents[aidx]
            new_val = not agent.agent_can_change_max_past_actions
            agent_mgr.update_agent(agent.agent_id, agent_can_change_max_past_actions=new_val)
            status = "YES" if new_val else "no"
            print_success(f"Agent '{agent.name}' can change past actions limit → {status}")

        elif choice == 5:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name} (notes={'ON' if a.show_notes else 'OFF'})" for a in agents]
            aidx = choose(alist, title="Select agent to toggle notes tab")
            agent = agents[aidx]
            new_val = not agent.show_notes
            agent_mgr.update_agent(agent.agent_id, show_notes=new_val)
            status = "ON" if new_val else "OFF"
            print_success(f"Notes tab for '{agent.name}' → {status}")

        elif choice == 6:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name} (diary={'ON' if a.show_diary else 'OFF'})" for a in agents]
            aidx = choose(alist, title="Select agent to toggle diary feature")
            agent = agents[aidx]
            new_val = not agent.show_diary
            agent_mgr.update_agent(agent.agent_id, show_diary=new_val)
            status = "ON" if new_val else "OFF"
            print_success(f"Diary feature for '{agent.name}' → {status}")

        elif choice == 7:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name} (time={'ON' if getattr(a, 'show_time', True) else 'OFF'})" for a in agents]
            aidx = choose(alist, title="Select agent to toggle time tab")
            agent = agents[aidx]
            new_val = not getattr(agent, "show_time", True)
            agent_mgr.update_agent(agent.agent_id, show_time=new_val)
            status = "ON" if new_val else "OFF"
            print_success(f"Time tab for '{agent.name}' → {status}")

        elif choice == 8:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name}" for a in agents]
            aidx = choose(alist, title="Select agent to view diary")
            agent = agents[aidx]
            diary_svc = CONFIG.get("diary_svc")
            if not diary_svc:
                print_warning("Diary service not initialized")
                pause()
                continue
            entries = diary_svc.list_entries(agent.agent_id)
            if not entries:
                print_warning("No diary entries for this agent")
                pause()
                continue
            from cli_service.display import print_table as _pt
            rows = []
            for e in entries:
                rows.append([e.date, e.content[:80] + ("..." if len(e.content) > 80 else ""), e.updated_at or ""])
            _pt(["Date", "Content", "Updated"], rows, title=f"Diary — {agent.name}")
            pause()

        elif choice == 9:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name}" for a in agents]
            aidx = choose(alist, title="Select agent to link primary model")
            agent = agents[aidx]
            ref = _pick_model_ref("Primary model")
            if ref is None:
                continue
            agent_mgr.update_agent(agent.agent_id, model_ref=ref)
            print_success(f"Linked {agent.agent_id} primary → {ref}")

        elif choice == 10:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name}" for a in agents]
            aidx = choose(alist, title="Select agent to link backup model")
            agent = agents[aidx]
            ref = _pick_model_ref("Backup model")
            if ref is None:
                continue
            agent_mgr.update_agent(agent.agent_id, backup_model_ref=ref)
            print_success(f"Linked {agent.agent_id} backup → {ref}")

        elif choice == 11:
            agents = agent_mgr.list_agents()
            if not agents:
                print_warning("No agents")
                pause()
                continue
            alist = [f"{a.agent_id} — {a.name}" for a in agents]
            aidx = choose(alist, title="Select agent to DELETE")
            agent = agents[aidx]
            if confirm(f"DELETE agent '{agent.name}' ({agent.agent_id}) permanently?", default=False):
                agent_app_mgr = CONFIG.get("agent_app_mgr")
                if agent_app_mgr:
                    agent_app_mgr.uninstall_all_for_agent(agent.agent_id)
                agent_mgr.delete_agent(agent.agent_id)
                print_success(f"Deleted agent: {agent.agent_id}")
            else:
                print_warning("Cancelled")


def cmd_apps_menu() -> None:
    app_registry = CONFIG["app_registry"]
    agent_app_mgr = CONFIG["agent_app_mgr"]
    agent_mgr = CONFIG["agent_mgr"]

    while True:
        print_header("App Management", "Main > Apps")

        apps = app_registry.list_apps()
        agents = agent_mgr.list_agents() if agent_mgr else []

        if apps:
            rows = []
            for a in apps:
                icon = a.icon or "◆"
                if cell_len(icon) != 2:
                    icon = "●" if a.is_available else "○"
                rows.append([icon, a.app_id, a.name, a.version, a.author])
            print_table(
                ["", "App ID", "Name", "Version", "Author"],
                rows,
                title="Registered Apps",
            )
        else:
            print_warning("No apps registered in the system")
            print_hint("Apps are auto-discovered from the apps/ directory")

        print_empty()
        choice = choose(
            [
                "Show app details",
                "Install app for an agent",
                "Uninstall app from an agent",
                "Toggle enable/disable for an agent",
                "List apps installed for an agent",
                "Configure app for an agent",
                "Toggle tab persistence",
                "Rescan apps directory",
                "Back to main menu",
            ],
            title="Select an action",
            default=7,
            hint="Manage agent applications and tools",
        )

        if choice == 8:
            return

        if choice == 0:
            if not apps:
                print_warning("No apps registered")
                pause()
                continue
            alist = [f"{a.app_id} — {a.name} (v{a.version})" for a in apps]
            aidx = choose(alist, title="Select an app to inspect")
            app = apps[aidx]

            import json
            manifest = {}
            if app.manifest:
                try:
                    manifest = json.loads(app.manifest)
                except (json.JSONDecodeError, TypeError):
                    pass

            params = manifest.get("parameters", [])
            outputs = manifest.get("outputs", [])

            lines = [
                f"  ID:             {app.app_id}",
                f"  Name:           {app.name}",
                f"  Description:    {app.description}",
                f"  Version:        {app.version}",
                f"  Author:         {app.author}",
                f"  Type:           {app.type}",
                f"  Available:      {'Yes' if app.is_available else 'No'}",
                f"  Requires Confirm: {'Yes' if app.requires_confirmation else 'No'}",
                f"  Timeout:        {app.timeout_seconds}s",
                f"  Directory:      {app.directory or '—'}",
            ]
            if params:
                param_lines = [f"    {p.get('name', '?')} ({p.get('type', 'string')}){' *' if p.get('required') else ''} — {p.get('description', '')}" for p in params]
                lines.append(f"  Parameters ({len(params)}):")
                lines.extend(param_lines)
            if outputs:
                out_lines = [f"    {o.get('name', '?')} ({o.get('type', 'string')}) — {o.get('description', '')}" for o in outputs]
                lines.append(f"  Outputs ({len(outputs)}):")
                lines.extend(out_lines)

            console.print(Panel(
                Text("\n".join(lines)),
                title=f"[bold cyan]{app.name}[/bold cyan]",
                box=rich_box.ROUNDED,
                border_style="cyan",
                padding=(1, 2),
            ))
            pause()

        elif choice == 1:
            if not apps:
                print_warning("No apps registered")
                pause()
                continue
            avail_apps = [a for a in apps if a.is_available]
            if not avail_apps:
                print_warning("No available apps to install")
                pause()
                continue
            if not agents:
                print_warning("No agents created yet. Create an agent first.")
                pause()
                continue

            alist = [f"{a.app_id} — {a.name}" for a in avail_apps]
            aidx = choose(alist, title="Select app to install")
            app = avail_apps[aidx]

            glist = [f"{g.agent_id} — {g.name}" for g in agents]
            gidx = choose(glist, title=f"Install '{app.name}' on which agent?")
            agent = agents[gidx]

            result = agent_app_mgr.install_app(agent.agent_id, app.app_id)
            if result is None:
                print_warning(f"App '{app.app_id}' is already installed for '{agent.name}'")
            else:
                print_success(f"Installed '{app.name}' on '{agent.name}'")
            pause()

        elif choice == 2:
            if not agents:
                print_warning("No agents created yet.")
                pause()
                continue

            glist = [f"{g.agent_id} — {g.name}" for g in agents]
            gidx = choose(glist, title="Select agent to uninstall from")
            agent = agents[gidx]

            installed = agent_app_mgr.list_agent_apps(agent.agent_id)
            if not installed:
                print_warning(f"No apps installed for '{agent.name}'")
                pause()
                continue

            ilist = [f"{i.app_id}" for i in installed]
            iidx = choose(ilist, title=f"Select app to uninstall from '{agent.name}'")
            target = installed[iidx]

            if confirm(f"Uninstall '{target.app_id}' from '{agent.name}'?", default=False):
                agent_app_mgr.uninstall_app(agent.agent_id, target.app_id)
                print_success(f"Uninstalled '{target.app_id}' from '{agent.name}'")
            else:
                print_warning("Cancelled")
            pause()

        elif choice == 3:
            if not agents:
                print_warning("No agents created yet.")
                pause()
                continue

            glist = [f"{g.agent_id} — {g.name}" for g in agents]
            gidx = choose(glist, title="Select agent to toggle app")
            agent = agents[gidx]

            installed = agent_app_mgr.list_agent_apps(agent.agent_id)
            if not installed:
                print_warning(f"No apps installed for '{agent.name}'")
                pause()
                continue

            ilist = [f"{'●' if i.is_enabled else '○'} {i.app_id}" for i in installed]
            iidx = choose(ilist, title=f"Select app to toggle for '{agent.name}'")
            target = installed[iidx]

            if target.is_enabled:
                agent_app_mgr.disable_app(agent.agent_id, target.app_id)
                print_success(f"Disabled '{target.app_id}' for '{agent.name}'")
            else:
                agent_app_mgr.enable_app(agent.agent_id, target.app_id)
                print_success(f"Enabled '{target.app_id}' for '{agent.name}'")
            pause()

        elif choice == 4:
            if not agents:
                print_warning("No agents created yet.")
                pause()
                continue

            glist = [f"{g.agent_id} — {g.name}" for g in agents]
            gidx = choose(glist, title="Select agent to list apps")
            agent = agents[gidx]

            installed = agent_app_mgr.list_agent_apps(agent.agent_id)
            if not installed:
                print_warning(f"No apps installed for '{agent.name}'")
            else:
                rows = []
                for i in installed:
                    status = "● enabled" if i.is_enabled else "○ disabled"
                    rows.append([i.app_id, status])
                print_table(
                    ["App ID", "Status"],
                    rows,
                    title=f"Apps installed for '{agent.name}' ({agent.agent_id})",
                )
            pause()

        elif choice == 5:
            if not agents:
                print_warning("No agents created yet.")
                pause()
                continue

            glist = [f"{g.agent_id} — {g.name}" for g in agents]
            gidx = choose(glist, title="Select agent to configure")
            agent = agents[gidx]

            import json as _json

            installed = agent_app_mgr.list_agent_apps(agent.agent_id)
            if not installed:
                print_warning(f"No apps installed for '{agent.name}'")
                pause()
                continue

            ilist = [f"{i.app_id}" for i in installed]
            iidx = choose(ilist, title=f"Select app to configure for '{agent.name}'")
            target = installed[iidx]

            app_record = app_registry.get_app(target.app_id)
            config_schema = []
            if app_record and app_record.manifest:
                try:
                    m = _json.loads(app_record.manifest) if isinstance(app_record.manifest, str) else app_record.manifest
                    config_schema = m.get("config_schema", [])
                except (_json.JSONDecodeError, TypeError):
                    pass

            if not config_schema:
                print_warning(f"App '{target.app_id}' has no configurable settings")
                pause()
                continue

            current_config = {}
            if target.config:
                try:
                    current_config = _json.loads(target.config) if isinstance(target.config, str) else target.config
                except (_json.JSONDecodeError, TypeError):
                    current_config = {}

            print_info(f"Configuring '{target.app_id}' for '{agent.name}'")
            values = {}
            for field in config_schema:
                fname = field.get("name", "")
                ftype = field.get("type", "string")
                flabel = field.get("label", fname)
                fdesc = field.get("description", "")
                freq = field.get("required", False)
                fdefault = field.get("default")
                current = current_config.get(fname, fdefault)

                prompt = flabel
                if freq:
                    prompt += " *"
                if fdesc:
                    prompt += f" ({fdesc})"

                if ftype == "boolean":
                    from cli_service.display import confirm as _confirm
                    val = _confirm(prompt, default=bool(current) if current is not None else False)
                elif ftype == "integer":
                    default_str = str(current) if current is not None else ""
                    raw = input(f"  {prompt}: ") if True else ""
                    if not raw and current is not None:
                        val = current
                    else:
                        try:
                            val = int(raw)
                        except (ValueError, TypeError):
                            val = current if current is not None else 0
                else:
                    default_str = str(current) if current is not None else ""
                    raw = input(f"  {prompt} [{default_str}]: ").strip()
                    if not raw and current is not None:
                        val = current
                    else:
                        val = raw or default_str

                values[fname] = val

            if confirm("Save configuration?", default=True):
                agent_app_mgr.set_app_config(agent.agent_id, target.app_id, _json.dumps(values))
                print_success(f"Configuration saved for '{target.app_id}' on '{agent.name}'")
            else:
                print_warning("Cancelled")
            pause()

        elif choice == 6:
            if not agents:
                print_warning("No agents created yet.")
                pause()
                continue

            glist = [f"{g.agent_id} — {g.name}" for g in agents]
            gidx = choose(glist, title="Select agent to manage tabs")
            agent = agents[gidx]

            app_tab_mgr = CONFIG.get("app_tab_mgr")
            if app_tab_mgr is None:
                print_warning("Tab manager not available in this context")
                pause()
                continue

            tabs = app_tab_mgr.list_open_apps(agent.agent_id)
            if not tabs:
                print_warning(f"No open tabs for '{agent.name}'")
                pause()
                continue

            tlist = [
                f"{'📌' if t.is_persistent else '  '} {t.app_id} ({t.tab_label or 'no label'})"
                for t in tabs
            ]
            tidx = choose(tlist, title=f"Select tab to toggle persistence for '{agent.name}'")
            target = tabs[tidx]

            new_val = not target.is_persistent
            app_tab_mgr.set_tab_persistence(target.id, new_val)
            app_tab_mgr.refresh_interface(target.id)
            status = "persistent" if new_val else "closable"
            print_success(f"Tab '{target.app_id}' is now {status}")
            pause()

        elif choice == 7:
            app_tab_mgr = CONFIG.get("app_tab_mgr")
            if app_tab_mgr is not None:
                app_tab_mgr.scan_app_handlers(str(APPS_DIR))
            count = len(app_registry.scan_apps_directory(str(APPS_DIR)))
            print_success(f"Rescanned apps directory. Found {count} apps.")
            pause()


def cmd_models_menu(tracker, provider) -> None:
    while True:
        print_header(
            f"Models for {provider.name}",
            f"Main > Providers > {provider.name} > Models",
        )

        items = list(provider.models.items())
        if items:
            rows = []
            for i, (mname, mid) in enumerate(items):
                flag = "●" if provider.active_models.get(mname) else "○"
                rows.append([flag, mname, mid])
            status_w = max(cell_len(r[0]) for r in rows)
            print_table(
                ["", "Name", "Model ID"],
                rows,
                col_widths=[status_w],
                justify=["center"],
            )
        else:
            print_warning("No models configured")

        print_empty()
        choice = choose(
            ["Add model", "Remove model", "Back"],
            title="Model management",
            default=2,
            hint="Add, remove, or toggle models for this provider",
        )

        if choice == 2:
            tracker.save_provider(provider)
            return

        if choice == 0:
            mname = ask(
                "Model name",
                hint="e.g. gpt-4o, claude-sonnet-4-20250514",
            )
            if not mname:
                print_warning("Cancelled")
                continue

            if mname in provider.models:
                print_warning(f"Model '{mname}' already exists")
                pause()
                continue

            mid = ask(
                "Model ID",
                default=mname,
                hint="The API model identifier (usually same as name)",
            )
            provider.models[mname] = mid or mname
            tracker.save_provider(provider)
            print_success(f"Added {mname} → {mid or mname}")

        elif choice == 1:
            items = list(provider.models.items())
            if not items:
                print_warning("No models to remove")
                pause()
                continue

            model_choices = [f"{mname} ({mid})" for mname, mid in items]
            idx = choose(
                model_choices,
                title="Select model to remove",
                hint="This removes the model configuration",
            )
            removed_name, removed_id = items[idx]
            del provider.models[removed_name]
            provider.active_models.pop(removed_name, None)
            tracker.save_provider(provider)
            print_success(f"Removed {removed_name} ({removed_id})")


def _display_host(raw_host: str) -> str:
    return "localhost" if raw_host in ("0.0.0.0", "::", "") else raw_host


def _get_lan_ip() -> Optional[str]:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _make_passkey(raw_host: str, port: str, username: str, password: str) -> str:
    import base64, json
    blob = json.dumps({
        "host": raw_host, "port": int(port), "username": username, "password": password,
        "encryption_available": True,
    }, separators=(",", ":"))
    return base64.urlsafe_b64encode(blob.encode()).decode()


def cmd_connection_info() -> None:
    config_mgr = CONFIG["config_mgr"]
    config = config_mgr.get_all_config()
    raw_host = config.get("api_host", "0.0.0.0")
    port = config.get("api_port", "4464")
    display_host = _display_host(raw_host)
    lan_ip = _get_lan_ip()

    row = config_mgr._svc.query_one(
        "SELECT username FROM api_users ORDER BY id LIMIT 1"
    )
    if not row:
        print_error("No user found. Run init first.")
        pause()
        return

    username = row["username"]
    password = config_mgr.get_config("frontend_password")

    if not password:
        import secrets
        import base64 as _b64
        password = _b64.b64encode(secrets.token_bytes(12)).decode()
        config_mgr._svc.execute(
            "INSERT OR REPLACE INTO api_config (key, value) VALUES (?, ?)",
            ("frontend_password", password),
        )
        from api_service.database import hash_password
        config_mgr._svc.execute(
            "UPDATE api_users SET hashed_password = ? WHERE username = ?",
            (hash_password(password), username),
        )
        print_info("Generated new frontend password")

    b64 = _make_passkey(raw_host, port, username, password)

    print_empty()
    host_label = f"{lan_ip}:{port}" if lan_ip else f"{display_host}:{port}"
    parts = [
        ("\n", ""),
        (f"  {'Host:':<12}", "bold"), (f"{host_label}\n", ""),
    ]
    if lan_ip:
        parts.append((f"    (also http://localhost:{port})\n", "dim"))
    parts += [
        (f"  {'Port:':<12}", "bold"), (f"{port}\n", ""),
        (f"  {'Username:':<12}", "bold"), (f"{username}\n", ""),
        (f"  {'Password:':<12}", "bold"), (f"{password}\n", ""),
        ("\n", ""),
        ("  Passkey", "bold"), ("  (click to select & copy)\n", "dim"),
        (f"  {b64}\n", "bold green"),
    ]
    lines = Text.assemble(*parts)

    console.print(Panel(
        lines,
        title="[bold cyan]Connection Info[/bold cyan]",
        box=rich_box.DOUBLE,
        border_style="cyan",
        padding=(1, 3),
    ))

    if confirm("Copy passkey to clipboard?"):
        if _copy_to_clipboard(b64):
            print_success("Copied passkey to clipboard")
        else:
            print_warning("Could not copy to clipboard")
            print_hint("Select the passkey text above and copy manually")

    if confirm("Start QR code server (60s)?", default=False):
        print_empty()
        _start_qr_server(raw_host, port, username, password, display_host, lan_ip)


def _start_qr_server(raw_host: str, port_raw: str, username: str, password: str, display_host: str, lan_ip: str | None) -> None:
    port = int(port_raw)
    import json
    import base64
    import io
    import time
    import qrcode
    from http.server import HTTPServer, BaseHTTPRequestHandler

    blob = json.dumps({
        "host": raw_host, "port": port, "username": username, "password": password,
        "encryption_available": True,
    }, separators=(",", ":"))
    passkey_b64 = base64.urlsafe_b64encode(blob.encode()).decode()

    qr_img = qrcode.make(passkey_b64)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_bytes = buf.getvalue()

    primary_host = lan_ip if lan_ip else display_host

    def _make_html(remaining: int) -> str:
        return f"""<!DOCTYPE html>
<html>
<head>
  <title>Cognithor — QR Code</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Courier New', monospace; background: #0d1117; color: #b7e1fa; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 2.5rem; text-align: center; max-width: 480px; width: 90%; }}
    h1 {{ color: #00d4ff; font-size: 1.8rem; margin-bottom: 0.3rem; }}
    .sub {{ color: #8b949e; margin-bottom: 1.5rem; }}
    .qr {{ margin: 1.5rem 0; }}
    .qr img {{ width: 280px; height: 280px; border-radius: 8px; }}
    .label {{ color: #8b949e; font-size: 0.8rem; margin-top: 1rem; }}
    .passkey {{ color: #3fb950; word-break: break-all; font-size: 0.75rem; margin: 0.5rem 0; background: #0d1117; padding: 0.8rem; border-radius: 6px; cursor: pointer; user-select: all; }}
    .passkey:hover {{ background: #1c2333; }}
    .info {{ color: #8b949e; font-size: 0.75rem; margin-top: 0.5rem; }}
    .timer {{ color: #f0883e; font-size: 0.9rem; font-weight: bold; margin-top: 0.8rem; }}
    .toast {{ opacity: 0; transition: opacity 0.3s; color: #3fb950; font-size: 0.8rem; margin-top: 0.3rem; }}
    .toast.show {{ opacity: 1; }}
    .gone {{ display: none; }}
  </style>
</head>
<body>
  <div class="card" id="card">
    <h1>◈ Cognithor</h1>
    <p class="sub">Scan to connect your frontend</p>
    <div class="qr"><img src="/qr.png" alt="QR Code" /></div>
    <p class="label">Passkey (click to copy)</p>
    <p class="passkey" id="passkey" onclick="copyPasskey()">{passkey_b64}</p>
    <p id="toast" class="toast">✓ Copied!</p>
    <p class="label">Server</p>
    <p class="info">http://{primary_host}:{port}</p>
    <p class="timer" id="timer">⏱ Auto-shutdown in {remaining} seconds</p>
  </div>
  <script>
    var remaining = {remaining};
    var alive = true;
    function shutdown() {{
      if (!alive) return;
      alive = false;
      var card = document.getElementById('card');
      card.innerHTML = '<h1>◈ Cognithor</h1><p class="sub" style="color:#f0883e;margin-top:1rem;">⏱ Server has shut down</p><p class="info">The QR server has stopped. Re-run the command to start a new one.</p>';
    }}
    function updateTimer() {{
      var t = document.getElementById('timer');
      if (!t || !alive) return;
      remaining--;
      if (remaining <= 0) {{
        shutdown();
      }} else {{
        t.textContent = '⏱ Auto-shutdown in ' + remaining + ' seconds';
      }}
    }}
    setInterval(updateTimer, 1000);
    function heartbeat() {{
      if (!alive) return;
      fetch('/').then(function(r) {{
        if (!r.ok) shutdown();
      }}).catch(function() {{
        shutdown();
      }});
    }}
    setInterval(heartbeat, 2000);
    function copyPasskey() {{
      var el = document.getElementById('passkey');
      if (!el) return;
      var text = el.textContent;
      if (navigator.clipboard) {{
        navigator.clipboard.writeText(text).then(function() {{
          var toast = document.getElementById('toast');
          if (toast) {{ toast.classList.add('show'); setTimeout(function() {{ toast.classList.remove('show'); }}, 1500); }}
        }});
      }} else {{
        var ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        var toast = document.getElementById('toast');
        if (toast) {{ toast.classList.add('show'); setTimeout(function() {{ toast.classList.remove('show'); }}, 1500); }}
      }}
    }}
  </script>
</body>
</html>"""

    class QRHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/qr.png", "/onboarding/passkey.qr"):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(qr_bytes)
            else:
                remaining = max(0, int(deadline - time.time()))
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(_make_html(remaining).encode())

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), QRHandler)
    server.timeout = 0.5
    deadline = time.time() + 60

    def _make_qr_panel(remaining: int) -> Panel:
        text = Text.assemble(
            ("\n", ""),
            (f"    Open http://{primary_host}:{port} in your browser\n", ""),
            ("" if not lan_ip else f"    Or http://localhost:{port}\n"),
            ("\n", ""),
            ("    Scan the QR code from the webpage to connect your frontend\n", "dim"),
            ("\n", ""),
            (f"    [ Auto-shutdown in {remaining}s ]", "bold yellow"),
            ("\n", ""),
        )
        return Panel(
            text,
            title="[bold cyan]QR Code Server[/bold cyan]",
            subtitle="[dim]Ctrl+C to stop early[/dim]",
            box=rich_box.ROUNDED,
            border_style="cyan",
            padding=(1, 3),
        )

    try:
        with Live(_make_qr_panel(60), console=console, refresh_per_second=4, transient=True) as live:
            while time.time() < deadline:
                remaining = max(0, int(deadline - time.time()))
                live.update(_make_qr_panel(remaining))
                try:
                    server.handle_request()
                except KeyboardInterrupt:
                    raise
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    print_empty()
    print_info("QR server stopped.")


def _copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except ImportError:
        pass

    import subprocess
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen(
                ["pbcopy"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            p.communicate(input=text.encode())
            return p.returncode == 0
        elif sys.platform == "linux":
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            p.communicate(input=text.encode())
            return p.returncode == 0
    except Exception:
        pass
    return False


def _do_encrypt() -> None:
    if not PYSQLCIPHER_AVAILABLE:
        print_error("pysqlcipher3 is not installed. Cannot encrypt.")
        print_info("Install: pip install pysqlcipher3")
        pause()
        return

    if CONFIG["use_encryption"]:
        print_warning("Databases are already encrypted.")
        pause()
        return

    print_header("Encrypt Database", "plain-text → SQLCipher")
    print_info("This encrypts both databases with a new key.")
    print_info("The key will be stored in your system keyring.")
    print_empty()

    if not confirm("Proceed with encryption?", default=False):
        print_warning("Cancelled.")
        return

    from secure_db_service.encrypt import encrypt_databases

    with spinner("Encrypting") as progress:
        task = progress.add_task("", total=None)
        try:
            encrypt_databases(CONFIG["config_mgr"], CONFIG["tracker"])
            CONFIG["use_encryption"] = True
            progress.stop()
            print_success("Databases are now ENCRYPTED")
            print_info("Restart the server for the change to take effect.")
        except Exception as e:
            progress.stop()
            print_error(f"Encryption failed: {e}")

    pause()


def _do_decrypt() -> None:
    if not CONFIG["use_encryption"]:
        print_warning("Databases are already plain-text.")
        pause()
        return

    print_header("Decrypt Database", "SQLCipher → plain-text")
    print_info("This decrypts both databases to plain-text SQLite.")
    print_empty()

    if not confirm("Proceed with decryption?", default=False):
        print_warning("Cancelled.")
        return

    from secure_db_service.decrypt import decrypt_databases

    with spinner("Decrypting") as progress:
        task = progress.add_task("", total=None)
        try:
            decrypt_databases(CONFIG["config_mgr"], CONFIG["tracker"])
            CONFIG["use_encryption"] = False
            progress.stop()
            print_success("Databases are now plain-text")
            print_info("Restart the server for the change to take effect.")
        except Exception as e:
            progress.stop()
            print_error(f"Decryption failed: {e}")

    pause()


def cmd_database_menu() -> None:
    while True:
        print_empty()
        print_encryption_status_panel(
            encrypted=CONFIG["use_encryption"],
            pysqlcipher_available=PYSQLCIPHER_AVAILABLE,
        )

        if not CONFIG["use_encryption"] and not PYSQLCIPHER_AVAILABLE:
            print_empty()
            console.print(Panel(
                Text(
                    "pysqlcipher3 is required to enable encryption.\n\n"
                    "  sudo apt install libsqlcipher-dev\n"
                    "  pip install pysqlcipher3",
                    style="yellow",
                ),
                title="[bold yellow]Encryption unavailable[/bold yellow]",
                box=rich_box.HEAVY,
                border_style="yellow",
                padding=(1, 2),
            ))
        elif not CONFIG["use_encryption"] and PYSQLCIPHER_AVAILABLE:
            print_empty()
            print_hint("Databases are plain-text. Encrypt them to protect data at rest.")

        print_empty()

        if CONFIG["use_encryption"]:
            choices = ["Decrypt database (SQLCipher → plain-text)", "Back to main menu"]
            default = 1
        else:
            choices = ["Encrypt database (plain-text → SQLCipher)", "Back to main menu"]
            default = 1

        choice = choose(
            choices,
            title="Select an action",
            default=default,
            hint="Manage database encryption",
        )

        if choice == 1:
            return

        if CONFIG["use_encryption"]:
            _do_decrypt()
        else:
            _do_encrypt()


def cmd_time_menu() -> None:
    time_svc = CONFIG.get("time_svc")
    if time_svc is None:
        print_warning("Time service not initialized.")
        pause()
        return

    while True:
        print_header("Time Configuration", "Main > Time")

        cfg = time_svc.get_config()
        now = time_svc.now()

        lines = [
            f"  Real epoch:    {cfg.real_epoch}",
            f"  Agent epoch:   {cfg.agent_epoch}",
            f"  Ratio:         {cfg.ratio}x",
            "",
            f"  Current agent time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"  Current timestamp:  {time_svc.now_timestamp():.0f}",
        ]
        now_real = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
        lines.append(f"  Real time:          {now_real.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        console.print(Panel(
            Text("\n".join(lines)),
            title="[bold cyan]Time Configuration[/bold cyan]",
            box=rich_box.ROUNDED,
            border_style="cyan",
            padding=(1, 2),
        ))

        print_empty()
        choice = choose(
            [
                "Set real epoch (day one mapping)",
                "Set agent epoch (day one mapping)",
                "Set ratio (speed multiplier)",
                "Reset to defaults (1970-01-01 1:1)",
                "Back to main menu",
            ],
            title="Select an action",
            default=4,
            hint="Time flows at ratio × real time from real_epoch",
        )

        if choice == 4:
            return

        if choice == 0:
            val = ask(
                "Real epoch (ISO datetime)",
                default=cfg.real_epoch,
                hint="e.g. 1999-05-21T00:00:00+00:00",
            )
            if val:
                try:
                    time_svc.set_config(real_epoch=str(val))
                    print_success("Real epoch updated")
                except Exception as e:
                    print_error(str(e))

        elif choice == 1:
            val = ask(
                "Agent epoch (ISO datetime)",
                default=cfg.agent_epoch,
                hint="e.g. 2024-06-15T00:00:00+00:00",
            )
            if val:
                try:
                    time_svc.set_config(agent_epoch=str(val))
                    print_success("Agent epoch updated")
                except Exception as e:
                    print_error(str(e))

        elif choice == 2:
            val = ask(
                "Ratio (speed multiplier)",
                default=str(cfg.ratio),
                hint="1.0 = real time, 3.0 = 3x faster, 0.5 = half speed",
            )
            if val:
                try:
                    time_svc.set_config(ratio=float(val))
                    print_success(f"Ratio set to {float(val)}x")
                except (ValueError, Exception) as e:
                    print_error(str(e))

        elif choice == 3:
            if confirm("Reset time config to defaults (1970-01-01, 1:1)?"):
                from core.time.time_service import _DEFAULT_REAL_EPOCH, _DEFAULT_AGENT_EPOCH, _DEFAULT_RATIO
                time_svc.set_config(
                    real_epoch=_DEFAULT_REAL_EPOCH,
                    agent_epoch=_DEFAULT_AGENT_EPOCH,
                    ratio=_DEFAULT_RATIO,
                )
                print_success("Reset to defaults")


def interactive_main() -> bool:
    print_banner(subtitle="Backend Management CLI")
    console.print(
        Text("Manage providers, models, encryption, and connection info", style="dim"),
        justify="center",
    )

    try:
        if db_exists():
            use_enc = detect_db_encryption()
            _init_services(use_enc)
            enc_label = "ENCRYPTED" if use_enc else "plain-text"
            print_success(f"Database loaded ({enc_label})")
            print_hint("All services initialized and ready")
        else:
            print_warning("No database found. Let's set one up.")
            print_hint("You'll be guided through initialization")
            print_empty()
            use_enc = confirm("Enable database encryption?", default=PYSQLCIPHER_AVAILABLE)
            cmd_init(use_encryption=use_enc, verbose=False)
            _init_services(use_encryption=use_enc)
    except Exception as e:
        print_error(str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)

    try:
        while True:

            if CONFIG["use_encryption"]:
                enc_label = "ENCRYPTED"
            elif PYSQLCIPHER_AVAILABLE:
                enc_label = "plain-text"
            else:
                enc_label = "plain-text !"

            config_mgr = CONFIG.get("config_mgr")
            tracker = CONFIG.get("tracker")
            agent_mgr = CONFIG.get("agent_mgr")
            app_registry = CONFIG.get("app_registry")
            status_api = "N/A"
            status_providers = "0"
            status_agents = "0"
            status_apps = "0"
            status_active = "none"
            if config_mgr and tracker:
                try:
                    cfg = config_mgr.get_all_config()
                    status_api = f"{cfg.get('api_host', '0.0.0.0')}:{cfg.get('api_port', '4464')}"
                    providers = tracker.list_providers()
                    status_providers = str(len(providers))
                    if agent_mgr:
                        status_agents = str(len(agent_mgr.list_agents()))
                    if app_registry:
                        status_apps = str(len(app_registry.list_apps()))
                    act = [p.name for p in providers if any(p.active_models.values()) or p.is_active]
                    status_active = act[0] if act else "none"
                except Exception:
                    pass

            status_lines = Text.assemble(
                ("\n", ""),
                (f"  {'Database:':<13}", "bold"), (f"{DB_PATH}\n", "cyan"),
                (f"  {'Encryption:':<13}", "bold"), (f"{enc_label}\n", "cyan"),
                (f"  {'API:':<13}", "bold"), (f"{status_api}\n", "cyan"),
                (f"  {'Providers:':<13}", "bold"), (f"{status_providers}", "cyan"),
                ("  active: ", "dim"), (f"{status_active}\n", "cyan"),
                (f"  {'Agents:':<13}", "bold"), (f"{status_agents}", "cyan"),
                (f"  {'Apps:':<13}", "bold"), (f"{status_apps}\n", "cyan"),
            )

            console.print(Panel(
                status_lines,
                title="[bold cyan]Main Menu[/bold cyan]",
                subtitle="[dim]navigate with ↑↓ · Enter to select[/dim]",
                box=rich_box.ROUNDED,
                border_style="cyan",
                padding=(1, 3),
            ))

            choice = choose(
                [
                    "Provider Management",
                    "Agent Management",
                    "App Management",
                    "Time Configuration",
                    "Database Management",
                    "Connection Info",
                    "Start server",
                    "Quit",
                ],
                title="Select an option",
                default=6,
                hint="Manage Cognithor backend configuration",
            )

            if choice == 0:
                cmd_providers_menu()
            elif choice == 1:
                cmd_agents_menu()
            elif choice == 2:
                cmd_apps_menu()
            elif choice == 3:
                cmd_time_menu()
            elif choice == 4:
                cmd_database_menu()
            elif choice == 5:
                cmd_connection_info()
            elif choice == 6:
                return True
            elif choice == 7:
                print_empty()
                console.print(
                    Panel(
                        Text("Thanks for using Cognithor!", style="bold cyan"),
                        box=rich_box.HEAVY,
                        border_style="cyan",
                        padding=(1, 4),
                    )
                )
                return False
    except KeyboardInterrupt:
        print_empty()
        console.print(
            Panel(
                Text("Thanks for using Cognithor!", style="bold cyan"),
                box=rich_box.HEAVY,
                border_style="cyan",
                padding=(1, 4),
            )
        )
        return False
