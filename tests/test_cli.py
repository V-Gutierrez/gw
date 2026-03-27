from __future__ import annotations

import json
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import MagicMock, patch

from gw.cli import main, run_cli
from gw.errors import EXIT_AUTH, EXIT_CONFIG, EXIT_GENERAL, GwConfigError


runner = CliRunner()

EXPECTED_SUBGROUPS = [
    "auth",
    "calendar",
    "completion",
    "config",
    "contacts",
    "docs",
    "doctor",
    "drive",
    "gmail",
    "meet",
    "mcp",
    "sheets",
    "tasks",
]


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


def test_root_help_shows_profile_option():
    result = runner.invoke(main, ["--help"])
    assert "--profile" in result.output


def test_root_help_lists_all_subgroups():
    result = runner.invoke(main, ["--help"])
    for name in EXPECTED_SUBGROUPS:
        assert name in result.output, f"Subgroup {name!r} missing from root help"


def test_version_flag():
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.5.0" in result.output


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


def test_profile_flag_passed_to_runtime_config():
    with patch("gw.cli.load_runtime_config") as mock_config:
        cfg = MagicMock()
        cfg.as_dict.return_value = {"profile": "work"}
        mock_config.return_value = cfg

        result = runner.invoke(main, ["--profile", "work", "config", "show", "--json"])

    assert result.exit_code == 0
    mock_config.assert_called_once_with(profile="work")


def test_completion_bash():
    result = runner.invoke(main, ["completion", "bash"])
    assert result.exit_code == 0
    assert "_GW_COMPLETE" in result.output


def test_completion_zsh():
    result = runner.invoke(main, ["completion", "zsh"])
    assert result.exit_code == 0
    assert "_GW_COMPLETE" in result.output


def test_completion_fish():
    result = runner.invoke(main, ["completion", "fish"])
    assert result.exit_code == 0
    assert "_GW_COMPLETE" in result.output


def test_mcp_subgroup_help():
    result = runner.invoke(main, ["mcp", "--help"])
    assert result.exit_code == 0


@patch("gw.cli.run_mcp_server")
@patch("gw.cli.set_mcp_config")
def test_mcp_serve_command(mock_set_mcp_config: MagicMock, mock_run_mcp_server: MagicMock):
    result = runner.invoke(main, ["mcp", "serve"])
    assert result.exit_code == 0
    mock_run_mcp_server.assert_called_once()
    mock_set_mcp_config.assert_called_once()


@patch("gw.doctor.credential_status")
def test_doctor_human_output(mock_status: MagicMock):
    mock_status.return_value = {
        "authenticated": True,
        "token_path": "/tmp/token.json",
        "credentials_path": "/tmp/credentials.json",
        "expiry": None,
        "scopes": [],
    }
    with runner.isolated_filesystem():
        Path("credentials.json").write_text("{}")
        Path("token.json").write_text("{}")
        with patch("gw.cli.load_runtime_config") as mock_config:
            cfg = MagicMock()
            cfg.credentials = Path("credentials.json")
            cfg.token = Path("token.json")
            cfg.timezone = "America/Sao_Paulo"
            mock_config.return_value = cfg
            result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 0
    assert "gw doctor" in result.output
    assert "authentication" in result.output


@patch("gw.doctor.credential_status")
def test_doctor_json_output(mock_status: MagicMock):
    mock_status.return_value = {
        "authenticated": False,
        "token_path": "/tmp/token.json",
        "credentials_path": "/tmp/credentials.json",
        "expiry": None,
        "scopes": [],
    }
    with patch("gw.cli.load_runtime_config") as mock_config:
        cfg = MagicMock()
        cfg.credentials = Path("/tmp/missing-credentials.json")
        cfg.token = Path("/tmp/missing-token.json")
        cfg.timezone = "America/Sao_Paulo"
        mock_config.return_value = cfg
        result = runner.invoke(main, ["doctor", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is False
    assert any(check["name"] == "authentication" for check in data["checks"])


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


def test_contacts_subgroup_help():
    result = runner.invoke(main, ["contacts", "--help"])
    assert result.exit_code == 0


def test_meet_subgroup_help():
    result = runner.invoke(main, ["meet", "--help"])
    assert result.exit_code == 0


def test_tasks_subgroup_help():
    result = runner.invoke(main, ["tasks", "--help"])
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


@patch("gw.services.contacts.build_service")
def test_contacts_search_json(mock_build_service: MagicMock):
    service = MagicMock()
    people = service.people.return_value
    people.searchContacts.side_effect = [
        _mock_execute({"results": []}),
        _mock_execute(
            {
                "results": [
                    {
                        "person": {
                            "resourceName": "people/123",
                            "names": [{"displayName": "Alice Example"}],
                            "emailAddresses": [{"value": "alice@example.com"}],
                            "phoneNumbers": [{"value": "+55 11 99999-0000"}],
                        }
                    }
                ]
            }
        ),
    ]
    mock_build_service.return_value = service

    result = runner.invoke(main, ["contacts", "search", "Alice", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["resource_name"] == "people/123"
    assert data[0]["name"] == "Alice Example"


@patch("gw.services.contacts.build_service")
def test_contacts_list_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.people.return_value.connections.return_value.list.return_value = _mock_execute(
        {
            "connections": [
                {
                    "resourceName": "people/456",
                    "names": [{"displayName": "Bob Example"}],
                    "emailAddresses": [{"value": "bob@example.com"}],
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["contacts", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["resource_name"] == "people/456"
    assert data[0]["emails"] == ["bob@example.com"]


@patch("gw.services.calendar.build_service")
def test_calendar_delete_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.events.return_value.delete.return_value = _mock_execute({})
    mock_build_service.return_value = service

    result = runner.invoke(main, ["calendar", "delete", "evt-1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"deleted": True, "event_id": "evt-1", "calendar": "primary"}


@patch("gw.services.calendar.build_service")
def test_calendar_update_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.events.return_value.patch.return_value = _mock_execute(
        {"id": "evt-1", "htmlLink": "https://calendar/event/evt-1"}
    )
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "calendar",
            "update",
            "evt-1",
            "--title",
            "Updated title",
            "--description",
            "Updated notes",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "evt-1"
    assert data["updated_fields"] == ["description", "summary"]


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


@patch("gw.services.gmail.build_service")
def test_gmail_search_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value = _mock_execute(
        {"messages": [{"id": "abc", "threadId": "thr"}]}
    )
    service.users.return_value.messages.return_value.get.return_value = _mock_execute(
        {
            "id": "abc",
            "threadId": "thr",
            "snippet": "Preview text",
            "labelIds": [],
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

    result = runner.invoke(main, ["gmail", "search", "from:alice@example.com", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["id"] == "abc"


@patch("gw.services.gmail.build_service")
def test_gmail_draft_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.drafts.return_value.create.return_value = _mock_execute(
        {"id": "draft-1", "message": {"id": "msg-1"}}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "draft", "to@example.com", "Subject", "Body", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {
        "id": "draft-1",
        "message_id": "msg-1",
        "to": "to@example.com",
        "subject": "Subject",
    }


@patch("gw.services.gmail.build_service")
def test_gmail_thread_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.get.return_value = _mock_execute(
        {
            "id": "abc",
            "threadId": "thr",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Seed"},
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Date", "value": "Thu, 26 Mar 2026 10:00:00 +0000"},
                ]
            },
        }
    )
    service.users.return_value.threads.return_value.get.return_value = _mock_execute(
        {
            "messages": [
                {
                    "id": "abc",
                    "threadId": "thr",
                    "payload": {
                        "mimeType": "text/plain",
                        "body": {"data": "SGVsbG8="},
                        "headers": [
                            {"name": "Subject", "value": "Hello"},
                            {"name": "From", "value": "alice@example.com"},
                            {"name": "Date", "value": "Thu, 26 Mar 2026 10:00:00 +0000"},
                        ],
                    },
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "thread", "abc", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["thread_id"] == "thr"
    assert data["message_count"] == 1


@patch("gw.services.gmail.build_service")
def test_gmail_count_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value = _mock_execute(
        {"resultSizeEstimate": 7}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "count", "--query", "is:unread", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"query": "is:unread", "count": 7}


@patch("gw.services.gmail.build_service")
def test_gmail_trash_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.trash.return_value = _mock_execute(
        {"id": "abc", "threadId": "thr"}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "trash", "abc", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["trashed"] is True
    assert data["id"] == "abc"


@patch("gw.services.gmail.build_service")
def test_gmail_archive_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.modify.return_value = _mock_execute(
        {"id": "abc", "threadId": "thr", "labelIds": ["CATEGORY_PERSONAL"]}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "archive", "abc", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["archived"] is True
    assert data["id"] == "abc"


@patch("gw.services.gmail.build_service")
def test_gmail_label_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.labels.return_value.list.return_value = _mock_execute(
        {"labels": [{"id": "Label_1", "name": "Work"}]}
    )
    service.users.return_value.messages.return_value.modify.return_value = _mock_execute(
        {"id": "abc", "threadId": "thr", "labelIds": ["Label_1"]}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "label", "abc", "Work", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["label"] == "Work"
    assert data["action"] == "added"


@patch("gw.services.gmail.build_service")
def test_gmail_star_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.modify.return_value = _mock_execute(
        {"id": "abc", "threadId": "thr", "labelIds": ["STARRED"]}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "star", "abc", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["starred"] is True
    assert data["id"] == "abc"


@patch("gw.services.gmail.build_service")
def test_gmail_mark_read_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.modify.return_value = _mock_execute(
        {"id": "abc", "threadId": "thr", "labelIds": []}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "mark-read", "abc", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["read"] is True


@patch("gw.services.gmail.build_service")
def test_gmail_mark_unread_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.messages.return_value.modify.return_value = _mock_execute(
        {"id": "abc", "threadId": "thr", "labelIds": ["UNREAD"]}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["gmail", "mark-unread", "abc", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["read"] is False


@patch("gw.services.calendar.build_service")
def test_calendar_agenda_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.events.return_value.list.return_value = _mock_execute(
        {
            "items": [
                {
                    "id": "evt-1",
                    "summary": "Standup",
                    "start": {"dateTime": "2026-03-27T10:00:00+00:00"},
                    "end": {"dateTime": "2026-03-27T10:30:00+00:00"},
                    "htmlLink": "https://calendar/event/evt-1",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["calendar", "agenda", "--days", "7", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["id"] == "evt-1"


@patch("gw.services.calendar.build_service")
def test_meet_create_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.events.return_value.insert.return_value = _mock_execute(
        {
            "id": "meet-1",
            "summary": "Team Sync",
            "start": {"dateTime": "2026-03-27T10:00:00-04:00", "timeZone": "America/Manaus"},
            "end": {"dateTime": "2026-03-27T10:30:00-04:00", "timeZone": "America/Manaus"},
            "htmlLink": "https://calendar.google.com/event?eid=meet-1",
            "conferenceData": {
                "entryPoints": [
                    {
                        "entryPointType": "video",
                        "uri": "https://meet.google.com/abc-defg-hij",
                    }
                ]
            },
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["meet", "create", "--title", "Team Sync", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "meet-1"
    assert data["meet_link"] == "https://meet.google.com/abc-defg-hij"


@patch("gw.services.calendar.build_service")
def test_calendar_next_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.events.return_value.list.return_value = _mock_execute(
        {
            "items": [
                {
                    "id": "evt-2",
                    "summary": "Next meeting",
                    "start": {"dateTime": "2999-03-27T10:00:00+00:00"},
                    "end": {"dateTime": "2999-03-27T10:30:00+00:00"},
                    "htmlLink": "https://calendar/event/evt-2",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["calendar", "next", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "evt-2"


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


@patch("gw.services.drive.MediaFileUpload")
@patch("gw.services.drive.build_service")
def test_drive_upload_json(mock_build_service: MagicMock, mock_media_upload: MagicMock):
    service = MagicMock()
    service.files.return_value.create.return_value = _mock_execute(
        {
            "id": "file-1",
            "name": "upload.txt",
            "mimeType": "text/plain",
            "webViewLink": "https://drive/file-1",
        }
    )
    mock_build_service.return_value = service
    mock_media_upload.return_value = MagicMock()

    with runner.isolated_filesystem():
        Path("upload.txt").write_text("hello")
        result = runner.invoke(main, ["drive", "upload", "upload.txt", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "file-1"
    assert data["name"] == "upload.txt"


@patch("gw.services.drive.MediaIoBaseDownload")
@patch("gw.services.drive.build_service")
def test_drive_download_json(mock_build_service: MagicMock, mock_downloader_cls: MagicMock):
    service = MagicMock()
    service.files.return_value.get.return_value = _mock_execute(
        {"id": "file-1", "name": "notes.txt", "mimeType": "text/plain", "size": "5"}
    )
    service.files.return_value.get_media.return_value = MagicMock()
    mock_build_service.return_value = service

    def _build_downloader(buffer, _request):
        class Downloader:
            def next_chunk(self):
                buffer.write(b"hello")
                return None, True

        return Downloader()

    mock_downloader_cls.side_effect = _build_downloader

    with runner.isolated_filesystem():
        result = runner.invoke(main, ["drive", "download", "file-1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "file-1"
    assert data["path"].endswith("notes.txt")


@patch("gw.services.drive.build_service")
def test_drive_search_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.files.return_value.list.return_value = _mock_execute(
        {
            "files": [
                {
                    "id": "drive-2",
                    "name": "Quarterly report",
                    "mimeType": "application/pdf",
                    "modifiedTime": "2026-03-26T10:00:00Z",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "search", "name contains 'report'", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["id"] == "drive-2"


@patch("gw.services.drive.build_service")
def test_drive_search_wraps_plain_query(mock_build_service: MagicMock):
    service = MagicMock()
    service.files.return_value.list.return_value = _mock_execute({"files": []})
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "search", "KWAN", "--json"])

    assert result.exit_code == 0
    call_kwargs = service.files.return_value.list.call_args.kwargs
    assert call_kwargs["q"] == "name contains 'KWAN'"


@patch("gw.services.drive.build_service")
def test_drive_mkdir_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.files.return_value.create.return_value = _mock_execute(
        {
            "id": "folder-1",
            "name": "Projects",
            "mimeType": "application/vnd.google-apps.folder",
            "webViewLink": "https://drive.google.com/drive/folders/folder-1",
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "mkdir", "Projects", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "folder-1"
    assert data["mime_type"] == "application/vnd.google-apps.folder"


@patch("gw.services.drive.build_service")
def test_drive_share_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.permissions.return_value.create.return_value = _mock_execute(
        {"id": "perm-1", "emailAddress": "user@example.com", "role": "writer", "type": "user"}
    )
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        ["drive", "share", "file-1", "user@example.com", "--role", "writer", "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["email"] == "user@example.com"
    assert data["role"] == "writer"


@patch("gw.services.drive.build_service")
def test_drive_info_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.files.return_value.get.return_value = _mock_execute(
        {
            "id": "file-1",
            "name": "Report",
            "mimeType": "application/pdf",
            "size": "1024",
            "createdTime": "2026-03-27T10:00:00Z",
            "modifiedTime": "2026-03-27T11:00:00Z",
            "owners": [{"displayName": "Victor"}],
            "webViewLink": "https://drive.google.com/file/d/file-1/view",
            "shared": True,
            "fileExtension": "pdf",
            "description": "Quarterly report",
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "info", "file-1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "Report"
    assert data["shared"] is True


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


@patch("gw.services.sheets.build_service")
def test_sheets_write_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value.update.return_value = _mock_execute(
        {
            "updatedRange": "Sheet1!A1",
            "updatedRows": 1,
            "updatedColumns": 1,
            "updatedCells": 1,
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["sheets", "write", "sheet-id", "Sheet1!A1", "data", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["range"] == "Sheet1!A1"
    assert data["updated_cells"] == 1


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


@patch("gw.services.tasks.build_service")
def test_tasks_lists_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.tasklists.return_value.list.return_value = _mock_execute(
        {"items": [{"id": "list-1", "title": "Personal", "updated": "2026-03-27T00:00:00.000Z"}]}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["tasks", "lists", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["title"] == "Personal"


@patch("gw.services.tasks.build_service")
def test_tasks_list_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.tasks.return_value.list.return_value = _mock_execute(
        {
            "items": [
                {
                    "id": "task-1",
                    "title": "Buy milk",
                    "status": "needsAction",
                    "due": "2026-04-01T00:00:00.000Z",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["tasks", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["id"] == "task-1"
    call_kwargs = service.tasks.return_value.list.call_args.kwargs
    assert call_kwargs["tasklist"] == "@default"


@patch("gw.services.tasks.build_service")
def test_tasks_add_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.tasks.return_value.insert.return_value = _mock_execute(
        {"id": "task-1", "title": "Buy milk", "status": "needsAction"}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["tasks", "add", "Buy milk", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["title"] == "Buy milk"


@patch("gw.services.tasks.build_service")
def test_tasks_complete_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.tasks.return_value.patch.return_value = _mock_execute(
        {"id": "task-1", "title": "Buy milk", "status": "completed", "completed": "2026-03-27T10:00:00Z"}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["tasks", "complete", "task-1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "completed"


@patch("gw.services.tasks.build_service")
def test_tasks_delete_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.tasks.return_value.delete.return_value = _mock_execute({})
    mock_build_service.return_value = service

    result = runner.invoke(main, ["tasks", "delete", "task-1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"deleted": True, "task_id": "task-1", "list_id": "@default"}


@patch("gw.services.gmail.build_service")
def test_run_cli_maps_auth_errors_to_code_2_json(mock_build_service: MagicMock, capsys):
    mock_build_service.side_effect = Exception("should be patched directly")

    with patch(
        "gw.services.gmail.build_service",
        side_effect=__import__("gw.errors", fromlist=["GwAuthError"]).GwAuthError(
            "Not authenticated. Run `gw auth login` first."
        ),
    ):
        exit_code = run_cli(["--json", "gmail", "list"])

    captured = capsys.readouterr()
    assert exit_code == EXIT_AUTH
    assert json.loads(captured.err) == {
        "error": "Not authenticated. Run `gw auth login` first.",
        "code": 2,
    }


def test_run_cli_maps_usage_errors_to_code_1(capsys):
    exit_code = run_cli(["--not-a-real-option"])

    captured = capsys.readouterr()
    assert exit_code == EXIT_GENERAL
    assert "No such option" in captured.err


def test_run_cli_maps_config_errors_to_code_3_json(capsys):
    with patch("gw.cli.load_runtime_config", side_effect=GwConfigError("broken config")):
        exit_code = run_cli(["--json", "config", "show"])

    captured = capsys.readouterr()
    assert exit_code == EXIT_CONFIG
    assert json.loads(captured.err) == {"error": "broken config", "code": 3}
