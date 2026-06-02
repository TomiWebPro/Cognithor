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
        lines = [f"[Available Apps]{label}"]
        lines.append("")
        lines.append("  Use {open_app:\"...\"} to open an app.")
        lines.append("  Batch: [{open_app:\"...\"}, {close_tab:\"...\"}]")
        lines.append("")
        lines.append("  Apps:")
        lines.append("")

        for app in apps:
            icon = app.icon or "\u25c6"
            lines.append(f"  {app.app_id}")
            lines.append(f"    {icon} {app.name}")
            desc = (app.description or "No description available.").replace("\n", " ")
            lines.append(f"    {desc}")
            lines.append(f'    {{open_app:"{app.app_id}"}}')
            lines.append("")

        lines.append("  (persistent tab)")
        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        apps = self._app_registry.list_available_apps()
        return {
            "success": True,
            "type": "system_list_apps",
            "app_count": len(apps),
        }
