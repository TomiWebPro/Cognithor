from __future__ import annotations

import subprocess
from typing import Optional

from core.app.app_manager import AppHandler


def execute_command(command: str, timeout_ms: int = 30000) -> dict:
    try:
        timeout_seconds = timeout_ms / 1000.0
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "success": True,
            "command": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "command": command,
            "error": f"Command timed out after {timeout_ms}ms",
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
        }
    except FileNotFoundError as e:
        return {
            "success": False,
            "command": command,
            "error": f"Shell not found: {e}",
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
        }
    except OSError as e:
        return {
            "success": False,
            "command": command,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
        }


def generate_terminal_interface(
    params: dict,
    tab_label: Optional[str] = None,
) -> str:
    label = f" ({tab_label})" if tab_label else ""
    lines = [
        f"[terminal]{label}",
        "  Status: Open",
        "",
    ]

    command = params.get("_last_command")
    stdout = params.get("_last_stdout")
    stderr = params.get("_last_stderr")
    exit_code = params.get("_last_exit_code")

    if command is not None:
        lines.append(f"  $ {command}")
        if exit_code is not None:
            lines.append(f"  Exit code: {exit_code}")
        if stdout:
            lines.append("")
            lines.append("  stdout:")
            for line in stdout.splitlines():
                lines.append(f"    {line}")
        if stderr:
            lines.append("")
            lines.append("  stderr:")
            for line in stderr.splitlines():
                lines.append(f"    {line}")
    else:
        lines.append("  No command executed yet. Run a command to see output here.")

    return "\n".join(lines)


class TerminalHandler(AppHandler):
    def generate_interface(
        self,
        params: dict,
        tab_label: Optional[str] = None,
    ) -> str:
        return generate_terminal_interface(params, tab_label=tab_label)

    def execute(self, params: dict) -> dict:
        command = params.get("command", "")
        timeout = params.get("timeout", 30000)
        result = execute_command(command, timeout_ms=int(timeout))

        tab_label = params.get("_tab_label")
        update_spec = {
            "app_id": "terminal",
            "params": {
                    "_last_command": result.get("command", command),
                    "_last_stdout": result.get("stdout", ""),
                    "_last_stderr": result.get("stderr", ""),
                    "_last_exit_code": result.get("exit_code"),
                },
            }
        if tab_label:
            update_spec["tab_label"] = tab_label
        result["_update_tabs"] = [update_spec]
        return result

    def get_action_summary(self, params: dict, result: dict) -> Optional[str]:
        if result.get("success"):
            cmd = params.get("command", "")
            code = result.get("exit_code")
            return f"Executed `{cmd}` (exit {code})"
        return result.get("past_action_summary")
