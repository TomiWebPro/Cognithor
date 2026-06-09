MANIFEST = {
    "app_id": "write_to_file",
    "name": "Write To File",
    "description": "Write content to a file on the local filesystem. "
                   "Can create new files or overwrite existing ones.",
    "version": "1.0.0",
    "author": "system",
    "icon": "📝",
    "parameters": [
        {
            "name": "filePath",
            "type": "string",
            "description": "Path to the file to write",
            "required": True,
        },
        {
            "name": "content",
            "type": "string",
            "description": "Content to write to the file",
            "required": True,
        },
    ],
    "outputs": [
        {
            "name": "path",
            "type": "string",
            "description": "Absolute path of the written file",
            "required": True,
        },
        {
            "name": "bytes_written",
            "type": "integer",
            "description": "Number of bytes written",
            "required": True,
        },
    ],
}
