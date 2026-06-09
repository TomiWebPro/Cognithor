from __future__ import annotations

import logging
import threading
import time as _time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from secure_db_service import SecureDbService
    from core.time.time_service import TimeService
    from agents_service import AgentManager

logger = logging.getLogger(__name__)


class AlarmScheduler:
    """Background daemon thread that monitors alarms at accurate times.

    Periodically checks all non-triggered alarms against the current
    agent-simulated time. When an alarm fires:
      - Marks it triggered in the DB
      - If the agent status is 'idle', sets it to 'active' (wakes it)
      - Logs the event

    The AgentRunner picks up triggered alarms on its next run() call
    via AlarmService.get_triggered_alarms().
    """

    def __init__(
        self,
        svc: SecureDbService,
        time_svc: TimeService,
        agent_mgr: Optional = None,
        interval: float = 1.0,
    ):
        self._svc = svc
        self._time_svc = time_svc
        self._agent_mgr = agent_mgr
        self._interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            logger.warning("AlarmScheduler already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="alarm-scheduler")
        self._thread.start()
        logger.info("AlarmScheduler started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        self._running = False
        logger.info("AlarmScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _run(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                logger.exception("AlarmScheduler tick error")
            _time.sleep(self._interval)

    def _tick(self) -> None:
        now = self._time_svc.now().isoformat()

        rows = self._svc.query(
            """SELECT * FROM agent_alarms
             WHERE triggered = 0 AND alarm_time <= ?
             ORDER BY alarm_time ASC""",
            (now,),
        )

        for r in rows:
            alarm_id = r["id"]
            agent_id = r["agent_id"]
            message = r["message"] or "(no message)"

            cursor = self._svc.execute(
                "UPDATE agent_alarms SET triggered = 1 WHERE id = ? AND triggered = 0",
                (alarm_id,),
            )
            if cursor.rowcount == 0:
                continue

            logger.info(
                "Alarm %s fired for agent %s: %s",
                alarm_id, agent_id, message,
            )

            if self._agent_mgr is not None:
                agent = self._agent_mgr.get_agent(agent_id)
                if agent is not None and getattr(agent, "status", "active") == "idle":
                    self._agent_mgr.update_agent(agent_id, status="active")
                    logger.info(
                        "Woke agent %s from idle due to alarm %s",
                        agent_id, alarm_id,
                    )
