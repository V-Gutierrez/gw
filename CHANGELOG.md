# Changelog

## v0.5.2 (2026-08-14)

### Features
- Added `gw gmail attachments <message_id>` to list a message's attachments with filename, MIME type, size, and attachment ID
- Added `gw gmail download <message_id>` to save attachments to disk — all of them by default, or narrowed with `--attachment-id` / `--filename`, targeted with `--output` / `--dir`
- `gw gmail read` now returns attachment metadata, so one call is enough to find an attachment ID
- Added MCP tools `gmail_attachments` and `gmail_download_attachments`
- Inline images (Content-ID parts) are treated as attachments and flagged `inline: true`; small attachments delivered in `body.data` are decoded locally instead of round-tripping to the API

### Fixes
- `gw auth login --headless` now sends a loopback `redirect_uri` (`http://localhost`, overridable with `--redirect-uri`). Without it Google rejected the authorization request, because the out-of-band flow this code path assumed was removed in January 2023
- `--headless` accepts the full pasted redirect URL, not just a bare code, and reports `error=access_denied` instead of failing on token exchange
- Attachment filenames are reduced to a single path component before writing, so a crafted `../../` filename cannot escape the download directory

### Notes
- No new OAuth scopes — `gmail.modify` already covers attachment reads, so no re-authentication is needed

## v0.5.0 (2026-03-27)

### Features
- Fixed `gw drive search` so free-text searches are translated into valid Drive API `q` syntax instead of returning a 400 Invalid Value error
- Added `gw tasks list/lists/add/complete/delete` for Google Tasks management from the terminal
- Added `gw meet create` for instant Google Meet link creation through Calendar conference data
- Added `gw drive mkdir/share/info` for folder creation, permission sharing, and metadata inspection
- Added `gw gmail draft` plus matching MCP tools for Tasks, Meet, Drive, and Gmail draft workflows

### Notes
- Re-authenticate with `gw auth logout && gw auth login` after upgrading so your token picks up the new Google Tasks scope

## v0.4.0 (2026-03-27)

### Features
- Retry-aware Google API execution with exponential backoff, 429 Retry-After support, and a 30-second configurable HTTP timeout
- `gw gmail search/thread/count/mark-read/mark-unread` for query-first search, full thread inspection, mailbox counts, and unread state management
- `gw calendar agenda --days N` and `gw calendar next` for short-horizon planning and next-event lookup
- Multi-profile foundation with `--profile`, `token-{profile}.json` storage, and `[profiles.<name>]` overrides in `config.toml`
- MCP server tools expanded to mirror the new Gmail and Calendar commands while honoring the active runtime config

### Notes
- Existing single-profile configs remain backward-compatible; omitting `--profile` keeps using `token.json`
- JSON errors still use the shape `{"error": "message", "code": N}` when `--json` is enabled

## v0.3.0 (2026-03-26)

### Features
- `gw contacts search/list` — People API contact lookup from the terminal
- `gw calendar update/delete` — patch existing events and remove them by ID
- `gw gmail trash/archive/label/star` — manage message state without leaving the CLI
- `gw drive upload/download/search` — move files in and out of Drive and query by Drive syntax
- `gw sheets write` — write single-cell values with user-entered or raw semantics
- Expanded MCP server tools for the new Contacts, Calendar, Gmail, Drive, and Sheets operations

### Notes
- Drive scope widened from `drive.readonly` to `drive`
- Sheets scope widened from `spreadsheets.readonly` to `spreadsheets`
- Re-authenticate with `gw auth logout && gw auth login` after upgrading to refresh token scopes

## v0.2.0 (2026-03-26)

### Features
- `gw auth login --headless` — browserless OAuth flow for servers, agents, and containers
- `gw auth setup` — interactive onboarding wizard for credentials import and first login
- `gw doctor` — health check for credentials, token, auth state, and timezone configuration
- `gw completion {bash,zsh,fish}` — built-in shell completion script output
- `gw mcp serve` — stdio MCP server exposing Gmail, Calendar, Drive, Sheets, and Docs tools
- Consistent CLI exit codes with JSON error output when `--json` is enabled

## v0.1.0 (2026-03-26)

### Features
- `gw auth login/status/logout` — OAuth 2.0 with permanent token
- `gw calendar today/tomorrow/week [--all]` — multi-calendar support
- `gw calendar create` — with recurrence, reminders, all-day
- `gw calendar list` — list all calendars
- `gw gmail send/reply/forward` — with CC/BCC support
- `gw gmail list` — with --max, --query, --unread, --after filters
- `gw gmail read` — full body extraction by ID or query
- `gw drive list` — recent files
- `gw sheets read` — by spreadsheet ID + range
- `gw docs read/export/list` — plain text, HTML, PDF, DOCX export
- `gw config show` — display current configuration
- `--json` flag on all commands for machine output
- TOML config file (~/.config/gw/config.toml)
- JSON token storage (no pickle)
