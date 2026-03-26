# gw — Google Workspace CLI

Google Workspace in your terminal: Gmail, Calendar, Drive, Sheets, and Docs through one CLI.

## Install

```bash
pip install -e ".[dev]"
```

## Authentication

`gw` expects an OAuth client credentials file at `~/.config/gw/credentials.json` by default.
After that:

```bash
gw auth login
gw auth status
gw auth logout
```

Tokens are stored as JSON at `~/.config/gw/token.json` and refreshed automatically.

## Configuration

Config lives at `~/.config/gw/config.toml`:

```toml
timezone = "America/Sao_Paulo"
default_calendar = "primary"
credentials_path = "~/.config/gw/credentials.json"
token_path = "~/.config/gw/token.json"
```

Inspect the active config with:

```bash
gw config show
gw config show --json
gw config path
```

## Usage

```bash
gw --help
gw calendar today
gw calendar today --all --json
gw calendar create "Standup" "2026-03-26T10:00" "2026-03-26T10:30"
gw calendar list
gw calendar calendars

gw gmail list --max 5
gw gmail list --query "from:alice@example.com" --json
gw gmail read 18c0ffee
gw gmail send "alice@example.com" "Subject" "Hello"

gw drive list --max 20 --json
gw sheets read SPREADSHEET_ID "Sheet1!A1:C5"
gw docs list
gw docs read DOCUMENT_ID
gw docs export DOCUMENT_ID --format txt
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## OAuth Scopes

gw requests the following Google API scopes during `gw auth login`:

| Scope | Why |
|-------|-----|
| `gmail.send` | Send emails, reply, forward |
| `gmail.modify` | Read, list, and search emails |
| `calendar` | Read and create calendar events |
| `drive.readonly` | List Drive files |
| `spreadsheets.readonly` | Read Sheets data |
| `documents.readonly` | Read and export Docs |
| `contacts.readonly` | Search contacts (planned) |
| `userinfo.email` | Identify authenticated account |

All scopes are the minimum required for each feature. You can review the exact scope list in `src/gw/auth.py`.
