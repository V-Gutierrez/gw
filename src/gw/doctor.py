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
        *_api_checks(config, authenticated=bool(status["authenticated"])),
    ]
    return {"ok": all(check["status"] == "ok" for check in checks), "checks": checks}


# Every API gw talks to, with a cheap read that proves it answers.
_APIS: tuple[str, ...] = ("gmail", "calendar", "drive", "sheets", "docs", "tasks", "people")


def _probe_api(api: str, config: GWConfig) -> None:
    """Make the smallest possible real call against one API. Raises on failure."""
    from gw.auth import build_service, execute_google_request

    if api == "gmail":
        service = build_service("gmail", "v1", config=config)
        execute_google_request(service.users().getProfile(userId="me"))
    elif api == "calendar":
        service = build_service("calendar", "v3", config=config)
        execute_google_request(service.calendarList().list(maxResults=1))
    elif api == "drive":
        service = build_service("drive", "v3", config=config)
        execute_google_request(service.about().get(fields="user"))
    elif api == "sheets":
        service = build_service("sheets", "v4", config=config)
        execute_google_request(service.spreadsheets().get(spreadsheetId="_gw_doctor_probe_"))
    elif api == "docs":
        service = build_service("docs", "v1", config=config)
        execute_google_request(service.documents().get(documentId="_gw_doctor_probe_"))
    elif api == "tasks":
        service = build_service("tasks", "v1", config=config)
        execute_google_request(service.tasklists().list(maxResults=1))
    elif api == "people":
        service = build_service("people", "v1", config=config)
        execute_google_request(
            service.people()
            .connections()
            .list(resourceName="people/me", pageSize=1, personFields="names")
        )


def _classify(api: str, exc: Exception) -> dict[str, Any]:
    """A 404 on a probe id means the API answered; 'not been used' means it is off."""
    message = str(exc)
    if "has not been used in project" in message or "it is disabled" in message:
        return {
            "name": f"api_{api}",
            "status": "error",
            "detail": (
                f"NOT ENABLED in the Google Cloud project — enable the {api} API at "
                f"https://console.cloud.google.com/apis/library/{_API_HOSTS[api]}"
            ),
        }
    if "404" in message or "not found" in message.lower():
        # The probe id is deliberately bogus; a 404 proves the API is reachable.
        return {"name": f"api_{api}", "status": "ok", "detail": "Reachable"}
    return {"name": f"api_{api}", "status": "error", "detail": message[:160]}


_API_HOSTS = {
    "gmail": "gmail.googleapis.com",
    "calendar": "calendar-json.googleapis.com",
    "drive": "drive.googleapis.com",
    "sheets": "sheets.googleapis.com",
    "docs": "docs.googleapis.com",
    "tasks": "tasks.googleapis.com",
    "people": "people.googleapis.com",
}


def _api_checks(config: GWConfig, *, authenticated: bool) -> list[dict[str, Any]]:
    """Actually call Google, once per API.

    Every other check here reads local files, so a green report used to prove only
    that the files existed — not that the token worked, and not that the APIs were
    even switched on in the Cloud project.
    """
    if not authenticated:
        return [
            {
                "name": f"api_{api}",
                "status": "error",
                "detail": "Skipped: not authenticated",
            }
            for api in _APIS
        ]

    checks: list[dict[str, Any]] = []
    for api in _APIS:
        try:
            _probe_api(api, config)
        except Exception as exc:  # noqa: BLE001 - any failure here is a failed check
            checks.append(_classify(api, exc))
        else:
            checks.append({"name": f"api_{api}", "status": "ok", "detail": "Reachable"})
    return checks


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
