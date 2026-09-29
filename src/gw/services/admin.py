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

**Writes exist, and they are gated by blast radius.** Every mutating command takes
``--dry-run``, which prints the exact body that would be sent, on screen and not only
under ``--json``. Reversible writes also take ``--yes`` to skip a confirmation prompt.

Five commands are armed differently, because they have no undo: ``user-delete``,
``group-delete``, ``orgunit-delete``, ``device-action`` and ``mobile-action`` ignore
``--yes`` and demand the target's name retyped. ``--yes`` stays accepted there so existing
scripts keep parsing, and its help says it is ignored — an inert flag advertised as a
safety step is worse than no flag.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.errors import EXIT_GENERAL, GwError
from gw.output import json_option, print_human, print_json, print_success, use_json_output

# The Admin SDK resolves this literal to the domain the caller administers, which keeps the
# numeric customer ID out of config and out of this repo.
CUSTOMER = "my_customer"


def _directory_service(config: GWConfig | None = None):
    return build_service("admin", "directory_v1", config=config)


def _chrome_service(config: GWConfig | None = None):
    return build_service("chromemanagement", "v1", config=config)


def _reports_service(config: GWConfig | None = None):
    """Audit and usage live in `reports_v1`, a different version of the same `admin` API."""
    return build_service("admin", "reports_v1", config=config)


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
    if limit < 0:
        # `collected[:-1]` would drop rows instead of capping them, so a negative limit used
        # to print `0 row(s)` and exit 0 — an empty domain reported as success.
        raise GwError("--limit must be zero (every page) or a positive number of rows.")

    collected: list[dict[str, Any]] = []
    page_token: str | None = None
    seen_tokens: set[str] = set()

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
        if page_token in seen_tokens:
            # A server that keeps handing back the same cursor would spin here forever.
            # Stopping with what we have beats a process that never returns.
            break
        seen_tokens.add(page_token)

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
        page_size=300,
        customerId=CUSTOMER,
        projection="FULL",
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
        projection="FULL",
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
        except GwError as exc:
            # Only a refusal from Google counts as "unreachable". A TypeError from a wrong
            # kwarg is our bug, and swallowing it here would disguise it as a denied API —
            # in the one command that exists to tell those two apart.
            probes.append({"api": name, "reachable": False, "error": exc.message})
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


# --------------------------------------------------------------------------- writes
#
# Victor's decision, 2026-09-29: the group manages the domain, it does not only read it.
# Three rails, in order of how much they cost when they are missing:
#
# 1. `--dry-run` returns the exact body that would be sent, and prints it. The two device
#    actions are the caveat: proving the retype means asking the registry who owns an
#    opaque resource id, so a read happens. Nothing is changed either way.
# 2. `--yes` skips an interactive confirmation that otherwise blocks.
# 3. The five irreversible commands ignore `--yes` and demand the target retyped, because
#    their victim is a person who did nothing wrong.
# 4. A rail is checked in this file, never delegated to click's `required`: the same 0.9.4
#    binary enforced `--grant/--revoke` under click 8.1.8 and let `{"status": None}` through
#    under 8.3.1 (measured 2026-09-29). A guarantee a minor bump can delete is not one.


# The two device actions must ask the registry who owns an opaque resource id before they
# can check the retype, so a read leaves under --dry-run. The design is deliberate; the
# blanket "nothing was sent" that used to describe it was simply false.
_DEVICE_DRY_RUN_NOTE = "the device was read to check the serial; nothing was changed"


def _confirm(action: str, target: str, *, yes: bool, dry_run: bool = False) -> None:
    """Ask before changing the domain.

    A dry run changes nothing even if it goes wrong, so it never asks: a prompt makes
    `--dry-run` unusable in exactly the scripts it exists for. The retyped argument the
    irreversible commands demand is a different rail and still applies — the rehearsal has
    to prove the real invocation is valid.
    """
    if yes or dry_run:
        return
    click.confirm(f"{action} {target}?", abort=True)


def _redact(row: dict[str, Any]) -> dict[str, Any]:
    """Secrets never reach stdout, but the key stays and is marked.

    Google echoes the password back on users.insert, and the dry-run body carries the one
    the admin typed. Dropping the key made the rehearsal lie by omission: `user-create
    --dry-run` printed a body with no password field at all, so nothing showed that one was
    being set.
    """
    return {key: "***" if key == "password" else value for key, value in row.items()}


def create_admin_user(
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    org_unit: str | None = None,
    title: str | None = None,
    department: str | None = None,
    location: str | None = None,
    phone: str | None = None,
    recovery_email: str | None = None,
    recovery_phone: str | None = None,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Create a user with the directory profile filled in the same call.

    `users.insert` takes the whole record, so the job title and the mobile number are not a
    second pass: they either travel in this body or the account opens with a directory entry
    that looks complete and is not. The shape of every block is the one the profiled accounts
    in this domain already use — `organizations` is a one-element list carrying title,
    department and location together, and the phone is the work profile's mobile.
    """
    body: dict[str, Any] = {
        "primaryEmail": email,
        "name": {"givenName": first_name, "familyName": last_name},
        "password": password,
        # A password typed by an admin is a shared secret until the owner replaces it.
        "changePasswordAtNextLogin": True,
    }
    if org_unit:
        body["orgUnitPath"] = org_unit
    if title or department or location:
        work: dict[str, Any] = {"primary": True, "type": "work"}
        if title:
            work["title"] = title
        if department:
            work["department"] = department
        if location:
            work["location"] = location
        body["organizations"] = [work]
    if phone:
        body["phones"] = [{"value": phone, "type": "mobile"}]
    if recovery_email:
        body["recoveryEmail"] = recovery_email
    if recovery_phone:
        body["recoveryPhone"] = recovery_phone

    if dry_run:
        return {"dry_run": True, "would_call": "users.insert", "body": _redact(body)}

    service = _directory_service(config)
    return _normalize_user(_redact(execute_google_request(service.users().insert(body=body))))


def set_admin_user_suspended(
    email: str,
    suspended: bool,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body = {"suspended": suspended}
    if dry_run:
        return {"dry_run": True, "would_call": "users.update", "userKey": email, "body": body}

    service = _directory_service(config)
    return _normalize_user(
        _redact(execute_google_request(service.users().update(userKey=email, body=body)))
    )


def move_admin_user(
    email: str,
    org_unit: str,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body = {"orgUnitPath": org_unit}
    if dry_run:
        return {"dry_run": True, "would_call": "users.update", "userKey": email, "body": body}

    service = _directory_service(config)
    return _normalize_user(
        _redact(execute_google_request(service.users().update(userKey=email, body=body)))
    )


def add_admin_group_member(
    group: str,
    member: str,
    role: str = "MEMBER",
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body = {"email": member, "role": role}
    if dry_run:
        return {"dry_run": True, "would_call": "members.insert", "groupKey": group, "body": body}

    service = _directory_service(config)
    return execute_google_request(service.members().insert(groupKey=group, body=body))


def remove_admin_group_member(
    group: str,
    member: str,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    if dry_run:
        return {
            "dry_run": True,
            "would_call": "members.delete",
            "groupKey": group,
            "memberKey": member,
        }

    service = _directory_service(config)
    execute_google_request(service.members().delete(groupKey=group, memberKey=member))
    return {"removed": member, "group": group}


DEVICE_ACTIONS = ("disable", "reenable", "deprovision", "wipe_users", "remote_powerwash")

# `ChromeOsDeviceAction.deprovisionReason` is required when the action is `deprovision`
# (Directory API discovery doc, read 2026-09-29) and the doc publishes no enum for it. These
# are the four values Google documents for the action; the device resource's own read-only
# field lists eleven, of which the rest are deprecated or set by the system. Validating
# locally turns a 400 nobody rehearsed into a refusal with the choices printed.
DEPROVISION_REASONS = (
    "same_model_replacement",
    "different_model_replacement",
    "retiring_device",
    "upgrade_transfer",
)


def act_on_chromeos_device(
    device_id: str,
    action: str,
    confirm_serial: str,
    reason: str | None = None,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Refuse unless the caller retyped the serial the API reports for this device.

    `--yes` deliberately does not arm this: an ID typed one character off names a different
    machine, and the confirmation prompt for a wipe is the last thing standing between a
    typo and someone's working day.

    The serial is read from the API even under --dry-run: an opaque deviceId can only be
    resolved by asking. That lookup is a read, nothing about the device changes, and it
    makes this and `mobile-action` the only commands here whose dry run is not offline.
    """
    service = _directory_service(config)
    device = execute_google_request(
        service.chromeosdevices().get(customerId=CUSTOMER, deviceId=device_id)
    )
    actual_serial = device.get("serialNumber")
    if confirm_serial != actual_serial:
        raise GwError(
            f"Serial mismatch: device {device_id} reports {actual_serial!r}, "
            f"you typed {confirm_serial!r}. Nothing was done."
        )

    body: dict[str, Any] = {"action": action}
    if reason:
        body["deprovisionReason"] = reason
    if dry_run:
        return {
            "dry_run": True,
            "would_call": "chromeosdevices.action",
            "deviceId": device_id,
            "body": body,
            "dry_run_note": _DEVICE_DRY_RUN_NOTE,
        }

    execute_google_request(
        service.chromeosdevices().action(customerId=CUSTOMER, resourceId=device_id, body=body)
    )
    return {"deviceId": device_id, "serialNumber": actual_serial, "action": action}


# --------------------------------------------------------------------------- lifecycle
#
# Everything below closes the loop from "who is in this domain" to "manage this domain":
# one user, a group's membership, who holds an admin role, and what people actually did.


def get_admin_user(email: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _directory_service(config)
    return _normalize_user(execute_google_request(service.users().get(userKey=email)))


def _normalize_member(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": member.get("id"),
        "email": member.get("email"),
        "role": member.get("role"),
        "type": member.get("type"),
        "status": member.get("status"),
    }


def list_admin_group_members(
    group: str, limit: int = 0, config: GWConfig | None = None
) -> list[dict[str, Any]]:
    service = _directory_service(config)
    rows = _paginate(
        service.members().list,
        items_key="members",
        limit=limit,
        page_size=200,
        groupKey=group,
    )
    return [_normalize_member(row) for row in rows]


def list_admin_roles(config: GWConfig | None = None) -> list[dict[str, Any]]:
    """Join assignments onto role names: a bare roleId answers nobody's question."""
    service = _directory_service(config)
    roles = {
        role.get("roleId"): role
        for role in _paginate(
            service.roles().list, items_key="items", page_size=100, customer=CUSTOMER
        )
    }
    assignments = _paginate(
        service.roleAssignments().list, items_key="items", page_size=100, customer=CUSTOMER
    )
    return [
        {
            "role_id": assignment.get("roleId"),
            "role_name": (roles.get(assignment.get("roleId")) or {}).get("roleName"),
            "is_super_admin": bool(
                (roles.get(assignment.get("roleId")) or {}).get("isSuperAdminRole", False)
            ),
            "assigned_to": assignment.get("assignedTo"),
            "scope_type": assignment.get("scopeType"),
            "org_unit_id": assignment.get("orgUnitId"),
        }
        for assignment in assignments
    ]


REPORT_APPS = ("login", "admin", "drive", "token", "groups", "mobile", "user_accounts")


def _normalize_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """`Activity.events` is a list, and one row used to keep `events[0]`.

    A single sign-in activity can carry several events, and the rest were dropped without a
    count — a silent loss inside the one command whose job is to be an audit trail. `event`
    and `type` stay as the first event so the human line is unchanged; the full list and the
    count are now on the row.
    """
    events = activity.get("events") or []
    first = events[0] if events else {}
    return {
        "time": (activity.get("id") or {}).get("time"),
        "actor": (activity.get("actor") or {}).get("email"),
        "event": first.get("name"),
        "type": first.get("type"),
        "event_count": len(events),
        "events": [{"name": e.get("name"), "type": e.get("type")} for e in events],
        "ip_address": activity.get("ipAddress"),
    }


def list_admin_reports(
    app: str = "login",
    limit: int = 0,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _reports_service(config)
    rows = _paginate(
        service.activities().list,
        items_key="items",
        limit=limit,
        page_size=1000,
        userKey="all",
        applicationName=app,
    )
    return [_normalize_activity(row) for row in rows]


def _require_match(
    kind: str,
    typed: str | None,
    actual: str | None,
    what: str,
    *,
    against: str,
) -> None:
    """Irreversible commands take the name retyped, never a bare --yes.

    `against` names where the reference value came from, because the callers do not source
    it the same way. A mobile serial has to be asked of the API: the resource id is opaque,
    so it names a phone nobody can see. A user's email, a group's email and an org unit path
    are already the key, so the reference is the argument the operator typed in that same
    command. Announcing "the target reports" in the second case dressed a copy of the input
    as an independent check, and it was false.
    """
    if not typed:
        raise click.UsageError(
            f"{what} requires --confirm-{kind}: retype the {kind} of what you mean. "
            "--yes does not cover an irreversible command."
        )
    if typed != actual:
        raise GwError(
            f"{kind.capitalize()} mismatch: {against} {actual!r}, you typed {typed!r}. "
            "Nothing was done."
        )


def delete_admin_user(
    email: str,
    confirm_email: str | None,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Deleting a user destroys their Drive and Gmail. Transfer first, then delete."""
    _require_match("email", confirm_email, email, "user-delete", against="the command names")
    if dry_run:
        return {"dry_run": True, "would_call": "users.delete", "userKey": email}

    service = _directory_service(config)
    execute_google_request(service.users().delete(userKey=email))
    return {"deleted": email}


def rename_admin_user(
    email: str,
    first_name: str,
    last_name: str,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body = {"name": {"givenName": first_name, "familyName": last_name}}
    if dry_run:
        return {"dry_run": True, "would_call": "users.update", "userKey": email, "body": body}

    service = _directory_service(config)
    return _normalize_user(
        _redact(execute_google_request(service.users().update(userKey=email, body=body)))
    )


def reset_admin_user_password(
    email: str,
    password: str,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body = {"password": password, "changePasswordAtNextLogin": True}
    if dry_run:
        return {
            "dry_run": True,
            "would_call": "users.update",
            "userKey": email,
            "body": _redact(body),
        }

    service = _directory_service(config)
    return _normalize_user(
        _redact(execute_google_request(service.users().update(userKey=email, body=body)))
    )


def set_admin_user_admin(
    email: str,
    grant: bool,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """`isAdmin` is read-only on the user resource; the grant goes through users.makeAdmin."""
    body = {"status": grant}
    if dry_run:
        return {"dry_run": True, "would_call": "users.makeAdmin", "userKey": email, "body": body}

    service = _directory_service(config)
    execute_google_request(service.users().makeAdmin(userKey=email, body=body))
    return {"email": email, "is_admin": grant}


def create_admin_group(
    email: str,
    name: str,
    description: str | None = None,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"email": email, "name": name}
    if description:
        body["description"] = description
    if dry_run:
        return {"dry_run": True, "would_call": "groups.insert", "body": body}

    service = _directory_service(config)
    return _normalize_group(execute_google_request(service.groups().insert(body=body)))


def delete_admin_group(
    email: str,
    confirm_email: str | None,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """The membership list goes with it, and no API brings it back."""
    _require_match("email", confirm_email, email, "group-delete", against="the command names")
    if dry_run:
        return {"dry_run": True, "would_call": "groups.delete", "groupKey": email}

    service = _directory_service(config)
    execute_google_request(service.groups().delete(groupKey=email))
    return {"deleted": email}


def create_admin_orgunit(
    name: str,
    parent: str = "/",
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body = {"name": name, "parentOrgUnitPath": parent}
    if dry_run:
        return {"dry_run": True, "would_call": "orgunits.insert", "body": body}

    service = _directory_service(config)
    return _normalize_orgunit(
        execute_google_request(service.orgunits().insert(customerId=CUSTOMER, body=body))
    )


def delete_admin_orgunit(
    path: str,
    confirm_path: str | None,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    _require_match("path", confirm_path, path, "orgunit-delete", against="the command names")
    if dry_run:
        return {"dry_run": True, "would_call": "orgunits.delete", "orgUnitPath": path}

    service = _directory_service(config)
    execute_google_request(service.orgunits().delete(customerId=CUSTOMER, orgUnitPath=path))
    return {"deleted": path}


MOBILE_ACTIONS = (
    "admin_account_wipe",
    "admin_remote_wipe",
    "approve",
    "block",
    "cancel_remote_wipe_then_activate",
)


def act_on_mobile_device(
    resource_id: str,
    action: str,
    confirm_serial: str | None,
    dry_run: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Refuse unless the caller retyped the serial of this resource.

    Same rail as `act_on_chromeos_device`, and the same caveat: proving the retype means
    asking the registry who owns that opaque resource id, so the read happens under
    --dry-run too. Nothing is changed either way.
    """
    service = _directory_service(config)
    device = execute_google_request(
        service.mobiledevices().get(customerId=CUSTOMER, resourceId=resource_id)
    )
    _require_match(
        "serial",
        confirm_serial,
        device.get("serialNumber"),
        "mobile-action",
        against="the device reports",
    )

    body = {"action": action}
    if dry_run:
        return {
            "dry_run": True,
            "would_call": "mobiledevices.action",
            "resourceId": resource_id,
            "body": body,
            "dry_run_note": _DEVICE_DRY_RUN_NOTE,
        }

    execute_google_request(
        service.mobiledevices().action(customerId=CUSTOMER, resourceId=resource_id, body=body)
    )
    return {"resourceId": resource_id, "action": action}


# --------------------------------------------------------------------------- CLI


def _emit(ctx: click.Context, json_output: bool | None, rows: list[dict[str, Any]], line) -> None:
    if use_json_output(ctx, json_output):
        print_json(rows)
    else:
        for row in rows:
            print_human(line(row))
        print_human(f"{len(rows)} row(s)")


def _emit_one(
    ctx: click.Context, json_output: bool | None, data: dict[str, Any], line: str
) -> None:
    if use_json_output(ctx, json_output):
        print_json(data)
    elif data.get("dry_run"):
        # The method name alone made two rehearsals of two different payloads identical on
        # screen. `--dry-run` exists to be read before the real invocation, and the default
        # output is the human one, so the body belongs here and not only under --json.
        print_human(
            f"[dry-run] {data['would_call']} — {data.get('dry_run_note', 'nothing was sent')}"
        )
        payload = {
            k: v for k, v in data.items() if k not in ("dry_run", "would_call", "dry_run_note")
        }
        if payload:
            for row in json.dumps(payload, indent=2, ensure_ascii=False).splitlines():
                print_human(f"  {row}")
    else:
        print_success(line)


def _exit_on_failed_probe(ctx: click.Context, data: dict[str, Any]) -> None:
    """Non-zero when any API said no, so `gw admin whoami && ...` means what it looks like."""
    if not data["ok"]:
        ctx.exit(EXIT_GENERAL)


def _validate_limit(ctx: click.Context, param: click.Parameter, value: int) -> int:
    if value < 0:
        raise click.BadParameter("must be 0 (every page) or a positive number of rows.")
    return value


def _limit_option(fn):
    return click.option(
        "--limit",
        default=0,
        show_default=True,
        type=int,
        callback=_validate_limit,
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
            _exit_on_failed_probe(ctx, data)
            return
        for entry in data["probes"]:
            mark = "ok" if entry["reachable"] else f"FAIL — {entry['error']}"
            print_human(f"{entry['api']}: {mark}")
        _exit_on_failed_probe(ctx, data)

    # ----------------------------------------------------------------- writes

    def _build_write_options(fn, *, yes_help: str, dry_run_help: str):
        fn = click.option("--dry-run", is_flag=True, help=dry_run_help)(fn)
        fn = click.option("--yes", is_flag=True, help=yes_help)(fn)
        return fn

    _DRY_RUN_HELP = "Print what would be sent; change nothing."
    _DRY_RUN_READS_HELP = (
        "Print what would be sent; change nothing. Reads the device to check the serial."
    )
    # The five irreversible commands never call `_confirm`, so there is no prompt for --yes
    # to skip. The flag stays accepted — scripts already pass it — and stops claiming a
    # safety step that does not exist.
    _YES_INERT_HELP = (
        "Accepted and ignored: this command is armed by the retyped --confirm-… argument."
    )

    def _write_options(fn):
        return _build_write_options(
            fn, yes_help="Skip the confirmation prompt.", dry_run_help=_DRY_RUN_HELP
        )

    def _irreversible_write_options(fn):
        return _build_write_options(fn, yes_help=_YES_INERT_HELP, dry_run_help=_DRY_RUN_HELP)

    def _device_write_options(fn):
        return _build_write_options(fn, yes_help=_YES_INERT_HELP, dry_run_help=_DRY_RUN_READS_HELP)

    def _require_retype(value: str | None, *, what: str, kind: str, because: str) -> None:
        """Refuse the unarmed invocation here, before anything reaches the network.

        `device-action` checked locally and `mobile-action` did not: the same missing
        argument cost a `mobiledevices.get` round-trip before the usage error. Same rail,
        one implementation.
        """
        if not value:
            raise click.UsageError(
                f"{what} requires --confirm-{kind}: retype the {kind} of what you mean. "
                f"--yes does not cover this command, because {because}."
            )

    @group.command("user-create")
    @click.argument("email")
    @click.option("--first-name", required=True)
    @click.option("--last-name", required=True)
    @click.option("--password", required=True, help="Temporary; the user must change it at login.")
    @click.option("--org-unit", default=None, help="Org unit path, e.g. /Ops.")
    @click.option("--title", default=None, help="Job title as the directory shows it.")
    @click.option("--department", default=None, help="Department, e.g. Sales.")
    @click.option("--location", default=None, help="Work location, e.g. the store's address.")
    @click.option("--phone", default=None, help="Mobile number; stored on the work profile.")
    @click.option(
        "--recovery-email",
        default=None,
        help="Where a locked-out user is reached. The personal address goes here.",
    )
    @click.option("--recovery-phone", default=None, help="SMS recovery number.")
    @_write_options
    @json_option
    @click.pass_context
    def user_create_command(
        ctx: click.Context,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        org_unit: str | None,
        title: str | None,
        department: str | None,
        location: str | None,
        phone: str | None,
        recovery_email: str | None,
        recovery_phone: str | None,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm("Create user", email, yes=yes, dry_run=dry_run)
        data = create_admin_user(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
            org_unit=org_unit,
            title=title,
            department=department,
            location=location,
            phone=phone,
            recovery_email=recovery_email,
            recovery_phone=recovery_phone,
            dry_run=dry_run,
            config=ctx.obj["config"],
        )
        _emit_one(ctx, json_output, data, f"User created: {email}")

    @group.command("user-suspend")
    @click.argument("email")
    @_write_options
    @json_option
    @click.pass_context
    def user_suspend_command(
        ctx: click.Context, email: str, yes: bool, dry_run: bool, json_output: bool | None
    ) -> None:
        _confirm("Suspend user", email, yes=yes, dry_run=dry_run)
        data = set_admin_user_suspended(
            email=email, suspended=True, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"User suspended: {email}")

    @group.command("user-restore")
    @click.argument("email")
    @_write_options
    @json_option
    @click.pass_context
    def user_restore_command(
        ctx: click.Context, email: str, yes: bool, dry_run: bool, json_output: bool | None
    ) -> None:
        _confirm("Restore user", email, yes=yes, dry_run=dry_run)
        data = set_admin_user_suspended(
            email=email, suspended=False, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"User restored: {email}")

    @group.command("user-move")
    @click.argument("email")
    @click.argument("org_unit")
    @_write_options
    @json_option
    @click.pass_context
    def user_move_command(
        ctx: click.Context,
        email: str,
        org_unit: str,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm(f"Move {email} to", org_unit, yes=yes, dry_run=dry_run)
        data = move_admin_user(
            email=email, org_unit=org_unit, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"User moved: {email} -> {org_unit}")

    @group.command("group-add")
    @click.argument("group_email")
    @click.argument("member")
    @click.option("--role", default="MEMBER", type=click.Choice(["MEMBER", "MANAGER", "OWNER"]))
    @_write_options
    @json_option
    @click.pass_context
    def group_add_command(
        ctx: click.Context,
        group_email: str,
        member: str,
        role: str,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm(f"Add {member} to", group_email, yes=yes, dry_run=dry_run)
        data = add_admin_group_member(
            group=group_email, member=member, role=role, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"Added {member} to {group_email}")

    @group.command("group-remove")
    @click.argument("group_email")
    @click.argument("member")
    @_write_options
    @json_option
    @click.pass_context
    def group_remove_command(
        ctx: click.Context,
        group_email: str,
        member: str,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm(f"Remove {member} from", group_email, yes=yes, dry_run=dry_run)
        data = remove_admin_group_member(
            group=group_email, member=member, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"Removed {member} from {group_email}")

    @group.command("device-action")
    @click.argument("device_id")
    @click.argument("action", type=click.Choice(DEVICE_ACTIONS))
    @click.option(
        "--confirm-serial",
        default=None,
        help="The device's serial, retyped. Required — --yes does not arm this command.",
    )
    @click.option(
        "--reason",
        default=None,
        type=click.Choice(DEPROVISION_REASONS),
        help="Required by the API for `deprovision`, ignored by every other action.",
    )
    @_device_write_options
    @json_option
    @click.pass_context
    def device_action_command(
        ctx: click.Context,
        device_id: str,
        action: str,
        confirm_serial: str | None,
        reason: str | None,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _require_retype(
            confirm_serial, what="device-action", kind="serial", because="a wipe has no undo"
        )
        if action == "deprovision" and not reason:
            raise click.UsageError(
                "deprovision requires --reason: the Directory API rejects the action without "
                "`deprovisionReason`, and it is audited because it can return a licence. "
                f"Choices: {', '.join(DEPROVISION_REASONS)}."
            )
        if action != "deprovision" and reason:
            raise click.UsageError(f"--reason applies only to deprovision, not to {action}.")
        data = act_on_chromeos_device(
            device_id=device_id,
            action=action,
            confirm_serial=confirm_serial,
            reason=reason,
            dry_run=dry_run,
            config=ctx.obj["config"],
        )
        _emit_one(ctx, json_output, data, f"{action} sent to {device_id}")

    # ----------------------------------------------------------------- lifecycle reads

    @group.command("user")
    @click.argument("email")
    @json_option
    @click.pass_context
    def user_command(ctx: click.Context, email: str, json_output: bool | None) -> None:
        data = get_admin_user(email, config=ctx.obj["config"])
        _emit_one(ctx, json_output, data, f"{data['email']}  {data.get('org_unit_path')}")

    @group.command("group-members")
    @click.argument("group_email")
    @_limit_option
    @json_option
    @click.pass_context
    def group_members_command(
        ctx: click.Context, group_email: str, limit: int, json_output: bool | None
    ) -> None:
        rows = list_admin_group_members(group_email, limit=limit, config=ctx.obj["config"])
        _emit(ctx, json_output, rows, lambda row: f"{row['email']}  {row.get('role')}")

    @group.command("roles")
    @json_option
    @click.pass_context
    def roles_command(ctx: click.Context, json_output: bool | None) -> None:
        rows = list_admin_roles(config=ctx.obj["config"])
        _emit(
            ctx,
            json_output,
            rows,
            lambda row: "{}  {}{}".format(
                row.get("assigned_to"),
                row.get("role_name"),
                "  [super admin]" if row["is_super_admin"] else "",
            ),
        )

    @group.command("reports")
    @click.option("--app", default="login", type=click.Choice(REPORT_APPS), show_default=True)
    @_limit_option
    @json_option
    @click.pass_context
    def reports_command(
        ctx: click.Context, app: str, limit: int, json_output: bool | None
    ) -> None:
        rows = list_admin_reports(app=app, limit=limit, config=ctx.obj["config"])
        _emit(
            ctx,
            json_output,
            rows,
            lambda row: f"{row.get('time')}  {row.get('actor')}  {row.get('event')}",
        )

    # ----------------------------------------------------------------- lifecycle writes

    @group.command("user-delete")
    @click.argument("email")
    @click.option(
        "--confirm-email",
        default=None,
        help="The user's email, retyped. Required — deleting destroys their Drive and Gmail.",
    )
    @_irreversible_write_options
    @json_option
    @click.pass_context
    def user_delete_command(
        ctx: click.Context,
        email: str,
        confirm_email: str | None,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        data = delete_admin_user(
            email=email, confirm_email=confirm_email, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"User deleted: {email}")

    @group.command("user-rename")
    @click.argument("email")
    @click.option("--first-name", required=True)
    @click.option("--last-name", required=True)
    @_write_options
    @json_option
    @click.pass_context
    def user_rename_command(
        ctx: click.Context,
        email: str,
        first_name: str,
        last_name: str,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm("Rename", email, yes=yes, dry_run=dry_run)
        data = rename_admin_user(
            email=email,
            first_name=first_name,
            last_name=last_name,
            dry_run=dry_run,
            config=ctx.obj["config"],
        )
        _emit_one(ctx, json_output, data, f"User renamed: {email}")

    @group.command("user-password")
    @click.argument("email")
    @click.option("--password", required=True, help="Temporary; changed at next login.")
    @_write_options
    @json_option
    @click.pass_context
    def user_password_command(
        ctx: click.Context,
        email: str,
        password: str,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm("Reset the password of", email, yes=yes, dry_run=dry_run)
        data = reset_admin_user_password(
            email=email, password=password, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"Password reset: {email}")

    @group.command("user-admin")
    @click.argument("email")
    @click.option(
        "--grant/--revoke",
        "grant",
        default=None,
        help="Required. Neither one is a refusal, never a silent revoke.",
    )
    @_write_options
    @json_option
    @click.pass_context
    def user_admin_command(
        ctx: click.Context,
        email: str,
        grant: bool,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        # click's `required=True` on a flag pair is enforced by 8.1.8 and ignored by 8.3.1:
        # the same 0.9.4 binary refused on Homebrew and, in the repo venv, sent
        # `{"status": None}` and printed "Admin revoked" with exit 0. A rail that a
        # transitive minor version can remove is checked in our own code.
        if grant is None:
            raise click.UsageError(
                "user-admin requires --grant or --revoke: say which privilege change you "
                "mean. Neither one is not a revoke."
            )
        _confirm(
            "Grant super admin to" if grant else "Revoke super admin from",
            email,
            yes=yes,
            dry_run=dry_run,
        )
        data = set_admin_user_admin(
            email=email, grant=grant, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"Admin {'granted' if grant else 'revoked'}: {email}")

    @group.command("group-create")
    @click.argument("group_email")
    @click.option("--name", required=True)
    @click.option("--description", default=None)
    @_write_options
    @json_option
    @click.pass_context
    def group_create_command(
        ctx: click.Context,
        group_email: str,
        name: str,
        description: str | None,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm("Create group", group_email, yes=yes, dry_run=dry_run)
        data = create_admin_group(
            email=group_email,
            name=name,
            description=description,
            dry_run=dry_run,
            config=ctx.obj["config"],
        )
        _emit_one(ctx, json_output, data, f"Group created: {group_email}")

    @group.command("group-delete")
    @click.argument("group_email")
    @click.option(
        "--confirm-email",
        default=None,
        help="The group's email, retyped. Required — the membership list does not come back.",
    )
    @_irreversible_write_options
    @json_option
    @click.pass_context
    def group_delete_command(
        ctx: click.Context,
        group_email: str,
        confirm_email: str | None,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        data = delete_admin_group(
            email=group_email,
            confirm_email=confirm_email,
            dry_run=dry_run,
            config=ctx.obj["config"],
        )
        _emit_one(ctx, json_output, data, f"Group deleted: {group_email}")

    @group.command("orgunit-create")
    @click.argument("name")
    @click.option("--parent", default="/", show_default=True, help="Parent org unit path.")
    @_write_options
    @json_option
    @click.pass_context
    def orgunit_create_command(
        ctx: click.Context,
        name: str,
        parent: str,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _confirm(f"Create org unit {name} under", parent, yes=yes, dry_run=dry_run)
        data = create_admin_orgunit(
            name=name, parent=parent, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"Org unit created: {data.get('path', name)}")

    @group.command("orgunit-delete")
    @click.argument("path")
    @click.option(
        "--confirm-path",
        default=None,
        help="The org unit path, retyped. Required — deleting an org unit is irreversible.",
    )
    @_irreversible_write_options
    @json_option
    @click.pass_context
    def orgunit_delete_command(
        ctx: click.Context,
        path: str,
        confirm_path: str | None,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        data = delete_admin_orgunit(
            path=path, confirm_path=confirm_path, dry_run=dry_run, config=ctx.obj["config"]
        )
        _emit_one(ctx, json_output, data, f"Org unit deleted: {path}")

    @group.command("mobile-action")
    @click.argument("resource_id")
    @click.argument("action", type=click.Choice(MOBILE_ACTIONS))
    @click.option(
        "--confirm-serial",
        default=None,
        help="The device's serial, retyped. Required — a wipe has no undo.",
    )
    @_device_write_options
    @json_option
    @click.pass_context
    def mobile_action_command(
        ctx: click.Context,
        resource_id: str,
        action: str,
        confirm_serial: str | None,
        yes: bool,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        _require_retype(
            confirm_serial, what="mobile-action", kind="serial", because="a wipe has no undo"
        )
        data = act_on_mobile_device(
            resource_id=resource_id,
            action=action,
            confirm_serial=confirm_serial,
            dry_run=dry_run,
            config=ctx.obj["config"],
        )
        _emit_one(ctx, json_output, data, f"{action} sent to {resource_id}")
