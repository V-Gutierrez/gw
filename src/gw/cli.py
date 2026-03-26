from __future__ import annotations

from typing import cast

import click

from gw import __version__
from gw.auth import register_auth_commands
from gw.config import get_config_path, load_config
from gw.output import json_option, print_human, print_json, use_json_output
from gw.services.calendar import register_calendar_commands
from gw.services.docs import register_docs_commands
from gw.services.drive import register_drive_commands
from gw.services.gmail import register_gmail_commands
from gw.services.sheets import register_sheets_commands


@click.group()
@click.option("--json", "use_json", is_flag=True, default=False, help="Output as JSON.")
@click.version_option(__version__, prog_name="gw")
@click.pass_context
def main(ctx: click.Context, use_json: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["use_json"] = use_json
    ctx.obj["config"] = load_config()


@click.group(name="config")
def config_group() -> None:
    pass


main_group = cast(click.Group, main)
config_click_group = cast(click.Group, config_group)
auth_group = click.Group(name="auth")
calendar_group = click.Group(name="calendar")
gmail_group = click.Group(name="gmail")
drive_group = click.Group(name="drive")
sheets_group = click.Group(name="sheets")
docs_group = click.Group(name="docs")


@click.command(name="show")
@json_option
@click.pass_context
def config_show(ctx: click.Context, json_output: bool | None) -> None:
    cfg = ctx.obj["config"]
    data = cfg.as_dict()
    if use_json_output(ctx, json_output):
        print_json(data)
    else:
        for key, value in data.items():
            print_human(f"{key}: {value}")


@click.command(name="path")
@json_option
@click.pass_context
def config_path(ctx: click.Context, json_output: bool | None) -> None:
    path_str = str(get_config_path())
    if use_json_output(ctx, json_output):
        print_json({"config_path": path_str})
    else:
        print_human(path_str, emoji="📁")


config_click_group.add_command(config_show)
config_click_group.add_command(config_path)

register_auth_commands(auth_group)
register_calendar_commands(calendar_group)
register_gmail_commands(gmail_group)
register_drive_commands(drive_group)
register_sheets_commands(sheets_group)
register_docs_commands(docs_group)

main_group.add_command(auth_group)
main_group.add_command(config_click_group)
main_group.add_command(calendar_group)
main_group.add_command(gmail_group)
main_group.add_command(drive_group)
main_group.add_command(sheets_group)
main_group.add_command(docs_group)
