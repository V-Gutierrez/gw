from __future__ import annotations

from typing import Any

import click

from gw.auth import credential_status
from gw.config import GWConfig
from gw.output import print_human, print_json


def run_doctor(config: GWConfig) -> dict[str, Any]:
    status = credential_status(config=config)
    checks = [
        {
            "name": "credentials_file",
            "status": "ok" if config.credentials.exists() else "error",
            "detail": str(config.credentials),
        },
        {
            "name": "token_file",
            "status": "ok" if config.token.exists() else "error",
            "detail": str(config.token),
        },
        {
            "name": "authentication",
            "status": "ok" if status["authenticated"] else "error",
            "detail": "Authenticated" if status["authenticated"] else "Not authenticated",
        },
        {
            "name": "timezone",
            "status": "ok" if bool(config.timezone) else "error",
            "detail": config.timezone,
        },
        _api_check(config, authenticated=bool(status["authenticated"])),
    ]
    return {"ok": all(check["status"] == "ok" for check in checks), "checks": checks}


def _api_check(config: GWConfig, *, authenticated: bool) -> dict[str, Any]:
    """Actually call Google.

    Every other check here reads local files, so a green report used to prove only
    that the files existed — not that the token still works against the API.
    """
    if not authenticated:
        return {
            "name": "api_reachable",
            "status": "error",
            "detail": "Skipped: not authenticated",
        }
    try:
        from gw.services.gmail import get_gmail_profile

        profile = get_gmail_profile(config=config)
    except Exception as exc:  # noqa: BLE001 - any failure here is a failed check
        return {"name": "api_reachable", "status": "error", "detail": str(exc)}
    return {
        "name": "api_reachable",
        "status": "ok",
        "detail": f"Gmail API OK as {profile['email']} ({profile['messages_total']} messages)",
    }


def print_doctor_report(report: dict[str, Any]) -> None:
    print_human("gw doctor", emoji="🩺")
    for check in report["checks"]:
        icon = "✅" if check["status"] == "ok" else "❌"
        print_human(f"{icon} {check['name']}: {check['detail']}")


def doctor_command(ctx: click.Context, json_output: bool | None) -> None:
    config = ctx.obj["config"]
    report = run_doctor(config)
    if json_output or bool((ctx.obj or {}).get("use_json", False)):
        print_json(report)
    else:
        print_doctor_report(report)
