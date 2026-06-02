from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional

from secure_db_service import SecureDbService


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


_DEFAULT_REAL_EPOCH = "1970-01-01T00:00:00+00:00"
_DEFAULT_AGENT_EPOCH = "1970-01-01T00:00:00+00:00"
_DEFAULT_RATIO = 1.0


@dataclass
class TimeConfig:
    real_epoch: str = _DEFAULT_REAL_EPOCH
    agent_epoch: str = _DEFAULT_AGENT_EPOCH
    ratio: float = _DEFAULT_RATIO


class TimeService:
    """Configurable time progression service with epoch mapping.

    Maps a real-world datetime (real_epoch) to an agent datetime
    (agent_epoch) with a configurable ratio.

    Example:
        real_epoch  = 1999-05-21 00:00:00 UTC
        agent_epoch = 2024-06-15 00:00:00 UTC
        ratio       = 3.0  (1 real second = 3 agent seconds)

        Querying now() at 2026-06-02 12:00:00 UTC would return:
          - elapsed real seconds from real_epoch
          - scaled by 3.0 ratio
          - added to agent_epoch

    Default: 1970-01-01 → 1970-01-01, ratio 1:1
    """

    def __init__(self, svc: SecureDbService):
        self._svc = svc
        self._init_db()
        self._load_config()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS time_config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

    def _get_cfg(self, key: str, default: str) -> str:
        row = self._svc.query_one(
            "SELECT value FROM time_config WHERE key = ?", (key,)
        )
        return row["value"] if row else default

    def _set_cfg(self, key: str, value: str) -> None:
        self._svc.execute(
            "INSERT OR REPLACE INTO time_config (key, value) VALUES (?, ?)",
            (key, value),
        )

    def _load_config(self) -> None:
        self._real_epoch = datetime.datetime.fromisoformat(
            self._get_cfg("real_epoch", _DEFAULT_REAL_EPOCH)
        )
        self._agent_epoch = datetime.datetime.fromisoformat(
            self._get_cfg("agent_epoch", _DEFAULT_AGENT_EPOCH)
        )
        self._ratio = float(self._get_cfg("ratio", str(_DEFAULT_RATIO)))

    def get_config(self) -> TimeConfig:
        return TimeConfig(
            real_epoch=self._real_epoch.isoformat(),
            agent_epoch=self._agent_epoch.isoformat(),
            ratio=self._ratio,
        )

    def set_config(
        self,
        real_epoch: Optional[str] = None,
        agent_epoch: Optional[str] = None,
        ratio: Optional[float] = None,
    ) -> TimeConfig:
        if real_epoch is not None:
            self._real_epoch = datetime.datetime.fromisoformat(real_epoch)
            self._set_cfg("real_epoch", self._real_epoch.isoformat())
        if agent_epoch is not None:
            self._agent_epoch = datetime.datetime.fromisoformat(agent_epoch)
            self._set_cfg("agent_epoch", self._agent_epoch.isoformat())
        if ratio is not None:
            if ratio <= 0:
                raise ValueError("Ratio must be positive")
            self._ratio = ratio
            self._set_cfg("ratio", str(ratio))

        return self.get_config()

    def set_ratio(self, ratio: float) -> None:
        self.set_config(ratio=ratio)

    def get_ratio(self) -> float:
        return self._ratio

    def now(self) -> datetime.datetime:
        elapsed = (_utcnow() - self._real_epoch).total_seconds()
        agent_offset = elapsed * self._ratio
        return self._agent_epoch + datetime.timedelta(seconds=agent_offset)

    def now_timestamp(self) -> float:
        return self.now().timestamp()
