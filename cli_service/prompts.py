"""Interactive user prompts — styled input, confirm, choose, secret.

Inspired by opencode's clack prompts for arrow-key navigation.
choose() supports interactive arrow-key selection with styled highlights.
Falls back to numeric input when terminal doesn't support raw mode.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional, TypeVar

from rich.text import Text

from cli_service.display import console, print_error, print_warning, print_hint

T = TypeVar("T")


# ── ANSI helpers for interactive menu ──────────────────────────────

_STYLE_RESET = "\033[0m"
_STYLE_BOLD = "\033[1m"
_STYLE_CYAN = "\033[96m"
_STYLE_DIM = "\033[90m"
_STYLE_BOLD_CYAN = "\033[1;96m"
_STYLE_GREEN = "\033[92m"
_STYLE_RED = "\033[91m"

_CURSOR_UP = "\033[A"
_CLEAR_LINE = "\033[K"
_CURSOR_HIDE = "\033[?25l"
_CURSOR_SHOW = "\033[?25h"


def _cursor_up(n: int = 1) -> str:
    return f"\033[{n}A" if n > 1 else _CURSOR_UP


def _clear_menu(num_lines: int) -> None:
    for _ in range(num_lines):
        sys.stdout.write(_CURSOR_UP + _CLEAR_LINE)
    sys.stdout.flush()


def _has_rich_terminal() -> bool:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    try:
        import termios, tty  # noqa: F401
        return True
    except ImportError:
        return False


# ── Interactive arrow-key selection ────────────────────────────────


def choose(
    options: list[str],
    *,
    title: str = "",
    default: int = 0,
    hint: str = "",
) -> int:
    if not _has_rich_terminal():
        return _choose_numeric(options, title, default, hint)

    import os
    import termios
    import tty

    selected = default
    num_lines = 0

    def _build_lines(sel: int) -> list[str]:
        lines: list[str] = []
        if title:
            lines.append(f"  {_STYLE_BOLD}{title}{_STYLE_RESET}")
        for i, opt in enumerate(options):
            if i == sel:
                lines.append(
                    f"    {_STYLE_BOLD_CYAN}●{_STYLE_RESET} "
                    f"{_STYLE_BOLD_CYAN}{opt}{_STYLE_RESET}  "
                    f"{_STYLE_DIM}←{_STYLE_RESET}"
                )
            else:
                lines.append(f"    ○ {opt}")
        if hint:
            lines.append(f"  {_STYLE_DIM}{hint}{_STYLE_RESET}")
        lines.append(
            f"  {_STYLE_DIM}↑↓ navigate  ·  Enter select  ·  Ctrl+C cancel{_STYLE_RESET}"
        )
        return lines

    def _render(sel: int) -> int:
        nonlocal num_lines
        lines = _build_lines(sel)
        if num_lines > 0:
            _clear_menu(num_lines)
        sys.stdout.write(_CURSOR_HIDE)
        for line in lines:
            sys.stdout.write(line + "\r\n")
        sys.stdout.flush()
        num_lines = len(lines)
        return num_lines

    def _read_byte(fd: int, timeout: float = 0.1) -> str:
        import select
        readable, _, _ = select.select([fd], [], [], timeout)
        if readable:
            return os.read(fd, 1).decode()
        return ""

    _render(selected)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            b = os.read(fd, 1)
            if not b:
                continue
            ch = b.decode()
            if ch == "\x1b":
                more1 = _read_byte(fd)
                if more1 == "[":
                    more2 = _read_byte(fd)
                    if more2 == "A":
                        selected = (selected - 1) % len(options)
                        _render(selected)
                    elif more2 == "B":
                        selected = (selected + 1) % len(options)
                        _render(selected)
            elif ch in ("\r", "\n"):
                break
            elif ch == "\x03":
                raise KeyboardInterrupt
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write(_CURSOR_SHOW)
        sys.stdout.flush()

    _clear_menu(num_lines)
    return selected


def _choose_numeric(
    options: list[str],
    title: str = "",
    default: int = 0,
    hint: str = "",
) -> int:
    hint_display = f"\n    {hint}" if hint else ""
    console.print()
    if title:
        console.print(Text(f"  {title}", style="bold"))

    for i, opt in enumerate(options):
        marker = Text(" *", style="bold yellow") if i == default else Text()
        console.print(
            Text.assemble(
                ("  ", ""),
                (f"{i + 1}.", "cyan"),
                (f" {opt}", ""),
                marker,
            )
        )

    console.print()
    if hint_display:
        console.print(Text(hint_display, style="dim italic"))

    while True:
        try:
            raw = input("  > ").strip()
            if not raw and default >= 0:
                return default
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
            console.print(Text(f"  Enter a number 1-{len(options)}", style="red"))
        except ValueError:
            console.print(Text(f"  Enter a number 1-{len(options)}", style="red"))
        except (EOFError, KeyboardInterrupt):
            console.print()
            print_warning("Cancelled")
            raise


# ── Other prompts ──────────────────────────────────────────────────


def ask(
    message: str,
    *,
    default: Optional[str] = None,
    validate: Optional[Callable[[str], Optional[str]]] = None,
    hint: str = "",
) -> str:
    default_display = f" [{default}]" if default else ""
    hint_display = f"\n    {hint}" if hint else ""

    while True:
        try:
            prompt_text = Text.assemble(
                ("  ? ", "bold cyan"),
                (message, ""),
                (default_display, "dim"),
            )
            console.print(prompt_text, end="")
            if hint_display:
                console.print(Text(hint_display, style="dim italic"), end="")
            console.print("")

            raw = input("  > ").strip()
            if not raw and default is not None:
                return default
            if not raw:
                print_error("Value cannot be empty")
                continue
            if validate:
                error = validate(raw)
                if error:
                    print_error(error)
                    continue
            return raw
        except (EOFError, KeyboardInterrupt):
            console.print()
            print_warning("Cancelled")
            raise


def ask_secret(message: str, *, hint: str = "") -> str:
    hint_display = f"\n    {hint}" if hint else ""
    try:
        prompt_text = Text.assemble(
            ("  ? ", "bold cyan"),
            (message, ""),
        )
        console.print(prompt_text, end="")
        if hint_display:
            console.print(Text(hint_display, style="dim italic"), end="")
        console.print("")

        import getpass

        val = getpass.getpass("  > ")
        return val.strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        print_warning("Cancelled")
        raise


def confirm(message: str, *, default: bool = True, hint: str = "") -> bool:
    default_str = "Y/n" if default else "y/N"
    hint_display = f"\n    {hint}" if hint else ""
    try:
        prompt_text = Text.assemble(
            ("  ? ", "bold cyan"),
            (message, ""),
            (f" [{default_str}]", "dim"),
        )
        console.print(prompt_text, end="")
        if hint_display:
            console.print(Text(hint_display, style="dim italic"), end="")
        console.print("")

        raw = input("  > ").strip().lower()
        if not raw:
            return default
        return raw in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        console.print()
        print_warning("Cancelled")
        raise


def pause(message: str = "Press Enter to continue") -> None:
    try:
        console.print(Text(f"  {message}", style="dim"))
        input("  ")
    except (EOFError, KeyboardInterrupt):
        console.print()
        pass
