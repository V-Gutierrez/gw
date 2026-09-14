# Changelog

## v0.8.3 (2026-09-14)

### Added
- **`gw auth login` deixou de ser interactivo por construção.** `--headless` imprimia o URL e
  ficava à espera de um prompt para o código; se esse prompt morresse (terminal fechado,
  processo em background, sessão de agente expirada) a autorização já dada no browser ficava
  impossível de trocar. Agora:
  - `gw auth login --headless --url-only` imprime o URL e sai
  - `gw auth login --headless --code '<redirect URL ou código>'` faz a troca, sem prompt

  As duas metades podem acontecer em sítios diferentes — ou num chat. Foi exactamente o que
  faltou hoje, duas vezes, ao conceder o scope `gmail.settings.basic` a três perfis.

## v0.8.2 (2026-09-14)

### Fixed
- **Adding a scope to the defaults broke every token that had to refresh.** `load_credentials`
  loaded the token *with* the scopes gw asks for, and google-auth sends that list when it
  refreshes — so a token granted before `gmail.settings.basic` existed got
  `invalid_scope` on refresh, `load_credentials` turned that into `None`, and every command
  answered "Not authenticated". Reproduced live on the personal profile minutes after 0.8.1:
  the only way back was a fresh login, per profile. The loader now hands google-auth the
  token path and nothing else — the scopes recorded in the token file are the only honest
  set, and the parameter stays only for caller compatibility.
- Covered by two tests that would have caught it: the loader never forwards requested
  scopes, and a token whose scopes predate the defaults still refreshes.

## v0.8.1 (2026-09-14)

### Fixed
- **`gw auth login` granted nothing when a scope had been added to the defaults.** The
  command printed "Authenticated" and returned the same token, so the
  `gmail.settings.basic` scope from 0.8.0 could never actually be granted and
  `gw gmail signature --set` stayed at a 403. Cause: the login short-circuit read the
  scopes off a loaded `Credentials` object, which carries the scopes gw *asks* for rather
  than the ones consented to. `granted_scopes()` now reads the token file — the honest
  source — and `login` only reuses a token that really covers what it asks for,
  re-consenting (and naming the new scopes) when it does not. Upgrading 0.8.0 → 0.8.1 and
  running `gw auth login` once per profile is what actually grants the scope.

## v0.8.0 (2026-09-14)

The signature you configured in Gmail now goes out with your mail.

### Gmail — account signature
- `send`, `draft`, `reply`, `forward` and `draft-edit` attach the signature configured
  for the account in Gmail (Settings → General → Signature). Gmail's signature is a
  *compose-time* setting: the web UI appends it, the API does not, and gw builds the raw
  MIME itself — so until now every message left bare, no matter what Gmail said
- Read from `users.settings.sendAs` — the default identity, or `signature_address` when
  the account has aliases — and cached for a week at
  `~/.config/gw/signature-<profile>.json`. When the API is unreachable the stale cache is
  used: a missing signature never costs you the message
- Message shape: with a signature the body becomes `multipart/alternative` (the
  signature's own HTML, plus a plain-text rendering of it for text-only clients), nested
  inside `multipart/mixed` when there are attachments. An account with no signature
  configured still sends the bare `text/plain` part, byte for byte what 0.7.0 sent
- `--signature / --no-signature` on every sending command overrides the config per
  message; `signature = false` turns signatures off for a whole profile
- `draft-edit` re-applies the signature instead of accumulating it: what gw appended
  last time is dropped before the rebuild
- New `gw gmail signature [--refresh] [--json]` reports what would be attached,
  without sending anything
- `gw gmail signature --set FILE` writes the signature **into Gmail** — creating it or
  replacing what is there — and `--set -` reads it from stdin, so a script or an agent
  can pipe it. `--edit` opens the current signature in `$EDITOR` and writes the result
  back (an account with none opens an empty buffer, so creating and editing are the same
  command), and `--clear` removes it. Gmail stays the single source; the local cache is
  refreshed at write time, and saving an untouched buffer writes nothing. Writing needs
  the `gmail.settings.basic` scope, new in `DEFAULT_SCOPES` — additive, so existing
  tokens keep sending and only need one `gw auth login` before the first write
- The MIME is built the same way in the MCP server, so drafts created from an agent
  carry the same signature

Verified live on 2026-09-14 against both configured identities: `victor@controlspacestorage.com`
(2058-char HTML signature, attached) and `ainiciative@gmail.com` (no signature configured —
output unchanged).

## v0.7.0 (2026-09-09)

Coverage release: 57 commands to 98. Gmail, Calendar, Drive and Sheets now cover
the API surface a personal CLI actually needs.

### Gmail — drafts became editable
- `gw gmail drafts` lists drafts with their draft IDs. Until now `gw gmail draft`
  returned an ID and the draft was unreachable from the CLI forever
- `gw gmail draft-read`, `draft-edit`, `draft-send`, `draft-delete`
- `draft-edit` changes only the fields you pass. `drafts.update` is a full PUT, so
  gw reads the draft back, applies your changes and re-sends the rest untouched.
  `--attachment` replaces the whole attachment set (same rule as `--attendees` on
  `calendar update`), omitting it keeps the existing files, `--clear-attachments`
  drops them. Verified against the live API: attachment bytes survive an edit
  unchanged, and the draft ID is stable across updates while the message ID is not

### Gmail — threads, bulk and introspection
- `thread-trash`, `thread-untrash`, `thread-archive`, `thread-label` act on a whole
  conversation instead of one message at a time
- `gw gmail bulk --query "..."` applies one change to every match in a single
  `batchModify` call rather than one request per message
- `gw gmail untrash` restores a message
- `gw gmail profile` and `gw gmail history --since <id>`

### Calendar
- `gw calendar freebusy EMAIL...` — when is each person busy in a window
- `gw calendar quick-add "lunch with Ana tomorrow 1pm"` — Google parses the phrase
- `gw calendar move EVENT_ID DESTINATION` — move an event between calendars
- `gw calendar instances EVENT_ID` — expand a recurring event into its occurrences
- `gw calendar create-calendar` / `delete-calendar`
- `gw calendar acl` / `share` / `unshare` — see and change who can read a calendar

### Drive
- `gw drive copy` and `gw drive move`. A Drive file can have several parents, so
  `move` reads the current ones and swaps them instead of adding a second, which
  would leave the file visible in two folders
- `gw drive about` — storage quota
- `gw drive revisions` / `revision-delete` — version history
- `gw drive comments` / `comment` / `comment-reply` / `comment-resolve`
- `gw drive permissions` — who has access. gw could share and unshare but never show
- `gw drive drives` — shared drives

### Sheets
- `gw sheets append` — add rows. VALUES is a JSON list for one row, a list of lists
  for several, or plain text for a single cell
- `gw sheets clear`, `create`, `info`, `add-tab`, `delete-tab`

### Fixes
- `gw doctor` now makes one real call per Google API. This immediately found that
  the **Sheets and Tasks APIs were never enabled in the Cloud project**, so
  `gw sheets read/write` and every `gw tasks` command have always failed silently.
  A disabled API is now reported by name with the console URL that fixes it
- `gw gmail drafts` originally passed `metadataHeaders` to `drafts.get`, which that
  endpoint rejects even though `messages.get` accepts it. Caught only by calling
  the real API — the mock accepted it happily

### Notes
- No existing flag changed meaning
- Attachments are still not exposed through the MCP server
- Docs write and Contacts write remain impossible without a re-auth: the token
  requests `documents.readonly` and `contacts.readonly`

### Roadmap
- Gmail attachments through the MCP server
- `gw tasks update` / `uncomplete`, `gw contacts create` / `delete`, Docs write —
  the last two need a widened OAuth scope, so they force a re-auth
- Gmail settings (filters, vacation, send-as) need `gmail.settings.basic`
- Permanent Gmail delete needs the restricted `https://mail.google.com/` scope

## v0.6.0 (2026-09-09)

### Features
- `gw gmail send`, `draft`, `reply` and `forward` now take `--attachment PATH` (repeatable). Files go out as raw binary with the MIME type resolved from the filename, so a signed PDF arrives intact instead of needing a hand-written Gmail API call
- All four commands also take `--body-file PATH`, so an agent-generated body no longer has to survive shell escaping. `--body-file` and the positional `BODY` are mutually exclusive
- `gw gmail reply` and `gw gmail forward` now take `--cc` and `--bcc`. Reply still keeps `In-Reply-To`, `References` and the original `threadId`
- `gw gmail search` now takes `--after` (`6h`, `24h`, `7d`), matching `gw gmail list`
- Added `gw drive delete <file_id>` (trashes by default, `--permanent` with a confirmation for a real delete), `gw drive rename <file_id> NAME` and `gw drive unshare <file_id> EMAIL`
- `gw calendar create` and `gw calendar update` now take `--attendees` (repeatable) and `--location`; `update` also takes `--reminder`. Google only emails guests when you pass `--send-updates`, so the default stays silent
- `gw drive list/search/download/info` now see files in shared drives

### Fixes
- A non-ASCII attachment filename is sent as RFC 2231 `filename*=UTF-8''…` instead of being mangled
- `datetime.fromisoformat` is now given the API's `Z` timestamps directly, dropping three hand-rolled `Z` → `+00:00` rewrites that Python 3.11 made redundant

### Notes
- A message without attachments is still a single `text/plain` part, byte for byte what gw sent before 0.6.0. No existing flag changed meaning
- Attachments are **not** exposed through the MCP server yet — the MCP tools stay read-only for attachments (`gmail_attachments`, `gmail_download_attachments`)
- The lint gate now pins `ruff>=0.16.3,<0.17`. The repo previously pinned `ruff>=0.4` and selected no rules, so the enforced rule set silently grew to 413 rules with the installed ruff

### Roadmap (v0.7.0+)
- Gmail attachments exposed through the MCP server
- `gw sheets append` for appending rows
- `gw tasks update` (title/notes/due) and `gw tasks uncomplete`
- `gw contacts create` / `gw contacts delete`
- Docs write support (create/edit via `documents.batchUpdate`)
- Per-event explicit timezone on `gw calendar create`
- Cell formatting for Sheets
- Multi-profile reporting in `gw doctor`

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
