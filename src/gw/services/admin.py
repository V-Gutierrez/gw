"""Workspace administration, read-only: the domain inventory by command.

Replaces a CSV exported by hand from the Admin Console — which is how the 2026-08-28
catalogue of 82 machines was actually built. Three APIs sit behind this one group:

* **Directory API** (``admin``/``directory_v1``) — users, groups, org units, ChromeOS and
  mobile devices.
* **Chrome Management API** (``chromemanagement``/``v1``) — device telemetry: CPU, RAM.

Two things in here are not decoration:

**Every command pages.** No other gw service does, because no other one has to return a
complete set — a truncated inventory still looks like an inventory. Directory API caps a
page at 100–500 rows depending on the endpoint, so a single call would have quietly
dropped everything past the first page of an 82-machine estate.

**Nothing writes.** Suspending a user or wiping a device has no undo, so the mutating half
of the Admin SDK is deliberately absent rather than merely unused.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.errors import GwError
from gw.output import json_option, print_human, print_json, use_json_output

# The Admin SDK resolves this literal to the domain the caller administers, which keeps the
# numeric customer ID out of config and out of this repo.
CUSTOMER = "my_customer"


def _directory_service(config: GWConfig | None = None):
    return build_service("admin", "directory_v1", config=config)


def _chrome_service(config: GWConfig | None = None):
    return build_service("chromemanagement", "v1", config=config)


def _paginate(
    list_method: Callable[..., Any],
    *,
    items_key: str,
    limit: int = 0,
    page_size: int = 100,
    page_size_key: str = "maxResults",
    **params: Any,
) -> list[dict[str, Any]]:
    """Collect every page, or stop early once ``limit`` rows are in hand.

    ``limit=0`` means "the whole thing" — the default, because the point of the group is a
    complete inventory. The page size is clamped to what is still missing so a ``--limit 2``
    does not pull 500 rows to throw 498 away.
    """
    collected: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        request_params = dict(params)
        remaining = limit - len(collected) if limit else page_size
        request_params[page_size_key] = max(1, min(page_size, remaining))
        if page_token:
            request_params["pageToken"] = page_token

        response = execute_google_request(list_method(**request_params))
        collected.extend(response.get(items_key, []) or [])

        page_token = response.get("nextPageToken")
        if not page_token or (limit and len(collected) >= limit):
            break

    return collected[:limit] if limit else collected


def _as_int(value: Any) -> int | None:
    """Directory API returns counts and byte sizes as strings. Give callers numbers."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- users


def _normalize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "email": user.get("primaryEmail"),
        "full_name": (user.get("name") or {}).get("fullName"),
        "is_admin": bool(user.get("isAdmin", False)),
        "suspended": bool(user.get("suspended", False)),
        "archived": bool(user.get("archived", False)),
        "org_unit_path": user.get("orgUnitPath"),
        "last_login_time": user.get("lastLoginTime"),
        "creation_time": user.get("creationTime"),
    }


def list_admin_users(
    query: str | None = None,
    org_unit: str | None = None,
    limit: int = 0,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _directory_service(config)

    filters = [part for part in (query, f"orgUnitPath='{org_unit}'" if org_unit else None) if part]
    params: dict[str, Any] = {"customer": CUSTOMER, "orderBy": "email"}
    if filters:
        params["query"] = " ".join(filters)

    rows = _paginate(service.users().list, items_key="users", limit=limit, page_size=500, **params)
    return [_normalize_user(row) for row in rows]


# --------------------------------------------------------------------------- groups


def _normalize_group(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": group.get("id"),
        "email": group.get("email"),
        "name": group.get("name"),
        "description": group.get("description"),
        "direct_members_count": _as_int(group.get("directMembersCount")),
    }


def list_admin_groups(limit: int = 0, config: GWConfig | None = None) -> list[dict[str, Any]]:
    service = _directory_service(config)
    rows = _paginate(
        service.groups().list,
        items_key="groups",
        limit=limit,
        page_size=200,
        customer=CUSTOMER,
    )
    return [_normalize_group(row) for row in rows]


# --------------------------------------------------------------------------- org units


def _normalize_orgunit(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": unit.get("orgUnitId"),
        "name": unit.get("name"),
        "path": unit.get("orgUnitPath"),
        "parent_path": unit.get("parentOrgUnitPath"),
        "description": unit.get("description"),
    }


def list_admin_orgunits(config: GWConfig | None = None) -> list[dict[str, Any]]:
    """The whole tree in one call — ``orgunits.list`` has no paging and ``type=all`` is why."""
    service = _directory_service(config)
    response = execute_google_request(service.orgunits().list(customerId=CUSTOMER, type="all"))
    return [_normalize_orgunit(row) for row in response.get("organizationUnits", []) or []]


# --------------------------------------------------------------------------- devices


def _normalize_chromeos(device: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": device.get("deviceId"),
        "serial_number": device.get("serialNumber"),
        "status": device.get("status"),
        "last_sync": device.get("lastSync"),
        "annotated_user": device.get("annotatedUser"),
        "model": device.get("model"),
        "os_version": device.get("osVersion"),
        "org_unit_path": device.get("orgUnitPath"),
    }


def list_admin_chromeos(limit: int = 0, config: GWConfig | None = None) -> list[dict[str, Any]]:
    service = _directory_service(config)
    # Device endpoints take `customerId`, while users and groups take `customer`. That
    # asymmetry is the Directory API's, not a typo.
    rows = _paginate(
        service.chromeosdevices().list,
        items_key="chromeosdevices",
        limit=limit,
        page_size=100,
        customerId=CUSTOMER,
    )
    return [_normalize_chromeos(row) for row in rows]


def _normalize_mobile(device: dict[str, Any]) -> dict[str, Any]:
    emails = device.get("email") or []
    return {
        "resource_id": device.get("resourceId"),
        "serial_number": device.get("serialNumber"),
        "model": device.get("model"),
        "os": device.get("os"),
        "status": device.get("status"),
        "email": emails[0] if isinstance(emails, list) and emails else None,
        "last_sync": device.get("lastSync"),
    }


def list_admin_mobile(limit: int = 0, config: GWConfig | None = None) -> list[dict[str, Any]]:
    service = _directory_service(config)
    rows = _paginate(
        service.mobiledevices().list,
        items_key="mobiledevices",
        limit=limit,
        page_size=100,
        customerId=CUSTOMER,
    )
    return [_normalize_mobile(row) for row in rows]


# --------------------------------------------------------------------------- telemetry

# Chrome Management refuses the call without a readMask, so it lists exactly the fields
# _normalize_telemetry reads. Adding a field below means adding it here too.
TELEMETRY_READ_MASK = "name,deviceId,serialNumber,orgUnitId,cpuInfo,memoryInfo"


def _normalize_telemetry(device: dict[str, Any]) -> dict[str, Any]:
    cpu_info = device.get("cpuInfo") or []
    memory_info = device.get("memoryInfo") or {}
    return {
        "device_id": device.get("deviceId"),
        "serial_number": device.get("serialNumber"),
        "org_unit_id": device.get("orgUnitId"),
        "cpu_model": cpu_info[0].get("model") if cpu_info else None,
        "total_ram_bytes": _as_int(memory_info.get("totalRamBytes")),
    }


def list_admin_telemetry(limit: int = 0, config: GWConfig | None = None) -> list[dict[str, Any]]:
    service = _chrome_service(config)
    rows = _paginate(
        service.customers().telemetry().devices().list,
        items_key="devices",
        limit=limit,
        page_size=100,
        page_size_key="pageSize",
        parent=f"customers/{CUSTOMER}",
        readMask=TELEMETRY_READ_MASK,
    )
    return [_normalize_telemetry(row) for row in rows]


# --------------------------------------------------------------------------- whoami


def admin_whoami(config: GWConfig | None = None) -> dict[str, Any]:
    """Ask each API one cheap question and report who answered.

    A domain half-way through setup is the normal first state: the OAuth consent succeeded,
    but an API is off in the Cloud project or the account lacks the admin role. Those show
    up as a 403 on one endpoint while the others work. Raising on the first failure would
    hide the other three, so every probe is caught and reported instead.
    """
    probes: list[dict[str, Any]] = []

    def probe(name: str, call: Callable[[], Any]) -> None:
        try:
            call()
        except (GwError, Exception) as exc:  # noqa: BLE001 - a probe reports, never raises
            probes.append({"api": name, "reachable": False, "error": str(exc)})
        else:
            probes.append({"api": name, "reachable": True, "error": None})

    directory = _directory_service(config)
    probe(
        "directory.users",
        lambda: execute_google_request(directory.users().list(customer=CUSTOMER, maxResults=1)),
    )
    probe(
        "directory.groups",
        lambda: execute_google_request(directory.groups().list(customer=CUSTOMER, maxResults=1)),
    )
    probe(
        "directory.chromeos",
        lambda: execute_google_request(
            directory.chromeosdevices().list(customerId=CUSTOMER, maxResults=1)
        ),
    )

    chrome = _chrome_service(config)
    probe(
        "chrome.telemetry",
        lambda: execute_google_request(
            chrome.customers()
            .telemetry()
            .devices()
            .list(parent=f"customers/{CUSTOMER}", pageSize=1, readMask=TELEMETRY_READ_MASK)
        ),
    )

    return {"ok": all(entry["reachable"] for entry in probes), "probes": probes}


# --------------------------------------------------------------------------- CLI


def _emit(ctx: click.Context, json_output: bool | None, rows: list[dict[str, Any]], line) -> None:
    if use_json_output(ctx, json_output):
        print_json(rows)
    else:
        for row in rows:
            print_human(line(row))
        print_human(f"{len(rows)} row(s)")


def _limit_option(fn):
    return click.option(
        "--limit",
        default=0,
        show_default=True,
        type=int,
        help="Stop after N rows. 0 fetches every page.",
    )(fn)


def register_admin_commands(group: click.Group) -> None:
    @group.command("users")
    @click.option("--query", default=None, help="Directory API user query, e.g. isSuspended=true.")
    @click.option("--org-unit", default=None, help="Restrict to an org unit path, e.g. /Ops.")
    @_limit_option
    @json_option
    @click.pass_context
    def users_command(
        ctx: click.Context,
        query: str | None,
        org_unit: str | None,
        limit: int,
        json_output: bool | None,
    ) -> None:
        rows = list_admin_users(
            query=query, org_unit=org_unit, limit=limit, config=ctx.obj["config"]
        )
        _emit(
            ctx,
            json_output,
            rows,
            lambda row: "{}  {}{}".format(
                row["email"],
                row.get("org_unit_path") or "",
                "  [suspended]" if row["suspended"] else "",
            ),
        )

    @group.command("groups")
    @_limit_option
    @json_option
    @click.pass_context
    def groups_command(ctx: click.Context, limit: int, json_output: bool | None) -> None:
        rows = list_admin_groups(limit=limit, config=ctx.obj["config"])
        _emit(
            ctx,
            json_output,
            rows,
            lambda row: f"{row['email']}  {row.get('direct_members_count')} member(s)",
        )

    @group.command("orgunits")
    @json_option
    @click.pass_context
    def orgunits_command(ctx: click.Context, json_output: bool | None) -> None:
        rows = list_admin_orgunits(config=ctx.obj["config"])
        _emit(ctx, json_output, rows, lambda row: f"{row['path']}  ({row.get('name')})")

    @group.command("chromeos")
    @_limit_option
    @json_option
    @click.pass_context
    def chromeos_command(ctx: click.Context, limit: int, json_output: bool | None) -> None:
        rows = list_admin_chromeos(limit=limit, config=ctx.obj["config"])
        _emit(
            ctx,
            json_output,
            rows,
            lambda row: "{}  {}  last sync {}".format(
                row.get("serial_number"), row.get("status"), row.get("last_sync")
            ),
        )

    @group.command("mobile")
    @_limit_option
    @json_option
    @click.pass_context
    def mobile_command(ctx: click.Context, limit: int, json_output: bool | None) -> None:
        rows = list_admin_mobile(limit=limit, config=ctx.obj["config"])
        _emit(
            ctx,
            json_output,
            rows,
            lambda row: f"{row.get('model')}  {row.get('os')}  {row.get('email')}",
        )

    @group.command("telemetry")
    @_limit_option
    @json_option
    @click.pass_context
    def telemetry_command(ctx: click.Context, limit: int, json_output: bool | None) -> None:
        rows = list_admin_telemetry(limit=limit, config=ctx.obj["config"])
        _emit(
            ctx,
            json_output,
            rows,
            lambda row: "{}  {}  {} GB".format(
                row.get("serial_number"),
                row.get("cpu_model"),
                round((row["total_ram_bytes"] or 0) / 1024**3, 1)
                if row["total_ram_bytes"]
                else "?",
            ),
        )

    @group.command("whoami")
    @json_option
    @click.pass_context
    def whoami_command(ctx: click.Context, json_output: bool | None) -> None:
        data = admin_whoami(config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
            return
        for entry in data["probes"]:
            mark = "ok" if entry["reachable"] else f"FAIL — {entry['error']}"
            print_human(f"{entry['api']}: {mark}")
