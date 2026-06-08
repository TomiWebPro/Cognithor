"""Terminal rendering — ANSI styles, ASCII logo, rich helpers.

Inspired by opencode's ui.ts: styled output, clean layout, visual guidance.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich import box as rich_box
from rich.style import Style as RichStyle

console = Console()

_COGNITHOR_LETTERS: dict[str, list[str]] = {
    "C": ["██████  ", "██      ", "██      ", "██      ", "██████  "],
    "O": ["██████  ", "██   ██ ", "██   ██ ", "██   ██ ", "██████  "],
    "G": ["██████  ", "██      ", "██  ███ ", "██   ██ ", " █████  "],
    "N": ["██   ██ ", "████ ██ ", "██ ████ ", "██  ████", "██   ██ "],
    "I": ["██████  ", "  ██    ", "  ██    ", "  ██    ", "██████  "],
    "T": ["████████", "  ██    ", "  ██    ", "  ██    ", "  ██    "],
    "H": ["██   ██ ", "██   ██ ", "████████", "██   ██ ", "██   ██ "],
    "R": ["██████  ", "██   ██ ", "█████   ", "██  ██  ", "██   ██ "],
}


def _build_logo() -> str:
    lines: list[str] = []
    for row in range(5):
        parts = [_COGNITHOR_LETTERS[ch][row] for ch in "COGNITHOR"]
        lines.append(" ".join(parts))
    return "\n".join(lines)


COGNITHOR_LOGO = _build_logo()


def print_banner(subtitle: str = "") -> None:
    logo = Text(COGNITHOR_LOGO, style="bold cyan")
    logo_width = max(len(line) for line in COGNITHOR_LOGO.split("\n"))
    term_width = console.width

    if logo_width + 24 <= term_width:
        panel = Panel(
            logo,
            box=rich_box.HEAVY,
            border_style="cyan",
            padding=(1, 4),
            subtitle=subtitle,
            subtitle_align="right",
        )
        console.print(panel)
    elif logo_width + 8 <= term_width:
        panel = Panel(
            logo,
            box=rich_box.HEAVY,
            border_style="cyan",
            padding=(1, 1),
            subtitle=subtitle,
            subtitle_align="right",
        )
        console.print(panel)
    else:
        rule = Text("─" * min(logo_width, term_width - 2), style="dim")
        console.print(rule)
        console.print(logo)
        console.print(rule)
        if subtitle:
            console.print(Text(f"  {subtitle}", style="bold cyan"))


def print_header(title: str, subtitle: str = "") -> None:
    panel = Panel(
        Text(subtitle, style="dim") if subtitle else "",
        title=Text(title, style="bold cyan"),
        box=rich_box.ROUNDED,
        border_style="cyan",
        padding=(0, 2),
    )
    console.print(panel)


def print_section(title: str) -> None:
    console.print()
    console.print(Text(f"  {title}", style="bold"))
    console.print(Text("  " + "─" * (len(title) + 2), style="dim"))


def print_step(current: int, total: int, description: str) -> None:
    console.print(
        f"  [{Text(str(current), style='bold cyan')}/{Text(str(total), style='cyan')}] "
        f"{description}"
    )


def print_success(message: str) -> None:
    console.print("  ", Text("✓", style="bold green"), " ", message)


def print_error(message: str) -> None:
    console.print("  ", Text("✗", style="bold red"), " ", Text(message, style="red"))


def print_warning(message: str) -> None:
    console.print("  ", Text("!", style="bold yellow"), " ", Text(message, style="yellow"))


def print_info(message: str) -> None:
    console.print("  ", Text("→", style="bold blue"), " ", message)


def print_dim(message: str) -> None:
    console.print(f"  {Text(message, style='dim')}")


def print_hint(message: str) -> None:
    console.print(f"    {Text(message, style='dim italic')}")


def print_table(headers: list[str], rows: list[list], title: str = "") -> Table:
    table = Table(
        title=title or None,
        box=rich_box.HEAVY_HEAD,
        border_style="cyan",
        header_style="bold cyan",
        title_style="bold",
        padding=(0, 2),
    )
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*[str(c) for c in row])
    console.print(table)
    return table


def print_credentials_box(data: dict[str, str]) -> None:
    lines = [f"[bold]{k}:[/bold] {v}" for k, v in data.items()]
    panel = Panel(
        "\n".join(lines),
        title="[bold cyan]Credentials[/bold cyan]",
        box=rich_box.DOUBLE,
        border_style="cyan",
        padding=(1, 4),
    )
    console.print(panel)


def print_passkey_box(passkey: str, username: str, password: str) -> None:
    text = Text()
    text.append("Passkey:\n", style="bold")
    text.append(f"{passkey}\n\n", style="green")
    text.append(f"→  Username: {username}\n", style="dim")
    text.append(f"→  Password: {password}", style="dim")
    panel = Panel(
        text,
        title="[bold cyan]Frontend Connection[/bold cyan]",
        box=rich_box.HEAVY,
        border_style="cyan",
        padding=(1, 3),
    )
    console.print(panel)


def print_status_panel(items: list[tuple[str, str]]) -> None:
    text = Text()
    for key, value in items:
        text.append(f"  {key}: ", style="bold")
        text.append(f"{value}\n", style="cyan")
    panel = Panel(
        text,
        title="[bold cyan]System Status[/bold cyan]",
        box=rich_box.ROUNDED,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def spinner(message: str = "Working"):
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn(f"[bold cyan]{message}..."),
        console=console,
        transient=True,
    )


def progress_bar(description: str = "Processing", total: int = 100):
    return Progress(
        TextColumn(f"[bold cyan]{description}[/bold cyan]"),
        BarColumn(complete_style="cyan"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def print_encryption_status_panel(
    encrypted: bool,
    pysqlcipher_available: bool,
) -> None:
    status_style = "bold green" if encrypted else ("bold yellow" if pysqlcipher_available else "bold red")
    status_text = "ENCRYPTED" if encrypted else "plain-text"
    status_line = Text.assemble(
        ("  Status:  ", ""),
        (status_text, status_style),
        ("  [!]" if not encrypted and not pysqlcipher_available else "", "bold red"),
    )
    driver_line = Text.assemble(
        ("  Driver:  ", ""),
        ("pysqlcipher3 ", ""),
        ("✓ installed" if pysqlcipher_available else "✗ NOT installed",
         "bold green" if pysqlcipher_available else "bold red"),
    )
    lines = Text.assemble(status_line, "\n", driver_line)

    panel = Panel(
        lines,
        title="[bold cyan]Database Management[/bold cyan]",
        box=rich_box.ROUNDED,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def print_empty() -> None:
    console.print()
