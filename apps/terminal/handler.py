from __future__ import annotations

import subprocess
import shlex
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
    result: Optional[dict] = None,
) -> str:
    label = f" ({tab_label})" if tab_label else ""
    lines = [
        f"[terminal]{label}",
        "  Status: Open",
        "",
    ]

    if result is None:
        cmd = params.get("command", "")
        if cmd:
            timeout = params.get("timeout", 30000)
            result = execute_command(cmd, timeout_ms=int(timeout))

    if result and result.get("success"):
        lines.append(f"  $ {result['command']}")
        lines.append(f"  Exit code: {result['exit_code']}")
        if result.get("stdout"):
            lines.append("")
            lines.append("  stdout:")
            for line in result["stdout"].splitlines():
                lines.append(f"    {line}")
        if result.get("stderr"):
            lines.append("")
            lines.append("  stderr:")
            for line in result["stderr"].splitlines():
                lines.append(f"    {line}")
    elif result:
        lines.append(f"  Command: {result.get('command', '')}")
        lines.append(f"  Error: {result.get('error', 'Unknown error')}")
        if result.get("stdout"):
            lines.append("  stdout:")
            for line in result["stdout"].splitlines():
                lines.append(f"    {line}")
        if result.get("stderr"):
            lines.append("  stderr:")
            for line in result["stderr"].splitlines():
                lines.append(f"    {line}")

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
        return execute_command(command, timeout_ms=int(timeout))

    def get_action_summary(self, params: dict, result: dict) -> Optional[str]:
        if result.get("success"):
            cmd = params.get("command", "")
            code = result.get("exit_code")
            return f"Executed `{cmd}` (exit {code})"
        return result.get("past_action_summary")
