MANIFEST = {
    "app_id": "list_directory",
    "name": "List Directory",
    "description": "List the contents of a directory on the local filesystem. "
                   "Returns file and folder names with metadata such as size.",
    "version": "1.0.0",
    "author": "system",
    "icon": "📁",
    "parameters": [
        {
            "name": "path",
            "type": "string",
            "description": "Path to the directory to list",
            "required": True,
        }
    ],
    "outputs": [
        {
            "name": "entries",
            "type": "string",
            "description": "Directory listing with file names, types, and sizes",
            "required": True,
        }
    ],
}
