from __future__ import annotations

import base64
import mimetypes
from collections.abc import Callable, Sequence
from email import encoders, message_from_bytes
from email.message import Message
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, print_success, use_json_output
from gw.signature import (
    AccountSignature,
    append_signature,
    cached_signature,
    resolve_signature,
    set_account_signature,
    signature_enabled,
    strip_signature,
)
from gw.utils import (
    atomic_write,
    clean_message_body,
    decode_base64url_bytes,
    extract_attachments,
    extract_message_body,
    header_map,
    parse_after_flag,
    safe_attachment_filename,
)


def _gmail_service(config: GWConfig | None = None):
    return build_service("gmail", "v1", config=config)


def _signature_option(function: Callable[..., Any]) -> Callable[..., Any]:
    """Attach the configured account signature unless told otherwise."""
    return click.option(
        "--signature/--no-signature",
        "signature",
        default=None,
        help="Attach the account signature. Defaults to the signature config setting.",
    )(function)


def _render_signature(config: GWConfig | None, override: bool | None) -> None:
    """Name the signature that went out — cache only, so it costs no extra call.

    Gmail's settings page can tell you a signature exists; it cannot tell you whether
    the message you just sent carried it. This line closes that loop.
    """
    if config is None or not signature_enabled(config, override):
        return
    signature = cached_signature(config)
    if signature is not None and signature.email:
        print_human(f"Signature: {signature.email}", emoji="✍️")


def _message_headers(message: dict[str, Any]) -> dict[str, str]:
    payload = message.get("payload", {})
    return header_map(payload.get("headers"))


def _encode_message(message: Message) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def _resolve_body(body: str | None, body_file: str | None) -> str:
    """Pick the message body from the positional argument or from a file, never both."""
    if body_file is not None and body is not None:
        raise click.ClickException("Pass either the BODY argument or --body-file, not both.")
    if body_file is not None:
        path = Path(body_file).expanduser()
        if not path.is_file():
            raise click.ClickException(f"Body file not found: {path}")
        return path.read_text(encoding="utf-8")
    if body is None:
        raise click.ClickException("Provide a BODY argument or --body-file PATH.")
    return body


def _attachment_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise click.ClickException(f"Attachment not found: {path}")
    return path


def _attachment_part(path: Path) -> MIMEBase:
    """Wrap a file as a base64 MIME part, keeping the bytes untouched."""
    guessed, _ = mimetypes.guess_type(path.name)
    maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
    part = MIMEBase(maintype, subtype or "octet-stream")
    part.set_payload(path.read_bytes())
    encoders.encode_base64(part)

    filename = safe_attachment_filename(path.name, "attachment")
    try:
        filename.encode("ascii")
    except UnicodeEncodeError:
        # RFC 2231 continuation, so non-ASCII names survive the header encoding.
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
    else:
        part.add_header("Content-Disposition", "attachment", filename=filename)
    return part


def _body_container(body: str, signature: AccountSignature | None) -> Message:
    """The body as a MIME part: plain text, or text+html once a signature exists.

    Without a signature the result is the bare ``MIMEText(body)`` gw has always sent,
    so an account with nothing configured in Gmail sees no change at all.
    """
    if signature is None:
        return MIMEText(body)

    plain, html_body = append_signature(body, signature)
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain, "plain", "utf-8"))
    alternative.attach(MIMEText(html_body, "html", "utf-8"))
    return alternative


def _build_mime_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    *,
    reply_headers: dict[str, str] | None = None,
    extra_parts: Sequence[Message] | None = None,
    signature: AccountSignature | None = None,
) -> tuple[Message, list[str]]:
    """Build the outgoing message, returning it with the attached filenames.

    Without attachments this stays a single ``text/plain`` part, byte for byte what
    gw sent before 0.6.0. With attachments it becomes ``multipart/mixed``. An account
    signature turns the body into ``multipart/alternative``, nested inside the mixed
    container when there are files to carry.

    ``extra_parts`` carries MIME parts that already exist — the attachments kept
    from a draft being edited, which never touch the filesystem.
    """
    paths = [_attachment_path(item) for item in attachments or []]
    kept = list(extra_parts or [])

    message: Message
    container = _body_container(body, signature)
    if paths or kept:
        message = MIMEMultipart("mixed")
        message.attach(container)
        for path in paths:
            message.attach(_attachment_part(path))
        for part in kept:
            message.attach(part)
    else:
        message = container

    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    for header, value in (reply_headers or {}).items():
        message[header] = value

    return message, [path.name for path in paths] + [
        part.get_filename() or "attachment" for part in kept
    ]


def _render_list(messages: list[dict[str, Any]]) -> None:
    if not messages:
        print_human("No messages found.", emoji="📧")
        return
    print_human(f"Emails ({len(messages)}):", emoji="📧")
    for message in messages:
        unread = " [UNREAD]" if message["unread"] else ""
        print_human(f"  • {message['date']}{unread}")
        print_human(f"    ID: {message['id']}")
        print_human(f"    From: {message['from']}")
        print_human(f"    Subject: {message['subject']}")
        print_human(f"    Preview: {message['snippet']}")


def _render_thread(thread: dict[str, Any]) -> None:
    messages = thread.get("messages", [])
    if not messages:
        print_human("Thread is empty.", emoji="📧")
        return

    print_human(
        f"Thread {thread['thread_id']} ({thread['message_count']} messages):",
        emoji="📧",
    )
    for message in messages:
        print_human(f"  • {message['date']}")
        print_human(f"    ID: {message['id']}")
        print_human(f"    From: {message['from']}")
        print_human(f"    Subject: {message['subject']}")
        print_human(f"    Body: {message['body']}")


def _render_attachments(data: dict[str, Any]) -> None:
    attachments = data.get("attachments", [])
    if not attachments:
        print_human(f"No attachments in message {data['message_id']}.", emoji="📎")
        return

    print_human(f"Attachments ({len(attachments)}) — {data.get('subject', '')}:", emoji="📎")
    for attachment in attachments:
        kind = "inline" if attachment["inline"] else "attachment"
        print_human(f"  • {attachment['filename']} ({attachment['mime_type']}, {kind})")
        print_human(f"    Size: {attachment['size']} bytes")
        print_human(f"    ID: {attachment['attachment_id'] or '(inline body data)'}")


def _render_sent_attachments(data: dict[str, Any]) -> None:
    filenames = data.get("attachments") or []
    if filenames:
        print_human(f"Attached {len(filenames)} file(s): {', '.join(filenames)}")


def _modify_gmail_labels(
    message_id: str,
    *,
    add_labels: list[str],
    remove_labels: list[str],
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    return execute_google_request(
        service.users()
        .messages()
        .modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": add_labels, "removeLabelIds": remove_labels},
        )
    )


def send_gmail_message(
    to: str,
    subject: str,
    body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    body_file: str | None = None,
    signature: bool | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    account_signature = resolve_signature(config, service=service, override=signature)
    message, filenames = _build_mime_message(
        to=to,
        subject=subject,
        body=_resolve_body(body, body_file),
        cc=cc,
        bcc=bcc,
        attachments=attachments,
        signature=account_signature,
    )

    sent = execute_google_request(
        service.users().messages().send(userId="me", body={"raw": _encode_message(message)})
    )
    return {
        "id": sent.get("id"),
        "to": to,
        "subject": subject,
        "attachments": filenames,
    }


def get_account_signature(
    config: GWConfig | None = None,
    *,
    refresh: bool = False,
) -> AccountSignature | None:
    """What this profile would attach to the next message, without sending one."""
    return resolve_signature(config, override=True, refresh=refresh)


def create_gmail_draft(
    to: str,
    subject: str,
    body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    body_file: str | None = None,
    signature: bool | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    account_signature = resolve_signature(config, service=service, override=signature)
    message, filenames = _build_mime_message(
        to=to,
        subject=subject,
        body=_resolve_body(body, body_file),
        cc=cc,
        bcc=bcc,
        attachments=attachments,
        signature=account_signature,
    )

    draft = execute_google_request(
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": _encode_message(message)}})
    )
    return {
        "id": draft.get("id"),
        "message_id": draft.get("message", {}).get("id"),
        "to": to,
        "subject": subject,
        "attachments": filenames,
    }


def _draft_parts(parsed: Message) -> tuple[str, list[Message]]:
    """Split a parsed draft into its text body and its attachment parts."""
    if not parsed.is_multipart():
        payload = parsed.get_payload(decode=True)
        if payload is None:
            return str(parsed.get_payload()), []
        charset = parsed.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace"), []

    body = ""
    attachments: list[Message] = []
    for part in parsed.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename() or part.get_content_disposition() == "attachment":
            attachments.append(part)
        elif not body and part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace") if payload else ""
    return body, attachments


def _fetch_draft(service: Any, draft_id: str) -> Message:
    draft = execute_google_request(
        service.users().drafts().get(userId="me", id=draft_id, format="raw")
    )
    raw = draft.get("message", {}).get("raw")
    if not raw:
        raise click.ClickException(f"Draft {draft_id!r} has no readable content.")
    return message_from_bytes(decode_base64url_bytes(raw))


def list_gmail_drafts(
    max_results: int = 10,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _gmail_service(config)
    response = execute_google_request(
        service.users().drafts().list(userId="me", maxResults=max_results)
    )
    drafts: list[dict[str, Any]] = []
    for stub in response.get("drafts", []):
        detail = execute_google_request(
            service.users()
            .drafts()
            # drafts.get takes no metadataHeaders — unlike messages.get, passing it
            # is rejected by the API with "unexpected keyword argument".
            .get(userId="me", id=stub["id"], format="metadata")
        )
        message = detail.get("message", {})
        headers = _message_headers(message)
        drafts.append(
            {
                "id": detail.get("id", stub["id"]),
                "message_id": message.get("id"),
                "thread_id": message.get("threadId"),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", ""),
                "snippet": message.get("snippet", ""),
            }
        )
    return drafts


def get_gmail_draft(draft_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    parsed = _fetch_draft(_gmail_service(config), draft_id)
    body, parts = _draft_parts(parsed)
    return {
        "id": draft_id,
        "to": parsed.get("To", ""),
        "cc": parsed.get("Cc", ""),
        "bcc": parsed.get("Bcc", ""),
        "subject": parsed.get("Subject", ""),
        "body": body,
        "attachments": [
            {
                "filename": part.get_filename() or "attachment",
                "mime_type": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b""),
            }
            for part in parts
        ],
    }


def update_gmail_draft(
    draft_id: str,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    body_file: str | None = None,
    clear_attachments: bool = False,
    signature: bool | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Edit a draft in place.

    ``drafts.update`` is a full PUT: Gmail replaces the whole message. So gw reads
    the draft back, applies only the fields you passed, and re-sends the rest
    untouched — the same "only what you pass changes" rule as ``gw calendar update``.

    Attachments follow the ``--attendees`` convention: passing ``attachments`` makes
    them the complete new set, passing nothing keeps what is there, and
    ``clear_attachments`` removes them all.

    The account signature is re-applied, not accumulated: a signature gw already
    appended to this draft is dropped before the rebuild.
    """
    service = _gmail_service(config)
    parsed = _fetch_draft(service, draft_id)
    current_body, current_parts = _draft_parts(parsed)

    new_body = current_body
    if body is not None or body_file is not None:
        new_body = _resolve_body(body, body_file)
    new_body = strip_signature(new_body, cached_signature(config) if config else None)
    account_signature = resolve_signature(config, service=service, override=signature)

    kept: list[Message] = []
    if not clear_attachments and not attachments:
        kept = current_parts

    message, filenames = _build_mime_message(
        to=to if to is not None else parsed.get("To", ""),
        subject=subject if subject is not None else parsed.get("Subject", ""),
        body=new_body,
        cc=cc if cc is not None else parsed.get("Cc"),
        bcc=bcc if bcc is not None else parsed.get("Bcc"),
        attachments=attachments,
        extra_parts=kept,
        signature=account_signature,
    )

    updated = execute_google_request(
        service.users()
        .drafts()
        .update(userId="me", id=draft_id, body={"message": {"raw": _encode_message(message)}})
    )
    return {
        # The draft id survives an update; the message id does not, so never key on it.
        "id": updated.get("id", draft_id),
        "message_id": updated.get("message", {}).get("id"),
        "to": message.get("To", ""),
        "subject": message.get("Subject", ""),
        "attachments": filenames,
    }


def send_gmail_draft(draft_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    sent = execute_google_request(
        service.users().drafts().send(userId="me", body={"id": draft_id})
    )
    return {"id": sent.get("id"), "thread_id": sent.get("threadId"), "draft_id": draft_id}


def delete_gmail_draft(draft_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    execute_google_request(service.users().drafts().delete(userId="me", id=draft_id))
    return {"id": draft_id, "deleted": True}


def reply_to_gmail_message(
    message_id: str,
    body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    body_file: str | None = None,
    signature: bool | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    resolved_body = _resolve_body(body, body_file)
    service = _gmail_service(config)
    account_signature = resolve_signature(config, service=service, override=signature)
    original = execute_google_request(
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["Message-ID", "Subject", "From", "To", "References"],
        )
    )
    headers = _message_headers(original)
    subject = headers.get("subject", "")
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    reply_headers: dict[str, str] = {}
    if headers.get("message-id"):
        reply_headers["In-Reply-To"] = headers["message-id"]
        reply_headers["References"] = headers.get("references", headers["message-id"])

    message, filenames = _build_mime_message(
        to=headers.get("from", ""),
        subject=reply_subject,
        body=resolved_body,
        cc=cc,
        bcc=bcc,
        attachments=attachments,
        reply_headers=reply_headers,
        signature=account_signature,
    )

    sent = execute_google_request(
        service.users()
        .messages()
        .send(
            userId="me",
            body={"raw": _encode_message(message), "threadId": original.get("threadId")},
        )
    )
    return {
        "id": sent.get("id"),
        "thread_id": original.get("threadId"),
        "attachments": filenames,
    }


def forward_gmail_message(
    message_id: str,
    to: str,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    signature: bool | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    account_signature = resolve_signature(config, service=service, override=signature)
    original = execute_google_request(
        service.users().messages().get(userId="me", id=message_id, format="full")
    )
    headers = _message_headers(original)
    body = clean_message_body(extract_message_body(original.get("payload")))
    forwarded_body = (
        "---------- Forwarded message ----------\n"
        f"From: {headers.get('from', '')}\n"
        f"Date: {headers.get('date', '')}\n"
        f"Subject: {headers.get('subject', '')}\n"
        f"To: {headers.get('to', '')}\n\n"
        f"{body}"
    )
    message, filenames = _build_mime_message(
        to=to,
        subject=f"Fwd: {headers.get('subject', '')}",
        body=forwarded_body,
        cc=cc,
        bcc=bcc,
        attachments=attachments,
        signature=account_signature,
    )
    sent = execute_google_request(
        service.users().messages().send(userId="me", body={"raw": _encode_message(message)})
    )
    return {"id": sent.get("id"), "to": to, "attachments": filenames}


def list_gmail_messages(
    max_results: int = 10,
    query: str | None = None,
    unread: bool = False,
    after: str | None = None,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _gmail_service(config)
    parts = []
    if query:
        parts.append(query)
    if after:
        parts.append(parse_after_flag(after))
    if unread:
        parts.append("is:unread")
    final_query = " ".join(parts) or None

    response = execute_google_request(
        service.users().messages().list(userId="me", maxResults=max_results, q=final_query)
    )
    messages: list[dict[str, Any]] = []
    for item in response.get("messages", []):
        message = execute_google_request(
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            )
        )
        headers = _message_headers(message)
        messages.append(
            {
                "id": message.get("id"),
                "thread_id": message.get("threadId"),
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "snippet": message.get("snippet", ""),
                "unread": "UNREAD" in message.get("labelIds", []),
            }
        )
    return messages


def read_gmail_messages(
    message_id: str | None = None,
    query: str | None = None,
    max_results: int = 1,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    if not message_id and not query:
        raise click.ClickException("Provide a message ID or use --query.")

    service = _gmail_service(config)
    ids: list[str]
    if message_id:
        ids = [message_id]
    else:
        response = execute_google_request(
            service.users().messages().list(userId="me", maxResults=max_results, q=query)
        )
        ids = [item["id"] for item in response.get("messages", [])]

    messages: list[dict[str, Any]] = []
    for selected_id in ids:
        message = execute_google_request(
            service.users().messages().get(userId="me", id=selected_id, format="full")
        )
        headers = _message_headers(message)
        body = clean_message_body(extract_message_body(message.get("payload")))
        messages.append(
            {
                "id": selected_id,
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "body": body or "(No plain text body — HTML only email)",
                "attachments": extract_attachments(message.get("payload")),
            }
        )
    return messages


def list_gmail_attachments(message_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    message = execute_google_request(
        service.users().messages().get(userId="me", id=message_id, format="full")
    )
    headers = _message_headers(message)
    attachments = extract_attachments(message.get("payload"))
    return {
        "message_id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "date": headers.get("date", ""),
        "count": len(attachments),
        "attachments": attachments,
    }


def _fetch_attachment_bytes(service: Any, message_id: str, attachment: dict[str, Any]) -> bytes:
    attachment_id = attachment.get("attachment_id")
    if attachment_id:
        payload = execute_google_request(
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
        )
        data = payload.get("data")
    else:
        data = attachment.get("data")

    if not data:
        raise click.ClickException(
            f"Attachment {attachment['filename']!r} carries no downloadable data."
        )
    return decode_base64url_bytes(data)


def _unique_filename(name: str, used: set[str]) -> str:
    candidate = Path(name)
    stem, suffix = candidate.stem, candidate.suffix
    unique = name
    counter = 2
    while unique in used:
        unique = f"{stem}-{counter}{suffix}"
        counter += 1
    used.add(unique)
    return unique


def _select_attachments(
    attachments: list[dict[str, Any]],
    message_id: str,
    attachment_id: str | None,
    filename: str | None,
) -> list[dict[str, Any]]:
    selected = attachments
    if attachment_id:
        selected = [item for item in selected if item["attachment_id"] == attachment_id]
        if not selected:
            raise click.ClickException(
                f"No attachment with ID {attachment_id!r} in message {message_id!r}."
            )
    if filename:
        matches = [item for item in selected if item["filename"] == filename]
        if not matches:
            lowered = filename.lower()
            matches = [item for item in selected if item["filename"].lower() == lowered]
        if not matches:
            raise click.ClickException(
                f"No attachment named {filename!r} in message {message_id!r}."
            )
        selected = matches
    return selected


def download_gmail_attachments(
    message_id: str,
    attachment_id: str | None = None,
    filename: str | None = None,
    output_path: str | None = None,
    directory: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    message = execute_google_request(
        service.users().messages().get(userId="me", id=message_id, format="full")
    )
    attachments = extract_attachments(message.get("payload"), include_data=True)
    if not attachments:
        raise click.ClickException(f"Message {message_id!r} has no attachments.")

    selected = _select_attachments(attachments, message_id, attachment_id, filename)
    if output_path and len(selected) > 1:
        raise click.ClickException(
            f"--output expects a single attachment but {len(selected)} matched. "
            "Narrow it with --attachment-id or --filename, or use --dir."
        )

    base_dir = Path(directory).expanduser() if directory else Path.cwd()
    used: set[str] = set()
    downloaded: list[dict[str, Any]] = []
    for index, attachment in enumerate(selected, start=1):
        data = _fetch_attachment_bytes(service, message_id, attachment)
        if output_path:
            target = Path(output_path).expanduser()
        else:
            safe_name = safe_attachment_filename(attachment["filename"], f"attachment-{index}.bin")
            target = base_dir / _unique_filename(safe_name, used)
        atomic_write(target, data)
        downloaded.append(
            {
                "attachment_id": attachment["attachment_id"],
                "filename": attachment["filename"],
                "mime_type": attachment["mime_type"],
                "inline": attachment["inline"],
                "path": str(target),
                "size": len(data),
            }
        )

    return {
        "message_id": message.get("id", message_id),
        "count": len(downloaded),
        "attachments": downloaded,
    }


def search_gmail_messages(
    query: str,
    max_results: int = 10,
    after: str | None = None,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    return list_gmail_messages(max_results=max_results, query=query, after=after, config=config)


def _resolve_label_ids(service: Any, names: Sequence[str] | None) -> list[str]:
    """Turn label names into ids, letting Gmail's built-in ids through untouched."""
    resolved: list[str] = []
    for name in names or []:
        if name.isupper() and " " not in name:
            resolved.append(name)  # INBOX, UNREAD, STARRED, TRASH…
        else:
            resolved.append(_resolve_label_id(service, name))
    return resolved


def modify_gmail_thread(
    thread_id: str,
    add_labels: Sequence[str] | None = None,
    remove_labels: Sequence[str] | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    thread = execute_google_request(
        service.users()
        .threads()
        .modify(
            userId="me",
            id=thread_id,
            body={
                "addLabelIds": _resolve_label_ids(service, add_labels),
                "removeLabelIds": _resolve_label_ids(service, remove_labels),
            },
        )
    )
    return {
        "thread_id": thread.get("id", thread_id),
        "message_count": len(thread.get("messages", [])),
    }


def trash_gmail_thread(thread_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    thread = execute_google_request(service.users().threads().trash(userId="me", id=thread_id))
    return {"thread_id": thread.get("id", thread_id), "trashed": True}


def untrash_gmail_thread(thread_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    thread = execute_google_request(service.users().threads().untrash(userId="me", id=thread_id))
    return {"thread_id": thread.get("id", thread_id), "trashed": False}


def untrash_gmail_message(message_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    message = execute_google_request(
        service.users().messages().untrash(userId="me", id=message_id)
    )
    return {"id": message.get("id", message_id), "trashed": False}


def bulk_modify_gmail_messages(
    query: str,
    max_results: int = 100,
    archive: bool = False,
    mark_read: bool = False,
    mark_unread: bool = False,
    add_label: str | None = None,
    remove_label: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Apply one label change to every message matching ``query`` in a single call.

    ``messages.batchModify`` takes up to 1000 ids per request, so this is one HTTP
    round trip rather than one per message.
    """
    service = _gmail_service(config)
    response = execute_google_request(
        service.users().messages().list(userId="me", q=query, maxResults=max_results)
    )
    ids = [item["id"] for item in response.get("messages", [])]
    if not ids:
        return {"count": 0, "ids": [], "query": query}

    add: list[str] = []
    remove: list[str] = []
    if archive:
        remove.append("INBOX")
    if mark_read:
        remove.append("UNREAD")
    if mark_unread:
        add.append("UNREAD")
    if add_label:
        add.extend(_resolve_label_ids(service, [add_label]))
    if remove_label:
        remove.extend(_resolve_label_ids(service, [remove_label]))

    execute_google_request(
        service.users()
        .messages()
        .batchModify(
            userId="me",
            body={"ids": ids, "addLabelIds": add, "removeLabelIds": remove},
        )
    )
    return {"count": len(ids), "ids": ids, "query": query}


def get_gmail_profile(config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    profile = execute_google_request(service.users().getProfile(userId="me"))
    return {
        "email": profile.get("emailAddress"),
        "messages_total": profile.get("messagesTotal"),
        "threads_total": profile.get("threadsTotal"),
        "history_id": profile.get("historyId"),
    }


def get_gmail_history(
    start_history_id: str,
    max_results: int = 100,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    response = execute_google_request(
        service.users()
        .history()
        .list(userId="me", startHistoryId=start_history_id, maxResults=max_results)
    )
    return {
        "history_id": response.get("historyId"),
        "start_history_id": start_history_id,
        "changes": response.get("history", []),
    }


def get_gmail_thread(message_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    seed_message = execute_google_request(
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        )
    )
    thread_id = seed_message.get("threadId")
    if not thread_id:
        raise click.ClickException(f"Message {message_id!r} does not belong to a thread.")

    thread = execute_google_request(
        service.users().threads().get(userId="me", id=thread_id, format="full")
    )
    messages: list[dict[str, Any]] = []
    for item in thread.get("messages", []):
        headers = _message_headers(item)
        body = clean_message_body(extract_message_body(item.get("payload")))
        messages.append(
            {
                "id": item.get("id"),
                "thread_id": item.get("threadId"),
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "body": body or "(No plain text body — HTML only email)",
            }
        )

    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "message_count": len(messages),
        "messages": messages,
    }


def count_gmail_messages(
    query: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    response = execute_google_request(
        service.users().messages().list(userId="me", maxResults=1, q=query)
    )
    return {"query": query, "count": response.get("resultSizeEstimate", 0)}


def mark_gmail_read(message_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    message = _modify_gmail_labels(
        message_id,
        add_labels=[],
        remove_labels=["UNREAD"],
        config=config,
    )
    return {
        "id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "read": True,
        "label_ids": message.get("labelIds", []),
    }


def mark_gmail_unread(message_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    message = _modify_gmail_labels(
        message_id,
        add_labels=["UNREAD"],
        remove_labels=[],
        config=config,
    )
    return {
        "id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "read": False,
        "label_ids": message.get("labelIds", []),
    }


def trash_gmail_message(message_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _gmail_service(config)
    message = execute_google_request(service.users().messages().trash(userId="me", id=message_id))
    return {
        "id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "trashed": True,
    }


def archive_gmail_message(message_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    message = _modify_gmail_labels(
        message_id,
        add_labels=[],
        remove_labels=["INBOX"],
        config=config,
    )
    return {
        "id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "archived": True,
        "label_ids": message.get("labelIds", []),
    }


def _resolve_label_id(service: Any, label_name: str) -> str:
    labels = execute_google_request(service.users().labels().list(userId="me")).get("labels", [])
    for label in labels:
        if label.get("name") == label_name:
            resolved = label.get("id")
            if resolved:
                return resolved
    raise click.ClickException(f"Label not found: {label_name}")


def label_gmail_message(
    message_id: str,
    label_name: str,
    remove: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    label_id = _resolve_label_id(service, label_name)
    message = _modify_gmail_labels(
        message_id,
        add_labels=[] if remove else [label_id],
        remove_labels=[label_id] if remove else [],
        config=config,
    )
    return {
        "id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "label": label_name,
        "action": "removed" if remove else "added",
        "label_ids": message.get("labelIds", []),
    }


def star_gmail_message(
    message_id: str,
    remove: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    message = _modify_gmail_labels(
        message_id,
        add_labels=[] if remove else ["STARRED"],
        remove_labels=["STARRED"] if remove else [],
        config=config,
    )
    return {
        "id": message.get("id", message_id),
        "thread_id": message.get("threadId"),
        "starred": not remove,
        "label_ids": message.get("labelIds", []),
    }


def register_gmail_commands(group: click.Group) -> None:
    @group.command("send")
    @click.argument("to")
    @click.argument("subject")
    @click.argument("body", required=False)
    @click.option("--cc", default=None)
    @click.option("--bcc", default=None)
    @click.option(
        "--attachment",
        "attachments",
        multiple=True,
        type=click.Path(exists=True, dir_okay=False),
        help="File to attach. Repeat for several.",
    )
    @click.option(
        "--body-file",
        "body_file",
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Read the body from this file instead of the BODY argument.",
    )
    @_signature_option
    @json_option
    @click.pass_context
    def send_command(
        ctx: click.Context,
        to: str,
        subject: str,
        body: str | None,
        cc: str | None,
        bcc: str | None,
        attachments: tuple[str, ...],
        body_file: str | None,
        signature: bool | None,
        json_output: bool | None,
    ) -> None:
        """Send an email. Attach files with --attachment (repeatable).

        The signature configured in Gmail for this account is attached by default.
        """
        config = ctx.obj["config"]
        data = send_gmail_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            body_file=body_file,
            signature=signature,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Email sent! Message ID: {data.get('id')}")
            _render_sent_attachments(data)
            _render_signature(config, signature)

    @group.command("draft")
    @click.argument("to")
    @click.argument("subject")
    @click.argument("body", required=False)
    @click.option("--cc", default=None)
    @click.option("--bcc", default=None)
    @click.option(
        "--attachment",
        "attachments",
        multiple=True,
        type=click.Path(exists=True, dir_okay=False),
        help="File to attach. Repeat for several.",
    )
    @click.option(
        "--body-file",
        "body_file",
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Read the body from this file instead of the BODY argument.",
    )
    @_signature_option
    @json_option
    @click.pass_context
    def draft_command(
        ctx: click.Context,
        to: str,
        subject: str,
        body: str | None,
        cc: str | None,
        bcc: str | None,
        attachments: tuple[str, ...],
        body_file: str | None,
        signature: bool | None,
        json_output: bool | None,
    ) -> None:
        """Create a draft. Attach files with --attachment (repeatable).

        The signature configured in Gmail for this account is attached by default.
        """
        config = ctx.obj["config"]
        data = create_gmail_draft(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            body_file=body_file,
            signature=signature,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Draft created! Draft ID: {data.get('id')}")
            _render_sent_attachments(data)
            _render_signature(config, signature)

    @group.command("drafts")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @json_option
    @click.pass_context
    def drafts_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        """List drafts with their draft IDs."""
        data = list_gmail_drafts(max_results=max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        elif not data:
            print_human("No drafts found.", emoji="📝")
        else:
            print_human(f"Drafts ({len(data)}):", emoji="📝")
            for draft in data:
                print_human(f"  • Draft ID: {draft['id']}")
                print_human(f"    To: {draft['to']}")
                print_human(f"    Subject: {draft['subject']}")
                print_human(f"    Preview: {draft['snippet']}")

    @group.command("draft-read")
    @click.argument("draft_id")
    @json_option
    @click.pass_context
    def draft_read_command(ctx: click.Context, draft_id: str, json_output: bool | None) -> None:
        """Show a draft's current content."""
        data = get_gmail_draft(draft_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Draft {data['id']}:", emoji="📝")
            print_human(f"  To: {data['to']}")
            if data["cc"]:
                print_human(f"  Cc: {data['cc']}")
            print_human(f"  Subject: {data['subject']}")
            for attachment in data["attachments"]:
                print_human(
                    f"  📎 {attachment['filename']} "
                    f"({attachment['mime_type']}, {attachment['size']} bytes)"
                )
            print_human("")
            print_human(data["body"])

    @group.command("draft-edit")
    @click.argument("draft_id")
    @click.option("--to", default=None, help="Replace the recipient.")
    @click.option("--subject", default=None, help="Replace the subject.")
    @click.option("--body", default=None, help="Replace the body.")
    @click.option("--cc", default=None, help="Replace the Cc list.")
    @click.option("--bcc", default=None, help="Replace the Bcc list.")
    @click.option(
        "--attachment",
        "attachments",
        multiple=True,
        type=click.Path(exists=True, dir_okay=False),
        help="Replace the attachments with these files. Repeat for several.",
    )
    @click.option(
        "--body-file",
        "body_file",
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Read the replacement body from this file.",
    )
    @click.option(
        "--clear-attachments",
        is_flag=True,
        help="Remove every attachment from the draft.",
    )
    @_signature_option
    @json_option
    @click.pass_context
    def draft_edit_command(
        ctx: click.Context,
        draft_id: str,
        to: str | None,
        subject: str | None,
        body: str | None,
        cc: str | None,
        bcc: str | None,
        attachments: tuple[str, ...],
        body_file: str | None,
        clear_attachments: bool,
        signature: bool | None,
        json_output: bool | None,
    ) -> None:
        """Edit a draft in place. Only the fields you pass change.

        --attachment replaces the whole attachment set; omit it to keep the files
        already on the draft, or use --clear-attachments to drop them.

        The account signature is re-applied, never doubled.
        """
        if not any(
            value is not None for value in (to, subject, body, cc, bcc, body_file)
        ) and not (attachments or clear_attachments):
            raise click.ClickException(
                "Nothing to change. Pass at least one of --to/--subject/--body/"
                "--body-file/--cc/--bcc/--attachment/--clear-attachments."
            )
        data = update_gmail_draft(
            draft_id,
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            body_file=body_file,
            clear_attachments=clear_attachments,
            signature=signature,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Draft updated! Draft ID: {data['id']}")
            _render_sent_attachments(data)

    @group.command("signature")
    @click.option(
        "--set",
        "set_file",
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Write the signature from this HTML file into Gmail.",
    )
    @click.option("--clear", is_flag=True, help="Remove the signature configured in Gmail.")
    @click.option("--address", default=None, help="Sending identity to read or write.")
    @click.option("--refresh", is_flag=True, help="Ignore the cache and read Gmail again.")
    @json_option
    @click.pass_context
    def signature_command(
        ctx: click.Context,
        set_file: str | None,
        clear: bool,
        address: str | None,
        refresh: bool,
        json_output: bool | None,
    ) -> None:
        """Show — or write — the account signature gw attaches to outgoing mail.

        Read from Gmail's own settings (``settings.sendAs``) and cached for a week.

        --set and --clear write to Gmail itself, so the signature is the same one the
        web interface shows. That needs the gmail.settings.basic scope: run
        `gw auth login` once after upgrading if the token predates it.
        """
        config = ctx.obj["config"]
        if set_file is not None and clear:
            raise click.ClickException("Pass either --set FILE or --clear, not both.")

        if set_file is not None or clear:
            markup = "" if clear else Path(set_file).read_text(encoding="utf-8")
            written = set_account_signature(config, markup, address=address)
            if use_json_output(ctx, json_output):
                print_json({"email": written.email, "chars": len(written.html), "cleared": clear})
            elif clear:
                print_success(f"Signature cleared for {written.email}.")
            else:
                print_success(
                    f"Signature updated for {written.email} ({len(written.html)} chars). "
                    "The next send carries it."
                )
            return

        data = get_account_signature(config, refresh=refresh)
        if use_json_output(ctx, json_output):
            print_json(
                {
                    "email": data.email if data else None,
                    "source": data.source if data else None,
                    "chars": len(data.html) if data else 0,
                    "enabled": signature_enabled(config),
                    "html": data.html if data else None,
                }
            )
            return

        if data is None:
            print_human("No signature attached: none configured for this account.", emoji="✍️")
            return
        print_human(f"Signature: {data.email} ({data.source}, {len(data.html)} chars)", emoji="✍️")
        if not signature_enabled(config):
            print_human("Off for this profile: signature = false in the config.", emoji="⚠️")
        print_human("")
        print_human(data.html)

    @group.command("draft-send")
    @click.argument("draft_id")
    @json_option
    @click.pass_context
    def draft_send_command(ctx: click.Context, draft_id: str, json_output: bool | None) -> None:
        """Send an existing draft."""
        data = send_gmail_draft(draft_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Draft sent! Message ID: {data['id']}")

    @group.command("draft-delete")
    @click.argument("draft_id")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def draft_delete_command(
        ctx: click.Context, draft_id: str, yes: bool, json_output: bool | None
    ) -> None:
        """Delete a draft. This cannot be undone."""
        if not yes:
            click.confirm(f"Delete draft {draft_id}? This cannot be undone.", abort=True)
        data = delete_gmail_draft(draft_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Draft {draft_id} deleted.")

    @group.command("reply")
    @click.argument("message_id")
    @click.argument("body", required=False)
    @click.option("--cc", default=None)
    @click.option("--bcc", default=None)
    @click.option(
        "--attachment",
        "attachments",
        multiple=True,
        type=click.Path(exists=True, dir_okay=False),
        help="File to attach. Repeat for several.",
    )
    @click.option(
        "--body-file",
        "body_file",
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Read the body from this file instead of the BODY argument.",
    )
    @_signature_option
    @json_option
    @click.pass_context
    def reply_command(
        ctx: click.Context,
        message_id: str,
        body: str | None,
        cc: str | None,
        bcc: str | None,
        attachments: tuple[str, ...],
        body_file: str | None,
        signature: bool | None,
        json_output: bool | None,
    ) -> None:
        """Reply in thread. Attach files with --attachment (repeatable)."""
        config = ctx.obj["config"]
        data = reply_to_gmail_message(
            message_id=message_id,
            body=body,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            body_file=body_file,
            signature=signature,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Reply sent! Message ID: {data.get('id')}")
            _render_sent_attachments(data)
            _render_signature(config, signature)

    @group.command("forward")
    @click.argument("message_id")
    @click.argument("to")
    @click.option("--cc", default=None)
    @click.option("--bcc", default=None)
    @click.option(
        "--attachment",
        "attachments",
        multiple=True,
        type=click.Path(exists=True, dir_okay=False),
        help="File to attach. Repeat for several.",
    )
    @_signature_option
    @json_option
    @click.pass_context
    def forward_command(
        ctx: click.Context,
        message_id: str,
        to: str,
        cc: str | None,
        bcc: str | None,
        attachments: tuple[str, ...],
        signature: bool | None,
        json_output: bool | None,
    ) -> None:
        """Forward a message. Add extra files with --attachment (repeatable).

        The original attachments are not re-sent; attach them explicitly after
        `gw gmail download` if the recipient needs them.
        """
        config = ctx.obj["config"]
        data = forward_gmail_message(
            message_id=message_id,
            to=to,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            signature=signature,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Forwarded! Message ID: {data.get('id')}")
            _render_sent_attachments(data)
            _render_signature(config, signature)

    @group.command("list")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @click.option("--query", default=None, help="Raw Gmail search query.")
    @click.option("--unread", is_flag=True, help="Only unread messages.")
    @click.option("--after", default=None, help="Relative date like 6h, 24h, or 7d.")
    @json_option
    @click.pass_context
    def list_command(
        ctx: click.Context,
        max_results: int,
        query: str | None,
        unread: bool,
        after: str | None,
        json_output: bool | None,
    ) -> None:
        messages = list_gmail_messages(
            max_results=max_results,
            query=query,
            unread=unread,
            after=after,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(messages)
        else:
            _render_list(messages)

    @group.command("search")
    @click.argument("query")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @click.option("--after", default=None, help="Relative date like 6h, 24h, or 7d.")
    @json_option
    @click.pass_context
    def search_command(
        ctx: click.Context,
        query: str,
        max_results: int,
        after: str | None,
        json_output: bool | None,
    ) -> None:
        messages = search_gmail_messages(
            query=query, max_results=max_results, after=after, config=ctx.obj["config"]
        )
        if use_json_output(ctx, json_output):
            print_json(messages)
        else:
            _render_list(messages)

    @group.command("thread-trash")
    @click.argument("thread_id")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def thread_trash_command(
        ctx: click.Context, thread_id: str, yes: bool, json_output: bool | None
    ) -> None:
        """Move an entire thread to the trash."""
        if not yes:
            click.confirm(f"Trash the whole thread {thread_id}?", abort=True)
        data = trash_gmail_thread(thread_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Thread {thread_id} moved to trash.")

    @group.command("thread-untrash")
    @click.argument("thread_id")
    @json_option
    @click.pass_context
    def thread_untrash_command(
        ctx: click.Context, thread_id: str, json_output: bool | None
    ) -> None:
        """Restore an entire thread from the trash."""
        data = untrash_gmail_thread(thread_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Thread {thread_id} restored.")

    @group.command("thread-archive")
    @click.argument("thread_id")
    @json_option
    @click.pass_context
    def thread_archive_command(
        ctx: click.Context, thread_id: str, json_output: bool | None
    ) -> None:
        """Archive an entire thread (removes it from the inbox)."""
        data = modify_gmail_thread(thread_id, remove_labels=["INBOX"], config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Thread {thread_id} archived ({data['message_count']} messages).")

    @group.command("thread-label")
    @click.argument("thread_id")
    @click.argument("label_name")
    @click.option("--remove", is_flag=True, help="Remove the label instead of adding it.")
    @json_option
    @click.pass_context
    def thread_label_command(
        ctx: click.Context,
        thread_id: str,
        label_name: str,
        remove: bool,
        json_output: bool | None,
    ) -> None:
        """Apply or remove a label across an entire thread."""
        data = modify_gmail_thread(
            thread_id,
            add_labels=[] if remove else [label_name],
            remove_labels=[label_name] if remove else [],
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            verb = "removed from" if remove else "applied to"
            print_success(f"Label {label_name!r} {verb} thread {thread_id}.")

    @group.command("untrash")
    @click.argument("message_id")
    @json_option
    @click.pass_context
    def untrash_command(ctx: click.Context, message_id: str, json_output: bool | None) -> None:
        """Restore a message from the trash."""
        data = untrash_gmail_message(message_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Message {message_id} restored.")

    @group.command("bulk")
    @click.option("--query", required=True, help="Gmail query selecting the messages.")
    @click.option("--max", "max_results", default=100, type=int, show_default=True)
    @click.option("--archive", is_flag=True, help="Remove from the inbox.")
    @click.option("--mark-read", is_flag=True, help="Mark as read.")
    @click.option("--mark-unread", is_flag=True, help="Mark as unread.")
    @click.option("--label", "add_label", default=None, help="Apply this label.")
    @click.option("--remove-label", default=None, help="Remove this label.")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def bulk_command(
        ctx: click.Context,
        query: str,
        max_results: int,
        archive: bool,
        mark_read: bool,
        mark_unread: bool,
        add_label: str | None,
        remove_label: str | None,
        yes: bool,
        json_output: bool | None,
    ) -> None:
        """Apply one change to every message matching a query, in a single API call."""
        if not any([archive, mark_read, mark_unread, add_label, remove_label]):
            raise click.ClickException(
                "Nothing to do. Pass at least one of --archive/--mark-read/"
                "--mark-unread/--label/--remove-label."
            )
        if mark_read and mark_unread:
            raise click.ClickException("--mark-read and --mark-unread contradict each other.")
        if not yes:
            click.confirm(
                f"Apply this to every message matching {query!r} (up to {max_results})?",
                abort=True,
            )
        data = bulk_modify_gmail_messages(
            query=query,
            max_results=max_results,
            archive=archive,
            mark_read=mark_read,
            mark_unread=mark_unread,
            add_label=add_label,
            remove_label=remove_label,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Updated {data['count']} message(s).")

    @group.command("profile")
    @json_option
    @click.pass_context
    def profile_command(ctx: click.Context, json_output: bool | None) -> None:
        """Show the mailbox profile straight from the Gmail API."""
        data = get_gmail_profile(config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Mailbox: {data['email']}", emoji="📬")
            print_human(f"  Messages: {data['messages_total']}")
            print_human(f"  Threads: {data['threads_total']}")
            print_human(f"  History ID: {data['history_id']}")

    @group.command("history")
    @click.option("--since", "start_history_id", required=True, help="Start history ID.")
    @click.option("--max", "max_results", default=100, type=int, show_default=True)
    @json_option
    @click.pass_context
    def history_command(
        ctx: click.Context, start_history_id: str, max_results: int, json_output: bool | None
    ) -> None:
        """List mailbox changes since a history ID (from `gw gmail profile`)."""
        data = get_gmail_history(
            start_history_id=start_history_id,
            max_results=max_results,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            changes = data["changes"]
            print_human(f"Changes since {start_history_id}: {len(changes)}", emoji="🕓")
            print_human(f"Current history ID: {data['history_id']}")

    @group.command("thread")
    @click.argument("message_id")
    @json_option
    @click.pass_context
    def thread_command(ctx: click.Context, message_id: str, json_output: bool | None) -> None:
        thread = get_gmail_thread(message_id=message_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(thread)
        else:
            _render_thread(thread)

    @group.command("count")
    @click.option("--query", default=None, help="Raw Gmail search query.")
    @json_option
    @click.pass_context
    def count_command(ctx: click.Context, query: str | None, json_output: bool | None) -> None:
        data = count_gmail_messages(query=query, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Count: {data['count']}", emoji="📧")

    @group.command("read")
    @click.argument("message_id", required=False)
    @click.option("--query", default=None, help="Search query to read matching messages.")
    @click.option("--max", "max_results", default=1, type=int, show_default=True)
    @json_option
    @click.pass_context
    def read_command(
        ctx: click.Context,
        message_id: str | None,
        query: str | None,
        max_results: int,
        json_output: bool | None,
    ) -> None:
        messages = read_gmail_messages(
            message_id=message_id,
            query=query,
            max_results=max_results,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(messages if query else messages[0])
        else:
            for message in messages:
                print_human(message["subject"], emoji="📧")
                print_human(f"From: {message['from']}")
                print_human(f"Date: {message['date']}")
                print_human("=" * 60)
                print_human(message["body"])

    @group.command("attachments")
    @click.argument("message_id")
    @json_option
    @click.pass_context
    def attachments_command(ctx: click.Context, message_id: str, json_output: bool | None) -> None:
        """List the attachments carried by a message."""
        data = list_gmail_attachments(message_id=message_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            _render_attachments(data)

    @group.command("download")
    @click.argument("message_id")
    @click.option("--attachment-id", default=None, help="Download only this attachment ID.")
    @click.option("--filename", default=None, help="Download only the attachment with this name.")
    @click.option(
        "--output",
        "output_path",
        default=None,
        type=click.Path(dir_okay=False),
        help="Write a single attachment to this exact path.",
    )
    @click.option(
        "--dir",
        "directory",
        default=None,
        type=click.Path(file_okay=False),
        help="Directory to save into. Defaults to the current directory.",
    )
    @json_option
    @click.pass_context
    def download_command(
        ctx: click.Context,
        message_id: str,
        attachment_id: str | None,
        filename: str | None,
        output_path: str | None,
        directory: str | None,
        json_output: bool | None,
    ) -> None:
        """Download attachments from a message. Downloads all of them by default."""
        data = download_gmail_attachments(
            message_id=message_id,
            attachment_id=attachment_id,
            filename=filename,
            output_path=output_path,
            directory=directory,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Downloaded {data['count']} attachment(s):")
            for attachment in data["attachments"]:
                print_human(f"  • {attachment['path']} ({attachment['size']} bytes)")

    @group.command("trash")
    @click.argument("message_id")
    @json_option
    @click.pass_context
    def trash_command(ctx: click.Context, message_id: str, json_output: bool | None) -> None:
        data = trash_gmail_message(message_id=message_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Message moved to trash: {data['id']}")

    @group.command("archive")
    @click.argument("message_id")
    @json_option
    @click.pass_context
    def archive_command(ctx: click.Context, message_id: str, json_output: bool | None) -> None:
        data = archive_gmail_message(message_id=message_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Message archived: {data['id']}")

    @group.command("label")
    @click.argument("message_id")
    @click.argument("label_name")
    @click.option("--remove", is_flag=True, help="Remove the label instead of adding it.")
    @json_option
    @click.pass_context
    def label_command(
        ctx: click.Context,
        message_id: str,
        label_name: str,
        remove: bool,
        json_output: bool | None,
    ) -> None:
        data = label_gmail_message(
            message_id=message_id,
            label_name=label_name,
            remove=remove,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            action = "removed from" if remove else "added to"
            print_success(f"Label {label_name!r} {action} message {data['id']}")

    @group.command("star")
    @click.argument("message_id")
    @click.option("--remove", is_flag=True, help="Remove the starred label.")
    @json_option
    @click.pass_context
    def star_command(
        ctx: click.Context, message_id: str, remove: bool, json_output: bool | None
    ) -> None:
        data = star_gmail_message(message_id=message_id, remove=remove, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            action = "unstarred" if remove else "starred"
            print_success(f"Message {action}: {data['id']}")

    @group.command("mark-read")
    @click.argument("message_id")
    @json_option
    @click.pass_context
    def mark_read_command(ctx: click.Context, message_id: str, json_output: bool | None) -> None:
        data = mark_gmail_read(message_id=message_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Message marked as read: {data['id']}")

    @group.command("mark-unread")
    @click.argument("message_id")
    @json_option
    @click.pass_context
    def mark_unread_command(ctx: click.Context, message_id: str, json_output: bool | None) -> None:
        data = mark_gmail_unread(message_id=message_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Message marked as unread: {data['id']}")
