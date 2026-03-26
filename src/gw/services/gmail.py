from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

import click

from gw.auth import build_service
from gw.output import json_option, print_human, print_json, print_success, use_json_output
from gw.utils import clean_message_body, extract_message_body, header_map, parse_after_flag


def _gmail_service():
    return build_service("gmail", "v1")


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


def send_gmail_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict[str, Any]:
    service = _gmail_service()
    message = MIMEText(body)
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc

    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": _encode_message(message)})
        .execute()
    )
    return {"id": sent.get("id"), "to": to, "subject": subject}


def reply_to_gmail_message(message_id: str, body: str) -> dict[str, Any]:
    service = _gmail_service()
    original = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["Message-ID", "Subject", "From", "To", "References"],
        )
        .execute()
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

    sent = (
        service.users()
        .messages()
        .send(
            userId="me",
            body={"raw": _encode_message(message), "threadId": original.get("threadId")},
        )
        .execute()
    )
    return {"id": sent.get("id"), "thread_id": original.get("threadId")}


def forward_gmail_message(message_id: str, to: str) -> dict[str, Any]:
    service = _gmail_service()
    original = service.users().messages().get(userId="me", id=message_id, format="full").execute()
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
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": _encode_message(message)})
        .execute()
    )
    return {"id": sent.get("id"), "to": to}


def list_gmail_messages(
    max_results: int = 10,
    query: str | None = None,
    unread: bool = False,
    after: str | None = None,
) -> list[dict[str, Any]]:
    service = _gmail_service()
    parts = []
    if query:
        parts.append(query)
    if after:
        parts.append(parse_after_flag(after))
    if unread:
        parts.append("is:unread")
    final_query = " ".join(parts) or None

    response = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, q=final_query)
        .execute()
    )
    messages: list[dict[str, Any]] = []
    for item in response.get("messages", []):
        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            )
            .execute()
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
) -> list[dict[str, Any]]:
    if not message_id and not query:
        raise click.ClickException("Provide a message ID or use --query.")

    service = _gmail_service()
    ids: list[str]
    if message_id:
        ids = [message_id]
    else:
        response = (
            service.users().messages().list(userId="me", maxResults=max_results, q=query).execute()
        )
        ids = [item["id"] for item in response.get("messages", [])]

    messages: list[dict[str, Any]] = []
    for selected_id in ids:
        message = (
            service.users().messages().get(userId="me", id=selected_id, format="full").execute()
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
        data = send_gmail_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc)
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Email sent! Message ID: {data.get('id')}")

    @group.command("reply")
    @click.argument("message_id")
    @click.argument("body")
    @json_option
    @click.pass_context
    def reply_command(
        ctx: click.Context, message_id: str, body: str, json_output: bool | None
    ) -> None:
        data = reply_to_gmail_message(message_id=message_id, body=body)
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
        data = forward_gmail_message(message_id=message_id, to=to)
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
        )
        if use_json_output(ctx, json_output):
            print_json(messages)
        else:
            _render_list(messages)

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
        messages = read_gmail_messages(message_id=message_id, query=query, max_results=max_results)
        if use_json_output(ctx, json_output):
            print_json(messages if query else messages[0])
        else:
            for message in messages:
                print_human(message["subject"], emoji="📧")
                print_human(f"From: {message['from']}")
                print_human(f"Date: {message['date']}")
                print_human("=" * 60)
                print_human(message["body"])
