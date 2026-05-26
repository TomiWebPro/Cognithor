"""Cognithor CLI service — interactive menus and server CLI.

Submodules:
  cli_service.interactive   — Interactive menu system
  cli_service.server        — Server CLI startup
  cli_service.display       — Rich rendering helpers
  cli_service.prompts       — User input prompts
"""

from cli_service.interactive import (
    interactive_main,
    cmd_init,
    cmd_status,
    cmd_database_menu,
    cmd_connection_info,
    detect_db_encryption as interactive_detect_db_encryption,
    db_exists,
)

__all__ = [
    "interactive_main",
    "cmd_init",
    "cmd_status",
    "cmd_database_menu",
    "cmd_connection_info",
    "interactive_detect_db_encryption",
    "db_exists",
]
