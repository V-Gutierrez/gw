"""Outbound attachments: send, draft and reply carrying files.

The inbound side (list/download) lives in ``test_gmail_attachments.py``.
"""

from __future__ import annotations

import base64
import email
import json
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.services.gmail import (
    create_gmail_draft,
    forward_gmail_message,
    reply_to_gmail_message,
    send_gmail_message,
)

runner = CliRunner()

PDF_BYTES = b"%PDF-1.4\nfake signed proposal\n%%EOF"
JPG_BYTES = b"\xff\xd8\xff\xe0fake jpeg payload"


def _mock_execute(payload: Any) -> MagicMock:
    request = MagicMock()
    request.execute.return_value = payload
    return request


def _pdf(tmp_path: Path, name: str = "proposta.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(PDF_BYTES)
    return path


def _jpg(tmp_path: Path, name: str = "foto.jpg") -> Path:
    path = tmp_path / name
    path.write_bytes(JPG_BYTES)
    return path


def _send_service() -> MagicMock:
    service = MagicMock()
    service.users.return_value.messages.return_value.send.return_value = _mock_execute(
        {"id": "sent-1", "threadId": "thr-1"}
    )
    return service


def _draft_service() -> MagicMock:
    service = MagicMock()
    service.users.return_value.drafts.return_value.create.return_value = _mock_execute(
        {"id": "draft-1", "message": {"id": "msg-1"}}
    )
    return service


ORIGINAL_METADATA = {
    "id": "orig-1",
    "threadId": "thr-9",
    "payload": {
        "headers": [
            {"name": "Message-ID", "value": "<seed@mail.example>"},
            {"name": "Subject", "value": "Seguro de Saude"},
            {"name": "From", "value": "jose@example.com"},
            {"name": "To", "value": "victor@example.com"},
        ]
    },
}

ORIGINAL_FULL = {
    "id": "orig-1",
    "threadId": "thr-9",
    "payload": {
        "mimeType": "text/plain",
        "body": {"data": base64.urlsafe_b64encode(b"corpo original").decode().rstrip("=")},
        "headers": [
            {"name": "Subject", "value": "Seguro de Saude"},
            {"name": "From", "value": "jose@example.com"},
            {"name": "To", "value": "victor@example.com"},
            {"name": "Date", "value": "Tue, 09 Sep 2026 10:00:00 +0100"},
        ],
    },
}


def _reply_service(original: dict[str, Any] = ORIGINAL_METADATA) -> MagicMock:
    service = MagicMock()
    service.users.return_value.messages.return_value.get.return_value = _mock_execute(original)
    service.users.return_value.messages.return_value.send.return_value = _mock_execute(
        {"id": "sent-2", "threadId": original["threadId"]}
    )
    return service


def _sent_message(service: MagicMock) -> Message:
    _, kwargs = service.users.return_value.messages.return_value.send.call_args
    return _decode_raw(kwargs["body"]["raw"])


def _drafted_message(service: MagicMock) -> Message:
    _, kwargs = service.users.return_value.drafts.return_value.create.call_args
    return _decode_raw(kwargs["body"]["message"]["raw"])


def _decode_raw(raw: str) -> Message:
    padded = raw + "=" * (-len(raw) % 4)
    return email.message_from_bytes(base64.urlsafe_b64decode(padded))


def _attachment_parts(message: Message) -> list[Message]:
    return [
        part
        for part in message.walk()
        if part.get_content_disposition() == "attachment"
    ]


# --- send ------------------------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_send_with_single_pdf_carries_binary_payload(
    mock_build_service: MagicMock, tmp_path: Path
):
    service = _send_service()
    mock_build_service.return_value = service
    pdf = _pdf(tmp_path)

    data = send_gmail_message(
        to="jose@example.com",
        subject="Proposta assinada",
        body="Segue em anexo.",
        attachments=[pdf],
    )

    assert data["id"] == "sent-1"
    assert data["attachments"] == ["proposta.pdf"]

    message = _sent_message(service)
    assert message.get_content_type() == "multipart/mixed"
    parts = _attachment_parts(message)
    assert len(parts) == 1
    assert parts[0].get_content_type() == "application/pdf"
    assert parts[0].get_filename() == "proposta.pdf"
    assert parts[0].get_payload(decode=True) == PDF_BYTES


@patch("gw.services.gmail.build_service")
def test_send_keeps_plain_text_body_alongside_attachment(
    mock_build_service: MagicMock, tmp_path: Path
):
    service = _send_service()
    mock_build_service.return_value = service

    send_gmail_message(
        to="jose@example.com",
        subject="Proposta",
        body="Segue em anexo.",
        attachments=[_pdf(tmp_path)],
    )

    message = _sent_message(service)
    text_parts = [
        part
        for part in message.walk()
        if part.get_content_type() == "text/plain"
        and part.get_content_disposition() != "attachment"
    ]
    assert len(text_parts) == 1
    assert text_parts[0].get_payload(decode=True).decode("utf-8") == "Segue em anexo."


@patch("gw.services.gmail.build_service")
def test_send_with_two_attachments_and_cc_bcc(mock_build_service: MagicMock, tmp_path: Path):
    service = _send_service()
    mock_build_service.return_value = service

    send_gmail_message(
        to="jose@example.com",
        subject="Docs",
        body="Dois ficheiros.",
        cc="carinna@example.com",
        bcc="arquivo@example.com",
        attachments=[_pdf(tmp_path), _jpg(tmp_path)],
    )

    message = _sent_message(service)
    parts = _attachment_parts(message)
    assert len(parts) == 2
    assert [part.get_filename() for part in parts] == ["proposta.pdf", "foto.jpg"]
    assert [part.get_content_type() for part in parts] == ["application/pdf", "image/jpeg"]
    assert parts[1].get_payload(decode=True) == JPG_BYTES
    assert message["Cc"] == "carinna@example.com"
    assert message["Bcc"] == "arquivo@example.com"


@patch("gw.services.gmail.build_service")
def test_send_without_attachments_stays_single_part(mock_build_service: MagicMock):
    service = _send_service()
    mock_build_service.return_value = service

    send_gmail_message(to="a@example.com", subject="Oi", body="Corpo")

    message = _sent_message(service)
    assert message.get_content_type() == "text/plain"
    assert message.get_payload(decode=True).decode("utf-8") == "Corpo"
    assert _attachment_parts(message) == []


@patch("gw.services.gmail.build_service")
def test_send_rejects_missing_attachment(mock_build_service: MagicMock, tmp_path: Path):
    mock_build_service.return_value = _send_service()

    with pytest.raises(Exception, match="not found"):
        send_gmail_message(
            to="a@example.com",
            subject="S",
            body="B",
            attachments=[tmp_path / "ghost.pdf"],
        )


@pytest.mark.parametrize(
    "raw_name",
    ["com espaço.pdf", "acentuação-çãé.pdf"],
)
@patch("gw.services.gmail.build_service")
def test_send_preserves_awkward_filenames(
    mock_build_service: MagicMock, tmp_path: Path, raw_name: str
):
    service = _send_service()
    mock_build_service.return_value = service

    send_gmail_message(
        to="a@example.com",
        subject="S",
        body="B",
        attachments=[_pdf(tmp_path, raw_name)],
    )

    part = _attachment_parts(_sent_message(service))[0]
    assert part.get_filename() == raw_name


@patch("gw.services.gmail.build_service")
def test_send_encodes_non_ascii_filename_with_rfc2231(
    mock_build_service: MagicMock, tmp_path: Path
):
    service = _send_service()
    mock_build_service.return_value = service

    send_gmail_message(
        to="a@example.com",
        subject="S",
        body="B",
        attachments=[_pdf(tmp_path, "acentuação.pdf")],
    )

    part = _attachment_parts(_sent_message(service))[0]
    disposition = part["Content-Disposition"]
    assert "filename*=" in disposition.lower()
    assert "utf-8''" in disposition.lower()


@patch("gw.services.gmail.build_service")
def test_send_strips_path_components_from_attachment_name(
    mock_build_service: MagicMock, tmp_path: Path
):
    service = _send_service()
    mock_build_service.return_value = service
    nested = tmp_path / "sub"
    nested.mkdir()
    pdf = _pdf(nested, "relatorio.pdf")

    send_gmail_message(to="a@example.com", subject="S", body="B", attachments=[pdf])

    part = _attachment_parts(_sent_message(service))[0]
    assert part.get_filename() == "relatorio.pdf"


@patch("gw.services.gmail.build_service")
def test_send_falls_back_to_octet_stream_for_unknown_type(
    mock_build_service: MagicMock, tmp_path: Path
):
    service = _send_service()
    mock_build_service.return_value = service
    blob = tmp_path / "dados.wtfext"
    blob.write_bytes(b"\x00\x01\x02binary")

    send_gmail_message(to="a@example.com", subject="S", body="B", attachments=[blob])

    part = _attachment_parts(_sent_message(service))[0]
    assert part.get_content_type() == "application/octet-stream"
    assert part.get_payload(decode=True) == b"\x00\x01\x02binary"


# --- body-file -------------------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_send_reads_body_from_file(mock_build_service: MagicMock, tmp_path: Path):
    service = _send_service()
    mock_build_service.return_value = service
    body_file = tmp_path / "body.txt"
    body_file.write_text("Corpo gerado por agente\ncom duas linhas.\n", encoding="utf-8")

    send_gmail_message(to="a@example.com", subject="S", body=None, body_file=str(body_file))

    message = _sent_message(service)
    assert (
        message.get_payload(decode=True).decode("utf-8")
        == "Corpo gerado por agente\ncom duas linhas.\n"
    )


@patch("gw.services.gmail.build_service")
def test_send_rejects_body_and_body_file_together(mock_build_service: MagicMock, tmp_path: Path):
    mock_build_service.return_value = _send_service()
    body_file = tmp_path / "body.txt"
    body_file.write_text("do ficheiro", encoding="utf-8")

    with pytest.raises(Exception, match="not both"):
        send_gmail_message(
            to="a@example.com", subject="S", body="inline", body_file=str(body_file)
        )


@patch("gw.services.gmail.build_service")
def test_send_rejects_missing_body_entirely(mock_build_service: MagicMock):
    mock_build_service.return_value = _send_service()

    with pytest.raises(Exception, match="--body-file"):
        send_gmail_message(to="a@example.com", subject="S", body=None)


# --- draft -----------------------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_draft_carries_attachments(mock_build_service: MagicMock, tmp_path: Path):
    service = _draft_service()
    mock_build_service.return_value = service

    data = create_gmail_draft(
        to="a@example.com",
        subject="S",
        body="B",
        attachments=[_pdf(tmp_path)],
    )

    assert data["attachments"] == ["proposta.pdf"]
    part = _attachment_parts(_drafted_message(service))[0]
    assert part.get_content_type() == "application/pdf"
    assert part.get_payload(decode=True) == PDF_BYTES


# --- reply -----------------------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_reply_keeps_threading_headers_with_attachment(
    mock_build_service: MagicMock, tmp_path: Path
):
    service = _reply_service()
    mock_build_service.return_value = service

    data = reply_to_gmail_message(
        message_id="orig-1",
        body="Segue assinado.",
        attachments=[_pdf(tmp_path)],
        cc="carinna@example.com",
        bcc="arquivo@example.com",
    )

    assert data["thread_id"] == "thr-9"
    _, kwargs = service.users.return_value.messages.return_value.send.call_args
    assert kwargs["body"]["threadId"] == "thr-9"

    message = _sent_message(service)
    assert message["In-Reply-To"] == "<seed@mail.example>"
    assert message["References"] == "<seed@mail.example>"
    assert message["To"] == "jose@example.com"
    assert message["Subject"] == "Re: Seguro de Saude"
    assert message["Cc"] == "carinna@example.com"
    assert message["Bcc"] == "arquivo@example.com"
    assert _attachment_parts(message)[0].get_payload(decode=True) == PDF_BYTES


@patch("gw.services.gmail.build_service")
def test_reply_without_attachments_is_unchanged(mock_build_service: MagicMock):
    service = _reply_service()
    mock_build_service.return_value = service

    reply_to_gmail_message(message_id="orig-1", body="Obrigado.")

    message = _sent_message(service)
    assert message.get_content_type() == "text/plain"
    assert message["In-Reply-To"] == "<seed@mail.example>"
    assert message["Cc"] is None


@patch("gw.services.gmail.build_service")
def test_reply_reads_body_from_file(mock_build_service: MagicMock, tmp_path: Path):
    service = _reply_service()
    mock_build_service.return_value = service
    body_file = tmp_path / "reply.txt"
    body_file.write_text("resposta longa", encoding="utf-8")

    reply_to_gmail_message(message_id="orig-1", body=None, body_file=str(body_file))

    assert _sent_message(service).get_payload(decode=True).decode("utf-8") == "resposta longa"


# --- forward ---------------------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_forward_carries_extra_attachments_and_cc(mock_build_service: MagicMock, tmp_path: Path):
    service = _reply_service(ORIGINAL_FULL)
    mock_build_service.return_value = service

    data = forward_gmail_message(
        message_id="orig-1",
        to="terceiro@example.com",
        attachments=[_pdf(tmp_path)],
        cc="carinna@example.com",
    )

    assert data["attachments"] == ["proposta.pdf"]
    message = _sent_message(service)
    assert message["To"] == "terceiro@example.com"
    assert message["Cc"] == "carinna@example.com"
    assert message["Subject"] == "Fwd: Seguro de Saude"
    body = next(
        part
        for part in message.walk()
        if part.get_content_type() == "text/plain"
        and part.get_content_disposition() != "attachment"
    )
    assert "Forwarded message" in body.get_payload(decode=True).decode("utf-8")
    assert _attachment_parts(message)[0].get_payload(decode=True) == PDF_BYTES


# --- CLI wiring ------------------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_cli_send_accepts_repeated_attachment_flag(mock_build_service: MagicMock, tmp_path: Path):
    service = _send_service()
    mock_build_service.return_value = service
    pdf = _pdf(tmp_path)
    jpg = _jpg(tmp_path)

    result = runner.invoke(
        main,
        [
            "gmail",
            "send",
            "jose@example.com",
            "Assunto",
            "Corpo",
            "--attachment",
            str(pdf),
            "--attachment",
            str(jpg),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["attachments"] == ["proposta.pdf", "foto.jpg"]
    assert len(_attachment_parts(_sent_message(service))) == 2


@patch("gw.services.gmail.build_service")
def test_cli_send_rejects_nonexistent_attachment(mock_build_service: MagicMock, tmp_path: Path):
    mock_build_service.return_value = _send_service()

    result = runner.invoke(
        main,
        [
            "gmail",
            "send",
            "a@example.com",
            "S",
            "B",
            "--attachment",
            str(tmp_path / "ghost.pdf"),
        ],
    )

    assert result.exit_code != 0
    assert "does not exist" in result.output


@patch("gw.services.gmail.build_service")
def test_cli_send_body_file_makes_body_optional(mock_build_service: MagicMock, tmp_path: Path):
    service = _send_service()
    mock_build_service.return_value = service
    body_file = tmp_path / "body.txt"
    body_file.write_text("corpo do ficheiro", encoding="utf-8")

    result = runner.invoke(
        main,
        ["gmail", "send", "a@example.com", "S", "--body-file", str(body_file), "--json"],
    )

    assert result.exit_code == 0, result.output
    assert (
        _sent_message(service).get_payload(decode=True).decode("utf-8") == "corpo do ficheiro"
    )


@patch("gw.services.gmail.build_service")
def test_cli_send_rejects_body_and_body_file(mock_build_service: MagicMock, tmp_path: Path):
    mock_build_service.return_value = _send_service()
    body_file = tmp_path / "body.txt"
    body_file.write_text("x", encoding="utf-8")

    result = runner.invoke(
        main,
        ["gmail", "send", "a@example.com", "S", "inline", "--body-file", str(body_file)],
    )

    assert result.exit_code != 0
    assert "not both" in result.output


@patch("gw.services.gmail.build_service")
def test_cli_send_requires_a_body(mock_build_service: MagicMock):
    mock_build_service.return_value = _send_service()

    result = runner.invoke(main, ["gmail", "send", "a@example.com", "S"])

    assert result.exit_code != 0
    assert "--body-file" in result.output


@patch("gw.services.gmail.build_service")
def test_cli_reply_accepts_attachment_and_cc(mock_build_service: MagicMock, tmp_path: Path):
    service = _reply_service()
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "gmail",
            "reply",
            "orig-1",
            "Com anexo",
            "--attachment",
            str(_pdf(tmp_path)),
            "--cc",
            "carinna@example.com",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    message = _sent_message(service)
    assert message["Cc"] == "carinna@example.com"
    assert _attachment_parts(message)[0].get_filename() == "proposta.pdf"


@patch("gw.services.gmail.build_service")
def test_cli_forward_accepts_attachment_and_bcc(mock_build_service: MagicMock, tmp_path: Path):
    service = _reply_service(ORIGINAL_FULL)
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "gmail",
            "forward",
            "orig-1",
            "terceiro@example.com",
            "--attachment",
            str(_pdf(tmp_path)),
            "--bcc",
            "arquivo@example.com",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    message = _sent_message(service)
    assert message["Bcc"] == "arquivo@example.com"
    assert _attachment_parts(message)[0].get_filename() == "proposta.pdf"


@patch("gw.services.gmail.build_service")
def test_cli_draft_accepts_attachment(mock_build_service: MagicMock, tmp_path: Path):
    service = _draft_service()
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "gmail",
            "draft",
            "a@example.com",
            "S",
            "B",
            "--attachment",
            str(_pdf(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _attachment_parts(_drafted_message(service))[0].get_filename() == "proposta.pdf"
