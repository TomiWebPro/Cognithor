from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "cognithor.db"

PYSQLCIPHER_AVAILABLE = False
try:
    from pysqlcipher3 import dbapi2 as _pysqlcipher
    PYSQLCIPHER_AVAILABLE = True
except ImportError:
    pass


def detect_db_encryption() -> bool:
    """Try to auto-detect if DB uses encryption. Returns True if encrypted."""
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

    try:
        from secure_db_service import SecureDbService
        svc = SecureDbService(db_path=DB_PATH, use_encryption=False)
        svc.query_one("SELECT 1")
        return False
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  DATABASE CANNOT BE OPENED")
    print("=" * 60)
    print(f"\n  File: {DB_PATH}")
    print("\n  Cannot open as plain OR encrypted database.")
    print("\n  Cleaning stale DB files and retrying...")

    for f in list(DB_PATH.parent.glob("cognithor*")):
        f.unlink()

    if not DB_PATH.exists():
        return PYSQLCIPHER_AVAILABLE

    print("  Use the interactive CLI (-i flag) to re-initialize.\n")
    sys.exit(1)


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
