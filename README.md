<p align="center">
  <img src="assets/logo.png" alt="gw logo" width="200" />
</p>

<h1 align="center">gw</h1>

<p align="center">
  <strong>Google Workspace in your terminal.</strong><br/>
  Gmail, Calendar, Contacts, Drive, Sheets, Docs, Tasks, Meet — one CLI. Permanent OAuth. Zero bloat.
</p>

<p align="center">
  <img src="https://img.shields.io/github/v/release/v-gutierrez/gw" alt="Version" />
  <img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
</p>

---

## Why

Every Google Workspace tool is either calendar-only, admin-only, or abandoned. No single CLI covers Gmail + Calendar + Contacts + Drive + Sheets + Docs with permanent OAuth.

`gw` fixes that. Login once, use forever. No re-auth loops, first-class JSON output, and profile-aware config when you need multiple accounts.

## Install

### macOS / Linux (pip)

```bash
pip install gw-cli
```

### macOS (Homebrew)

```bash
brew tap v-gutierrez/gw
brew install gw
```

### From source

```bash
git clone https://github.com/v-gutierrez/gw.git
cd gw
pip install -e .
```

## Getting Started

### 1. Create a Google Cloud OAuth App (one-time, ~3 minutes)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Go to **APIs & Services** → **Library**
4. Enable these APIs:
   - Gmail API
   - Google Calendar API
   - Google Drive API
   - Google Sheets API
   - Google Docs API
   - People API (Contacts)
   - Google Tasks API
5. Go to **APIs & Services** → **Credentials**
6. Click **Create Credentials** → **OAuth client ID**
7. Application type: **Desktop app**
8. Name: `gw-cli`
9. Click **Create** → **Download JSON**
10. Move the file:
    ```bash
    mv ~/Downloads/client_secret_*.json ~/.config/gw/credentials.json
    ```

### 2. Login

```bash
gw auth login
```

For headless environments (no browser):

```bash
gw auth login --headless
```

For multiple accounts:

```bash
gw auth login --profile work
```

### 3. Verify

```bash
gw doctor
gw calendar today
```

### Full auth command reference

```bash
gw auth setup           # guided setup wizard (creates config + logs in)
gw auth login           # OAuth login (opens browser)
gw auth login --headless  # print auth URL, paste code manually
gw auth login --profile work  # login a named profile
gw auth status          # show current token/scope status
gw auth logout          # revoke token and delete local files
```

Tokens are stored at `~/.config/gw/token.json` by default, or `token-{profile}.json` when you pass `--profile PROFILE`.

> **Upgrading from v0.4.x?** Run `gw auth logout && gw auth login` to refresh your token with the new Tasks scope.

## Configuration

Config lives at `~/.config/gw/config.toml`:

```toml
timezone = "America/Sao_Paulo"
default_calendar = "primary"
credentials_path = "~/.config/gw/credentials.json"
token_path = "~/.config/gw/token.json"
timeout_seconds = 30

[profiles.work]
credentials_path = "~/.config/gw/work-credentials.json"

[profiles.personal]
timezone = "Europe/London"
```

Inspect the active config with:

```bash
gw config show
gw config show --json
gw config path
gw --profile work config show --json
```

## Usage

```bash
gw --help
gw --profile work --help
gw completion zsh
gw completion bash
gw completion fish

gw calendar today
gw calendar agenda --days 7
gw calendar next --json
gw calendar today --all --json
gw calendar create "Standup" "2026-03-26T10:00" "2026-03-26T10:30"
gw calendar update EVENT_ID --title "Rescheduled standup" --start "2026-03-26T11:00" --end "2026-03-26T11:30"
gw calendar delete EVENT_ID
gw calendar list
gw calendar calendars

gw meet create
gw meet create --title "Weekly sync" --json

gw contacts search "alice"
gw contacts list --max 20 --json

gw gmail list --max 5
gw gmail search "from:alice@example.com newer_than:7d"
gw gmail thread 18c0ffee --json
gw gmail count --query "is:unread"
gw gmail mark-read 18c0ffee
gw gmail mark-unread 18c0ffee --json
gw gmail list --query "from:alice@example.com" --json
gw gmail read 18c0ffee
gw gmail send "alice@example.com" "Subject" "Hello"
gw gmail draft "alice@example.com" "Draft subject" "Hello later"
gw gmail trash 18c0ffee
gw gmail archive 18c0ffee
gw gmail label 18c0ffee Work
gw gmail star 18c0ffee

gw drive list --max 20 --json
gw drive search "report"
gw drive search "name contains 'report'"
gw drive upload file.txt
gw drive mkdir "Projects"
gw drive share FILE_ID alice@example.com --role writer
gw drive info FILE_ID --json
gw drive download FILE_ID --out report.pdf
gw drive download FILE_ID --format txt
gw drive download SHEET_FILE_ID --format csv

gw tasks lists
gw tasks list --json
gw tasks add "Buy milk" --due 2026-04-01
gw tasks complete TASK_ID
gw tasks delete TASK_ID

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

- `gmail_send`, `gmail_draft`, `gmail_reply`, `gmail_forward`, `gmail_list`, `gmail_search`, `gmail_thread`, `gmail_count`, `gmail_read`, `gmail_trash`, `gmail_archive`, `gmail_label`, `gmail_star`, `gmail_mark_read`, `gmail_mark_unread`
- `calendar_today`, `calendar_tomorrow`, `calendar_week`, `calendar_agenda`, `calendar_next`, `calendar_create`, `calendar_list`, `calendar_delete`, `calendar_update`, `meet_create`
- `contacts_search`, `contacts_list`
- `drive_list`, `drive_search`, `drive_mkdir`, `drive_share`, `drive_info`, `drive_upload`, `drive_download`
- `sheets_read`, `sheets_write`
- `docs_read`, `docs_export`, `docs_list`
- `tasks_lists`, `tasks_list`, `tasks_add`, `tasks_complete`, `tasks_delete`

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
| `tasks` | List, create, complete, and delete Google Tasks |
| `spreadsheets` | Read and write Sheets data |
| `documents.readonly` | Read and export Docs |
| `contacts.readonly` | Search and list contacts |
| `userinfo.email` | Identify authenticated account |

All scopes are the minimum required for each feature. You can review the exact scope list in `src/gw/auth.py`.
