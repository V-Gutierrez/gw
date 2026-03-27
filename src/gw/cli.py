from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import click
from click.shell_completion import get_completion_class

from gw import __version__
from gw.auth import register_auth_commands
from gw.config import get_config_path, load_config
from gw.doctor import doctor_command
from gw.errors import EXIT_GENERAL, EXIT_SUCCESS, GwAuthError, GwConfigError, GwError
from gw.mcp_server import run_mcp_server, set_mcp_config
from gw.output import json_option, print_human, print_json, render_error, use_json_output
from gw.services.calendar import register_calendar_commands, register_meet_commands
from gw.services.contacts import register_contacts_commands
from gw.services.docs import register_docs_commands
from gw.services.drive import register_drive_commands
from gw.services.gmail import register_gmail_commands
from gw.services.sheets import register_sheets_commands
from gw.services.tasks import register_tasks_commands


def load_runtime_config(profile: str | None = None):
    try:
        return load_config(profile=profile)
    except ValueError as exc:
        raise GwConfigError(str(exc)) from exc


def _argv_requests_json(argv: Sequence[str] | None) -> bool:
    return bool(argv and "--json" in argv)


def _format_click_error(exc: click.ClickException) -> str:
    return exc.format_message()


def run_cli(argv: Sequence[str] | None = None, *, prog_name: str = "gw") -> int:
    use_json = _argv_requests_json(argv)

    try:
        main_group.main(
            args=list(argv) if argv is not None else None,
            prog_name=prog_name,
            standalone_mode=False,
        )
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.UsageError as exc:
        render_error(_format_click_error(exc), EXIT_GENERAL, use_json=use_json)
        return EXIT_GENERAL
    except GwAuthError as exc:
        render_error(exc.message, exc.exit_code, use_json=use_json)
        return exc.exit_code
    except GwConfigError as exc:
        render_error(exc.message, exc.exit_code, use_json=use_json)
        return exc.exit_code
    except GwError as exc:
        render_error(exc.message, exc.exit_code, use_json=use_json)
        return exc.exit_code
    except click.ClickException as exc:
        render_error(_format_click_error(exc), EXIT_GENERAL, use_json=use_json)
        return EXIT_GENERAL
    except Exception as exc:
        render_error(str(exc), EXIT_GENERAL, use_json=use_json)
        return EXIT_GENERAL

    return EXIT_SUCCESS


@click.group()
@click.option("--json", "use_json", is_flag=True, default=False, help="Output as JSON.")
@click.option("--profile", default=None, help="Use a named profile from config.toml.")
@click.version_option(__version__, prog_name="gw")
@click.pass_context
def main(ctx: click.Context, use_json: bool, profile: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["use_json"] = use_json
    ctx.obj["profile"] = profile
    ctx.obj["config"] = load_runtime_config(profile=profile)


@click.group(name="config")
def config_group() -> None:
    pass


main_group = cast(click.Group, main)
config_click_group = cast(click.Group, config_group)
auth_group = click.Group(name="auth")
calendar_group = click.Group(name="calendar")
contacts_group = click.Group(name="contacts")
gmail_group = click.Group(name="gmail")
drive_group = click.Group(name="drive")
sheets_group = click.Group(name="sheets")
docs_group = click.Group(name="docs")
meet_group = click.Group(name="meet")
tasks_group = click.Group(name="tasks")


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


@click.command(name="completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion_command(shell: str) -> None:
    complete_var = "_GW_COMPLETE"
    completion_class = get_completion_class(shell)
    if completion_class is None:
        raise click.ClickException(f"Unsupported shell: {shell}")
    completion = completion_class(main_group, {}, "gw", complete_var)
    click.echo(completion.source())


@click.command(name="doctor")
@json_option
@click.pass_context
def doctor_cli(ctx: click.Context, json_output: bool | None) -> None:
    doctor_command(ctx, json_output)


@click.group(name="mcp")
def mcp_group() -> None:
    pass


@click.command(name="serve")
@click.pass_context
def mcp_serve_command(ctx: click.Context) -> None:
    set_mcp_config(ctx.obj["config"])
    run_mcp_server()


mcp_click_group = cast(click.Group, mcp_group)


config_click_group.add_command(config_show)
config_click_group.add_command(config_path)

register_auth_commands(auth_group)
register_calendar_commands(calendar_group)
register_contacts_commands(contacts_group)
register_gmail_commands(gmail_group)
register_drive_commands(drive_group)
register_sheets_commands(sheets_group)
register_docs_commands(docs_group)
register_meet_commands(meet_group)
register_tasks_commands(tasks_group)
mcp_click_group.add_command(mcp_serve_command)

main_group.add_command(auth_group)
main_group.add_command(completion_command)
main_group.add_command(config_click_group)
main_group.add_command(doctor_cli)
main_group.add_command(mcp_click_group)
main_group.add_command(calendar_group)
main_group.add_command(contacts_group)
main_group.add_command(gmail_group)
main_group.add_command(drive_group)
main_group.add_command(sheets_group)
main_group.add_command(docs_group)
main_group.add_command(meet_group)
main_group.add_command(tasks_group)
