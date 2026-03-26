from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

import click


def print_json(data: Any) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def print_json_error(message: str, code: int) -> None:
    click.echo(
        json.dumps({"error": message, "code": code}, indent=2, ensure_ascii=False),
        err=True,
    )


def print_human(message: str, emoji: str = "", err: bool = False) -> None:
    prefix = f"{emoji} " if emoji else ""
    click.echo(f"{prefix}{message}", err=err)


def print_success(message: str) -> None:
    print_human(message, emoji="✅")


def print_error(message: str) -> None:
    print_human(message, emoji="❌", err=True)


def print_warning(message: str) -> None:
    print_human(message, emoji="⚠️", err=True)


def print_info(message: str) -> None:
    print_human(message, emoji="ℹ️")


def output(data: Any, human_message: str, *, use_json: bool = False, emoji: str = "") -> None:
    if use_json:
        print_json(data)
    else:
        print_human(human_message, emoji=emoji)


def json_option(function: Callable[..., Any]) -> Callable[..., Any]:
    return click.option(
        "--json",
        "json_output",
        is_flag=True,
        default=None,
        help="Output as JSON.",
    )(function)


def use_json_output(ctx: click.Context, json_output: bool | None) -> bool:
    if json_output is not None:
        return json_output
    return bool((ctx.obj or {}).get("use_json", False))


def abort(message: str, code: int = 1) -> None:
    print_error(message)
    sys.exit(code)


def render_error(message: str, code: int, *, use_json: bool) -> None:
    if use_json:
        print_json_error(message, code)
    else:
        print_error(message)
