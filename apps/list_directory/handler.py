from __future__ import annotations

import os
from typing import Optional

from core.app_manager import AppHandler


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    else:
        return f"{size / 1024 / 1024 / 1024:.1f} GB"


def execute_list_directory(path: str) -> dict:
    try:
        entries = []
        total_size = 0
        dir_count = 0
        file_count = 0

        with os.scandir(path) as it:
            for entry in sorted(it, key=lambda e: (not e.is_dir(), e.name.lower())):
                try:
                    is_dir = entry.is_dir()
                    is_file = entry.is_file()
                    size = entry.stat().st_size if is_file else 0
                    total_size += size
                    if is_dir:
                        dir_count += 1
                    elif is_file:
                        file_count += 1

                    entries.append({
                        "name": entry.name,
                        "type": "dir" if is_dir else "file" if is_file else "other",
                        "size": size,
                        "size_formatted": _format_size(size) if is_file else "-",
                    })
                except OSError:
                    entries.append({
                        "name": entry.name,
                        "type": "unknown",
                        "size": 0,
                        "size_formatted": "?",
                    })

        return {
            "success": True,
            "path": os.path.abspath(path),
            "entries": entries,
            "entry_count": len(entries),
            "dir_count": dir_count,
            "file_count": file_count,
            "total_size": total_size,
            "total_size_formatted": _format_size(total_size),
        }
    except PermissionError as e:
        return {"success": False, "error": f"Permission denied: {e}", "path": path}
    except FileNotFoundError as e:
        return {"success": False, "error": f"Path not found: {e}", "path": path}
    except NotADirectoryError as e:
        return {"success": False, "error": f"Not a directory: {e}", "path": path}
    except OSError as e:
        return {"success": False, "error": str(e), "path": path}


def generate_list_directory_interface(
    params: dict,
    tab_label: Optional[str] = None,
    result: Optional[dict] = None,
) -> str:
    label = f" ({tab_label})" if tab_label else ""
    lines = [
        f"[list_directory]{label}",
        "  Status: Open",
        "",
    ]

    if result is None:
        path = params.get("path", "")
        result = execute_list_directory(path) if path else None

    if result and result.get("success"):
        lines.append(f"  Path: {result['path']}")
        lines.append(f"  Entries: {result['entry_count']} ({result['dir_count']} dirs, {result['file_count']} files)")
        lines.append(f"  Total size: {result['total_size_formatted']}")
        lines.append("")

        for entry in result["entries"][:50]:
            ic = "+" if entry["type"] == "dir" else " " if entry["type"] == "file" else "?"
            name = entry["name"]
            size_str = entry["size_formatted"]
            lines.append(f"  [{ic}] {name:<30} {size_str:>10}")

        if result["entry_count"] > 50:
            lines.append(f"  ... and {result['entry_count'] - 50} more entries")
    elif result:
        lines.append(f"  Error: {result.get('error', 'Unknown error')}")
    else:
        lines.append("  No directory loaded yet.")
        lines.append("")

    lines.append("")
    lines.append("  Commands:")
    lines.append('    {"command": "list", "path": "<dir>"}')
    lines.append("      List contents of a directory.")

    return "\n".join(lines)


class ListDirectoryHandler(AppHandler):
    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        return generate_list_directory_interface(params, tab_label=tab_label)

    def execute(self, params: dict) -> dict:
        path = params.get("path", "")
        return execute_list_directory(path)
