from __future__ import annotations

from typing import Optional

from apps_service import AppRegistry

from core.app_manager import AppHandler


class ListAppsHandler(AppHandler):
    def __init__(self, app_registry: AppRegistry):
        self._app_registry = app_registry

    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        apps = self._app_registry.list_available_apps()
        label = f" ({tab_label})" if tab_label else ""
        lines = [f"--- Available Apps{label} ---------------------------"]
        lines.append("")
        lines.append("  You have the following apps available. Open an app tab")
        lines.append("  to use its functionality in your context window.")
        lines.append("")

        for app in apps:
            icon = app.icon or "◆"
            lines.append(f"  Tool: {app.app_id}")
            lines.append(f"    Name: {icon} {app.name}")
            desc = (app.description or "No description available.").replace("\n", " ")
            lines.append(f"    Description: {desc}")
            lines.append(f"    Usage: Call open_app tool with app_id=\"{app.app_id}\"")
            lines.append("")

        lines.append("  This tab is persistent and cannot be closed.")
        lines.append("-------------------------------------------------")
        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        apps = self._app_registry.list_available_apps()
        return {
            "success": True,
            "type": "system_list_apps",
            "app_count": len(apps),
        }
