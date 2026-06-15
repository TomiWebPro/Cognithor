from __future__ import annotations

import datetime
import logging
import random
import string
from typing import TYPE_CHECKING, Optional

from secure_db_service import SecureDbService

if TYPE_CHECKING:
    from core.time.time_service import TimeService

logger = logging.getLogger(__name__)


def _generate_alarm_id() -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))


class AlarmService:
    def __init__(self, svc: SecureDbService, time_svc: TimeService):
        self._svc = svc
        self._time_svc = time_svc
        self._init_db()

    def _init_db(self) -> None:
        self._svc.execute_script("""
            CREATE TABLE IF NOT EXISTS agent_alarms (
                id            TEXT PRIMARY KEY,
                agent_id      TEXT NOT NULL,
                alarm_time    TEXT NOT NULL,
                time_type     TEXT DEFAULT 'agent',
                message       TEXT DEFAULT '',
                triggered     INTEGER DEFAULT 0,
                created_at    TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_agent_alarms_agent
                ON agent_alarms(agent_id, triggered);
        """)

    def set_alarm(
        self,
        agent_id: str,
        alarm_time: str,
        time_type: str = "agent",
        message: str = "",
    ) -> Optional[str]:
        now = self._time_svc.now()
        alarm_dt = datetime.datetime.fromisoformat(alarm_time)

        if time_type == "real":
            real_now = datetime.datetime.now(datetime.timezone.utc)
            if alarm_dt.tzinfo is None:
                alarm_dt = alarm_dt.replace(tzinfo=datetime.timezone.utc)
            elapsed = (alarm_dt - real_now).total_seconds()
            ratio = self._time_svc.get_ratio()
            agent_offset = elapsed * ratio
            converted = now + datetime.timedelta(seconds=agent_offset)
            alarm_time = converted.isoformat()
        else:
            if alarm_dt.tzinfo is None:
                alarm_dt = alarm_dt.replace(tzinfo=datetime.timezone.utc)
            if alarm_dt <= now:
                logger.warning("Alarm time %s is in the past (agent time %s)", alarm_dt, now)
                return None

        alarm_id = _generate_alarm_id()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._svc.execute(
            """INSERT INTO agent_alarms (id, agent_id, alarm_time, time_type, message, triggered, created_at)
             VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (alarm_id, agent_id, alarm_time, time_type, message, now_str),
        )
        return alarm_id

    def check_alarms(self, agent_id: str) -> list[dict]:
        now = self._time_svc.now().isoformat()
        rows = self._svc.query(
            """SELECT * FROM agent_alarms
             WHERE agent_id = ? AND triggered = 0 AND alarm_time <= ?
             ORDER BY alarm_time ASC""",
            (agent_id, now),
        )
        results = []
        for r in rows:
            self._svc.execute(
                "UPDATE agent_alarms SET triggered = 1 WHERE id = ?",
                (r["id"],),
            )
            results.append({
                "id": r["id"],
                "agent_id": r["agent_id"],
                "alarm_time": r["alarm_time"],
                "time_type": r["time_type"],
                "message": r["message"] or "",
            })
        return results

    def acknowledge_alarm(self, alarm_id: str) -> bool:
        existing = self._svc.query_one(
            "SELECT id FROM agent_alarms WHERE id = ?", (alarm_id,)
        )
        if existing is None:
            return False
        self._svc.execute("DELETE FROM agent_alarms WHERE id = ?", (alarm_id,))
        return True

    def get_triggered_alarms(self, agent_id: str) -> list[dict]:
        rows = self._svc.query(
            """SELECT * FROM agent_alarms
             WHERE agent_id = ? AND triggered = 1
             ORDER BY alarm_time ASC""",
            (agent_id,),
        )
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "alarm_time": r["alarm_time"],
                "time_type": r["time_type"],
                "message": r["message"] or "",
            }
            for r in rows
        ]

    def get_pending_alarms(self, agent_id: str) -> list[dict]:
        rows = self._svc.query(
            """SELECT * FROM agent_alarms
             WHERE agent_id = ? AND triggered = 0
             ORDER BY alarm_time ASC""",
            (agent_id,),
        )
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "alarm_time": r["alarm_time"],
                "time_type": r["time_type"],
                "message": r["message"] or "",
            }
            for r in rows
        ]

    def list_alarms(self, agent_id: str) -> list[dict]:
        rows = self._svc.query(
            "SELECT * FROM agent_alarms WHERE agent_id = ? ORDER BY created_at DESC",
            (agent_id,),
        )
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "alarm_time": r["alarm_time"],
                "time_type": r["time_type"],
                "message": r["message"] or "",
                "triggered": bool(r["triggered"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def batch_list_alarms(self, agent_ids: list[str]) -> dict[str, list[dict]]:
        if not agent_ids:
            return {}
        placeholders = ",".join("?" for _ in agent_ids)
        rows = self._svc.query(
            f"SELECT * FROM agent_alarms WHERE agent_id IN ({placeholders}) ORDER BY created_at DESC",
            agent_ids,
        )
        grouped: dict[str, list[dict]] = {aid: [] for aid in agent_ids}
        for r in rows:
            aid = r["agent_id"]
            if aid in grouped:
                grouped[aid].append({
                    "id": r["id"],
                    "agent_id": r["agent_id"],
                    "alarm_time": r["alarm_time"],
                    "time_type": r["time_type"],
                    "message": r["message"] or "",
                    "triggered": bool(r["triggered"]),
                    "created_at": r["created_at"],
                })
        return grouped

    def cancel_alarm(self, alarm_id: str) -> bool:
        existing = self._svc.query_one(
            "SELECT id FROM agent_alarms WHERE id = ? AND triggered = 0",
            (alarm_id,),
        )
        if existing is None:
            return False
        self._svc.execute("DELETE FROM agent_alarms WHERE id = ?", (alarm_id,))
        return True
