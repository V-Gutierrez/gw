<p align="center">
  <img src="assets/logo.png" alt="gw logo" width="200" />
</p>

<h1 align="center">gw</h1>

<p align="center">
  <strong>Google Workspace in your terminal.</strong><br/>
  Gmail, Calendar, Contacts, Drive, Sheets, Docs, Tasks, Meet — and the domain itself. One CLI.<br/>
  Permanent OAuth. Zero bloat.
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

Since v0.9.0 it also administers the domain: 31 commands under `gw admin` that read the inventory and manage it — create a user with their full directory profile, move a leaver's Drive to whoever stays, then delete the account. The Admin Console does all of this too, in a browser, one click at a time.

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

# Account signature (see "Account Signature" below)
signature = true                        # attach the signature Gmail has for the account
signature_address = "victor@example.com" # pick among aliases (default: the account default)
signature_cache_path = "~/.config/gw/signature.json"  # default: signature-<profile>.json
signature_cache_ttl_seconds = 604800    # a week

[profiles.work]
credentials_path = "~/.config/gw/work-credentials.json"

[profiles.personal]
timezone = "Europe/London"
signature = false                       # this mailbox has no signature to attach
```

Inspect the active config with:

```bash
gw config show
gw config show --json
gw config path
gw --profile work config show --json
```

## Account Signature

Gmail's signature is a compose-time setting: the web UI appends it, the Gmail API does
not. gw builds the raw MIME itself, so it reads the signature from the account
(`users.settings.sendAs`) and attaches it to everything it sends — `send`, `draft`,
`reply`, `forward` and `draft-edit`.

The signature is cached for a week at `~/.config/gw/signature-<profile>.json`, so sending
does not pay for an extra API call. If the API is unreachable the cached copy is used;
an account with no signature configured keeps sending the plain message it always did.

```bash
gw gmail signature                 # what the next message will carry
gw gmail signature --refresh       # ignore the cache and read Gmail again
gw gmail signature --json
gw gmail signature --set signature.html   # create or replace it in Gmail
gw gmail signature --set - < signature.html   # ...or pipe it in
gw gmail signature --edit                 # edit the current one in $EDITOR
gw gmail signature --clear                # remove the signature from Gmail
gw gmail send "to@example.com" "Subject" "Body" --no-signature   # this one time only
gw --profile personal gmail send "to@example.com" "Subject" "Body"
```

Writing goes to Gmail's own settings, so the web interface shows the same signature gw
attaches. `--set` creates it when there is none and replaces it when there is; `--edit`
pulls the current one into `$EDITOR`, and leaving the buffer untouched writes nothing.

`--signature / --no-signature` is available on every sending command and beats the config
for that single message.

Reading works with the scopes gw already asks for. Writing needs `gmail.settings.basic`,
which is in the default set from 0.8.0 on — a token issued earlier only needs one re-login:

```bash
gw --profile work auth login
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
gw gmail send "alice@example.com" "Subject" "Hello" --no-signature
gw gmail signature --json
gw auth login --headless --url-only
gw auth login --headless --code 'http://localhost/?code=...'
gw gmail draft "alice@example.com" "Draft subject" "Hello later"
gw gmail trash 18c0ffee
gw gmail archive 18c0ffee
gw gmail label 18c0ffee Work
gw gmail star 18c0ffee
gw gmail attachments 18c0ffee --json
gw gmail download 18c0ffee --dir ~/Downloads
gw gmail download 18c0ffee --filename invoice.pdf --output ~/Desktop/invoice.pdf
gw gmail download 18c0ffee --attachment-id ANGjdJ... --dir .

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

gw admin whoami
gw admin users --limit 1000 --json
gw admin user someone@yourdomain.com
gw admin user someone@yourdomain.com --raw
gw admin user-create new@yourdomain.com --first-name New --last-name Person \
  --password 'Temp!1234' --org-unit "/Sales" --title "Store Manager" \
  --department Sales --phone "+351900000000" --recovery-email personal@gmail.com
gw admin user-suspend someone@yourdomain.com --dry-run
gw admin transfer-apps
gw admin user-delete leaver@yourdomain.com \
  --confirm-email leaver@yourdomain.com --transfer-to stays@yourdomain.com

gw mcp serve
```

## Workspace Administration

`gw admin` covers the domain: 31 commands, 14 of them read-only. It needs its own consent
(`gw auth login --admin` for reading, `--admin-write` to manage) and a super-admin role on
the domain — the scopes are deliberately separate from the personal ones, so granting them
cannot disturb an existing login.

```bash
gw auth login --admin-write        # consent once, per profile
gw admin whoami                    # which APIs actually answer; exits non-zero if any denied
```

### Three rails, because writing to a domain has no undo

**`--dry-run` prints the exact body that would be sent**, on screen and not only under
`--json`. Passwords appear as `"***"` — the field shows, the value never does.

**`--yes` skips the confirmation prompt** on reversible writes.

**Five commands ignore `--yes` and demand the target retyped**: `user-delete`,
`group-delete`, `orgunit-delete`, `device-action`, `mobile-action`. They accept `--yes` so
existing scripts keep parsing, and their help says it is ignored — an inert flag advertised
as a safety step is worse than no flag.

### Offboarding without destroying the data

Deleting a user destroys their Drive and Gmail. `--transfer-to` moves it first and **waits**:

```bash
gw admin transfer-apps                                   # what this domain can move
gw admin user-delete leaver@corp.com \
  --confirm-email leaver@corp.com --transfer-to manager@corp.com
```

The wait is the whole point. `transfers.insert` returns immediately with `inProgress` and
the work runs afterwards, so deleting in that window destroys exactly what was being
copied — silently, because `users.delete` succeeds anyway. Only `completed` authorises the
deletion; any other state, including the `--transfer-timeout` expiring (900s by default),
raises and leaves the account standing.

Private data only by default. `--include-shared` also moves shared files, which rewrites
permissions on other people's documents, so it is asked for and never inherited.

Transfers are asynchronous, so they can be followed or used as a gate:

```bash
gw admin transfer-status TRANSFER_ID --wait   # exits non-zero until `completed`
gw admin transfers --status completed --json
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

### Headless login

Google removed the out-of-band (OOB) copy/paste flow in January 2023, so a headless login still
has to send a loopback `redirect_uri` — `gw` uses `http://localhost` and nothing listens on it:

```bash
gw auth login --headless
gw auth login --headless --redirect-uri http://127.0.0.1:9000
```

Open the printed URL in any browser. After you approve, the browser lands on
`http://localhost/?code=...` and shows a connection error — that is expected. Copy that whole
URL from the address bar and paste it back. A bare `code` value is accepted too.

## Shell Completion

```bash
eval "$(gw completion zsh)"
eval "$(gw completion bash)"
gw completion fish | source
```

## MCP Server

`gw mcp serve` starts a stdio Model Context Protocol server for AI agents.

Exposed tools:

- `gmail_send`, `gmail_draft`, `gmail_reply`, `gmail_forward`, `gmail_list`, `gmail_search`, `gmail_thread`, `gmail_count`, `gmail_read`, `gmail_attachments`, `gmail_download_attachments`, `gmail_trash`, `gmail_archive`, `gmail_label`, `gmail_star`, `gmail_mark_read`, `gmail_mark_unread`
- `calendar_today`, `calendar_tomorrow`, `calendar_week`, `calendar_agenda`, `calendar_next`, `calendar_create`, `calendar_list`, `calendar_delete`, `calendar_update`, `meet_create`
- `contacts_search`, `contacts_list`
- `drive_list`, `drive_search`, `drive_mkdir`, `drive_share`, `drive_info`, `drive_upload`, `drive_download`
- `sheets_read`, `sheets_write`
- `docs_read`, `docs_export`, `docs_list`
- `tasks_lists`, `tasks_list`, `tasks_add`, `tasks_complete`, `tasks_delete`
- `admin_users`, `admin_user_get`, `admin_groups`, `admin_group_members`, `admin_orgunits`, `admin_chromeos`, `admin_mobile`, `admin_telemetry`, `admin_roles`, `admin_reports`, `admin_check_access`
- `admin_user_create`, `admin_user_suspend`, `admin_user_restore`, `admin_user_move`, `admin_user_rename`, `admin_user_set_admin`, `admin_group_add`, `admin_group_remove`, `admin_group_create`, `admin_orgunit_create`
- `admin_transfer`, `admin_transfer_apps`, `admin_transfer_status`, `admin_transfers`

The five irreversible commands are **not** exposed over MCP: deleting a user, a group or an
org unit, and wiping a device, stay on the CLI where the retyped confirmation lives.

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

### Administration (`--admin` / `--admin-write`, opt-in)

These are never granted to a normal login. They belong to a dedicated profile with its own
token file, which is why adding them cannot re-consent an existing one.

| Scope | Why |
|-------|-----|
| `admin.directory.user` | Read the directory; with `--admin-write`, create, suspend, move and delete users |
| `admin.directory.group` | Read groups and membership; with write, manage them |
| `admin.directory.orgunit` | Read the org unit tree; with write, create and delete |
| `admin.directory.device.chromeos` | ChromeOS inventory; with write, device actions |
| `admin.directory.device.mobile` | Mobile inventory; with write, `.action` for block and wipe |
| `admin.directory.rolemanagement.readonly` | Who holds which admin role |
| `admin.reports.audit.readonly` | What people actually did |
| `chrome.management.telemetry.readonly` | Device telemetry |
| **`admin.datatransfer`** | Move a leaving user's Drive and Calendar before deletion |

`--admin` requests the `.readonly` variant of each; `--admin-write` replaces it with the
broad scope. Google treats the broad one as a superset, so asking for both is redundant
rather than additive.

All scopes are the minimum required for each feature. You can review the exact scope list in `src/gw/auth.py`.
