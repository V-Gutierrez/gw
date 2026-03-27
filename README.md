<p align="center">
  <img src="assets/logo.png" alt="gw logo" width="200" />
</p>

<h1 align="center">gw</h1>

<p align="center">
  <strong>Google Workspace in your terminal.</strong><br/>
  Gmail, Calendar, Contacts, Drive, Sheets, Docs — one CLI. Permanent OAuth. Zero bloat.
</p>

<p align="center">
  <img src="https://img.shields.io/github/v/release/v-gutierrez/gw" alt="Version" />
  <img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
</p>

---

## Why

Every Google Workspace tool is either calendar-only, admin-only, or abandoned. No single CLI covers Gmail + Calendar + Contacts + Drive + Sheets + Docs with permanent OAuth.

`gw` fixes that. Login once, use forever. No re-auth, no token expiry, no config files to manage.

## Install

```bash
pip install -e ".[dev]"
```

## Authentication

`gw` expects an OAuth client credentials file at `~/.config/gw/credentials.json` by default.
After that:

```bash
gw auth login
gw auth login --headless
gw auth setup
gw auth status
gw auth logout
gw doctor
```

Tokens are stored as JSON at `~/.config/gw/token.json` and refreshed automatically.
Headless login prints an authorization URL and prompts for the code instead of opening a browser.

If you used `gw` before v0.3.0, run `gw auth logout && gw auth login` after upgrading so your token picks up the new Drive and Sheets write scopes.

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
gw completion zsh
gw completion bash
gw completion fish

gw calendar today
gw calendar today --all --json
gw calendar create "Standup" "2026-03-26T10:00" "2026-03-26T10:30"
gw calendar update EVENT_ID --title "Rescheduled standup" --start "2026-03-26T11:00" --end "2026-03-26T11:30"
gw calendar delete EVENT_ID
gw calendar list
gw calendar calendars

gw contacts search "alice"
gw contacts list --max 20 --json

gw gmail list --max 5
gw gmail list --query "from:alice@example.com" --json
gw gmail read 18c0ffee
gw gmail send "alice@example.com" "Subject" "Hello"
gw gmail trash 18c0ffee
gw gmail archive 18c0ffee
gw gmail label 18c0ffee Work
gw gmail star 18c0ffee

gw drive list --max 20 --json
gw drive search "name contains 'report'"
gw drive upload file.txt
gw drive download FILE_ID --out report.pdf
gw drive download FILE_ID --format txt
gw drive download SHEET_FILE_ID --format csv

gw sheets read SPREADSHEET_ID "Sheet1!A1:C5"
gw sheets write SPREADSHEET_ID "Sheet1!A1" "data"

gw docs list
gw docs read DOCUMENT_ID
gw docs export DOCUMENT_ID --format txt

gw mcp serve
```

## Onboarding and Health Checks

```bash
gw auth setup
gw auth setup --headless
gw doctor
gw doctor --json
```

`gw auth setup` guides you through creating or importing OAuth credentials and then logs in.
`gw doctor` reports the state of credentials, token, authentication, and timezone configuration.

## Shell Completion

```bash
eval "$(gw completion zsh)"
eval "$(gw completion bash)"
gw completion fish | source
```

## MCP Server

`gw mcp serve` starts a stdio Model Context Protocol server for AI agents.

Exposed tools:

- `gmail_send`, `gmail_reply`, `gmail_forward`, `gmail_list`, `gmail_read`, `gmail_trash`, `gmail_archive`, `gmail_label`, `gmail_star`
- `calendar_today`, `calendar_tomorrow`, `calendar_week`, `calendar_create`, `calendar_list`, `calendar_delete`, `calendar_update`
- `contacts_search`, `contacts_list`
- `drive_list`, `drive_search`, `drive_upload`, `drive_download`
- `sheets_read`, `sheets_write`
- `docs_read`, `docs_export`, `docs_list`

## Exit Codes

- `0` success
- `1` general or usage error
- `2` auth failure
- `3` config failure

When `--json` is enabled, errors are emitted as JSON with the shape `{"error": "message", "code": N}`.

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
| `gmail.modify` | Read, list, search, trash, archive, label, and star emails |
| `calendar` | Read, create, update, and delete calendar events |
| `drive` | List, search, upload, and download Drive files |
| `spreadsheets` | Read and write Sheets data |
| `documents.readonly` | Read and export Docs |
| `contacts.readonly` | Search and list contacts |
| `userinfo.email` | Identify authenticated account |

All scopes are the minimum required for each feature. You can review the exact scope list in `src/gw/auth.py`.
