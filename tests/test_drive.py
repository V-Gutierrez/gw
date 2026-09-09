from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.services.drive import (
    delete_drive_file,
    list_drive_files,
    rename_drive_file,
    search_drive_files,
    unshare_drive_file,
)

runner = CliRunner()


def _service_with_files(files: list[dict]) -> MagicMock:
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": files}
    return service


@patch("gw.services.drive.execute_google_request")
@patch("gw.services.drive._drive_service")
def test_list_drive_files_includes_shared_drives(mock_drive_service, mock_execute):
    service = _service_with_files([{"id": "1", "name": "a"}])
    mock_drive_service.return_value = service
    mock_execute.side_effect = lambda request: request.execute()

    list_drive_files(max_results=10)

    _, kwargs = service.files.return_value.list.call_args
    assert kwargs.get("includeItemsFromAllDrives") is True
    assert kwargs.get("supportsAllDrives") is True
    assert kwargs.get("corpora") == "allDrives"


@patch("gw.services.drive.execute_google_request")
@patch("gw.services.drive._drive_service")
def test_search_drive_files_includes_shared_drives(mock_drive_service, mock_execute):
    service = _service_with_files([{"id": "1", "name": "frozen_history_pre2026.enc"}])
    mock_drive_service.return_value = service
    mock_execute.side_effect = lambda request: request.execute()

    results = search_drive_files(query="frozen_history_pre2026")

    _, kwargs = service.files.return_value.list.call_args
    assert kwargs.get("includeItemsFromAllDrives") is True
    assert kwargs.get("supportsAllDrives") is True
    assert kwargs.get("corpora") == "allDrives"
    assert results == [{"id": "1", "name": "frozen_history_pre2026.enc"}]


@patch("gw.services.drive.execute_google_request")
@patch("gw.services.drive._drive_service")
def test_delete_drive_file_trashes_by_default(mock_drive_service, mock_execute):
    service = MagicMock()
    mock_drive_service.return_value = service
    mock_execute.return_value = {"id": "f1", "name": "doc.pdf", "trashed": True}

    data = delete_drive_file(file_id="f1")

    _, kwargs = service.files.return_value.update.call_args
    assert kwargs["fileId"] == "f1"
    assert kwargs["body"] == {"trashed": True}
    assert kwargs["supportsAllDrives"] is True
    service.files.return_value.delete.assert_not_called()
    assert data == {
        "id": "f1",
        "name": "doc.pdf",
        "trashed": True,
        "permanent": False,
    }


@patch("gw.services.drive.execute_google_request")
@patch("gw.services.drive._drive_service")
def test_delete_drive_file_permanent_calls_delete(mock_drive_service, mock_execute):
    service = MagicMock()
    mock_drive_service.return_value = service
    mock_execute.return_value = {}

    data = delete_drive_file(file_id="f1", permanent=True)

    _, kwargs = service.files.return_value.delete.call_args
    assert kwargs["fileId"] == "f1"
    assert kwargs["supportsAllDrives"] is True
    service.files.return_value.update.assert_not_called()
    assert data == {"id": "f1", "name": None, "trashed": False, "permanent": True}


@patch("gw.services.drive.execute_google_request")
@patch("gw.services.drive._drive_service")
def test_rename_drive_file_patches_name(mock_drive_service, mock_execute):
    service = MagicMock()
    mock_drive_service.return_value = service
    mock_execute.return_value = {"id": "f1", "name": "Novo Nome.pdf"}

    data = rename_drive_file(file_id="f1", name="Novo Nome.pdf")

    _, kwargs = service.files.return_value.update.call_args
    assert kwargs["body"] == {"name": "Novo Nome.pdf"}
    assert kwargs["supportsAllDrives"] is True
    assert data["name"] == "Novo Nome.pdf"


@patch("gw.services.drive.execute_google_request")
@patch("gw.services.drive._drive_service")
def test_unshare_drive_file_finds_permission_by_email(mock_drive_service, mock_execute):
    service = MagicMock()
    mock_drive_service.return_value = service
    mock_execute.side_effect = [
        {
            "permissions": [
                {"id": "p1", "emailAddress": "owner@example.com", "role": "owner"},
                {"id": "p2", "emailAddress": "Carinna@Example.com", "role": "writer"},
            ]
        },
        {},
    ]

    data = unshare_drive_file(file_id="f1", email="carinna@example.com")

    _, kwargs = service.permissions.return_value.delete.call_args
    assert kwargs["permissionId"] == "p2"
    assert kwargs["fileId"] == "f1"
    assert data["removed"] is True
    assert data["role"] == "writer"
    assert data["email"] == "Carinna@Example.com"


@patch("gw.services.drive.execute_google_request")
@patch("gw.services.drive._drive_service")
def test_unshare_drive_file_errors_without_permission(mock_drive_service, mock_execute):
    mock_drive_service.return_value = MagicMock()
    mock_execute.return_value = {"permissions": [{"id": "p1", "emailAddress": "a@b.com"}]}

    with pytest.raises(click.ClickException, match="No permission"):
        unshare_drive_file(file_id="f1", email="ghost@example.com")


@patch("gw.services.drive.build_service")
def test_cli_drive_delete_trashes_and_reports_json(mock_build_service: MagicMock):
    service = MagicMock()
    request = MagicMock()
    request.execute.return_value = {"id": "f1", "name": "doc.pdf", "trashed": True}
    service.files.return_value.update.return_value = request
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "delete", "f1", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["trashed"] is True


@patch("gw.services.drive.build_service")
def test_cli_drive_permanent_delete_requires_confirmation(mock_build_service: MagicMock):
    service = MagicMock()
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "delete", "f1", "--permanent"], input="n\n")

    assert result.exit_code != 0
    service.files.return_value.delete.assert_not_called()


@patch("gw.services.drive.build_service")
def test_cli_drive_permanent_delete_runs_with_yes(mock_build_service: MagicMock):
    service = MagicMock()
    request = MagicMock()
    request.execute.return_value = {}
    service.files.return_value.delete.return_value = request
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "delete", "f1", "--permanent", "--yes", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["permanent"] is True


@patch("gw.services.drive.build_service")
def test_cli_drive_rename_json(mock_build_service: MagicMock):
    service = MagicMock()
    request = MagicMock()
    request.execute.return_value = {"id": "f1", "name": "Renomeado.pdf"}
    service.files.return_value.update.return_value = request
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "rename", "f1", "Renomeado.pdf", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["name"] == "Renomeado.pdf"


@patch("gw.services.drive.build_service")
def test_cli_drive_unshare_json(mock_build_service: MagicMock):
    service = MagicMock()
    list_request = MagicMock()
    list_request.execute.return_value = {
        "permissions": [{"id": "p2", "emailAddress": "carinna@example.com", "role": "reader"}]
    }
    delete_request = MagicMock()
    delete_request.execute.return_value = {}
    service.permissions.return_value.list.return_value = list_request
    service.permissions.return_value.delete.return_value = delete_request
    mock_build_service.return_value = service

    result = runner.invoke(main, ["drive", "unshare", "f1", "carinna@example.com", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["removed"] is True
