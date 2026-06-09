from __future__ import annotations

import os
from typing import Optional

from core.app.app_manager import AppHandler


def execute_write_file(file_path: str, content: str) -> dict:
    try:
        abs_path = os.path.abspath(file_path)
        dir_path = os.path.dirname(abs_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        bytes_written = len(content.encode("utf-8"))
        return {
            "success": True,
            "path": abs_path,
            "bytes_written": bytes_written,
        }
    except PermissionError as e:
        return {"success": False, "error": f"Permission denied: {e}", "path": file_path}
    except IsADirectoryError as e:
        return {"success": False, "error": f"Is a directory: {e}", "path": file_path}
    except OSError as e:
        return {"success": False, "error": str(e), "path": file_path}


def generate_write_file_interface(
    params: dict,
    tab_label: Optional[str] = None,
    result: Optional[dict] = None,
) -> str:
    label = f" ({tab_label})" if tab_label else ""
    lines = [
        f"[write_to_file]{label}",
        "  Status: Open",
        "",
    ]

    if result is None:
        file_path = params.get("filePath", "")
        content = params.get("content", "")
        if file_path:
            result = execute_write_file(file_path, content)

    if result and result.get("success"):
        lines.append(f"  Written to: {result['path']}")
        lines.append(f"  Bytes written: {result['bytes_written']}")
    elif result:
        lines.append(f"  Error: {result.get('error', 'Unknown error')}")

    return "\n".join(lines)


class WriteFileHandler(AppHandler):
    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        return generate_write_file_interface(params, tab_label=tab_label)

    def execute(self, params: dict) -> dict:
        file_path = params.get("filePath", "")
        content = params.get("content", "")
        return execute_write_file(file_path, content)

    def get_action_summary(self, params: dict, result: dict) -> Optional[str]:
        if result.get("success"):
            return f"Wrote {result['bytes_written']} bytes to {result['path']}"
        return result.get("past_action_summary")
