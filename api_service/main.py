from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

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
    """Read database_encryption_enabled from api_config table, if accessible."""
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
    """Detect if DB uses encryption. Checks persisted config first, then probes."""
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

    print("\n" + "=" * 60)
    print("  DATABASE CANNOT BE OPENED")
    print("=" * 60)
    print(f"\n  File: {DB_PATH}")
    print("\n  Cannot open as plain OR encrypted database.")
    print("  Server will start in degraded mode.\n")

    return PYSQLCIPHER_AVAILABLE


def create_app(use_encryption: bool = False):
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from endpoint import EndpointManager

    from api_service.database import ApiConfigManager
    from api_service.middleware import EncryptionMiddleware
    from api_service.routers import (
        auth_router,
        base,
        onboarding_router,
        providers_router,
        security_router,
        settings_router,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config_mgr = ApiConfigManager(use_encryption=use_encryption, key_name="db_key")
        app.state.config_mgr = config_mgr
        app.state.endpoint_mgr = EndpointManager(svc=config_mgr._svc)
        app.state.encryption_in_progress = False

        degraded = []
        if config_mgr._svc.is_degraded():
            degraded.append(("ApiConfig", config_mgr._svc.degraded_reason))
        if app.state.endpoint_mgr.tracker._svc.is_degraded():
            degraded.append(("Tracker", app.state.endpoint_mgr.tracker._svc.degraded_reason))
        if degraded:
            _recovery_prompt(degraded)

        yield

    app = FastAPI(
        title="Cognithor API",
        description="REST API for the Cognithor autonomous agent system",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(base.router)
    app.include_router(auth_router.router)
    app.include_router(onboarding_router.router)
    app.include_router(security_router.router)
    app.include_router(settings_router.router)
    app.include_router(providers_router.router)

    app.add_middleware(EncryptionMiddleware)

    return app


app = None

if __name__ != "__main__":
    try:
        use_enc = detect_db_encryption()
        app = create_app(use_encryption=use_enc)
    except SystemExit:
        app = create_app(use_encryption=False)


def _recovery_prompt(degraded_services: list[tuple[str, str]]) -> None:
    """Ask user how to handle corrupted databases."""
    print("\n" + "=" * 60)
    print("  DATABASE DEGRADED — Recovery Required")
    print("=" * 60)
    for name, reason in degraded_services:
        print(f"\n  [{name}]")
        print(f"  {reason}")
    print()
    print("  Recovery options:")
    print("    [R] Remove corrupted file(s) and recreate fresh databases")
    print("    [I] Ignore and continue in degraded mode (DB features disabled)")
    print("    [E] Exit")
    print()
    if not sys.stdin.isatty():
        print("  No interactive terminal detected. Continuing in degraded mode.")
        return
    while True:
        try:
            choice = input("  Choice (R/I/E): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Continuing in degraded mode.")
            return
        if choice == "r":
            for f in list(DB_PATH.parent.glob("cognithor*")):
                p = Path(f)
                print(f"  Removing {p}...")
                p.unlink()
            print("  Corrupted files removed. Restart the server to recreate them.")
            sys.exit(0)
        elif choice == "i":
            print("  Continuing in degraded mode.")
            return
        elif choice == "e":
            print("  Exiting.")
            sys.exit(0)
        print("  Invalid choice. Please enter R, I, or E.")


def main():
    global app

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
        from api_service.cli_launcher import interactive_main
        interactive_main()
        return

    if args.encrypt and args.no_encrypt:
        print("Error: Cannot specify both --encrypt and --no-encrypt")
        sys.exit(1)

    if args.no_encrypt:
        use_encryption = False
    elif args.encrypt:
        use_encryption = True
    else:
        use_encryption = detect_db_encryption()

    if use_encryption and not PYSQLCIPHER_AVAILABLE:
        print("WARNING: Encryption requested but pysqlcipher3/sqlcipher3 not installed.")
        print("Falling back to plain-text SQLite.")
        use_encryption = False

    print(f"Cognithor API Server ({'encrypted' if use_encryption else 'plain-text'} DB)")
    if DB_PATH.exists():
        print(f"  Database: {DB_PATH}")
    else:
        print(f"  Database: will be created at {DB_PATH}")

    import uvicorn
    from api_service.database import ApiConfigManager

    config_mgr = ApiConfigManager(use_encryption=use_encryption, key_name="db_key")

    degraded = []
    if config_mgr._svc.is_degraded():
        degraded.append(("ApiConfig", config_mgr._svc.degraded_reason))
    if degraded:
        _recovery_prompt(degraded)

    config = config_mgr.get_all_config()
    host = config.get("api_host", "0.0.0.0")
    port = int(config.get("api_port", "8000"))

    if app is None:
        app = create_app(use_encryption=use_encryption)

    print(f"  Listening on: http://{host}:{port}")
    print()

    uvicorn.run(
        "api_service.main:app",
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
