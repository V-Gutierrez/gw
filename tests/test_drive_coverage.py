from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.services.drive import (
    add_drive_comment,
    copy_drive_file,
    delete_drive_revision,
    get_drive_about,
    list_drive_comments,
    list_drive_revisions,
    list_shared_drives,
    move_drive_file,
)


def _service() -> MagicMock:
    service = MagicMock()
    service.files.return_value.copy.return_value.execute.return_value = {
        "id": "copy1",
        "name": "Cópia de Contrato",
        "webViewLink": "https://drive/copy1",
    }
    service.files.return_value.get.return_value.execute.return_value = {
        "id": "f1",
        "name": "Contrato",
        "parents": ["old_folder"],
    }
    service.files.return_value.update.return_value.execute.return_value = {
        "id": "f1",
        "name": "Contrato",
        "parents": ["new_folder"],
    }
    service.about.return_value.get.return_value.execute.return_value = {
        "user": {"emailAddress": "victor@x.com", "displayName": "Victor"},
        "storageQuota": {"limit": "16106127360", "usage": "8053063680", "usageInDrive": "1000"},
    }
    service.revisions.return_value.list.return_value.execute.return_value = {
        "revisions": [
            {
                "id": "r1",
                "modifiedTime": "2026-09-01T10:00:00Z",
                "lastModifyingUser": {"displayName": "Victor"},
                "size": "1024",
            }
        ]
    }
    service.comments.return_value.list.return_value.execute.return_value = {
        "comments": [
            {
                "id": "c1",
                "content": "rever cláusula 3",
                "author": {"displayName": "Ana"},
                "createdTime": "2026-09-02T09:00:00Z",
                "resolved": False,
                "replies": [],
            }
        ]
    }
    service.comments.return_value.create.return_value.execute.return_value = {
        "id": "c2",
        "content": "feito",
        "author": {"displayName": "Victor"},
    }
    service.drives.return_value.list.return_value.execute.return_value = {
        "drives": [{"id": "d1", "name": "Equipa VC"}]
    }
    return service


def test_copy_keeps_the_original_and_returns_a_new_id() -> None:
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        data = copy_drive_file("f1", name="Cópia de Contrato", folder="dest")

    kwargs = service.files.return_value.copy.call_args.kwargs
    assert kwargs["fileId"] == "f1"
    assert kwargs["body"]["name"] == "Cópia de Contrato"
    assert kwargs["body"]["parents"] == ["dest"]
    assert data["id"] == "copy1"


def test_move_swaps_parents_rather_than_adding_one() -> None:
    """A file with two parents shows up in two folders; move must remove the old."""
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        move_drive_file("f1", folder="new_folder")

    kwargs = service.files.return_value.update.call_args.kwargs
    assert kwargs["addParents"] == "new_folder"
    assert kwargs["removeParents"] == "old_folder"


def test_about_reports_storage_quota() -> None:
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        data = get_drive_about()

    assert data["email"] == "victor@x.com"
    assert data["limit"] == 16106127360
    assert data["usage"] == 8053063680
    assert data["percent_used"] == 50.0


def test_about_handles_unlimited_storage() -> None:
    service = _service()
    service.about.return_value.get.return_value.execute.return_value = {
        "user": {"emailAddress": "v@x.com"},
        "storageQuota": {"usage": "100"},
    }
    with patch("gw.services.drive._drive_service", return_value=service):
        data = get_drive_about()

    assert data["limit"] is None
    assert data["percent_used"] is None


def test_revisions_list_returns_version_history() -> None:
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        data = list_drive_revisions("f1")

    assert data[0]["id"] == "r1"
    assert data[0]["modified_by"] == "Victor"


def test_delete_revision_targets_file_and_revision() -> None:
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        delete_drive_revision("f1", "r1")

    kwargs = service.revisions.return_value.delete.call_args.kwargs
    assert kwargs["fileId"] == "f1"
    assert kwargs["revisionId"] == "r1"


def test_comments_list_requests_the_required_fields() -> None:
    """Drive's comments.list returns nothing useful unless fields are named."""
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        data = list_drive_comments("f1")

    assert "fields" in service.comments.return_value.list.call_args.kwargs
    assert data[0]["content"] == "rever cláusula 3"
    assert data[0]["author"] == "Ana"


def test_add_comment_posts_content() -> None:
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        data = add_drive_comment("f1", "feito")

    assert service.comments.return_value.create.call_args.kwargs["body"] == {"content": "feito"}
    assert data["id"] == "c2"


def test_shared_drives_are_listed() -> None:
    service = _service()
    with patch("gw.services.drive._drive_service", return_value=service):
        data = list_shared_drives()

    assert data[0]["name"] == "Equipa VC"


def test_move_errors_when_the_file_has_no_parents() -> None:
    service = _service()
    service.files.return_value.get.return_value.execute.return_value = {"id": "f1", "name": "X"}
    with (
        patch("gw.services.drive._drive_service", return_value=service),
        pytest.raises(click.ClickException),
    ):
        move_drive_file("f1", folder="new_folder")


def test_drive_commands_are_wired() -> None:
    service = _service()
    runner = CliRunner()
    with patch("gw.services.drive._drive_service", return_value=service):
        assert runner.invoke(main, ["drive", "copy", "f1"]).exit_code == 0
        assert runner.invoke(main, ["drive", "move", "f1", "new_folder"]).exit_code == 0
        assert runner.invoke(main, ["drive", "about"]).exit_code == 0
        assert runner.invoke(main, ["drive", "revisions", "f1"]).exit_code == 0
        assert runner.invoke(main, ["drive", "comments", "f1"]).exit_code == 0
        assert runner.invoke(main, ["drive", "comment", "f1", "feito"]).exit_code == 0
        assert runner.invoke(main, ["drive", "drives"]).exit_code == 0
        assert runner.invoke(main, ["drive", "permissions", "f1"]).exit_code == 0
