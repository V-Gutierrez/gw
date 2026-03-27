from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, print_success, use_json_output
from gw.utils import clean_message_body, extract_message_body, header_map, parse_after_flag


def _gmail_service(config: GWConfig | None = None):
    return build_service("gmail", "v1", config=config)


def _message_headers(message: dict[str, Any]) -> dict[str, str]:
    payload = message.get("payload", {})
    return header_map(payload.get("headers"))


def _encode_message(message: MIMEText) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


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
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    message = MIMEText(body)
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc

    sent = execute_google_request(
        service.users().messages().send(userId="me", body={"raw": _encode_message(message)})
    )
    return {"id": sent.get("id"), "to": to, "subject": subject}


def create_gmail_draft(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _gmail_service(config)
    message = MIMEText(body)
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc

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
    }


def reply_to_gmail_message(
    message_id: str,
    body: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
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

    message = MIMEText(body)
    message["To"] = headers.get("from", "")
    message["Subject"] = reply_subject
    if headers.get("message-id"):
        message["In-Reply-To"] = headers["message-id"]
        message["References"] = headers.get("references", headers["message-id"])

    sent = execute_google_request(
        service.users()
        .messages()
        .send(
            userId="me",
            body={"raw": _encode_message(message), "threadId": original.get("threadId")},
        )
    )
    return {"id": sent.get("id"), "thread_id": original.get("threadId")}


def forward_gmail_message(
    message_id: str,
    to: str,
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
    message = MIMEText(forwarded_body)
    message["To"] = to
    message["Subject"] = f"Fwd: {headers.get('subject', '')}"
    sent = execute_google_request(
        service.users().messages().send(userId="me", body={"raw": _encode_message(message)})
    )
    return {"id": sent.get("id"), "to": to}


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
            }
        )
    return messages


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
    @click.argument("body")
    @click.option("--cc", default=None)
    @click.option("--bcc", default=None)
    @json_option
    @click.pass_context
    def send_command(
        ctx: click.Context,
        to: str,
        subject: str,
        body: str,
        cc: str | None,
        bcc: str | None,
        json_output: bool | None,
    ) -> None:
        config = ctx.obj["config"]
        data = send_gmail_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc, config=config)
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Email sent! Message ID: {data.get('id')}")

    @group.command("draft")
    @click.argument("to")
    @click.argument("subject")
    @click.argument("body")
    @click.option("--cc", default=None)
    @click.option("--bcc", default=None)
    @json_option
    @click.pass_context
    def draft_command(
        ctx: click.Context,
        to: str,
        subject: str,
        body: str,
        cc: str | None,
        bcc: str | None,
        json_output: bool | None,
    ) -> None:
        config = ctx.obj["config"]
        data = create_gmail_draft(to=to, subject=subject, body=body, cc=cc, bcc=bcc, config=config)
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Draft created! Draft ID: {data.get('id')}")

    @group.command("reply")
    @click.argument("message_id")
    @click.argument("body")
    @json_option
    @click.pass_context
    def reply_command(
        ctx: click.Context, message_id: str, body: str, json_output: bool | None
    ) -> None:
        data = reply_to_gmail_message(message_id=message_id, body=body, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Reply sent! Message ID: {data.get('id')}")

    @group.command("forward")
    @click.argument("message_id")
    @click.argument("to")
    @json_option
    @click.pass_context
    def forward_command(
        ctx: click.Context, message_id: str, to: str, json_output: bool | None
    ) -> None:
        data = forward_gmail_message(message_id=message_id, to=to, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Forwarded! Message ID: {data.get('id')}")

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
