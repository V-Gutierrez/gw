from __future__ import annotations

import click
from typing import Any

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, use_json_output


def read_sheet_values(
    spreadsheet_id: str,
    range_name: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = build_service("sheets", "v4", config=config)
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
    service = build_service("sheets", "v4", config=config)
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


def register_sheets_commands(group: click.Group) -> None:
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
