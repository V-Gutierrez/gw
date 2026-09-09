from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, use_json_output


def _sheets_service(config: GWConfig | None = None):
    return build_service("sheets", "v4", config=config)


def _parse_values(raw: str) -> list[list[Any]]:
    """Turn the VALUES argument into rows.

    A JSON list of lists is several rows, a flat JSON list is one row, and
    anything that is not JSON at all is a single cell.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [[raw]]

    if not isinstance(parsed, list):
        raise click.ClickException(
            "VALUES must be a JSON list (a row) or a list of lists (several rows), "
            f"not {type(parsed).__name__}."
        )
    if parsed and all(isinstance(item, list) for item in parsed):
        return parsed
    return [parsed]


def read_sheet_values(
    spreadsheet_id: str,
    range_name: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _sheets_service(config)
    response = execute_google_request(
        service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name)
    )
    values = response.get("values", [])
    return {"spreadsheet_id": spreadsheet_id, "range": range_name, "rows": values}


def write_sheet_value(
    spreadsheet_id: str,
    range_name: str,
    value: str,
    raw: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _sheets_service(config)
    result = execute_google_request(
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW" if raw else "USER_ENTERED",
            body={"values": [[value]]},
        )
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "range": result.get("updatedRange", range_name),
        "updated_rows": result.get("updatedRows", 0),
        "updated_columns": result.get("updatedColumns", 0),
        "updated_cells": result.get("updatedCells", 0),
        "value_input_option": "RAW" if raw else "USER_ENTERED",
    }


def append_sheet_rows(
    spreadsheet_id: str,
    range_name: str,
    values: str,
    raw: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Append rows after the last row with data in the range."""
    service = _sheets_service(config)
    result = execute_google_request(
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW" if raw else "USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": _parse_values(values)},
        )
    )
    updates = result.get("updates", {})
    return {
        "spreadsheet_id": spreadsheet_id,
        "range": updates.get("updatedRange", range_name),
        "updated_rows": updates.get("updatedRows", 0),
        "updated_cells": updates.get("updatedCells", 0),
    }


def clear_sheet_values(
    spreadsheet_id: str,
    range_name: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Clear the values in a range, leaving the formatting alone."""
    service = _sheets_service(config)
    result = execute_google_request(
        service.spreadsheets()
        .values()
        .clear(spreadsheetId=spreadsheet_id, range=range_name, body={})
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "cleared_range": result.get("clearedRange", range_name),
    }


def create_spreadsheet(
    title: str,
    sheets: Sequence[str] | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _sheets_service(config)
    body: dict[str, Any] = {"properties": {"title": title}}
    if sheets:
        body["sheets"] = [{"properties": {"title": name}} for name in sheets]
    created = execute_google_request(service.spreadsheets().create(body=body))
    return {
        "id": created.get("spreadsheetId"),
        "title": created.get("properties", {}).get("title", title),
        "url": created.get("spreadsheetUrl"),
    }


def get_spreadsheet_info(
    spreadsheet_id: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Show a spreadsheet's tabs, their ids and their dimensions."""
    service = _sheets_service(config)
    data = execute_google_request(
        service.spreadsheets().get(spreadsheetId=spreadsheet_id, includeGridData=False)
    )
    sheets = []
    for sheet in data.get("sheets", []):
        properties = sheet.get("properties", {})
        grid = properties.get("gridProperties", {})
        sheets.append(
            {
                "sheet_id": properties.get("sheetId"),
                "title": properties.get("title"),
                "index": properties.get("index"),
                "rows": grid.get("rowCount"),
                "columns": grid.get("columnCount"),
            }
        )
    return {
        "id": data.get("spreadsheetId", spreadsheet_id),
        "title": data.get("properties", {}).get("title", ""),
        "timezone": data.get("properties", {}).get("timeZone"),
        "url": data.get("spreadsheetUrl"),
        "sheets": sheets,
    }


def add_sheet_tab(
    spreadsheet_id: str,
    title: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _sheets_service(config)
    result = execute_google_request(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        )
    )
    properties = (
        result.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_id": properties.get("sheetId"),
        "title": properties.get("title", title),
    }


def delete_sheet_tab(
    spreadsheet_id: str,
    title: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Delete a tab by name, resolving the name to Sheets' numeric sheetId."""
    info = get_spreadsheet_info(spreadsheet_id, config=config)
    match = next((sheet for sheet in info["sheets"] if sheet["title"] == title), None)
    if match is None:
        available = ", ".join(sheet["title"] or "" for sheet in info["sheets"])
        raise click.ClickException(
            f"No tab named {title!r} in this spreadsheet. Available: {available}"
        )

    service = _sheets_service(config)
    execute_google_request(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": match["sheet_id"]}}]},
        )
    )
    return {"spreadsheet_id": spreadsheet_id, "title": title, "deleted": True}


def register_sheets_commands(group: click.Group) -> None:
    @group.command("append")
    @click.argument("spreadsheet_id")
    @click.argument("range_name")
    @click.argument("values")
    @click.option("--raw", is_flag=True, help="Write the values without Sheets parsing.")
    @json_option
    @click.pass_context
    def append_command(
        ctx: click.Context,
        spreadsheet_id: str,
        range_name: str,
        values: str,
        raw: bool,
        json_output: bool | None,
    ) -> None:
        """Append rows after the last row with data.

        VALUES is a JSON list for one row ('["ana", 10]') or a list of lists for
        several ('[["a",1],["b",2]]'). Plain text becomes a single cell.
        """
        data = append_sheet_rows(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            values=values,
            raw=raw,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(
                f"Appended {data['updated_rows']} row(s) to {data['range']}",
                emoji="📊",
            )

    @group.command("clear")
    @click.argument("spreadsheet_id")
    @click.argument("range_name")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def clear_command(
        ctx: click.Context,
        spreadsheet_id: str,
        range_name: str,
        yes: bool,
        json_output: bool | None,
    ) -> None:
        """Clear the values in a range. Formatting is left alone."""
        if not yes:
            click.confirm(f"Clear every value in {range_name}?", abort=True)
        data = clear_sheet_values(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Cleared {data['cleared_range']}", emoji="📊")

    @group.command("create")
    @click.argument("title")
    @click.option("--sheet", "sheets", multiple=True, help="Tab name. Repeat for several.")
    @json_option
    @click.pass_context
    def create_command(
        ctx: click.Context, title: str, sheets: tuple[str, ...], json_output: bool | None
    ) -> None:
        """Create a new spreadsheet."""
        data = create_spreadsheet(title, sheets=list(sheets), config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Spreadsheet created: {data['title']}", emoji="📊")
            print_human(f"  ID: {data['id']}")
            if data.get("url"):
                print_human(f"  {data['url']}")

    @group.command("info")
    @click.argument("spreadsheet_id")
    @json_option
    @click.pass_context
    def info_command(ctx: click.Context, spreadsheet_id: str, json_output: bool | None) -> None:
        """Show a spreadsheet's tabs, their IDs and their sizes."""
        data = get_spreadsheet_info(spreadsheet_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"{data['title']} ({data['id']})", emoji="📊")
            for sheet in data["sheets"]:
                print_human(
                    f"  • {sheet['title']} — id {sheet['sheet_id']}, "
                    f"{sheet['rows']}x{sheet['columns']}"
                )

    @group.command("add-tab")
    @click.argument("spreadsheet_id")
    @click.argument("title")
    @json_option
    @click.pass_context
    def add_tab_command(
        ctx: click.Context, spreadsheet_id: str, title: str, json_output: bool | None
    ) -> None:
        """Add a tab to an existing spreadsheet."""
        data = add_sheet_tab(spreadsheet_id, title, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Tab {data['title']!r} added (sheet id {data['sheet_id']})", emoji="📊")

    @group.command("delete-tab")
    @click.argument("spreadsheet_id")
    @click.argument("title")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def delete_tab_command(
        ctx: click.Context,
        spreadsheet_id: str,
        title: str,
        yes: bool,
        json_output: bool | None,
    ) -> None:
        """Delete a tab and everything on it. Cannot be undone."""
        if not yes:
            click.confirm(f"Delete tab {title!r} and all its data?", abort=True)
        data = delete_sheet_tab(spreadsheet_id, title, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Tab {title!r} deleted.", emoji="📊")

    @group.command("read")
    @click.argument("spreadsheet_id")
    @click.argument("range_name")
    @json_option
    @click.pass_context
    def read_command(
        ctx: click.Context,
        spreadsheet_id: str,
        range_name: str,
        json_output: bool | None,
    ) -> None:
        data = read_sheet_values(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            values = data["rows"]
            if not values:
                print_human("No data found.", emoji="📊")
                return
            print_human(f"Spreadsheet data ({len(values)} rows):", emoji="📊")
            for row in values:
                print_human("  " + " | ".join(str(cell) for cell in row))

    @group.command("write")
    @click.argument("spreadsheet_id")
    @click.argument("range_name")
    @click.argument("value")
    @click.option("--raw", is_flag=True, help="Write the value without Sheets parsing.")
    @json_option
    @click.pass_context
    def write_command(
        ctx: click.Context,
        spreadsheet_id: str,
        range_name: str,
        value: str,
        raw: bool,
        json_output: bool | None,
    ) -> None:
        data = write_sheet_value(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            value=value,
            raw=raw,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(
                f"Updated {data['updated_cells']} cell(s) in {data['range']}",
                emoji="📊",
            )
