"""Server CLI — startup, detection, recovery.

Refactored from api_service/main.py CLI portions.
Handles argument parsing, database detection, and uvicorn launch.
create_app() stays in api_service/main.py for module-level app export.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from rich.text import Text
from rich.panel import Panel
from rich import box as rich_box

from cli_service.display import (
    console,
    print_banner,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_status_panel,
    print_empty,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "cognithor.db"

PYSQLCIPHER_AVAILABLE = False
try:
    from pysqlcipher3 import dbapi2 as _pysqlcipher
    PYSQLCIPHER_AVAILABLE = True
except ImportError:
    pass


def _check_config_encryption(svc) -> Optional[bool]:
    try:
        row = svc.query_one(
            "SELECT value FROM api_config WHERE key = 'database_encryption_enabled'",
        )
        if row is not None:
            val = row["value"].strip().lower()
            return val == "true"
    except Exception:
        pass
    return None


def detect_db_encryption() -> bool:
    if not DB_PATH.exists():
        return PYSQLCIPHER_AVAILABLE

    import sqlite3
    from secure_db_service import SecureDbService

    tried_plain = False
    tried_encrypted = False

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
        tried_plain = True
        svc = SecureDbService(db_path=DB_PATH, use_encryption=False)
        result = _check_config_encryption(svc)
        if result is not None:
            return result
        return False
    except sqlite3.DatabaseError:
        pass

    try:
        svc = SecureDbService(db_path=DB_PATH, use_encryption=True)
        svc.query_one("SELECT 1")
        tried_encrypted = True
        result = _check_config_encryption(svc)
        if result is not None:
            return result
        return True
    except Exception:
        pass

    try:
        svc = SecureDbService(db_path=DB_PATH, use_encryption=False)
        svc.query_one("SELECT 1")
        tried_plain = True
        result = _check_config_encryption(svc)
        if result is not None:
            return result
        return False
    except Exception:
        pass

    if tried_plain or tried_encrypted:
        return tried_encrypted

    console.print(Panel(
        Text(f"File: {DB_PATH}\n\nCannot open as plain or encrypted database.\nServer will start in degraded mode.", style="yellow"),
        title="[bold red]Database Cannot Be Opened[/bold red]",
        box=rich_box.HEAVY,
        border_style="red",
        padding=(1, 2),
    ))
    return PYSQLCIPHER_AVAILABLE


def _recovery_prompt(degraded_services: list[tuple[str, str]]) -> None:
    lines = []
    for name, reason in degraded_services:
        lines.append(f"[bold]{name}[/bold]")
        lines.append(f"  {reason}")
    lines.append("")
    lines.append("Recovery options:")
    lines.append("  [R] Remove corrupted files and recreate fresh databases")
    lines.append("  [I] Ignore and continue in degraded mode")
    lines.append("  [E] Exit")

    console.print(Panel(
        Text.from_markup("\n".join(lines)),
        title="[bold red]Database Degraded — Recovery Required[/bold red]",
        box=rich_box.HEAVY,
        border_style="red",
        padding=(1, 2),
    ))

    if not sys.stdin.isatty():
        print_info("No interactive terminal. Continuing in degraded mode.")
        return

    while True:
        try:
            choice = input("  Choice (R/I/E): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print_warning("Continuing in degraded mode.")
            return
        if choice == "r":
            for f in list(DB_PATH.parent.glob("cognithor*")):
                p = Path(f)
                print_info(f"Removing {p}...")
                p.unlink()
            print_success("Corrupted files removed. Restart to recreate them.")
            sys.exit(0)
        elif choice == "i":
            print_warning("Continuing in degraded mode.")
            return
        elif choice == "e":
            print_info("Exiting.")
            sys.exit(0)
        console.print(Text("Invalid choice. Enter R, I, or E.", style="red"))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="Cognithor",
        description="Cognithor Backend - API Server or Interactive CLI",
    )
    parser.add_argument(
        "-i", "--interactive", "--cli",
        action="store_true",
        help="Launch interactive menu-driven CLI",
    )
    parser.add_argument(
        "--no-encrypt",
        action="store_true",
        help="Force plain-text SQLite (no pysqlcipher3 encryption)",
    )
    parser.add_argument(
        "--encrypt",
        action="store_true",
        help="Force encrypted SQLite (requires pysqlcipher3)",
    )

    args = parser.parse_args()

    if args.interactive:
        from cli_service.interactive import interactive_main
        start_server = interactive_main()
        if not start_server:
            return

    if args.interactive and start_server:
        use_encryption = detect_db_encryption()
        from api_service.main import create_app
        app = create_app(use_encryption=use_encryption)
        from api_service.database import ApiConfigManager
        config_mgr = ApiConfigManager(use_encryption=use_encryption, key_name="db_key")
        config = config_mgr.get_all_config()
        host = config.get("api_host", "0.0.0.0")
        port = int(config.get("api_port", "4464"))
        print_empty()
        print_status_panel([
            ("Status", "Starting server"),
            ("Host", host),
            ("Port", str(port)),
            ("Database", str(DB_PATH)),
            ("Encryption", "ENCRYPTED" if use_encryption else "plain-text"),
        ])
        print_empty()
        import uvicorn
        uvicorn.run(app, host=host, port=port)
        return

    if args.encrypt and args.no_encrypt:
        print_error("Cannot specify both --encrypt and --no-encrypt.")
        sys.exit(1)

    if args.no_encrypt:
        use_encryption = False
    elif args.encrypt:
        use_encryption = True
    else:
        use_encryption = detect_db_encryption()

    if use_encryption and not PYSQLCIPHER_AVAILABLE:
        print_warning("Encryption requested but pysqlcipher3 not installed.")
        print_warning("Falling back to plain-text SQLite.")
        use_encryption = False

    print_banner(subtitle=f"API Server ({'encrypted' if use_encryption else 'plain-text'} DB)")

    from api_service.database import ApiConfigManager

    config_mgr = ApiConfigManager(use_encryption=use_encryption, key_name="db_key")

    degraded = []
    if config_mgr._svc.is_degraded():
        degraded.append(("ApiConfig", config_mgr._svc.degraded_reason))
    if degraded:
        _recovery_prompt(degraded)

    config = config_mgr.get_all_config()
    host = config.get("api_host", "0.0.0.0")
    port = int(config.get("api_port", "4464"))

    print_empty()
    print_status_panel([
        ("Status", "Starting server"),
        ("Host", host),
        ("Port", str(port)),
        ("Database", str(DB_PATH)),
        ("Encryption", "ENCRYPTED" if use_encryption else "plain-text"),
    ])
    print_empty()

    # Import app to trigger create_app before uvicorn starts
    from api_service.main import app as _app

    import uvicorn
    uvicorn.run(
        "api_service.main:app",
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
