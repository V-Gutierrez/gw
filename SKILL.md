---
name: gw
description: >
  Access Google Workspace via gw CLI (Gmail, Calendar, Drive, Sheets, Docs, Contacts, Tasks, Meet).
  Permanent OAuth (never expires). Use when: (1) Checking calendar (today/week/agenda),
  (2) Sending/searching/reading Gmail, (3) Managing Drive files, (4) Reading/writing Sheets,
  (5) Reading/exporting Docs, (6) Searching contacts.
---

# gw — Google Workspace CLI

**Binary:** `/opt/homebrew/bin/gw` (or `which gw`)  
**Config:** `~/.config/gw/config.toml`  
**Auth:** Permanent OAuth 2.0 (auto-refresh, never expires)

## Global Flags

| Flag | Description |
|------|-------------|
| `--json` | Output as JSON (works on all commands) |
| `--profile TEXT` | Use a named profile from config.toml (multi-account) |
| `--version` | Show version |

---

## Auth Commands

```bash
gw auth login           # Authorize via browser OAuth
gw auth login --headless  # No browser: prints the URL, you paste the redirect back
gw auth logout          # Revoke and remove stored token
gw auth status          # Show current auth status / which account
gw auth setup           # Interactive setup wizard (config.toml)
```

`--headless` uses a loopback `redirect_uri` (`http://localhost`, override with
`--redirect-uri`). Paste the **whole** redirect URL back, not just the code.

---

## Gmail Commands

### List / Read
```bash
gw gmail list                        # 10 most recent emails
gw gmail list --max 20               # 20 most recent
gw gmail list --unread               # Unread only
gw gmail list --after 6h             # Last 6 hours (also 24h, 7d)
gw gmail list --query "from:boss@example.com"
gw gmail read <message_id>           # Read full email body
gw gmail thread <thread_id>          # Show full thread
gw gmail search "query"              # Search emails (Gmail query syntax)
gw gmail search "invoice" --after 7d # Search narrowed to the last 7 days
gw gmail count                       # Count unread messages
```

`--after` takes `6h`, `24h` or `7d` and becomes a `newer_than:` filter, which is
hour-granular. Gmail's own `after:` is day-granular, so prefer `--after`.

### Send / Reply / Forward
```bash
gw gmail send TO SUBJECT BODY        # Send email
gw gmail send "to@example.com" "Subject" "Body text"
gw gmail send "to@example.com" "Subject" "Body" --cc "cc@example.com"
gw gmail send "to@example.com" "Subject" "Body" --bcc "bcc@example.com"
gw gmail draft "to@example.com" "Subject" "Body text"

gw gmail reply <message_id> "Reply body"
gw gmail reply <message_id> "Reply body" --cc "cc@example.com"
gw gmail forward <message_id> "to@example.com" --cc "cc@example.com"
```

**Attachments** — `--attachment` is repeatable and works on all four commands:

```bash
gw gmail send "to@example.com" "Signed contract" "See attached." \
  --attachment ~/docs/contract-signed.pdf \
  --attachment ~/docs/annex.jpg
gw gmail reply <message_id> "Signed and attached." \
  --attachment ~/docs/contract-signed.pdf --cc "broker@example.com"
gw gmail forward <message_id> "to@example.com" --attachment ~/docs/extra.pdf
gw gmail draft "to@example.com" "Subject" "Body" --attachment ~/docs/a.pdf
```

**Long bodies** — `--body-file` avoids shell escaping. It replaces the positional
`BODY`; passing both is an error, passing neither is an error:

```bash
gw gmail send "to@example.com" "Subject" --body-file /tmp/body.txt
gw gmail reply <message_id> --body-file /tmp/reply.txt --attachment /tmp/a.pdf
```

**Account signature** — the signature configured in Gmail for the account is attached
automatically. Gmail's signature is a compose-time setting, so the API never applied it;
gw reads it from `users.settings.sendAs`, caches it for a week and appends it:

```bash
gw gmail signature                   # show what the next message will carry
gw gmail signature --refresh         # bypass the cache and re-read Gmail
gw gmail send "to@example.com" "Subject" "Body" --no-signature   # skip it once
gw gmail reply <message_id> "Sem assinatura" --no-signature
```

- `--signature / --no-signature` exists on `send`, `draft`, `draft-edit`, `reply` and
  `forward`, and beats the config for that one message
- Config: `signature = false` disables it for a profile, `signature_address` picks among
  aliases, `signature_cache_path` / `signature_cache_ttl_seconds` tune the cache
- An account with no signature configured is unaffected: the message stays a plain
  `text/plain` part
- With a signature the body becomes `multipart/alternative` (HTML + plain text), wrapped
  in `multipart/mixed` when you also attach files
- `draft-edit` re-applies the signature rather than stacking a second copy

Notes:
- Files are sent as raw binary with the MIME type resolved from the filename
  (fallback `application/octet-stream`). A PDF arrives as a PDF.
- Non-ASCII filenames are encoded as RFC 2231 `filename*=UTF-8''…`.
- `reply` keeps `In-Reply-To`, `References` and the original `threadId`.
- `forward` does **not** re-send the original attachments. Pull them with
  `gw gmail download <id>` first, then pass them with `--attachment`.
- Attachments are not exposed through the MCP server yet (see `mcp_server.py`).

### Drafts

```bash
gw gmail drafts                      # List drafts WITH their draft IDs
gw gmail draft-read <draft_id>       # Show a draft's current content
gw gmail draft-send <draft_id>       # Send that draft
gw gmail draft-delete <draft_id>     # Delete it (asks to confirm)
```

**Editing a draft** — only the fields you pass change:

```bash
gw gmail draft-edit <draft_id> --subject "New subject"
gw gmail draft-edit <draft_id> --body-file /tmp/v2.txt
gw gmail draft-edit <draft_id> --attachment new.pdf    # REPLACES the whole set
gw gmail draft-edit <draft_id> --clear-attachments     # drops every attachment
```

Notes:
- Use the **draft ID**, not the message ID. Gmail changes the message ID on every
  edit; the draft ID is stable.
- `drafts.update` replaces the whole message, so gw reads the draft back and
  re-sends the parts you did not touch. Attachment bytes survive unchanged.
- `--attachment` means "the attachments are now exactly these", the same rule as
  `--attendees` on `gw calendar update`. Omit it to keep what is there.

### Manage
```bash
gw gmail mark-read <message_id>      # Mark as read
gw gmail mark-unread <message_id>    # Mark as unread
gw gmail archive <message_id>        # Archive email
gw gmail trash <message_id>          # Move to trash
gw gmail label <message_id> LABEL    # Apply label
gw gmail label <message_id> LABEL --remove   # Remove label
gw gmail star <message_id>           # Star a message
gw gmail star <message_id> --remove  # Unstar a message
gw gmail untrash <message_id>        # Restore from trash
```

### Whole threads and bulk changes

```bash
gw gmail thread-archive <thread_id>            # Archive the whole conversation
gw gmail thread-trash <thread_id>              # Trash it (asks to confirm)
gw gmail thread-untrash <thread_id>
gw gmail thread-label <thread_id> LABEL [--remove]

# One API call for every message matching the query, not one per message
gw gmail bulk --query "from:newsletter@x.com older_than:1y" --archive
gw gmail bulk --query "is:unread label:promo" --mark-read --max 500
gw gmail bulk --query "from:x@y.com" --label "Seguros" --yes
```

`bulk` asks to confirm unless you pass `--yes`, and refuses to run with no action flag.

### Mailbox introspection

```bash
gw gmail profile                     # Address, message/thread totals, history ID
gw gmail history --since <history_id>   # Changes since that point
```

### Attachments
```bash
gw gmail attachments <message_id>              # List attachments (name, mime, size, ID)
gw gmail download <message_id>                 # Download ALL attachments to cwd
gw gmail download <message_id> --dir ~/Downloads
gw gmail download <message_id> --filename invoice.pdf --output ~/Desktop/invoice.pdf
gw gmail download <message_id> --attachment-id <id> --dir .
```
`gw gmail read --json` also lists attachment metadata, so one call is enough to find an ID.
Inline images (Content-ID parts) count as attachments and are marked `"inline": true`.

### JSON output
```bash
gw --json gmail list
gw --json gmail search "from:boss@example.com newer_than:7d"
gw --json gmail attachments <message_id>
```

---

## Calendar Commands

### View Events
```bash
gw calendar today                    # Today (primary calendar)
gw calendar today --all              # Today (all calendars) ← USE THIS
gw calendar tomorrow --all           # Tomorrow (all calendars)
gw calendar week --all               # This week (all calendars)
gw calendar agenda --all             # Upcoming agenda (all calendars)
gw calendar next --all               # Next event
gw calendar list --all               # List events
```

### Create / Update / Delete
```bash
# Create event (required: TITLE START END)
gw calendar create "Meeting" "2026-03-27T14:00:00" "2026-03-27T15:00:00"
gw calendar create "Meeting" "2026-03-27T14:00:00" "2026-03-27T15:00:00" \
  --description "Discuss roadmap" \
  --reminder 15 \
  --calendar "calendar_id"

# All-day event
gw calendar create "Birthday" "2026-03-27" "2026-03-28" --all-day

# Recurring event
gw calendar create "Weekly Sync" "2026-03-27T10:00:00" "2026-03-27T11:00:00" \
  --recurrence "RRULE:FREQ=WEEKLY;BYDAY=FR"

# Guests and location
gw calendar create "Review" "2026-09-15T14:00:00" "2026-09-15T15:00:00" \
  --attendees "ana@example.com" --attendees "bob@example.com" \
  --location "Lisbon office" \
  --send-updates all

gw calendar update <event_id>        # Update event
gw calendar update <event_id> --location "Room 2" --reminder 10
gw calendar update <event_id> --attendees "ana@example.com"  # REPLACES the guest list
gw calendar delete <event_id>        # Delete event
gw meet create                       # Create instant Meet link
gw meet create --title "Team Sync"   # Custom instant meeting title
```

`--attendees` is repeatable. On `update` it **replaces** the whole guest list, so
pass every guest you want to keep. Google only emails guests when you pass
`--send-updates all` (or `externalOnly`); the default is `none`, so nothing is sent.

### Scheduling, recurrence and moving

```bash
# When is each person busy? The scheduling primitive.
gw calendar freebusy ana@x.com bob@x.com --start 2026-09-10 --end 2026-09-11

# Let Google parse the phrase
gw calendar quick-add "Lunch with Ana tomorrow at 1pm"

# Move an event to another calendar; it keeps its ID
gw calendar move <event_id> <destination_calendar_id>

# Expand a recurring event into its real occurrences
gw calendar instances <event_id> --max 10
```

### Calendars themselves, and who can see them

```bash
gw calendar create-calendar "Projects" [--timezone Europe/Lisbon]
gw calendar delete-calendar <calendar_id>       # asks to confirm; deletes its events
gw calendar acl [--calendar <id>]               # who has access
gw calendar share ana@x.com --role reader       # reader|writer|owner|freeBusyReader
gw calendar unshare ana@x.com                   # asks to confirm
```

### JSON output
```bash
gw --json calendar today --all
gw --json calendar week --all
```

---

## Drive Commands

```bash
gw drive list                        # List recent files (10)
gw drive list --max 20               # List 20 files
gw drive search "query"              # Search Drive files
gw drive upload /path/to/file        # Upload file
gw drive upload /path/to/file --name "Custom Name"
gw drive upload /path/to/file --folder "folder_id"
gw drive download <file_id>          # Download file
gw drive mkdir "Projects"           # Create folder
gw drive share <file_id> user@example.com --role writer
gw drive unshare <file_id> user@example.com   # Remove that person's access
gw drive rename <file_id> "New name"          # Rename file or folder
gw drive delete <file_id>            # Move to trash (recoverable)
gw drive delete <file_id> --permanent         # Real delete; asks to confirm
gw drive delete <file_id> --permanent --yes   # Skip the confirmation
gw drive info <file_id>              # Show metadata
```

`delete` trashes by default because that is recoverable. `--permanent` cannot be
undone. `list`, `search`, `download` and `info` include files in shared drives.

### Copy, move, quota and shared drives

```bash
gw drive copy <file_id> [--name "Copy"] [--folder <folder_id>]
gw drive move <file_id> <folder_id>   # swaps the parent, no ghost second copy
gw drive about                        # storage quota
gw drive drives                       # shared drives you can reach
gw drive permissions <file_id>        # who currently has access
```

A Drive file can have several parents, so `move` reads the current ones and
removes them. Adding a parent without removing the old leaves the file in both
folders — that is why there is a `move` command and not just a flag.

### Version history and comments

```bash
gw drive revisions <file_id>                       # version history
gw drive revision-delete <file_id> <revision_id>   # asks to confirm

gw drive comments <file_id> [--include-resolved]
gw drive comment <file_id> "text"
gw drive comment-reply <file_id> <comment_id> "text"
gw drive comment-resolve <file_id> <comment_id>
```

### JSON output
```bash
gw --json drive list
gw --json drive search "report 2026"
```

---

## Sheets Commands

```bash
gw sheets read <spreadsheet_id> <range>     # Read cells
gw sheets read "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms" "Sheet1!A1:D20"

gw sheets write <spreadsheet_id> <range> <value>   # Write ONE cell
gw sheets write "spreadsheet_id" "Sheet1!A1" "Hello"
```

> `write` sets a **single cell** — the VALUE is written literally. Earlier versions
> of this file showed `'[["Hello", "World"]]'`, which would put that JSON text into
> A1 as a string. To write rows, use `append`.

### Rows, tabs and new spreadsheets

```bash
# append: JSON list = one row, list of lists = several, plain text = one cell
gw sheets append <id> "Sheet1!A:C" '["ana", 10, "pago"]'
gw sheets append <id> "Sheet1!A:B" '[["a", 1], ["b", 2]]'

gw sheets clear <id> "Sheet1!A2:C99"     # clears values, keeps formatting
gw sheets create "Budget" [--sheet Jan --sheet Feb]
gw sheets info <id>                      # tab names, sheet IDs, dimensions
gw sheets add-tab <id> "March"
gw sheets delete-tab <id> "March"        # asks to confirm
```

### JSON output
```bash
gw --json sheets read "spreadsheet_id" "Sheet1!A1:C10"
```

---

## Docs Commands

```bash
gw docs list                         # List recent Docs
gw docs read <document_id>           # Read document content
gw docs export <document_id>         # Export document (PDF, DOCX, etc.)
```

### JSON output
```bash
gw --json docs list
gw --json docs read <document_id>
```

---

## Contacts Commands

```bash
gw contacts list                     # List all contacts
gw contacts search "query"           # Search contacts by name/email
```

### JSON output
```bash
gw --json contacts search "Victor"
```

---

## Tasks Commands

```bash
gw tasks lists                       # List task lists
gw tasks list                        # List tasks from the default list
gw tasks list --list <list_id>       # List tasks from a specific list
gw tasks add "Buy milk"              # Create a task
gw tasks add "Buy milk" --notes "2L" --due 2026-04-01
gw tasks complete <task_id>          # Mark task complete
gw tasks delete <task_id>            # Delete task
```

### JSON output
```bash
gw --json tasks list
gw --json tasks add "Prepare review" --due 2026-04-02
```

---

## Diagnostics & Config

```bash
gw doctor                            # Check auth, config AND every Google API
gw config show                       # Show current config.toml contents
gw --version                         # Show installed version
```

`gw doctor` makes one real call per API, so it catches an API that is switched off
in the Google Cloud project — a failure that otherwise only shows up as a 403 the
first time you use that service. It names the API and prints the console URL to
enable it.

---

## Multi-Account (Profiles)

Define profiles in `~/.config/gw/config.toml`:

```toml
[profiles.work]
credentials_file = "~/.config/gw/work-credentials.json"

[profiles.personal]
credentials_file = "~/.config/gw/personal-credentials.json"
```

Use:
```bash
gw --profile work calendar today --all
gw --profile personal gmail list
```

---

## Agent Rules

1. **Calendar:** Always use `--all` unless the user explicitly asks for primary only
2. **Gmail send:** Show the draft (to/subject/body/attachments), get confirmation,
   then execute. To attach files use `gw gmail send|reply|forward|draft
   --attachment PATH` (repeatable) — never call the Gmail API by hand
3. **JSON:** Use `--json` when output needs to be parsed programmatically
4. **Auth:** The token **does** expire and is refreshed automatically by the refresh
   token. If the refresh fails, gw returns `Authentication refresh failed` /
   `Authentication expired` → run `gw auth login` (or `gw auth login --headless`).
   Diagnose with `gw auth status` / `gw doctor`
5. **Timezone:** Comes from `config.toml` (`gw config show`); when unset it is
   auto-detected from the system. Do not assume a fixed zone in event datetimes
6. **Secrets:** If gw needs Keychain secrets, use `kc run -- gw <cmd>`
   (process-scoped, not `eval "$(kc env)"`)

