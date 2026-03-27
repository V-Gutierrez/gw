---
name: gw
description: >
  Access Google Workspace via gw CLI (Gmail, Calendar, Drive, Sheets, Docs, Contacts).
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
gw auth logout          # Revoke and remove stored token
gw auth status          # Show current auth status / which account
gw auth setup           # Interactive setup wizard (config.toml)
```

---

## Gmail Commands

### List / Read
```bash
gw gmail list                        # 10 most recent emails
gw gmail list --max 20               # 20 most recent
gw gmail read <message_id>           # Read full email body
gw gmail thread <thread_id>          # Show full thread
gw gmail search "query"              # Search emails (Gmail query syntax)
gw gmail count                       # Count unread messages
```

### Send / Reply / Forward
```bash
gw gmail send TO SUBJECT BODY        # Send email
gw gmail send "to@example.com" "Subject" "Body text"
gw gmail send "to@example.com" "Subject" "Body" --cc "cc@example.com"
gw gmail send "to@example.com" "Subject" "Body" --bcc "bcc@example.com"

gw gmail reply <message_id> "Reply body"
gw gmail forward <message_id> "to@example.com"
```

### Manage
```bash
gw gmail mark-read <message_id>      # Mark as read
gw gmail mark-unread <message_id>    # Mark as unread
gw gmail archive <message_id>        # Archive email
gw gmail trash <message_id>          # Move to trash
gw gmail label <message_id> LABEL    # Apply label
gw gmail star <message_id>           # Star a message
```

### JSON output
```bash
gw --json gmail list
gw --json gmail search "from:boss@example.com newer_than:7d"
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

gw calendar update <event_id>        # Update event
gw calendar delete <event_id>        # Delete event
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

gw sheets write <spreadsheet_id> <range> <values>  # Write cells
gw sheets write "spreadsheet_id" "Sheet1!A1" '[["Hello", "World"]]'
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

## Diagnostics & Config

```bash
gw doctor                            # Check auth, API access, config
gw config show                       # Show current config.toml contents
gw --version                         # Show installed version
```

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

1. **Calendar:** Always use `--all` unless user explicitly asks for primary only
2. **Gmail send:** Show draft (to/subject/body), get confirmation, then execute
3. **JSON:** Use `--json` when output needs to be parsed/processed programmatically
4. **Auth:** Token never expires — no troubleshooting needed
5. **Timezone:** Uses `America/Sao_Paulo` automatically

## Victor's Calendars

| Calendar | Type |
|----------|------|
| Eu (Primary) | Personal |
| Leroy Merlin | Work |
| Família | Family events |
| Health & Meds | Medications/vitamins |
| VC ENG | VC Engineering projects |
| Social Media | Content calendar |
| Mentoria | Mentorship sessions |
| Feriados no Brasil | Brazilian holidays |
