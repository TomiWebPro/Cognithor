from __future__ import annotations

from typing import Optional

from core.app.app_manager import AppHandler


class ContextWindowHandler(AppHandler):
    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        used_tokens = params.get("used_tokens", 0)
        max_tokens = params.get("max_tokens", 4096)
        label = f" ({tab_label})" if tab_label else ""

        if max_tokens > 0:
            pct = (used_tokens / max_tokens) * 100
        else:
            pct = 0

        lines = [
            f"[Context Window]{label}",
            "  Status: Open",
            "",
            f"  Tokens: {used_tokens:,} / {max_tokens:,}",
            f"  Usage: {pct:.1f}% full",
        ]
        return "\n".join(lines)

    def execute(self, params: dict) -> dict:
        return {"success": True, "type": "system_context_window"}
