from __future__ import annotations

import base64
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gw.cli import main
from gw.services.gmail import (
    delete_gmail_draft,
    get_gmail_draft,
    list_gmail_drafts,
    send_gmail_draft,
    update_gmail_draft,
)


def _raw(message: Message) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def _plain_draft(to="a@x.com", subject="Assunto", body="corpo", cc=None) -> Message:
    message = MIMEText(body)
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    return message


def _draft_with_pdf() -> Message:
    message = MIMEMultipart("mixed")
    message.attach(MIMEText("corpo"))
    part = MIMEText("", "plain")
    part.set_payload(base64.b64encode(b"%PDF-1.4 fake").decode())
    part.replace_header("Content-Type", "application/pdf")
    part.add_header("Content-Transfer-Encoding", "base64")
    part.add_header("Content-Disposition", "attachment", filename="velho.pdf")
    message.attach(part)
    message["To"] = "a@x.com"
    message["Subject"] = "Com anexo"
    return message


def _service(existing: Message | None = None) -> MagicMock:
    service = MagicMock()
    drafts = service.users.return_value.drafts.return_value
    if existing is not None:
        drafts.get.return_value.execute.return_value = {
            "id": "d1",
            "message": {"raw": _raw(existing)},
        }
    drafts.update.return_value.execute.return_value = {
        "id": "d1",
        "message": {"id": "m2", "threadId": "t1"},
    }
    return service


def _updated_message(service: MagicMock) -> Message:
    """Decode whatever the code just PUT back to Gmail."""
    import email

    body = service.users.return_value.drafts.return_value.update.call_args.kwargs["body"]
    return email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]))


# ---------------- list / get / send / delete ----------------


def test_list_drafts_returns_id_and_headers() -> None:
    service = MagicMock()
    drafts = service.users.return_value.drafts.return_value
    drafts.list.return_value.execute.return_value = {
        "drafts": [{"id": "d1", "message": {"id": "m1"}}]
    }
    drafts.get.return_value.execute.return_value = {
        "id": "d1",
        "message": {
            "id": "m1",
            "threadId": "t1",
            "snippet": "ola",
            "payload": {
                "headers": [
                    {"name": "To", "value": "a@x.com"},
                    {"name": "Subject", "value": "Assunto"},
                ]
            },
        },
    }
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = list_gmail_drafts(max_results=5)

    assert result == [
        {
            "id": "d1",
            "message_id": "m1",
            "thread_id": "t1",
            "to": "a@x.com",
            "subject": "Assunto",
            "snippet": "ola",
        }
    ]
    # drafts.get rejects metadataHeaders, which messages.get accepts. A MagicMock
    # swallows any kwarg, so only this assertion catches the difference.
    assert "metadataHeaders" not in drafts.get.call_args.kwargs


def test_get_draft_exposes_body_and_attachments() -> None:
    service = MagicMock()
    service.users.return_value.drafts.return_value.get.return_value.execute.return_value = {
        "id": "d1",
        "message": {"raw": _raw(_draft_with_pdf())},
    }
    with patch("gw.services.gmail._gmail_service", return_value=service):
        data = get_gmail_draft("d1")

    assert data["subject"] == "Com anexo"
    assert data["body"] == "corpo"
    assert [a["filename"] for a in data["attachments"]] == ["velho.pdf"]


def test_send_draft_uses_the_drafts_send_endpoint() -> None:
    service = MagicMock()
    service.users.return_value.drafts.return_value.send.return_value.execute.return_value = {
        "id": "m9",
        "threadId": "t9",
    }
    with patch("gw.services.gmail._gmail_service", return_value=service):
        data = send_gmail_draft("d1")

    kwargs = service.users.return_value.drafts.return_value.send.call_args.kwargs
    assert kwargs["body"] == {"id": "d1"}
    assert data["id"] == "m9"


def test_delete_draft_calls_delete() -> None:
    service = MagicMock()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        delete_gmail_draft("d1")

    kwargs = service.users.return_value.drafts.return_value.delete.call_args.kwargs
    assert kwargs["id"] == "d1"


# ---------------- update: the field-preservation contract ----------------


def test_editing_only_the_subject_preserves_to_and_body() -> None:
    service = _service(_plain_draft(to="a@x.com", subject="Velho", body="corpo original"))
    with patch("gw.services.gmail._gmail_service", return_value=service):
        update_gmail_draft("d1", subject="Novo")

    sent = _updated_message(service)
    assert sent["Subject"] == "Novo"
    assert sent["To"] == "a@x.com"
    assert sent.get_payload() == "corpo original"


def test_editing_only_the_body_preserves_subject_and_cc() -> None:
    service = _service(_plain_draft(subject="Mantido", body="v1", cc="c@x.com"))
    with patch("gw.services.gmail._gmail_service", return_value=service):
        update_gmail_draft("d1", body="v2")

    sent = _updated_message(service)
    assert sent["Subject"] == "Mantido"
    assert sent["Cc"] == "c@x.com"
    assert sent.get_payload() == "v2"


def test_update_keeps_the_draft_id_as_the_handle() -> None:
    """The message id changes on every update, so gw must key on the draft id."""
    service = _service(_plain_draft())
    with patch("gw.services.gmail._gmail_service", return_value=service):
        data = update_gmail_draft("d1", subject="Novo")

    assert service.users.return_value.drafts.return_value.update.call_args.kwargs["id"] == "d1"
    assert data["id"] == "d1"


def test_unpassed_attachment_flag_preserves_existing_attachments() -> None:
    service = _service(_draft_with_pdf())
    with patch("gw.services.gmail._gmail_service", return_value=service):
        update_gmail_draft("d1", subject="Novo assunto")

    sent = _updated_message(service)
    names = [p.get_filename() for p in sent.walk() if p.get_filename()]
    assert names == ["velho.pdf"]


def test_passing_attachment_replaces_the_whole_set(tmp_path) -> None:
    novo = tmp_path / "novo.pdf"
    novo.write_bytes(b"%PDF-1.4 novo")
    service = _service(_draft_with_pdf())
    with patch("gw.services.gmail._gmail_service", return_value=service):
        update_gmail_draft("d1", attachments=[str(novo)])

    sent = _updated_message(service)
    names = [p.get_filename() for p in sent.walk() if p.get_filename()]
    assert names == ["novo.pdf"]


def test_clear_attachments_drops_them_all() -> None:
    service = _service(_draft_with_pdf())
    with patch("gw.services.gmail._gmail_service", return_value=service):
        update_gmail_draft("d1", clear_attachments=True)

    sent = _updated_message(service)
    assert [p.get_filename() for p in sent.walk() if p.get_filename()] == []


# ---------------- CLI wiring ----------------


def test_draft_edit_command_is_wired() -> None:
    service = _service(_plain_draft())
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = CliRunner().invoke(main, ["gmail", "draft-edit", "d1", "--subject", "Novo"])

    assert result.exit_code == 0, result.output
    assert _updated_message(service)["Subject"] == "Novo"


def test_draft_edit_without_any_field_is_an_error() -> None:
    service = _service(_plain_draft())
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = CliRunner().invoke(main, ["gmail", "draft-edit", "d1"])

    assert result.exit_code != 0
    assert "nothing to change" in result.output.lower()


def test_drafts_and_draft_send_and_delete_commands_are_wired() -> None:
    service = MagicMock()
    drafts = service.users.return_value.drafts.return_value
    drafts.list.return_value.execute.return_value = {"drafts": []}
    drafts.send.return_value.execute.return_value = {"id": "m9", "threadId": "t9"}
    runner = CliRunner()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        assert runner.invoke(main, ["gmail", "drafts"]).exit_code == 0
        assert runner.invoke(main, ["gmail", "draft-send", "d1"]).exit_code == 0
        assert runner.invoke(main, ["gmail", "draft-delete", "d1", "--yes"]).exit_code == 0
