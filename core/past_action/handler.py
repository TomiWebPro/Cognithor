from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from core.app.app_manager import AppHandler

if TYPE_CHECKING:
    from core.past_action.past_actions import PastActionsService

logger = logging.getLogger(__name__)


class PastActionsHandler(AppHandler):
    def __init__(self, past_actions_svc: PastActionsService):
        self._past_actions_svc = past_actions_svc

    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        agent_id = params.get("agent_id", "")
        max_count = params.get("max_past_actions", 15)
        interface = self._past_actions_svc.generate_tab_interface(agent_id, max_count)
        if interface is None:
            label = f" ({tab_label})" if tab_label else ""
            return f"[Past Actions]{label}\n  Status: Open\n  (no recent actions)"
        return interface

    def execute(self, params: dict) -> dict:
        return {"success": True, "type": "system_past_actions"}
