"""Backward-compatible re-export — CLI code moved to cli_service/.

This file is kept for compatibility. Import from cli_service directly.
"""

from cli_service.interactive import *

__all__ = [
    "interactive_main",
    "cmd_init",
    "cmd_status",
    "cmd_providers_menu",
    "cmd_models_menu",
    "cmd_connection_info",
    "cmd_encrypt",
    "cmd_decrypt",
    "detect_db_encryption",
    "db_exists",
]
