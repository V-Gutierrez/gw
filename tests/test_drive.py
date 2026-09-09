from __future__ import annotations

from unittest.mock import MagicMock, patch

from gw.services.drive import list_drive_files, search_drive_files


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
