from __future__ import annotations

import base64
import mimetypes
from collections.abc import Sequence
from email import encoders
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


def _build_mime_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    *,
    reply_headers: dict[str, str] | None = None,
) -> tuple[Message, list[str]]:
    """Build the outgoing message, returning it with the attached filenames.

    Without attachments this stays a single ``text/plain`` part, byte for byte what
    gw sent before 0.6.0. With attachments it becomes ``multipart/mixed``.
    """
    paths = [_attachment_path(item) for item in attachments or []]

    message: Message
    if paths:
        message = MIMEMultipart("mixed")
        message.attach(MIMEText(body, "plain", "utf-8"))
        for path in paths:
            message.attach(_attachment_part(path))
    else:
        message = MIMEText(body)

    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    for header, value in (reply_headers or {}).items():
        message[header] = value

    return message, [path.name for path in paths]


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
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    message, filenames = _build_mime_message(
        to=to,
        subject=subject,
        body=_resolve_body(body, body_file),
        cc=cc,
        bcc=bcc,
        attachments=attachments,
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


def create_gmail_draft(
    to: str,
    subject: str,
    body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    body_file: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    message, filenames = _build_mime_message(
        to=to,
        subject=subject,
        body=_resolve_body(body, body_file),
        cc=cc,
        bcc=bcc,
        attachments=attachments,
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


def reply_to_gmail_message(
    message_id: str,
    body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: Sequence[str | Path] | None = None,
    body_file: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    resolved_body = _resolve_body(body, body_file)
    service = _gmail_service(config)
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
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
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
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    return list_gmail_messages(max_results=max_results, query=query, config=config)


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
        json_output: bool | None,
    ) -> None:
        """Send an email. Attach files with --attachment (repeatable)."""
        config = ctx.obj["config"]
        data = send_gmail_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            body_file=body_file,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Email sent! Message ID: {data.get('id')}")
            _render_sent_attachments(data)

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
        json_output: bool | None,
    ) -> None:
        """Create a draft. Attach files with --attachment (repeatable)."""
        config = ctx.obj["config"]
        data = create_gmail_draft(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            body_file=body_file,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Draft created! Draft ID: {data.get('id')}")
            _render_sent_attachments(data)

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
        json_output: bool | None,
    ) -> None:
        """Reply in thread. Attach files with --attachment (repeatable)."""
        data = reply_to_gmail_message(
            message_id=message_id,
            body=body,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            body_file=body_file,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Reply sent! Message ID: {data.get('id')}")
            _render_sent_attachments(data)

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
    @json_option
    @click.pass_context
    def forward_command(
        ctx: click.Context,
        message_id: str,
        to: str,
        cc: str | None,
        bcc: str | None,
        attachments: tuple[str, ...],
        json_output: bool | None,
    ) -> None:
        """Forward a message. Add extra files with --attachment (repeatable).

        The original attachments are not re-sent; attach them explicitly after
        `gw gmail download` if the recipient needs them.
        """
        data = forward_gmail_message(
            message_id=message_id,
            to=to,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Forwarded! Message ID: {data.get('id')}")
            _render_sent_attachments(data)

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
    @json_option
    @click.pass_context
    def search_command(
        ctx: click.Context,
        query: str,
        max_results: int,
        json_output: bool | None,
    ) -> None:
        messages = search_gmail_messages(
            query=query, max_results=max_results, config=ctx.obj["config"]
        )
        if use_json_output(ctx, json_output):
            print_json(messages)
        else:
            _render_list(messages)

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
