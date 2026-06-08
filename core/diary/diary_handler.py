from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.app.app_manager import AppHandler

if TYPE_CHECKING:
    from core.diary.diary_service import DiaryService
    from core.time import TimeService


class DiaryHandler(AppHandler):
    def __init__(self, diary_svc: DiaryService, time_svc: TimeService):
        self._diary_svc = diary_svc
        self._time_svc = time_svc

    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        agent_id = params.get("agent_id", "")
        today = self._diary_svc._today(time_svc=self._time_svc)
        entry = self._diary_svc.get_entry(agent_id, today)

        label = f" ({tab_label})" if tab_label else ""
        lines = [
            f"[Diary]{label}",
            "  Status: Open",
            "",
        ]

        lines.append(f"  Today: {today}")
        if entry and entry.content:
            lines.append("  Entry:")
            for line in entry.content.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append("  (no entry yet today)")

        lines.append("")
        lines.append('  To write today: {"command": "write_diary", "content": "..."}')
        lines.append('  To list past:   {"command": "list_diary"} or {"command": "list_diary", "date": "YYYY-MM-DD"}')
        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        return {"success": True, "type": "system_diary"}
