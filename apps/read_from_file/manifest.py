MANIFEST = {
    "app_id": "read_from_file",
    "name": "Read From File",
    "description": "Read the contents of a file from the local filesystem. "
                   "Returns the file content as text along with metadata such as file size.",
    "version": "1.0.0",
    "author": "system",
    "icon": "📄",
    "parameters": [
        {
            "name": "filePath",
            "type": "string",
            "description": "Path to the file to read",
            "required": True,
        },
    ],
    "outputs": [
        {
            "name": "content",
            "type": "string",
            "description": "File content as text",
            "required": True,
        },
        {
            "name": "size",
            "type": "integer",
            "description": "File size in bytes",
            "required": True,
        },
    ],
}
