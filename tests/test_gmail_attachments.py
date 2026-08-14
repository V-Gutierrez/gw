from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.services.gmail import download_gmail_attachments, list_gmail_attachments
from gw.utils import extract_attachments, safe_attachment_filename

runner = CliRunner()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


PDF_BYTES = b"%PDF-1.4 fake report"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"
CSV_BYTES = b"a,b\n"


def _message(parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "msg-1",
        "threadId": "thr-1",
        "payload": {
            "mimeType": "multipart/mixed",
            "filename": "",
            "body": {"size": 0},
            "headers": [
                {"name": "Subject", "value": "Tech Lead | Conversa"},
                {"name": "From", "value": "alice@example.com"},
                {"name": "Date", "value": "Sat, 09 Aug 2026 12:00:00 +0100"},
            ],
            "parts": parts,
        },
    }


TEXT_PART = {
    "partId": "0",
    "mimeType": "text/plain",
    "filename": "",
    "body": {"data": _b64(b"Hello"), "size": 5},
}

INLINE_IMAGE_PART = {
    "partId": "1",
    "mimeType": "multipart/related",
    "filename": "",
    "body": {"size": 0},
    "parts": [
        {
            "partId": "1.0",
            "mimeType": "image/png",
            "filename": "image.png",
            "headers": [
                {"name": "Content-Disposition", "value": 'inline; filename="image.png"'},
                {"name": "Content-ID", "value": "<img001>"},
            ],
            "body": {"attachmentId": "att-png", "size": len(PNG_BYTES)},
        }
    ],
}

PDF_PART = {
    "partId": "2",
    "mimeType": "application/pdf",
    "filename": "report.pdf",
    "headers": [{"name": "Content-Disposition", "value": 'attachment; filename="report.pdf"'}],
    "body": {"attachmentId": "att-pdf", "size": len(PDF_BYTES)},
}

SMALL_CSV_PART = {
    "partId": "3",
    "mimeType": "text/csv",
    "filename": "tiny.csv",
    "headers": [{"name": "Content-Disposition", "value": 'attachment; filename="tiny.csv"'}],
    "body": {"data": _b64(CSV_BYTES), "size": len(CSV_BYTES)},
}

FULL_MESSAGE = _message([TEXT_PART, INLINE_IMAGE_PART, PDF_PART, SMALL_CSV_PART])

ATTACHMENT_BYTES = {"att-png": PNG_BYTES, "att-pdf": PDF_BYTES}


def _mock_execute(payload: Any) -> MagicMock:
    request = MagicMock()
    request.execute.return_value = payload
    return request


def _mock_service(message: dict[str, Any] = FULL_MESSAGE) -> MagicMock:
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.get.return_value = _mock_execute(message)

    def attachment_get(userId: str, messageId: str, id: str) -> MagicMock:
        raw = ATTACHMENT_BYTES[id]
        return _mock_execute({"size": len(raw), "data": _b64(raw)})

    messages.attachments.return_value.get.side_effect = attachment_get
    return service


# --- utils.extract_attachments -------------------------------------------------


def test_extract_attachments_walks_nested_parts_and_skips_body_parts():
    attachments = extract_attachments(FULL_MESSAGE["payload"])

    assert [item["filename"] for item in attachments] == ["image.png", "report.pdf", "tiny.csv"]


def test_extract_attachments_marks_inline_parts():
    by_name = {item["filename"]: item for item in extract_attachments(FULL_MESSAGE["payload"])}

    assert by_name["image.png"]["inline"] is True
    assert by_name["image.png"]["content_id"] == "img001"
    assert by_name["report.pdf"]["inline"] is False


def test_extract_attachments_reports_ids_and_sizes():
    by_name = {item["filename"]: item for item in extract_attachments(FULL_MESSAGE["payload"])}

    assert by_name["report.pdf"]["attachment_id"] == "att-pdf"
    assert by_name["report.pdf"]["mime_type"] == "application/pdf"
    assert by_name["report.pdf"]["size"] == len(PDF_BYTES)
    # Small attachments arrive inline in body.data, with no attachmentId.
    assert by_name["tiny.csv"]["attachment_id"] is None


def test_extract_attachments_hides_raw_data_unless_requested():
    listed = extract_attachments(FULL_MESSAGE["payload"])
    assert all("data" not in item for item in listed)

    with_data = extract_attachments(FULL_MESSAGE["payload"], include_data=True)
    by_name = {item["filename"]: item for item in with_data}
    assert by_name["tiny.csv"]["data"] == _b64(CSV_BYTES)


def test_extract_attachments_handles_empty_payload():
    assert extract_attachments(None) == []
    assert extract_attachments({"mimeType": "text/plain", "body": {"data": "x"}}) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("/etc/passwd", "passwd"),
        ("..", "fallback.bin"),
        ("", "fallback.bin"),
        ("dir\\..\\evil.sh", "evil.sh"),
    ],
)
def test_safe_attachment_filename_strips_paths(raw: str, expected: str):
    assert safe_attachment_filename(raw, "fallback.bin") == expected


# --- list_gmail_attachments ----------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_list_gmail_attachments_returns_message_context(mock_build_service: MagicMock):
    mock_build_service.return_value = _mock_service()

    data = list_gmail_attachments("msg-1")

    assert data["message_id"] == "msg-1"
    assert data["subject"] == "Tech Lead | Conversa"
    assert data["count"] == 3
    assert data["attachments"][0]["filename"] == "image.png"


@patch("gw.services.gmail.build_service")
def test_gmail_attachments_command_json(mock_build_service: MagicMock):
    mock_build_service.return_value = _mock_service()

    result = runner.invoke(main, ["gmail", "attachments", "msg-1", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["count"] == 3


@patch("gw.services.gmail.build_service")
def test_gmail_attachments_command_human_output(mock_build_service: MagicMock):
    mock_build_service.return_value = _mock_service()

    result = runner.invoke(main, ["gmail", "attachments", "msg-1"])

    assert result.exit_code == 0, result.output
    assert "report.pdf" in result.output
    assert "att-pdf" in result.output


@patch("gw.services.gmail.build_service")
def test_gmail_attachments_command_reports_empty_message(mock_build_service: MagicMock):
    mock_build_service.return_value = _mock_service(_message([TEXT_PART]))

    result = runner.invoke(main, ["gmail", "attachments", "msg-1"])

    assert result.exit_code == 0, result.output
    assert "No attachments" in result.output


# --- download_gmail_attachments ------------------------------------------------


@patch("gw.services.gmail.build_service")
def test_download_writes_every_attachment_by_default(
    mock_build_service: MagicMock, tmp_path: Path
):
    mock_build_service.return_value = _mock_service()

    data = download_gmail_attachments("msg-1", directory=str(tmp_path))

    assert data["count"] == 3
    assert (tmp_path / "image.png").read_bytes() == PNG_BYTES
    assert (tmp_path / "report.pdf").read_bytes() == PDF_BYTES
    assert (tmp_path / "tiny.csv").read_bytes() == CSV_BYTES


@patch("gw.services.gmail.build_service")
def test_download_filters_by_attachment_id(mock_build_service: MagicMock, tmp_path: Path):
    mock_build_service.return_value = _mock_service()

    data = download_gmail_attachments("msg-1", attachment_id="att-pdf", directory=str(tmp_path))

    assert data["count"] == 1
    assert data["attachments"][0]["path"] == str(tmp_path / "report.pdf")
    assert not (tmp_path / "image.png").exists()


@patch("gw.services.gmail.build_service")
def test_download_filters_by_filename_case_insensitively(
    mock_build_service: MagicMock, tmp_path: Path
):
    mock_build_service.return_value = _mock_service()

    data = download_gmail_attachments("msg-1", filename="IMAGE.PNG", directory=str(tmp_path))

    assert data["count"] == 1
    assert (tmp_path / "image.png").read_bytes() == PNG_BYTES


@patch("gw.services.gmail.build_service")
def test_download_honours_output_path_for_single_attachment(
    mock_build_service: MagicMock, tmp_path: Path
):
    mock_build_service.return_value = _mock_service()
    target = tmp_path / "nested" / "renamed.png"

    data = download_gmail_attachments("msg-1", filename="image.png", output_path=str(target))

    assert target.read_bytes() == PNG_BYTES
    assert data["attachments"][0]["path"] == str(target)


@patch("gw.services.gmail.build_service")
def test_download_rejects_output_path_for_multiple_attachments(
    mock_build_service: MagicMock, tmp_path: Path
):
    mock_build_service.return_value = _mock_service()

    with pytest.raises(Exception) as excinfo:
        download_gmail_attachments("msg-1", output_path=str(tmp_path / "one.bin"))

    assert "--output" in str(excinfo.value)


@patch("gw.services.gmail.build_service")
def test_download_raises_when_message_has_no_attachments(
    mock_build_service: MagicMock, tmp_path: Path
):
    mock_build_service.return_value = _mock_service(_message([TEXT_PART]))

    with pytest.raises(Exception) as excinfo:
        download_gmail_attachments("msg-1", directory=str(tmp_path))

    assert "no attachments" in str(excinfo.value).lower()


@patch("gw.services.gmail.build_service")
def test_download_raises_on_unknown_filename(mock_build_service: MagicMock, tmp_path: Path):
    mock_build_service.return_value = _mock_service()

    with pytest.raises(Exception) as excinfo:
        download_gmail_attachments("msg-1", filename="nope.txt", directory=str(tmp_path))

    assert "nope.txt" in str(excinfo.value)


@patch("gw.services.gmail.build_service")
def test_download_keeps_traversal_filenames_inside_target_dir(
    mock_build_service: MagicMock, tmp_path: Path
):
    evil_part = {
        "partId": "1",
        "mimeType": "application/x-sh",
        "filename": "../../evil.sh",
        "headers": [{"name": "Content-Disposition", "value": "attachment"}],
        "body": {"data": _b64(b"rm -rf /"), "size": 8},
    }
    mock_build_service.return_value = _mock_service(_message([TEXT_PART, evil_part]))
    target_dir = tmp_path / "downloads"
    target_dir.mkdir()

    data = download_gmail_attachments("msg-1", directory=str(target_dir))

    assert data["attachments"][0]["path"] == str(target_dir / "evil.sh")
    assert (target_dir / "evil.sh").exists()
    assert not (tmp_path.parent / "evil.sh").exists()


@patch("gw.services.gmail.build_service")
def test_download_deduplicates_repeated_filenames(mock_build_service: MagicMock, tmp_path: Path):
    duplicate = dict(SMALL_CSV_PART, partId="4")
    mock_build_service.return_value = _mock_service(
        _message([TEXT_PART, SMALL_CSV_PART, duplicate])
    )

    data = download_gmail_attachments("msg-1", directory=str(tmp_path))

    paths = [item["path"] for item in data["attachments"]]
    assert paths == [str(tmp_path / "tiny.csv"), str(tmp_path / "tiny-2.csv")]


@patch("gw.services.gmail.build_service")
def test_gmail_download_command_json(mock_build_service: MagicMock, tmp_path: Path):
    mock_build_service.return_value = _mock_service()

    result = runner.invoke(main, ["gmail", "download", "msg-1", "--dir", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["count"] == 3


@patch("gw.services.gmail.build_service")
def test_gmail_download_command_exits_nonzero_without_attachments(
    mock_build_service: MagicMock, tmp_path: Path
):
    mock_build_service.return_value = _mock_service(_message([TEXT_PART]))

    result = runner.invoke(main, ["gmail", "download", "msg-1", "--dir", str(tmp_path)])

    assert result.exit_code != 0


# --- gmail read surfaces attachment metadata -----------------------------------


@patch("gw.services.gmail.build_service")
def test_gmail_read_lists_attachments(mock_build_service: MagicMock):
    mock_build_service.return_value = _mock_service()

    result = runner.invoke(main, ["gmail", "read", "msg-1", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [item["filename"] for item in data["attachments"]] == [
        "image.png",
        "report.pdf",
        "tiny.csv",
    ]
