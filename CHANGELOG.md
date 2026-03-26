# Changelog

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
