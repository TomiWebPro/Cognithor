from __future__ import annotations
import logging
import os

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

from .key_manager import FALLBACK_KEY, get_or_create_key, resolve_key


def _sql_escape(val: str) -> str:
    return val.replace("'", "''")


logger = logging.getLogger(__name__)


class DegradedError(RuntimeError):
    """Raised when database is corrupted and service enters degraded mode."""


class _DegradedCursor:
    lastrowid = 0
    rowcount = -1

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def __iter__(self):
        return iter([])


class _DegradedConnection:
    row_factory = None

    def execute(self, sql, params=None):
        return _DegradedCursor()

    def executescript(self, sql):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def iterdump(self):
        return iter([])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class SecureDbService:
    def __init__(
        self,
        db_path: str | Path,
        use_encryption: bool = False,
        wal_mode: bool = True,
        retry_attempts: int = 5,
        retry_delay_seconds: float = 0.1,
        service_name: str = "Cognithor",
        key_name: str = "db_key",
        key_env_var: Optional[str] = None,
    ):
        self.db_path = Path(db_path)
        self.use_encryption = use_encryption
        self.wal_mode = wal_mode
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.service_name = service_name
        self.key_name = key_name
        self.key_env_var = key_env_var
        self._cipher_module = None
        self._cipher_available = False
        self._cached_key: str | None = None
        self._generation = 0
        self._lock = threading.Lock()

        self.degraded = False
        self.degraded_reason = ""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def is_degraded(self) -> bool:
        return self.degraded

    def recover(self) -> None:
        self.degraded = False
        self.degraded_reason = ""

    def _get_driver(self):
        if not self.use_encryption:
            return sqlite3
        if self._cipher_module is not None:
            return self._cipher_module
        try:
            from pysqlcipher3 import dbapi2 as cipher
            self._cipher_module = cipher
            self._cipher_available = True
            return cipher
        except ImportError:
            try:
                from sqlcipher3 import dbapi2 as cipher
                self._cipher_module = cipher
                self._cipher_available = True
                return cipher
            except ImportError:
                logger.warning(
                    "Encryption requested but neither pysqlcipher3 nor sqlcipher3 is installed. "
                    "Falling back to plain sqlite3."
                )
                self.use_encryption = False
                return sqlite3

    def _get_encryption_key(self) -> Optional[str]:
        if not self.use_encryption:
            return None
        resolved = resolve_key(
            use_encryption=True,
            service_name=self.service_name,
            key_name=self.key_name,
            env_var=self.key_env_var,
        )
        if resolved == FALLBACK_KEY and self._cached_key:
            return self._cached_key
        return resolved

    def connect(self) -> sqlite3.Connection:
        if self.degraded:
            return _DegradedConnection()
        driver = self._get_driver()
        encryption_key = self._get_encryption_key()

        for attempt in range(self.retry_attempts):
            try:
                conn = driver.connect(str(self.db_path))

                if encryption_key:
                    conn.execute(f"PRAGMA key = '{_sql_escape(encryption_key)}'")

                if self.wal_mode:
                    conn.execute("PRAGMA journal_mode=WAL")

                conn.execute("PRAGMA foreign_keys=ON")
                conn.row_factory = driver.Row

                return conn

            except driver.OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < self.retry_attempts - 1:
                    logger.warning(
                        "Database locked, retrying in %ss (attempt %d/%d)",
                        self.retry_delay_seconds,
                        attempt + 1,
                        self.retry_attempts,
                    )
                    time.sleep(self.retry_delay_seconds)
                else:
                    logger.error("Failed to connect: %s", e)
                    raise

            except Exception as e:
                err_str = str(e).lower()
                if "file is not a database" in err_str or "not a database" in err_str:
                    reason = (
                        f"Database file {self.db_path} is corrupted or "
                        f"encrypted with wrong key: {e}"
                    )
                    logger.critical(reason)
                    raise
                logger.error("Unexpected error connecting to database: %s", e)
                raise

        raise RuntimeError(f"Could not connect to database after {self.retry_attempts} attempts")

    @contextmanager
    def connection(self) -> sqlite3.Connection:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(
        self,
        sql: str,
        params: Optional[list | tuple | dict] = None,
    ) -> sqlite3.Cursor:
        with self.connection() as conn:
            return conn.execute(sql, params or [])

    def execute_many(
        self,
        sql: str,
        params_list: list[list | tuple | dict],
    ) -> None:
        with self.connection() as conn:
            conn.executemany(sql, params_list)

    def execute_script(self, sql: str) -> None:
        with self.connection() as conn:
            conn.executescript(sql)

    def query(
        self,
        sql: str,
        params: Optional[list | tuple | dict] = None,
    ) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(sql, params or []).fetchall()

    def query_one(
        self,
        sql: str,
        params: Optional[list | tuple | dict] = None,
    ) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            row = conn.execute(sql, params or []).fetchone()
            return row

    def insert(
        self,
        sql: str,
        params: Optional[list | tuple | dict] = None,
    ) -> int:
        with self.connection() as conn:
            cur = conn.execute(sql, params or [])
            return cur.lastrowid

    def table_info(self, table_name: str) -> list[sqlite3.Row]:
        return self.query(f"PRAGMA table_info({table_name})")

    def table_exists(self, table_name: str) -> bool:
        row = self.query_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return row is not None

    def _transfer(self, src_conn, dst_path, dst_key):
        driver = self._get_driver()
        dst_conn = driver.connect(str(dst_path))
        try:
            if dst_key:
                dst_conn.execute(f"PRAGMA key = '{_sql_escape(dst_key)}'")
            dst_conn.execute("PRAGMA journal_mode=DELETE")
            dst_conn.execute("PRAGMA foreign_keys=OFF")

            dst_conn.executescript("".join(src_conn.iterdump()))
            dst_conn.commit()

            dst_conn.execute("PRAGMA foreign_keys=ON")
            dst_conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except Exception:
            dst_conn.close()
            raise
        dst_conn.close()

    def toggle_encryption(self, enable: bool) -> bool:
        with self._lock:
            if enable == self.use_encryption:
                return False

            if self.degraded:
                raise DegradedError(
                    f"Cannot toggle encryption: database is in degraded mode: {self.degraded_reason}"
                )

            generated_key: str | None = None
            if enable:
                generated_key = get_or_create_key(
                    service_name=self.service_name,
                    key_name=self.key_name,
                )

            import time as _time
            temp_path = self.db_path.with_suffix(f".{int(_time.time())}.tmp")
            backup_path = self.db_path.with_suffix(".bak")

            old_use_encryption = self.use_encryption
            old_cipher_module = self._cipher_module

            src_conn = self.connect()
            try:
                self.use_encryption = enable
                self._cipher_module = None

                if enable:
                    dst_key = self._get_encryption_key()
                    if dst_key == FALLBACK_KEY and generated_key is not None:
                        dst_key = generated_key
                else:
                    dst_key = None

                self._cached_key = dst_key
                self._transfer(src_conn, temp_path, dst_key)
            except Exception:
                if temp_path.exists():
                    temp_path.unlink()
                self.use_encryption = old_use_encryption
                self._cipher_module = old_cipher_module
                self._cached_key = None
                src_conn.close()
                raise
            src_conn.close()

            if backup_path.exists():
                backup_path.unlink()
            os.replace(self.db_path, backup_path)
            os.replace(temp_path, self.db_path)

            for suffix in ("-wal", "-shm"):
                stale = self.db_path.with_name(self.db_path.name + suffix)
                if stale.exists():
                    stale.unlink()

            backup_path.unlink(missing_ok=True)
            self._generation += 1

        return True

    def vacuum(self) -> None:
        self.execute("VACUUM")

    def backup(self, target_path: str | Path) -> None:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        src_conn = self.connect()
        try:
            dst_conn = sqlite3.connect(str(target))
            try:
                src_conn.backup(dst_conn)
                dst_conn.commit()
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

    @contextmanager
    def transaction(self) -> sqlite3.Connection:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def run_transaction(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.transaction() as conn:
            return fn(conn)
