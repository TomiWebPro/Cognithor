MANIFEST = {
    "app_id": "terminal",
    "name": "Terminal",
    "description": "Execute shell commands on the local system. "
                   "Supports running arbitrary commands with timeout and returns stdout, stderr, and exit code.",
    "version": "1.0.0",
    "author": "system",
    "icon": "⌨️",
    "parameters": [
        {
            "name": "command",
            "type": "string",
            "description": "Shell command to execute",
            "required": True,
        },
        {
            "name": "timeout",
            "type": "integer",
            "description": "Timeout in milliseconds",
            "required": False,
            "default": 30000,
        },
    ],
    "outputs": [
        {
            "name": "stdout",
            "type": "string",
            "description": "Standard output from the command",
            "required": False,
        },
        {
            "name": "stderr",
            "type": "string",
            "description": "Standard error from the command",
            "required": False,
        },
        {
            "name": "exit_code",
            "type": "integer",
            "description": "Exit code of the command",
            "required": True,
        },
    ],
}
