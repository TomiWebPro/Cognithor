from __future__ import annotations

from typing import Optional

from apps_service import AppRegistry, AgentAppManager

from core.app.app_manager import AppHandler


class ListAppsHandler(AppHandler):
    def __init__(self, app_registry: AppRegistry, agent_app_mgr: AgentAppManager):
        self._app_registry = app_registry
        self._agent_app_mgr = agent_app_mgr

    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        agent_id = params.get("agent_id", "")
        installed = self._agent_app_mgr.list_enabled_agent_apps(agent_id) if agent_id else []
        if not installed:
            return ""
        label = f" ({tab_label})" if tab_label else ""
        lines = [f"[Available Apps]{label}"]
        lines.append("")
        lines.append("  Use {open_app:\"...\"} to open an app.")
        lines.append("  Batch: [{open_app:\"...\"}, {close_tab:\"...\"}]")
        lines.append("")
        lines.append("  Apps:")
        lines.append("")

        for ia in installed:
            app = self._app_registry.get_app(ia.app_id)
            if app is None:
                continue
            lines.append(f"  {app.app_id}")
            lines.append(f"    {app.name}")
            desc = (app.description or "No description available.").replace("\n", " ")
            lines.append(f"    {desc}")
            lines.append(f'    {{open_app:"{app.app_id}"}}')
            lines.append("")

        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        installed = self._agent_app_mgr.list_enabled_agent_apps(agent_id) if agent_id else []
        return {
            "success": True,
            "type": "system_list_apps",
            "app_count": len(installed),
        }
