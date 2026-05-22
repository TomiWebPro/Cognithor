from __future__ import annotations
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

from .key_manager import resolve_key


logger = logging.getLogger(__name__)


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

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_driver(self):
        if not self.use_encryption:
            return sqlite3
        if self._cipher_module is not None:
            return self._cipher_module
        try:
            from pysqlcipher3 import dbapi2 as cipher
            self._cipher_module = cipher
            return cipher
        except ImportError:
            try:
                from sqlcipher3 import dbapi2 as cipher
                self._cipher_module = cipher
                return cipher
            except ImportError:
                logger.warning(
                    "Encryption requested but neither pysqlcipher3 nor sqlcipher3 is installed. "
                    "Falling back to plain sqlite3."
                )
                self.use_encryption = False
                return sqlite3

    def _get_encryption_key(self) -> Optional[str]:
        return resolve_key(
            use_encryption=self.use_encryption,
            service_name=self.service_name,
            key_name=self.key_name,
            env_var=self.key_env_var,
        )

    def connect(self) -> sqlite3.Connection:
        driver = self._get_driver()
        encryption_key = self._get_encryption_key()

        for attempt in range(self.retry_attempts):
            try:
                conn = driver.connect(str(self.db_path))

                if encryption_key:
                    conn.execute(f"PRAGMA key = '{encryption_key}'")

                if self.wal_mode:
                    conn.execute("PRAGMA journal_mode=WAL")

                conn.execute("PRAGMA foreign_keys=ON")
                conn.row_factory = sqlite3.Row

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
