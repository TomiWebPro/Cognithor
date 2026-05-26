#!/usr/bin/env python3
"""Cognithor onboarding — initialise all three services.

Usage:
    python onboarding/setup.py init          # create DBs, tables, seed data
    python onboarding/setup.py init --no-encrypt
    python onboarding/setup.py clear         # remove all DB files
    python onboarding/setup.py reset         # clear + init
    python onboarding/setup.py reset --no-encrypt
    python onboarding/setup.py status        # show what exists
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

sys.path.insert(0, str(PROJECT_ROOT))

DB_FILES: list[Path] = [
    DATA_DIR / "cognithor.db",
    DATA_DIR / "cognithor_logs.db",
]


DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin"


def _log(msg: str) -> None:
    print(f"  [{msg}]")


def cmd_init(use_encryption: bool, verbose: bool) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    enc_label = "encrypted" if use_encryption else "plain-text"
    print(f"Initialising all services ({enc_label}) …")

    from secure_db_service import get_or_create_key, has_key, set_key

    svc_key = get_or_create_key()
    if verbose:
        _log(f"SecureDbService key {'already exists' if has_key() else 'created and stored in system keyring'}")

    from log_service import LogDatabase, LogService

    log_db = LogDatabase(use_encryption=use_encryption)
    log_svc = LogService(database=log_db)
    if verbose:
        _log(f"LogService ready → {log_db.db_path} (table: log_entries)")

    from endpoint import Tracker

    tracker = Tracker(use_encryption=use_encryption, log_service=log_svc)
    provider_count = len(tracker.list_providers())
    if verbose:
        _log(f"Endpoint Tracker ready → {tracker.db_path} (tables: providers, usage_log, health_checks)")
        _log(f"Seeded {provider_count} default provider(s)")

    from api_service.database import ApiConfigManager

    config_mgr = ApiConfigManager(use_encryption=use_encryption, key_name="db_key")
    if not config_mgr.user_exists(DEFAULT_ADMIN_USER):
        config_mgr.create_user(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS)
        if verbose:
            _log(f"Created default admin user: {DEFAULT_ADMIN_USER}/{DEFAULT_ADMIN_PASS}")
            _log("  WARNING: change the default password in production!")

    print(f"Done — {len(DB_FILES)} database(s) created in {DATA_DIR}/")


def cmd_clear(force: bool) -> None:
    if not force:
        print("Are you sure? This will delete all Cognithor database files.")
        print("Use --force (or -f) to confirm.")
        return

    removed = 0
    for fp in DB_FILES:
        if fp.exists():
            fp.unlink()
            removed += 1
            _log(f"Deleted {fp}")
        for suffix in ("-wal", "-shm"):
            sidecar = fp.with_suffix(fp.suffix + suffix)
            if sidecar.exists():
                sidecar.unlink()
                _log(f"Deleted {sidecar}")

    if DATA_DIR.exists() and not any(DATA_DIR.iterdir()):
        DATA_DIR.rmdir()
        _log(f"Removed empty {DATA_DIR}/")

    print(f"Done — removed {removed} database file(s)")


def cmd_status() -> None:
    import logging
    logging.getLogger("secure_db_service").setLevel(logging.CRITICAL)
    logging.getLogger("secure_db_service.service").setLevel(logging.CRITICAL)

    print("Cognithor — service status")
    print()

    for fp in DB_FILES:
        exists = fp.exists()
        size = fp.stat().st_size if exists else 0
        status = "present" if exists else "missing"
        label = fp.relative_to(PROJECT_ROOT)
        print(f"  {label}  [{status}]  {size} bytes")

    print()

    if not any(f.exists() for f in DB_FILES):
        print("No databases found — run `python onboarding/setup.py init` to create them.")
        return

    sys.path.insert(0, str(PROJECT_ROOT))

    def _check_log_db(use_encryption: bool) -> int:
        from log_service import LogDatabase
        log_db = LogDatabase(use_encryption=use_encryption)
        row = log_db._svc.query_one("SELECT COUNT(*) AS cnt FROM log_entries")
        return row["cnt"]

    def _check_endpoint_db(use_encryption: bool) -> tuple[int, list]:
        from log_service import LogDatabase, LogService
        from endpoint import Tracker
        log_db = LogDatabase(use_encryption=use_encryption)
        log_svc = LogService(database=log_db)
        tracker = Tracker(use_encryption=use_encryption, log_service=log_svc)
        providers = tracker.list_providers()
        return len(providers), providers

    for try_enc in [False, True]:
        if try_enc and not any(f.exists() for f in DB_FILES):
            break
        print(f"  (trying {'encrypted' if try_enc else 'plain-text'} access …)")
        try:
            cnt = _check_log_db(try_enc)
            print(f"  log_entries table: {cnt} row(s)")
            break
        except Exception as exc:
            if try_enc:
                print(f"  log_entries table: error — {exc}")

    for try_enc in [False, True]:
        if try_enc and not any(f.exists() for f in DB_FILES):
            break
        print(f"  (trying {'encrypted' if try_enc else 'plain-text'} endpoint access …)")
        try:
            n, providers = _check_endpoint_db(try_enc)
            print(f"  providers table: {n} row(s)")
            for p in providers:
                print(f"    · {p.name}  (active={p.is_active}, models={p.models})")
            break
        except Exception as exc:
            if try_enc:
                print(f"  providers table: error — {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cognithor onboarding — initialise or reset all services")
    parser.add_argument(
        "command",
        choices=["init", "clear", "reset", "status"],
        help="init = create DBs & seed data | clear = remove all DB files | reset = clear then init | status = show current state",
    )
    parser.add_argument(
        "--no-encrypt",
        action="store_true",
        help="Use plain-text (non-encrypted) SQLite databases instead of pysqlcipher3",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed initialisation logs",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip confirmation prompts (clear / reset)",
    )

    args = parser.parse_args()

    if args.command == "clear":
        cmd_clear(force=args.force)
    elif args.command == "init":
        cmd_init(use_encryption=not args.no_encrypt, verbose=args.verbose)
    elif args.command == "reset":
        cmd_clear(force=args.force)
        if args.force or not any(f.exists() for f in DB_FILES):
            cmd_init(use_encryption=not args.no_encrypt, verbose=args.verbose)
        else:
            print("Skipping init — use --force to confirm reset.")
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()
