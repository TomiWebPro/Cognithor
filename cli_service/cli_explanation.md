# CLI Service Explanation

The `cli_service` package provides the interactive terminal UI for managing
the Cognithor backend.  It is launched via `-i` / `--interactive` and gives
administrators a menu-driven interface for provider configuration, database
encryption, connection sharing, and server startup.

The package is split into four files:

## File: server.py

Entry point for the Cognithor command line.  Parses arguments and decides
whether to launch the interactive CLI or the FastAPI server.

**Arguments**:

| Flag | Description |
|------|-------------|
| `-i`, `--interactive`, `--cli` | Launch the interactive menu-driven CLI |
| `--no-encrypt` | Force plain-text SQLite (skip pysqlcipher3) |
| `--encrypt` | Force encrypted SQLite (requires pysqlcipher3) |

Before entering the interactive menu, `server.py` detects whether the
existing database is encrypted or plain-text by trying both `sqlite3` and
`pysqlcipher3` connections.  If the database is encrypted and pysqlcipher3
is not installed, the user is offered recovery options (install, reset
encrypted, reset plain-text).

```
python -m api_service.main -i          # launch interactive CLI
python -m api_service.main             # start API server (default)
```

## File: interactive.py

The core of the CLI — renders menus, processes user choices, and calls
the appropriate service functions.  Uses the `rich` library for colourful
terminal output (panels, tables, spinners, progress bars).

### Main menu

```
 1. System Status
 2. Provider Management
 3. Database Management  [ENCRYPTED] / [plain-text] / [plain-text !]
 4. Connection Info
 5. Quit
```

The **Database Management** menu item includes a live status badge:
- `[ENCRYPTED]` (green) — databases are encrypted with SQLCipher
- `[plain-text]` (yellow) — databases are plain-text, encryption is available
- `[plain-text !]` (red) — databases are plain-text, pysqlcipher3 is NOT installed

Navigation uses arrow keys (`↑` / `↓`) or numeric input in non-TTY mode.

### Menu structure

```
Main Menu
├── 1. System Status
│      Shows database path, encryption status, API host, provider
│      count, and a provider table with active model info.
│
├── 2. Provider Management
│      Lists all providers with API key status.
│      Sub-actions:
│      ├── Show details — inspect provider config
│      ├── Set API key — store an API key (hidden input)
│      ├── Manage models — add / remove model entries
│      │     └── Sub-sub-menu: Add model, Remove model, Back
│      ├── Test model — send a test request to a provider model
│      ├── Delete provider — remove permanently (with confirmation)
│      └── Back to main menu
│
├── 3. Database Management
│      Shows encryption status panel and pysqlcipher3 availability.
│      If pysqlcipher3 is missing and DB is plain-text, shows
│      installation instructions in an orange warning panel.
│      Sub-actions (dynamic):
│      ├── Encrypt database  (visible when plain-text)
│      └── Decrypt database  (visible when encrypted)
│      └── Back to main menu
│
├── 4. Connection Info
│      Sub-actions:
│      ├── Show connection info
│      │     Displays host, port, username, password, and a base64
│      │     passkey.  Copies passkey to clipboard automatically.
│      ├── Start QR code server (60s)
│      │     Starts a temporary HTTP server on the API port that
│      │     serves a QR code and HTML page.  Auto-shuts down after
│      │     60 seconds.  The QR code encodes the passkey for
│      │     frontend onboarding.
│      └── Back to main menu
│
└── 5. Quit
```

### Key functions

**`interactive_main()`**: Initialises services (database, tracker, config
manager), then enters the main menu loop.  Handles `KeyboardInterrupt`
gracefully with a farewell message.

**`cmd_status()`**: Reads all config and providers, displays a system
status panel and a provider table with active model indicators.

**`cmd_providers_menu()`**: Provider CRUD sub-menu.  Reads the provider
list from `Tracker` and offers show / set-key / manage-models / test /
delete actions.

**`cmd_models_menu(tracker, provider)`**: Sub-sub-menu for adding and
removing models from a specific provider.

**`cmd_database_menu()`**: Shows the encryption status panel and
pysqlcipher3 availability check.  Offers encrypt or decrypt depending
on current state.  Displays a warning panel with install instructions
when pysqlcipher3 is missing.

**`cmd_connection_menu()`**: Sub-menu that wraps connection info display
and QR code server start.

**`_do_encrypt()`**: Confirms with the user, then calls
`encrypt_databases()` to convert main + log databases from plain-text
to SQLCipher.  Shows a spinner during the operation.

**`_do_decrypt()`**: Confirms with the user, then calls
`decrypt_databases()` to convert from SQLCipher back to plain-text.
Shows a spinner during the operation.

**`cmd_connection_info()`**: Reads API host, port, admin username, and
frontend password from config.  Generates a base64-urlsafe JSON passkey
containing `{host, port, username, password, encryption_available}`.
Displays credentials in a double-border box and copies the passkey to
the clipboard.

**`cmd_qr_server()`**: Starts a temporary `http.server.HTTPServer` on
the configured API port.  Generates a QR code PNG from the passkey using
the `qrcode` library.  Serves an HTML page with the QR image and raw
passkey for 60 seconds, then shuts down automatically.

### Encryption status badge logic

| State | Badge | Style | Meaning |
|-------|-------|-------|---------|
| `CONFIG["use_encryption"]` is `True` | `[ENCRYPTED]` | green | Databases use SQLCipher |
| Plain-text + pysqlcipher3 installed | `[plain-text]` | yellow | Encryption available but not enabled |
| Plain-text + pysqlcipher3 missing | `[plain-text !]` | red | Encryption unavailable, installation required |

### Database state machine

```
    ┌──────────┐    user selects     ┌───────────┐
    │ plain-   │ ──── "Encrypt" ───→ │ ENCRYPTED │
    │ text     │ ←── "Decrypt" ───── │           │
    └──────────┘                     └───────────┘
```

The menu dynamically shows only the relevant action — "Encrypt" when
plain-text, "Decrypt" when encrypted.

## File: display.py

Rendering helpers built on top of `rich`.  Provides consistent styling
for all terminal output.

**`print_banner(subtitle)`**: Renders the Cognithor ASCII logo in a
heavy-bordered panel.  Adapts layout based on terminal width.

**`print_header(title, subtitle)`**: Renders a breadcrumb-style header
panel (e.g. `Main > Providers > OpenAI > Models`).

**`print_section(title)`**: Prints a section heading with an underline.

**`print_step(current, total, description)`**: Prints a step indicator
like `[1/3] Creating tables`.

**`print_success / print_error / print_warning / print_info / print_dim / print_hint`**:
Standard message helpers with coloured prefixes (`✓`, `✗`, `!`, `→`).

**`print_table(headers, rows, title)`**: Renders a Rich `Table` with
cyan-styled headers and heavy head borders.

**`print_credentials_box(data)`**: Double-border panel displaying
connection credentials (host, port, username, password).

**`print_passkey_box(passkey, username, password)`**: Heavy-border panel
showing the base64 passkey and plain-text username/password.

**`print_status_panel(items)`**: Panel showing system status key-value
pairs.

**`print_encryption_status_panel(encrypted, pysqlcipher_available)`**:
Panel showing the current database encryption state and whether the
pysqlcipher3 driver is installed.  Used by the Database Management
sub-menu.

**`spinner(message)`**: Returns a `Progress` with a spinner column and
transient text.  Used for short-running operations (encrypt, decrypt,
test model).

**`progress_bar(description, total)`**: Returns a `Progress` with a bar
column, percentage, and elapsed time.  Defined but not currently used
in the interactive menu.

## File: prompts.py

User input prompts with arrow-key navigation and fallback to numeric
input.

**`choose(options, title, default, hint)`**: Interactive single-select
with arrow keys.  Renders options with `●` for the selected item and `○`
for others, with a `←` marker.  Supports `↑` / `↓` navigation, `Enter`
to confirm, and `Ctrl+C` to cancel.  Falls back to numeric input
(`_choose_numeric`) when the terminal does not support raw mode.

**`ask(message, default, validate, hint)`**: Text input prompt with
optional default value and validation callback.

**`ask_secret(message, hint)`**: Hidden text input using `getpass.getpass`
for API keys and passwords.

**`confirm(message, default, hint)`**: Yes/no prompt with `[Y/n]` or
`[y/N]` default indicator.  Accepts `y`, `yes`, or empty for default.

**`pause(message)`**: Waits for the user to press Enter.  Used after
displaying transient information.

## File: __init__.py

Exports the public API:

```python
interactive_main      # entry point for the interactive CLI
cmd_init              # database initialisation
cmd_status            # system status display
cmd_database_menu     # database management sub-menu
cmd_connection_menu   # connection info sub-menu
interactive_detect_db_encryption  # encryption state detection
db_exists             # check if database file exists
```

## Usage

```bash
# Launch interactive CLI
python -m api_service.main -i

# Or directly
python -m cli_service.server -i
```
