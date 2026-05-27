"""Interactive CLI menu — refactored from api_service/cli_launcher.py.

Uses rich for colorful rendering, panels, tables, and spinners.
Breadcrumb navigation, step guidance, and context-sensitive hints.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

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

PYSQLCIPHER_AVAILABLE = False
try:
    from pysqlcipher3 import dbapi2 as _pysqlcipher
    PYSQLCIPHER_AVAILABLE = True
except ImportError:
    pass

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "cognithor.db"

CONFIG: dict = {
    "config_mgr": None,
    "tracker": None,
    "use_encryption": False,
}


def _init_services(use_encryption: bool = False) -> None:
    if CONFIG["config_mgr"] is not None:
        return

    CONFIG["use_encryption"] = use_encryption

    from log_service import LogDatabase, LogService
    from endpoint.database import Tracker
    from api_service.database import ApiConfigManager
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


def db_exists() -> bool:
    return DB_PATH.exists()


def detect_db_encryption() -> bool:
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

    if not PYSQLCIPHER_AVAILABLE:
        print_empty()
        console.print(Panel(
            Text(
                "The database file appears to be encrypted,\n"
                "and pysqlcipher3 is not installed.\n\n"
                "Options:\n"
                "  1. Install pysqlcipher3\n"
                "  2. Reset with NEW encrypted database\n"
                "  3. Reset with NEW plain-text database",
                style="yellow",
            ),
            title="[bold red]Database Locked[/bold red]",
            box=rich_box.HEAVY,
            border_style="red",
            padding=(1, 2),
        ))

        choice = choose(
            ["Install pysqlcipher3", "Reset → NEW encrypted database",
             "Reset → NEW plain-text database", "Quit"],
            title="How would you like to proceed?",
            default=2,
        )

        if choice == 0:
            import subprocess
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "pysqlcipher3"]
                )
                print_success("Installed pysqlcipher3. Please restart.")
            except subprocess.CalledProcessError:
                print_error("Installation failed.")
                print_info("Try: sudo apt install libsqlcipher-dev && pip install pysqlcipher3")
            sys.exit(1)
        elif choice == 1:
            from cli_service.onboarding import cmd_clear
            cmd_clear(force=True)
            print_success("Cleared. Re-initializing with encryption...")
            return True
        elif choice == 2:
            from cli_service.onboarding import cmd_clear
            cmd_clear(force=True)
            print_success("Cleared. Re-initializing plain-text...")
            return False
        else:
            sys.exit(0)

    from secure_db_service import SecureDbService
    try:
        svc = SecureDbService(db_path=DB_PATH, use_encryption=True)
        svc.query_one("SELECT 1")
        return True
    except Exception:
        pass

    try:
        svc = SecureDbService(db_path=DB_PATH, use_encryption=False)
        svc.query_one("SELECT 1")
        return False
    except Exception:
        pass

    print_empty()
    console.print(Panel(
        Text("The database file is invalid or corrupt.", style="yellow"),
        title="[bold red]Corrupt Database[/bold red]",
        box=rich_box.HEAVY,
        border_style="red",
        padding=(1, 2),
    ))

    choice = choose(
        ["Reset → NEW encrypted database", "Reset → NEW plain-text database", "Quit"],
        title="Recovery options",
        default=2,
    )
    if choice == 0:
        from cli_service.onboarding import cmd_clear
        cmd_clear(force=True)
        print_success("Cleared. Re-initializing with encryption...")
        return True
    elif choice == 1:
        from cli_service.onboarding import cmd_clear
        cmd_clear(force=True)
        print_success("Cleared. Re-initializing plain-text...")
        return False
    else:
        sys.exit(0)


def cmd_init() -> None:
    print_header("Initialize Database", "Step 1/3: Create database")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    removed = 0
    for f in list(DATA_DIR.glob("cognithor*")):
        f.unlink()
        removed += 1
        print_dim(f"Removed stale: {f.name}")

    print_empty()
    use_enc = confirm(
        "Use database encryption?",
        default=True,
        hint="Encryption protects data at rest via SQLCipher (AES-256)",
    )

    if use_enc:
        if not PYSQLCIPHER_AVAILABLE:
            print_warning("pysqlcipher3 not installed. Falling back to plain-text SQLite.")
            use_enc = False
        else:
            from secure_db_service import get_or_create_key
            db_key = get_or_create_key()
            print_success(f"DB key {'generated' if db_key else 'ready'}")

    print_step(2, 3, "Creating tables and seeding defaults")
    from secure_db_service import SecureDbService
    from log_service import LogDatabase, LogService

    svc = SecureDbService(
        db_path=DB_PATH,
        use_encryption=use_enc,
        key_name="db_key",
    )

    log_db = LogDatabase(
        db_path=DATA_DIR / "cognithor_logs.db",
        use_encryption=use_enc,
    )
    log_svc = LogService(database=log_db)
    print_success("Log database initialized")

    from api_service.database import DEFAULT_CONFIG, hash_password
    import secrets

    svc.execute_script("""
        CREATE TABLE IF NOT EXISTS api_config (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            key   TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT NOT NULL UNIQUE,
            hashed_password TEXT NOT NULL,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS providers (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            name                    TEXT NOT NULL UNIQUE,
            api_key                 TEXT,
            base_url                TEXT NOT NULL,
            endpoint_path           TEXT DEFAULT '/chat/completions',
            models                  TEXT,
            active_models           TEXT DEFAULT '{}',
            headers_template        TEXT DEFAULT '{}',
            auth_type               TEXT DEFAULT 'bearer',
            auth_header_name        TEXT,
            body_template           TEXT NOT NULL,
            response_content_path   TEXT DEFAULT 'choices.0.message.content',
            response_usage_input_path  TEXT DEFAULT 'usage.prompt_tokens',
            response_usage_output_path TEXT DEFAULT 'usage.completion_tokens',
            response_usage_cost_path   TEXT,
            is_streaming            INTEGER DEFAULT 0,
            is_active               INTEGER DEFAULT 0,
            max_retries             INTEGER DEFAULT 3,
            timeout_seconds         INTEGER DEFAULT 60,
            max_concurrent          INTEGER DEFAULT 5,
            created_at              TEXT DEFAULT (datetime('now')),
            updated_at              TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS usage_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            provider        TEXT NOT NULL,
            model           TEXT NOT NULL,
            input_tokens    INTEGER DEFAULT 0,
            output_tokens   INTEGER DEFAULT 0,
            cost            REAL DEFAULT 0.0,
            duration_ms     REAL,
            status          TEXT DEFAULT 'completed',
            context         TEXT,
            timestamp       TEXT DEFAULT (datetime('now')),
            metadata        TEXT
        );
        CREATE TABLE IF NOT EXISTS health_checks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            provider    TEXT NOT NULL,
            available   INTEGER NOT NULL,
            latency_ms  REAL,
            error       TEXT,
            checked_at  TEXT DEFAULT (datetime('now'))
        );
    """)

    for key, default_value in DEFAULT_CONFIG.items():
        existing = svc.query_one("SELECT value FROM api_config WHERE key = ?", (key,))
        if existing is not None:
            continue
        if default_value is None:
            if key == "encryption_key":
                continue
            value = secrets.token_hex(32)
        else:
            value = default_value
        svc.execute("INSERT INTO api_config (key, value) VALUES (?, ?)", (key, value))

    admin = svc.query_one("SELECT id FROM api_users WHERE username = ?", ("admin",))
    if admin is None:
        import base64 as _b64
        raw_pw = _b64.b64encode(secrets.token_bytes(12)).decode()
        svc.execute(
            "INSERT INTO api_users (username, hashed_password) VALUES (?, ?)",
            ("admin", hash_password(raw_pw)),
        )
        svc.execute(
            "INSERT OR REPLACE INTO api_config (key, value) VALUES (?, ?)",
            ("frontend_password", raw_pw),
        )
        print_success("Admin user created")
        print_hint("Use 'Connection info' in main menu to reveal credentials")

    from endpoint.database import DEFAULT_PROVIDERS
    import json
    import datetime as _dt

    for rec in DEFAULT_PROVIDERS:
        existing = svc.query_one(
            "SELECT id FROM providers WHERE name = ?", (rec.name,)
        )
        if existing:
            continue
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        svc.execute(
            """INSERT INTO providers
                (name, api_key, base_url, endpoint_path, models, active_models,
                 headers_template, auth_type, auth_header_name, body_template,
                 response_content_path, response_usage_input_path,
                 response_usage_output_path, response_usage_cost_path,
                 is_streaming, is_active, max_retries, timeout_seconds, max_concurrent,
                 created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.name, rec.api_key, rec.base_url, rec.endpoint_path,
                json.dumps(rec.models), json.dumps(rec.active_models),
                json.dumps(rec.headers_template), rec.auth_type,
                rec.auth_header_name, rec.body_template,
                rec.response_content_path, rec.response_usage_input_path,
                rec.response_usage_output_path, rec.response_usage_cost_path,
                int(rec.is_streaming), int(rec.is_active),
                rec.max_retries, rec.timeout_seconds, rec.max_concurrent,
                now, now,
            ),
        )
    print_success("Default providers seeded")

    from api_service.database import ApiConfigManager
    from endpoint.database import Tracker
    CONFIG["use_encryption"] = use_enc
    CONFIG["tracker"] = Tracker(
        db_path=DB_PATH, use_encryption=use_enc, log_service=log_svc, svc=svc,
    )
    CONFIG["config_mgr"] = ApiConfigManager(
        db_path=DB_PATH, svc=svc, key_name="db_key",
    )

    print_empty()
    print_step(3, 3, "Initialization complete")
    enc_label = "encrypted" if use_enc else "plain-text"
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
        print_table(
            ["", "Provider", "Active Models", "API Key"],
            rows,
            title="Providers",
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
            print_table(
                ["", "Provider", "API Key"],
                rows,
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
            print_table(
                ["", "Name", "Model ID"],
                rows,
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


def interactive_main() -> None:
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
            cmd_init()
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
            status_api = "N/A"
            status_providers = "0"
            status_active = "none"
            if config_mgr and tracker:
                try:
                    cfg = config_mgr.get_all_config()
                    status_api = f"{cfg.get('api_host', '0.0.0.0')}:{cfg.get('api_port', '4464')}"
                    providers = tracker.list_providers()
                    status_providers = str(len(providers))
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
                    "Database Management",
                    "Connection Info",
                    "Quit",
                ],
                title="Select an option",
                default=3,
                hint="Manage Cognithor backend configuration",
            )

            if choice == 0:
                cmd_providers_menu()
            elif choice == 1:
                cmd_database_menu()
            elif choice == 2:
                cmd_connection_info()
            elif choice == 3:
                print_empty()
                console.print(
                    Panel(
                        Text("Thanks for using Cognithor!", style="bold cyan"),
                        box=rich_box.HEAVY,
                        border_style="cyan",
                        padding=(1, 4),
                    )
                )
                break
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
