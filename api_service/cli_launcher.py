"""Interactive CLI launcher for Cognithor - accessible from api_service imports."""

from __future__ import annotations

import sys
from typing import Optional

from api_service.database import ApiConfigManager
from endpoint.database import Tracker
from log_service import LogDatabase, LogService
from pathlib import Path
from secure_db_service.decrypt import decrypt_databases
from secure_db_service.encrypt import encrypt_databases

PYSQLCIPHER_AVAILABLE = False
try:
    from pysqlcipher3 import dbapi2 as _pysqlcipher
    PYSQLCIPHER_AVAILABLE = True
except ImportError:
    pass

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "cognithor.db"

CONFIG = {
    "config_mgr": None,
    "tracker": None,
    "use_encryption": False,
}


def _init_services(use_encryption: bool = False):
    if CONFIG["config_mgr"] is not None:
        return

    CONFIG["use_encryption"] = use_encryption

    log_db = LogDatabase(
        db_path=DATA_DIR / "cognithor_logs.db",
        use_encryption=use_encryption,
    )
    log_svc = LogService(database=log_db)

    CONFIG["tracker"] = Tracker(
        db_path=DB_PATH,
        use_encryption=use_encryption,
        log_service=log_svc,
    )

    CONFIG["config_mgr"] = ApiConfigManager(
        db_path=DB_PATH,
        use_encryption=use_encryption,
        key_name="db_key",
    )


def _input(prompt: str, default: Optional[str] = None) -> str:
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def _input_secret(prompt: str) -> str:
    try:
        import getpass
        return getpass.getpass(f"{prompt}: ")
    except Exception:
        return input(f"{prompt} (warning: will echo): ")


def _choice(options: list[str], default: int = 0) -> int:
    for i, opt in enumerate(options):
        marker = " *" if i == default else ""
        print(f"  {i + 1}. {opt}{marker}")

    while True:
        choice = input(f"\nChoose [1-{len(options)}]: ").strip()
        if not choice:
            return default
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print(f"Invalid choice. Enter 1-{len(options)}")


def _confirm(prompt: str, default_yes: bool = True) -> bool:
    default = "Y/n" if default_yes else "y/N"
    result = input(f"{prompt} [{default}]: ").strip().lower()
    if not result:
        return default_yes
    return result in ("y", "yes")


def _print_table(headers: list[str], rows: list[list]) -> None:
    if not rows:
        print("(no data)")
        return

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  " + "-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))
    for row in rows:
        padded = [str(c) for c in row]
        while len(padded) < len(headers):
            padded.append("")
        print(fmt.format(*padded))


def _copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except ImportError:
        pass

    import subprocess
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen(
                ["pbcopy"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            p.communicate(input=text.encode())
            return p.returncode == 0
        elif sys.platform == "linux":
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            p.communicate(input=text.encode())
            return p.returncode == 0
    except Exception:
        pass
    return False


def cmd_status():
    config_mgr = CONFIG["config_mgr"]
    tracker = CONFIG["tracker"]

    config = config_mgr.get_all_config()
    print("\n--- System Status ---\n")
    print(f"  Database: {DB_PATH}")
    print(f"  API: {config.get('api_host', '0.0.0.0')}:{config.get('api_port', '4464')}")

    providers = tracker.list_providers()
    active = [p.name for p in providers if any(p.active_models.values()) or p.is_active]
    print(f"\n  Providers ({len(providers)}):")
    rows = []
    for p in providers:
        a = "*" if (any(p.active_models.values()) or p.is_active) else " "
        key = "key:SET" if p.api_key else "key:NOT SET"
        active_m = ', '.join(m for m, ok in p.active_models.items() if ok) if p.active_models else ''
        models_info = active_m if active_m else (', '.join(p.models) if p.models else '-')
        rows.append([f"{a} {p.name}", models_info, key])
    _print_table(["Provider", "Active Models", "API Key"], rows)
    print(f"\n  Active provider: {active[0] if active else '(none)'}")
    print(f"  Auth: POST /token with username + password to receive JWT")


def cmd_providers_menu():
    tracker = CONFIG["tracker"]

    while True:
        print("\n--- Provider Management ---\n")
        providers = tracker.list_providers()
        print("  Providers:")
        for p in providers:
            a = " (*)" if (any(p.active_models.values()) or p.is_active) else ""
            k = " [KEY SET]" if p.api_key else " [NO KEY]"
            print(f"    {p.name}{a}{k}")

        choice = _choice([
            "Show details",
            "Set API key",
            "Manage models",
            "Test model",
            "Delete provider",
            "Back",
        ], 5)

        if choice == 5:
            return
        elif choice == 0:
            name = _input("Provider name")
            p = tracker.get_provider(name) if name else None
            if not p:
                print("Not found")
                continue
            print(f"\n  {p.name}:")
            active_m = ', '.join(m for m, ok in p.active_models.items() if ok) if p.active_models else 'none'
            print(f"    Active models: {active_m}")
            print(f"    URL: {p.base_url}{p.endpoint_path}")
            print(f"    Auth: {p.auth_type}")
            print(f"    API key set: {bool(p.api_key)}")
            print(f"    Registered models ({len(p.models)}): {', '.join(p.models) if p.models else 'none'}")
        elif choice == 1:
            name = _input("Provider name")
            p = tracker.get_provider(name) if name else None
            if not p:
                print("Not found")
                continue
            key = _input_secret("API Key")
            if not key:
                print("Cancelled")
                continue
            p.api_key = key
            tracker.save_provider(p)
            print(f"API key set for: {name}")
        elif choice == 2:
            name = _input("Provider name")
            p = tracker.get_provider(name) if name else None
            if not p:
                print("Not found")
                continue
            cmd_models_menu(tracker, p)
        elif choice == 3:
            name = _input("Provider name")
            p = tracker.get_provider(name) if name else None
            if not p:
                print("Not found")
                continue
            if not p.models:
                print("No models configured for this provider")
                continue
            print("  Select model to test:")
            model_list = list(p.models.items())
            for i, (mname, mid) in enumerate(model_list):
                active_flag = " [active]" if p.active_models.get(mname) else ""
                print(f"    {i + 1}. {mname} ({mid}){active_flag}")
            idx = _input(f"Model number [1-{len(model_list)}]")
            if not idx:
                print("Cancelled")
                continue
            try:
                idx = int(idx) - 1
                if idx < 0 or idx >= len(model_list):
                    print("Invalid number")
                    continue
            except ValueError:
                print("Invalid number")
                continue
            test_name, test_id = model_list[idx]
            print(f"\n  Testing {name}/{test_name}...")
            try:
                from endpoint.manager import EndpointManager
                mgr = EndpointManager(tracker=tracker)
                result = mgr.test_model(name, test_name)
                if result["available"]:
                    print(f"    PASSED latency={result['latency_ms']:.0f}ms output_tokens={result['output_tokens']}")
                else:
                    print(f"    FAILED: {result.get('error')}")
            except Exception as e:
                print(f"    ERROR: {e}")
        elif choice == 4:
            name = _input("Provider name to DELETE")
            if name and tracker.get_provider(name):
                if _confirm(f"DELETE '{name}'?", False):
                    tracker._svc.execute("DELETE FROM providers WHERE name = ?", (name,))
                    print(f"Deleted: {name}")
            else:
                print("Not found")


def cmd_models_menu(tracker, provider):
    while True:
        print(f"\n--- Models for {provider.name} ---\n")
        items = list(provider.models.items())
        print(f"  Models ({len(items)}):")
        for i, (mname, mid) in enumerate(items):
            active_flag = " [active]" if provider.active_models.get(mname) else ""
            print(f"    {i + 1}. {mname} ({mid}){active_flag}")

        choice = _choice([
            "Add model",
            "Remove model",
            "Back",
        ], 2)

        if choice == 2:
            tracker.save_provider(provider)
            return
        elif choice == 0:
            mname = _input("Model name (e.g. gpt-4o)")
            if not mname:
                print("Cancelled")
                continue
            if mname in provider.models:
                print(f"Model '{mname}' already exists")
                continue
            mid = _input(f"Model ID (e.g. gpt-4o-2024-05-13) [same as name]", mname)
            provider.models[mname] = mid or mname
            tracker.save_provider(provider)
            print(f"Added: {mname} -> {mid or mname}")
        elif choice == 1:
            items = list(provider.models.items())
            if not items:
                print("No models to remove")
                continue
            print("  Select model to remove:")
            for i, (mname, mid) in enumerate(items):
                print(f"    {i + 1}. {mname} ({mid})")
            idx = _input(f"Model number [1-{len(items)}]")
            if not idx:
                print("Cancelled")
                continue
            try:
                idx = int(idx) - 1
                if idx < 0 or idx >= len(items):
                    print("Invalid number")
                    continue
            except ValueError:
                print("Invalid number")
                continue
            removed_name, removed_id = items[idx]
            del provider.models[removed_name]
            provider.active_models.pop(removed_name, None)
            tracker.save_provider(provider)
            print(f"Removed: {removed_name} ({removed_id})")


def cmd_connection_info():
    config_mgr = CONFIG["config_mgr"]

    config = config_mgr.get_all_config()
    host = config.get("api_host", "0.0.0.0")
    port = config.get("api_port", "4464")

    row = config_mgr._svc.query_one(
        "SELECT username FROM api_users ORDER BY id LIMIT 1"
    )
    if not row:
        print("  No user found. Run init first.")
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
        print("  (generated new frontend password)")

    import base64
    import json
    blob = json.dumps({
        "host": host, "port": int(port), "username": username, "password": password,
        "encryption_available": True,
    }, separators=(",", ":"))
    b64 = base64.urlsafe_b64encode(blob.encode()).decode()

    print(f"\n  ┌──────────────────────────────────────────────────────────────────────┐")
    print(f"  │  CREDENTIALS                                                        │")
    print(f"  │                                                                      │")
    print(f"  │  Host:      {host:<46} │")
    print(f"  │  Port:      {port:<46} │")
    print(f"  │  Username:  {username:<46} │")
    print(f"  │  Password:  {password:<46} │")
    print(f"  └──────────────────────────────────────────────────────────────────────┘")
    print(f"\n  ┌──────────────────────────────────────────────────────────────────────┐")
    print(f"  │  PASSKEY (copy-paste this into the frontend, or scan QR at            │")
    print(f"  │  /onboarding/passkey.qr)                                              │")
    print(f"  │                                                                      │")
    print(f"  │  {b64:<68} │")
    print(f"  │                                                                      │")
    print(f"  │  →  Username: {username:<50} │")
    print(f"  │  →  Password: {password:<50} │")
    print(f"  └──────────────────────────────────────────────────────────────────────┘")
    _copy_to_clipboard(b64)
    print("  (passkey copied to clipboard)")


def cmd_init():
    print("\n--- Initialize Database ---\n")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for f in list(DATA_DIR.glob("cognithor*")):
        f.unlink()
        print(f"  Removed stale: {f.name}")

    use_enc = _confirm("Use database encryption?", True)

    if use_enc:
        try:
            from pysqlcipher3 import dbapi2
        except ImportError:
            print("\n  WARNING: pysqlcipher3 not installed.")
            print("  Falling back to plain-text SQLite.\n")
            use_enc = False

    if use_enc:
        from secure_db_service import get_or_create_key
        db_key = get_or_create_key()
        print(f"  DB key: {'generated' if db_key else 'ready'}")

    from secure_db_service import SecureDbService

    svc = SecureDbService(
        db_path=DB_PATH,
        use_encryption=use_enc,
        key_name="db_key",
    )

    from api_service.database import hash_password

    log_db = LogDatabase(
        db_path=DATA_DIR / "cognithor_logs.db",
        use_encryption=use_enc,
    )
    log_svc = LogService(database=log_db)
    print("  Log DB: initialized")

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

    from api_service.database import DEFAULT_CONFIG
    import secrets

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
        print(f"  Connection credentials created (user: admin)")
        print(f"  To reveal: connect-info command in main menu")

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

    providers = tracker.list_providers() if CONFIG["tracker"] else []
    print(f"  Providers: seeded")

    CONFIG["use_encryption"] = use_enc
    CONFIG["tracker"] = Tracker(db_path=DB_PATH, use_encryption=use_enc, log_service=log_svc, svc=svc)
    CONFIG["config_mgr"] = ApiConfigManager(db_path=DB_PATH, use_encryption=use_enc, key_name="db_key")


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
        print("\n" + "=" * 60)
        print("  DATABASE DETECTED BUT CANNOT BE OPENED")
        print("=" * 60)
        print("\n  The database file appears to be encrypted,")
        print("  and pysqlcipher3 is not installed.\n")
        print("  Options:")
        print("    1. Install pysqlcipher3")
        print("    2. Reset with NEW encrypted database")
        print("    3. Reset with NEW plain-text database")
        print("=" * 60)

        choice = _choice([
            "Install pysqlcipher3",
            "Reset → NEW encrypted database",
            "Reset → NEW plain-text database",
            "Quit",
        ], 3)

        if choice == 0:
            import subprocess
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "pysqlcipher3"])
                print("\n  Installed. Please restart.\n")
            except subprocess.CalledProcessError:
                print("\n  Installation failed.")
                print("  Try: sudo apt install libsqlcipher-dev && pip install pysqlcipher3\n")
            sys.exit(1)
        elif choice == 1:
            from onboarding import setup
            setup.cmd_clear(force=True)
            print("\n  Re-initializing with encryption...\n")
            return True
        elif choice == 2:
            from onboarding import setup
            setup.cmd_clear(force=True)
            print("\n  Re-initializing plain-text...\n")
            return False
        else:
            sys.exit(0)

    try:
        from secure_db_service import SecureDbService
        svc = SecureDbService(db_path=DB_PATH, use_encryption=True)
        svc.query_one("SELECT 1")
        return True
    except Exception:
        pass

    try:
        from secure_db_service import SecureDbService
        svc = SecureDbService(db_path=DB_PATH, use_encryption=False)
        svc.query_one("SELECT 1")
        return False
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  DATABASE FILE IS INVALID OR CORRUPT")
    print("=" * 60)
    print("\n  Options:")
    print("    1. Reset with NEW encrypted database")
    print("    2. Reset with NEW plain-text database")
    print("=" * 60)

    choice = _choice([
        "Reset → NEW encrypted database",
        "Reset → NEW plain-text database",
        "Quit",
    ], 2)

    if choice == 0:
        from onboarding import setup
        setup.cmd_clear(force=True)
        print("\n  Re-initializing with encryption...\n")
        return True
    elif choice == 1:
        from onboarding import setup
        setup.cmd_clear(force=True)
        print("\n  Re-initializing plain-text...\n")
        return False
    else:
        sys.exit(0)


def cmd_encrypt():
    if not PYSQLCIPHER_AVAILABLE:
        print("\n  pysqlcipher3 is not installed. Cannot encrypt.")
        return
    if CONFIG["use_encryption"]:
        print("\n  Databases are already encrypted.")
        return

    print("\n--- Encrypt Database ---\n")
    print("  This will encrypt both databases with a new key.")
    print("  The key will be stored in your system keyring.\n")

    if not _confirm("Proceed?", False):
        print("  Cancelled.")
        return

    print("  Encrypting...", end=" ")
    try:
        encrypt_databases(CONFIG["config_mgr"], CONFIG["tracker"])
        CONFIG["use_encryption"] = True
        print("OK")
        print("\n  Databases are now ENCRYPTED.")
        print("  Restart the server (without -i) for the change to take effect.\n")
    except Exception as e:
        print(f"FAILED: {e}")


def cmd_decrypt():
    if not CONFIG["use_encryption"]:
        print("\n  Databases are already plain-text.")
        return

    print("\n--- Decrypt Database ---\n")
    print("  This will decrypt both databases to plain-text SQLite.\n")

    if not _confirm("Proceed?", False):
        print("  Cancelled.")
        return

    print("  Decrypting...", end=" ")
    try:
        decrypt_databases(CONFIG["config_mgr"], CONFIG["tracker"])
        CONFIG["use_encryption"] = False
        print("OK")
        print("\n  Databases are now plain-text.")
        print("  Restart the server (without -i) for the change to take effect.\n")
    except Exception as e:
        print(f"FAILED: {e}")


def interactive_main():
    header = """
============================================================
  Cognithor Backend - Interactive CLI
============================================================
"""
    print(header)

    try:
        if db_exists():
            use_enc = detect_db_encryption()
            _init_services(use_enc)
        else:
            print("\n  No database found. Let's initialize.\n")
            cmd_init()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    while True:
        enc_label = "ENCRYPTED" if CONFIG["use_encryption"] else "plain-text"
        print("\n--- Main Menu ---\n")
        choice = _choice([
            "Show system status",
            "Provider management",
            "Show connection info (copy for frontend)",
            "Encrypt database",
            "Decrypt database",
            f"Quit (databases: {enc_label})",
        ], 5)

        if choice == 0:
            cmd_status()
        elif choice == 1:
            cmd_providers_menu()
        elif choice == 2:
            cmd_connection_info()
        elif choice == 3:
            cmd_encrypt()
        elif choice == 4:
            cmd_decrypt()
        elif choice == 5:
            print("\n  Bye.\n")
            break


if __name__ == "__main__":
    try:
        interactive_main()
    except KeyboardInterrupt:
        print("\n\n  Cancelled. Bye.\n")
