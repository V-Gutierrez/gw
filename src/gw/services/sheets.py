from __future__ import annotations

import click
from typing import Any

from gw.auth import build_service
from gw.output import json_option, print_human, print_json, use_json_output


def read_sheet_values(spreadsheet_id: str, range_name: str) -> dict[str, Any]:
    service = build_service("sheets", "v4")
    values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
        .get("values", [])
    )
    return {"spreadsheet_id": spreadsheet_id, "range": range_name, "rows": values}


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
        data = read_sheet_values(spreadsheet_id=spreadsheet_id, range_name=range_name)
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
