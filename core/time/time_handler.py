from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Optional

from core.app.app_manager import AppHandler

if TYPE_CHECKING:
    from core.time.time_service import TimeService
    from core.time.alarm_service import AlarmService


class TimeHandler(AppHandler):
    def __init__(self, time_svc: TimeService, alarm_svc: Optional[AlarmService] = None):
        self._time_svc = time_svc
        self._alarm_svc = alarm_svc

    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        agent_id = params.get("agent_id", "")
        agent_time = self._time_svc.now()
        real_time = datetime.datetime.now(datetime.timezone.utc)
        cfg = self._time_svc.get_config()

        label = f" ({tab_label})" if tab_label else ""
        lines = [
            f"[Time]{label}",
            "  Status: Open",
            "",
            "  Agent Simulated Time operates on its own clock that may run faster",
            "  than real time. Use agent time for planning and thinking. Use real",
            "  (UTC) time for time-sensitive external tasks.",
            "",
            f"  Agent Simulated Time:  {agent_time.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"  Human (UTC) Time:      {real_time.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"  Ratio:                 {cfg.ratio}x",
            f"  Agent Epoch:           {cfg.agent_epoch}",
            f"  Real Epoch:            {cfg.real_epoch}",
            "",
            "  Commands:",
            '    Set alarm:   {"command": "set_alarm", "time": "<ISO datetime>", "message": "..."}',
            '    With type:   {"command": "set_alarm", "time": "...", "time_type": "agent|real", "message": "..."}',
            '    Acknowledge: {"command": "acknowledge_alarm", "alarm_id": "..."}',
            '    Wait:        {"command": "wait", "duration": <seconds>, "time_type": "agent|real"}',
            '    Wait until:  {"command": "wait_until", "time": "<ISO datetime>", "time_type": "agent|real"}',
        ]

        if self._alarm_svc and agent_id:
            pending = self._alarm_svc.get_pending_alarms(agent_id)
            if pending:
                lines.append("")
                lines.append("  Pending Alarms:")
                for a in pending:
                    msg = a.get("message", "") or "(no message)"
                    lines.append(f"    - {a['alarm_time']} | {msg} | id={a['id']}")

        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        return {"success": True, "type": "system_time"}
