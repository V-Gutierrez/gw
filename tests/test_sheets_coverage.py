from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.services.sheets import (
    add_sheet_tab,
    append_sheet_rows,
    clear_sheet_values,
    create_spreadsheet,
    delete_sheet_tab,
    get_spreadsheet_info,
)


def _service() -> MagicMock:
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    values.append.return_value.execute.return_value = {
        "updates": {"updatedRange": "Sheet1!A5:C5", "updatedRows": 1, "updatedCells": 3}
    }
    values.clear.return_value.execute.return_value = {"clearedRange": "Sheet1!A1:C10"}
    service.spreadsheets.return_value.create.return_value.execute.return_value = {
        "spreadsheetId": "new1",
        "properties": {"title": "Orçamento"},
        "spreadsheetUrl": "https://sheets/new1",
    }
    service.spreadsheets.return_value.get.return_value.execute.return_value = {
        "spreadsheetId": "s1",
        "properties": {"title": "Orçamento", "timeZone": "Europe/Lisbon"},
        "spreadsheetUrl": "https://sheets/s1",
        "sheets": [
            {
                "properties": {
                    "sheetId": 0,
                    "title": "Sheet1",
                    "index": 0,
                    "gridProperties": {"rowCount": 1000, "columnCount": 26},
                }
            }
        ],
    }
    service.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
        "replies": [{"addSheet": {"properties": {"sheetId": 42, "title": "Nova"}}}]
    }
    return service


def test_append_parses_a_json_row() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        data = append_sheet_rows("s1", "Sheet1!A:C", '["ana", 10, "pago"]')

    kwargs = service.spreadsheets.return_value.values.return_value.append.call_args.kwargs
    assert kwargs["body"] == {"values": [["ana", 10, "pago"]]}
    assert kwargs["insertDataOption"] == "INSERT_ROWS"
    assert data["updated_rows"] == 1


def test_append_accepts_several_rows() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        append_sheet_rows("s1", "Sheet1!A:B", '[["a", 1], ["b", 2]]')

    body = service.spreadsheets.return_value.values.return_value.append.call_args.kwargs["body"]
    assert body["values"] == [["a", 1], ["b", 2]]


def test_append_treats_plain_text_as_one_cell() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        append_sheet_rows("s1", "Sheet1!A:A", "apenas texto")

    body = service.spreadsheets.return_value.values.return_value.append.call_args.kwargs["body"]
    assert body["values"] == [["apenas texto"]]


def test_append_rejects_a_json_object() -> None:
    service = _service()
    with (
        patch("gw.services.sheets._sheets_service", return_value=service),
        pytest.raises(click.ClickException, match="list"),
    ):
        append_sheet_rows("s1", "Sheet1!A:A", '{"a": 1}')


def test_clear_wipes_a_range() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        data = clear_sheet_values("s1", "Sheet1!A1:C10")

    assert data["cleared_range"] == "Sheet1!A1:C10"


def test_create_spreadsheet_returns_id_and_url() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        data = create_spreadsheet("Orçamento")

    body = service.spreadsheets.return_value.create.call_args.kwargs["body"]
    assert body["properties"]["title"] == "Orçamento"
    assert data["id"] == "new1"
    assert data["url"] == "https://sheets/new1"


def test_create_spreadsheet_with_named_tabs() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        create_spreadsheet("Orçamento", sheets=["Jan", "Fev"])

    body = service.spreadsheets.return_value.create.call_args.kwargs["body"]
    assert [s["properties"]["title"] for s in body["sheets"]] == ["Jan", "Fev"]


def test_info_lists_tabs_with_ids_and_dimensions() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        data = get_spreadsheet_info("s1")

    assert data["title"] == "Orçamento"
    assert data["sheets"][0] == {
        "sheet_id": 0,
        "title": "Sheet1",
        "index": 0,
        "rows": 1000,
        "columns": 26,
    }


def test_add_tab_sends_an_add_sheet_request() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        data = add_sheet_tab("s1", "Nova")

    body = service.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
    assert body["requests"] == [{"addSheet": {"properties": {"title": "Nova"}}}]
    assert data["sheet_id"] == 42


def test_delete_tab_resolves_the_title_to_a_sheet_id() -> None:
    service = _service()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        delete_sheet_tab("s1", "Sheet1")

    body = service.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
    assert body["requests"] == [{"deleteSheet": {"sheetId": 0}}]


def test_delete_tab_errors_on_an_unknown_title() -> None:
    service = _service()
    with (
        patch("gw.services.sheets._sheets_service", return_value=service),
        pytest.raises(click.ClickException, match="Fantasma"),
    ):
        delete_sheet_tab("s1", "Fantasma")


def test_sheets_commands_are_wired() -> None:
    service = _service()
    runner = CliRunner()
    with patch("gw.services.sheets._sheets_service", return_value=service):
        assert runner.invoke(main, ["sheets", "append", "s1", "A:C", '["a"]']).exit_code == 0
        assert runner.invoke(main, ["sheets", "clear", "s1", "A1:C2", "--yes"]).exit_code == 0
        assert runner.invoke(main, ["sheets", "create", "Novo"]).exit_code == 0
        assert runner.invoke(main, ["sheets", "info", "s1"]).exit_code == 0
        assert runner.invoke(main, ["sheets", "add-tab", "s1", "Nova"]).exit_code == 0
        assert (
            runner.invoke(main, ["sheets", "delete-tab", "s1", "Sheet1", "--yes"]).exit_code == 0
        )
