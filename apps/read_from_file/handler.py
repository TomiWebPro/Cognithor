from __future__ import annotations

import os
from typing import Optional

from core.app.app_manager import AppHandler


def execute_read_file(file_path: str) -> dict:
    try:
        size = os.path.getsize(file_path)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {
            "success": True,
            "path": os.path.abspath(file_path),
            "content": content,
            "size": size,
            "size_formatted": _format_size(size),
        }
    except FileNotFoundError as e:
        return {"success": False, "error": f"File not found: {e}", "path": file_path}
    except PermissionError as e:
        return {"success": False, "error": f"Permission denied: {e}", "path": file_path}
    except IsADirectoryError as e:
        return {"success": False, "error": f"Is a directory: {e}", "path": file_path}
    except OSError as e:
        return {"success": False, "error": str(e), "path": file_path}


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    else:
        return f"{size / 1024 / 1024 / 1024:.1f} GB"


def generate_read_file_interface(
    params: dict,
    tab_label: Optional[str] = None,
    result: Optional[dict] = None,
) -> str:
    label = f" ({tab_label})" if tab_label else ""
    lines = [
        f"[read_from_file]{label}",
        "  Status: Open",
        "",
    ]

    if result is None:
        file_path = params.get("filePath", "")
        if file_path:
            result = execute_read_file(file_path)

    if result and result.get("success"):
        content = result["content"]
        lines.append(f"  File: {result['path']}")
        lines.append(f"  Size: {result['size_formatted']} ({result['size']} bytes)")
        lines.append("")
        max_preview = 2000
        if len(content) > max_preview:
            lines.append(content[:max_preview])
            lines.append(f"  ... ({len(content) - max_preview} more characters)")
        else:
            lines.append(content)
    elif result:
        lines.append(f"  Error: {result.get('error', 'Unknown error')}")

    return "\n".join(lines)


class ReadFileHandler(AppHandler):
    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        return generate_read_file_interface(params, tab_label=tab_label)

    def execute(self, params: dict) -> dict:
        file_path = params.get("filePath", "")
        return execute_read_file(file_path)
