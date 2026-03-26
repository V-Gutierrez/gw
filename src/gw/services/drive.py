from __future__ import annotations

import click

from gw.auth import build_service
from gw.output import json_option, print_human, print_json, use_json_output


def list_drive_files(max_results: int = 10):
    service = build_service("drive", "v3")
    return (
        service.files()
        .list(pageSize=max_results, fields="files(id, name, mimeType, modifiedTime)")
        .execute()
        .get("files", [])
    )


def register_drive_commands(group: click.Group) -> None:
    @group.command("list")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        files = list_drive_files(max_results=max_results)
        if use_json_output(ctx, json_output):
            print_json(files)
        else:
            if not files:
                print_human("No files found.", emoji="📂")
                return
            print_human(f"Recent files ({len(files)}):", emoji="📂")
            for item in files:
                print_human(f"  • {item.get('name')} ({item.get('mimeType')})")
                print_human(f"    ID: {item.get('id')}")
                print_human(f"    Modified: {item.get('modifiedTime')}")
