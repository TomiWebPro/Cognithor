"""Decrypt Cognithor databases (SQLCipher -> plain-text).

Can be used from CLI, API, or standalone:
    python -m secure_db_service.decrypt
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from api_service.database import ApiConfigManager
    from endpoint.database import Tracker

ProgressCallback = Callable[[int, int], None]


def decrypt_databases(
    config_mgr: ApiConfigManager,
    tracker: Tracker,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Decrypt both main and log databases. Services must be in encrypted mode."""
    config_mgr.toggle_encryption(False, progress_callback)
    tracker.toggle_encryption(False, progress_callback)
    tracker.log.db.toggle_encryption(False, progress_callback)
    config_mgr.set_config("database_encryption_enabled", "false")

    from secure_db_service.key_manager import delete_key
    delete_key(service_name=config_mgr._svc.service_name, key_name=config_mgr._svc.key_name)


def _detect_encryption() -> bool | None:
    from secure_db_service.service import SecureDbService

    DATA_DIR = Path(__file__).resolve().parent.parent / "data"
    db_path = DATA_DIR / "cognithor.db"

    if not db_path.exists():
        return None

    import sqlite3

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
        return False
    except sqlite3.DatabaseError:
        pass

    try:
        svc = SecureDbService(db_path=db_path, use_encryption=True)
        svc.query_one("SELECT 1")
        return True
    except Exception:
        pass

    try:
        svc = SecureDbService(db_path=db_path, use_encryption=False)
        svc.query_one("SELECT 1")
        return False
    except Exception:
        pass

    return None


def main():
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))

    from api_service.database import ApiConfigManager
    from endpoint.database import Tracker
    from log_service import LogDatabase, LogService

    DATA_DIR = PROJECT_ROOT / "data"

    state = _detect_encryption()
    if state is None:
        print("Database file is missing or corrupted. Run init first.")
        sys.exit(1)
    if not state:
        print("Databases are already plain-text.")
        return

    log_db = LogDatabase(db_path=DATA_DIR / "cognithor_logs.db", use_encryption=True)
    log_svc = LogService(database=log_db)
    tracker = Tracker(db_path=DATA_DIR / "cognithor.db", use_encryption=True, log_service=log_svc)
    config_mgr = ApiConfigManager(db_path=DATA_DIR / "cognithor.db", use_encryption=True, key_name="db_key")

    print("Decrypting databases...")
    try:
        decrypt_databases(config_mgr, tracker)
        print("Done. Databases are now plain-text.")
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
