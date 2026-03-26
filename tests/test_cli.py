from __future__ import annotations

import json
from click.testing import CliRunner
from unittest.mock import MagicMock, patch

from gw.cli import main


runner = CliRunner()

EXPECTED_SUBGROUPS = ["auth", "calendar", "config", "docs", "drive", "gmail", "sheets"]


def _mock_execute(payload):
    request = MagicMock()
    request.execute.return_value = payload
    return request


def test_root_help_exits_zero():
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0


def test_root_help_shows_version_option():
    result = runner.invoke(main, ["--help"])
    assert "--version" in result.output


def test_root_help_shows_json_option():
    result = runner.invoke(main, ["--help"])
    assert "--json" in result.output


def test_root_help_lists_all_subgroups():
    result = runner.invoke(main, ["--help"])
    for name in EXPECTED_SUBGROUPS:
        assert name in result.output, f"Subgroup {name!r} missing from root help"


def test_version_flag():
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_config_show():
    result = runner.invoke(main, ["config", "show"])
    assert result.exit_code == 0
    assert "timezone" in result.output
    assert "America/Sao_Paulo" in result.output


def test_config_show_json():
    result = runner.invoke(main, ["--json", "config", "show"])
    assert result.exit_code == 0
    assert '"timezone"' in result.output


def test_config_path():
    result = runner.invoke(main, ["config", "path"])
    assert result.exit_code == 0
    assert "config.toml" in result.output


def test_config_path_json():
    result = runner.invoke(main, ["--json", "config", "path"])
    assert result.exit_code == 0
    assert '"config_path"' in result.output


def test_calendar_subgroup_help():
    result = runner.invoke(main, ["calendar", "--help"])
    assert result.exit_code == 0


def test_auth_subgroup_help():
    result = runner.invoke(main, ["auth", "--help"])
    assert result.exit_code == 0


def test_gmail_subgroup_help():
    result = runner.invoke(main, ["gmail", "--help"])
    assert result.exit_code == 0


def test_drive_subgroup_help():
    result = runner.invoke(main, ["drive", "--help"])
    assert result.exit_code == 0


def test_sheets_subgroup_help():
    result = runner.invoke(main, ["sheets", "--help"])
    assert result.exit_code == 0


def test_docs_subgroup_help():
    result = runner.invoke(main, ["docs", "--help"])
    assert result.exit_code == 0


def test_calendar_calendars_alias_help():
    result = runner.invoke(main, ["calendar", "calendars", "--help"])
    assert result.exit_code == 0


@patch("gw.services.calendar.build_service")
def test_calendar_today_all_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.calendarList.return_value.list.return_value = _mock_execute(
        {
            "items": [
                {"id": "primary", "summary": "Primary", "primary": True},
                {"id": "team", "summary": "Team"},
            ]
        }
    )
    service.events.return_value.list.side_effect = [
        _mock_execute(
            {"items": [{"summary": "Standup", "start": {"dateTime": "2026-03-26T10:00:00+00:00"}}]}
        ),
        _mock_execute({"items": []}),
    ]
    mock_build_service.return_value = service

    result = runner.invoke(main, ["calendar", "today", "--all", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["summary"] == "Standup"
    assert data[0]["calendar"] == "Primary"


@patch("gw.services.gmail.build_service")
def test_gmail_list_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value = _mock_execute(
        {"messages": [{"id": "abc", "threadId": "thr"}]}
    )
    service.users.return_value.messages.return_value.get.return_value = _mock_execute(
        {
            "id": "abc",
            "threadId": "thr",
            "snippet": "Preview text",
            "labelIds": ["UNREAD"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hello"},
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Date", "value": "Thu, 26 Mar 2026 10:00:00 +0000"},
                ]
            },
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["id"] == "abc"
    assert data[0]["subject"] == "Hello"


@patch("gw.services.drive.build_service")
def test_drive_list_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.files.return_value.list.return_value = _mock_execute(
        {
            "files": [
                {
                    "id": "1",
                    "name": "Doc",
                    "mimeType": "text/plain",
                    "modifiedTime": "2026-03-26T10:00:00Z",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["name"] == "Doc"


@patch("gw.services.sheets.build_service")
def test_sheets_read_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value.get.return_value = _mock_execute(
        {"range": "Sheet1!A1:B2", "values": [["a", "b"], ["1", "2"]]}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["sheets", "read", "sheet-id", "Sheet1!A1:B2", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["rows"][0] == ["a", "b"]


@patch("gw.services.docs.build_service")
def test_docs_list_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.files.return_value.list.return_value = _mock_execute(
        {"files": [{"id": "doc-1", "name": "Notes", "modifiedTime": "2026-03-26T10:00:00Z"}]}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["docs", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["id"] == "doc-1"
