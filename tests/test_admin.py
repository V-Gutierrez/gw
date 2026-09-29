"""Tests for the `gw admin` group: Workspace inventory, read-only.

The group exists to answer "what does this domain actually have" by command instead of
by a CSV exported by hand from the Admin Console. Two properties matter more than the
field mapping and are asserted here first:

* **Every page is fetched.** The 2026-08-28 catalogue was 82 machines; Directory API
  hands back 100 per page at most and the rest only through ``nextPageToken``. A single
  call would silently return a truncated inventory that still looks complete.
* **``whoami`` never raises.** It is the diagnostic for a half-granted setup, so an API
  that answers 403 has to be *reported*, not propagated.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gw.cli import main

runner = CliRunner()


def _mock_execute(payload):
    request = MagicMock()
    request.execute.return_value = payload
    return request


def _paged(*payloads):
    """A ``list()`` mock that hands back one payload per call, in order."""
    return MagicMock(side_effect=[_mock_execute(payload) for payload in payloads])


# --------------------------------------------------------------------------- wiring


def test_admin_subgroup_help():
    result = runner.invoke(main, ["admin", "--help"])
    assert result.exit_code == 0
    for command in ("users", "groups", "orgunits", "chromeos", "mobile", "telemetry", "whoami"):
        assert command in result.output


def test_every_mutating_command_offers_dry_run_and_confirmation():
    """Writing is in scope (Victor, 2026-09-29). Writing without a rail is not.

    This replaces an earlier `test_admin_group_is_read_only`, which asserted no mutating
    verb existed at all. That assertion described a scope decision the owner overruled, so
    it is gone; what survives is the rule that outlived it — a command that changes the
    domain must be able to show its work first and must ask before doing it.
    """
    mutating = (
        "user-create",
        "user-suspend",
        "user-restore",
        "user-move",
        "group-add",
        "group-remove",
        "device-action",
    )
    listing = runner.invoke(main, ["admin", "--help"])
    for command in mutating:
        assert command in listing.output

        help_text = runner.invoke(main, ["admin", command, "--help"]).output
        assert "--dry-run" in help_text, command
        if command != "device-action":
            assert "--yes" in help_text, command
        else:
            # The one command --yes must not arm: a wipe names a machine, and a machine
            # belongs to a person.
            assert "--confirm-serial" in help_text


# --------------------------------------------------------------------------- users


@patch("gw.services.admin.build_service")
def test_admin_users_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.list = _paged(
        {
            "users": [
                {
                    "primaryEmail": "victor@controlspacestorage.com",
                    "name": {"fullName": "Victor Gutierrez"},
                    "isAdmin": True,
                    "suspended": False,
                    "orgUnitPath": "/",
                    "lastLoginTime": "2026-09-29T08:00:00.000Z",
                    "id": "1",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "users", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["email"] == "victor@controlspacestorage.com"
    assert payload[0]["is_admin"] is True
    assert payload[0]["suspended"] is False
    assert payload[0]["org_unit_path"] == "/"
    assert mock_build_service.call_args.args == ("admin", "directory_v1")


@patch("gw.services.admin.build_service")
def test_admin_users_follows_every_page(mock_build_service: MagicMock):
    """A truncated inventory is worse than none: it looks complete."""
    service = MagicMock()
    service.users.return_value.list = _paged(
        {"users": [{"primaryEmail": "a@x.com", "id": "1"}], "nextPageToken": "p2"},
        {"users": [{"primaryEmail": "b@x.com", "id": "2"}], "nextPageToken": "p3"},
        {"users": [{"primaryEmail": "c@x.com", "id": "3"}]},
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "users", "--json"])

    assert result.exit_code == 0
    assert [row["email"] for row in json.loads(result.output)] == [
        "a@x.com",
        "b@x.com",
        "c@x.com",
    ]
    assert service.users.return_value.list.call_count == 3
    assert service.users.return_value.list.call_args_list[1].kwargs["pageToken"] == "p2"
    assert service.users.return_value.list.call_args_list[2].kwargs["pageToken"] == "p3"


@patch("gw.services.admin.build_service")
def test_admin_users_limit_stops_paging(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.list = _paged(
        {
            "users": [{"primaryEmail": "a@x.com"}, {"primaryEmail": "b@x.com"}],
            "nextPageToken": "p2",
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "users", "--limit", "2", "--json"])

    assert result.exit_code == 0
    assert len(json.loads(result.output)) == 2
    assert service.users.return_value.list.call_count == 1


@patch("gw.services.admin.build_service")
def test_admin_users_query_and_orgunit_reach_the_api(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.list = _paged({"users": []})
    mock_build_service.return_value = service

    result = runner.invoke(
        main, ["admin", "users", "--query", "isSuspended=true", "--org-unit", "/Ops", "--json"]
    )

    assert result.exit_code == 0
    kwargs = service.users.return_value.list.call_args.kwargs
    assert kwargs["query"] == "isSuspended=true orgUnitPath='/Ops'"
    assert kwargs["customer"] == "my_customer"


# --------------------------------------------------------------------------- groups


@patch("gw.services.admin.build_service")
def test_admin_groups_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.groups.return_value.list = _paged(
        {
            "groups": [
                {
                    "email": "ops@controlspacestorage.com",
                    "name": "Ops",
                    "directMembersCount": "4",
                    "id": "g1",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "groups", "--json"])

    assert result.exit_code == 0
    row = json.loads(result.output)[0]
    assert row["email"] == "ops@controlspacestorage.com"
    assert row["direct_members_count"] == 4


# --------------------------------------------------------------------------- orgunits


@patch("gw.services.admin.build_service")
def test_admin_orgunits_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.orgunits.return_value.list.return_value = _mock_execute(
        {
            "organizationUnits": [
                {"name": "Ops", "orgUnitPath": "/Ops", "parentOrgUnitPath": "/", "orgUnitId": "o1"}
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "orgunits", "--json"])

    assert result.exit_code == 0
    row = json.loads(result.output)[0]
    assert row["path"] == "/Ops"
    assert row["parent_path"] == "/"
    # orgunits is a flat non-paginated endpoint: type=all returns the whole tree at once.
    assert service.orgunits.return_value.list.call_args.kwargs["type"] == "all"


# --------------------------------------------------------------------------- devices


@patch("gw.services.admin.build_service")
def test_admin_chromeos_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.chromeosdevices.return_value.list = _paged(
        {
            "chromeosdevices": [
                {
                    "deviceId": "d1",
                    "serialNumber": "SN1",
                    "status": "ACTIVE",
                    "lastSync": "2026-09-20T10:00:00.000Z",
                    "annotatedUser": "victor@controlspacestorage.com",
                    "osVersion": "126.0",
                    "orgUnitPath": "/",
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "chromeos", "--json"])

    assert result.exit_code == 0
    row = json.loads(result.output)[0]
    assert row["serial_number"] == "SN1"
    assert row["status"] == "ACTIVE"
    assert row["last_sync"] == "2026-09-20T10:00:00.000Z"


@patch("gw.services.admin.build_service")
def test_admin_mobile_json(mock_build_service: MagicMock):
    service = MagicMock()
    service.mobiledevices.return_value.list = _paged(
        {
            "mobiledevices": [
                {
                    "resourceId": "m1",
                    "serialNumber": "SN9",
                    "model": "Pixel 8",
                    "os": "Android 15",
                    "status": "APPROVED",
                    "email": ["victor@controlspacestorage.com"],
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "mobile", "--json"])

    assert result.exit_code == 0
    row = json.loads(result.output)[0]
    assert row["model"] == "Pixel 8"
    assert row["email"] == "victor@controlspacestorage.com"


# --------------------------------------------------------------------------- telemetry


@patch("gw.services.admin.build_service")
def test_admin_telemetry_uses_chrome_management(mock_build_service: MagicMock):
    service = MagicMock()
    service.customers.return_value.telemetry.return_value.devices.return_value.list = _paged(
        {
            "devices": [
                {
                    "deviceId": "t1",
                    "serialNumber": "SN1",
                    "orgUnitId": "o1",
                    "cpuInfo": [{"model": "Intel i5"}],
                    "memoryInfo": {"totalRamBytes": "8589934592"},
                }
            ]
        }
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "telemetry", "--json"])

    assert result.exit_code == 0
    row = json.loads(result.output)[0]
    assert row["serial_number"] == "SN1"
    assert row["cpu_model"] == "Intel i5"
    assert row["total_ram_bytes"] == 8589934592
    assert mock_build_service.call_args.args == ("chromemanagement", "v1")
    kwargs = service.customers.return_value.telemetry.return_value.devices.return_value.list.call_args.kwargs
    assert kwargs["parent"] == "customers/my_customer"


# --------------------------------------------------------------------------- whoami


@patch("gw.services.admin.build_service")
def test_admin_whoami_reports_each_api(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.list.return_value = _mock_execute({"users": []})
    service.groups.return_value.list.return_value = _mock_execute({"groups": []})
    service.chromeosdevices.return_value.list.return_value = _mock_execute({"chromeosdevices": []})
    service.customers.return_value.telemetry.return_value.devices.return_value.list.return_value = _mock_execute(
        {"devices": []}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "whoami", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    names = {probe["api"] for probe in payload["probes"]}
    assert names == {
        "directory.users",
        "directory.groups",
        "directory.chromeos",
        "chrome.telemetry",
    }
    assert all(probe["reachable"] for probe in payload["probes"])


@patch("gw.services.admin.build_service")
def test_admin_whoami_reports_a_denied_api_without_raising(mock_build_service: MagicMock):
    """A half-granted domain is the normal first state — diagnose it, do not crash on it."""
    from gw.errors import GwError

    service = MagicMock()
    service.users.return_value.list.return_value = _mock_execute({"users": []})
    service.groups.return_value.list.side_effect = GwError("Insufficient permission")
    service.chromeosdevices.return_value.list.return_value = _mock_execute({"chromeosdevices": []})
    service.customers.return_value.telemetry.return_value.devices.return_value.list.return_value = _mock_execute(
        {"devices": []}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "whoami", "--json"])

    # Reports instead of propagating: the other three probes still ran and are in the output.
    # The exit code is non-zero (see test_whoami_exits_nonzero_when_an_api_is_denied) —
    # what matters here is that nothing raised and every probe is accounted for.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert len(payload["probes"]) == 4
    denied = next(probe for probe in payload["probes"] if probe["api"] == "directory.groups")
    assert denied["reachable"] is False
    assert "Insufficient permission" in denied["error"]


# --------------------------------------------------------------------------- defects
#
# Everything below was found by adversarial review after the suite was already green.
# Mocks agreed with the code because they were written from the same wrong assumptions;
# these tests encode what the Google docs and a real invocation say instead.


@patch("gw.services.admin.build_service")
def test_negative_limit_is_rejected_not_silently_emptied(mock_build_service: MagicMock):
    """`--limit -1` used to exit 0 printing `0 row(s)` — an empty domain reported as success.

    The slice `collected[:limit]` with a negative limit drops rows instead of capping them.
    An inventory tool that answers "nothing here" with exit 0 is the worst possible failure.
    """
    service = MagicMock()
    service.users.return_value.list = _paged({"users": [{"primaryEmail": "a@x.com"}]})
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "users", "--limit", "-1", "--json"])

    assert result.exit_code != 0
    assert "limit" in result.output.lower()


@patch("gw.services.admin.build_service")
def test_paging_stops_when_the_token_does_not_advance(mock_build_service: MagicMock):
    """A server that keeps handing back the same pageToken must not spin forever."""
    service = MagicMock()
    service.users.return_value.list = MagicMock(
        return_value=_mock_execute(
            {"users": [{"primaryEmail": "a@x.com"}], "nextPageToken": "same"}
        )
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "users", "--json"])

    assert result.exit_code == 0
    # Two calls: the first page, then one more that proves the token repeated.
    assert service.users.return_value.list.call_count == 2


@patch("gw.services.admin.build_service")
def test_device_listings_ask_for_the_full_projection(mock_build_service: MagicMock):
    """BASIC's field list is documented with `e.g.` — last_sync and os_version are not in it.

    Google states the BASIC projection "includes only the basic metadata fields (e.g.,
    deviceId, serialNumber, status, and user)". Reading lastSync or osVersion off a BASIC
    row is reading a field nobody promised. FULL guarantees the whole schema.
    """
    service = MagicMock()
    service.chromeosdevices.return_value.list = _paged({"chromeosdevices": []})
    service.mobiledevices.return_value.list = _paged({"mobiledevices": []})
    mock_build_service.return_value = service

    assert runner.invoke(main, ["admin", "chromeos", "--json"]).exit_code == 0
    assert service.chromeosdevices.return_value.list.call_args.kwargs["projection"] == "FULL"

    assert runner.invoke(main, ["admin", "mobile", "--json"]).exit_code == 0
    assert service.mobiledevices.return_value.list.call_args.kwargs["projection"] == "FULL"


@patch("gw.services.admin.build_service")
def test_whoami_exits_nonzero_when_an_api_is_denied(mock_build_service: MagicMock):
    """whoami is a gate. Exit 0 on four denied APIs makes it useless in a script."""
    from gw.errors import GwError

    service = MagicMock()
    service.users.return_value.list.return_value = _mock_execute({"users": []})
    service.groups.return_value.list.side_effect = GwError("Insufficient permission")
    service.chromeosdevices.return_value.list.return_value = _mock_execute({"chromeosdevices": []})
    service.customers.return_value.telemetry.return_value.devices.return_value.list.return_value = _mock_execute(
        {"devices": []}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "whoami", "--json"])

    assert result.exit_code != 0
    assert json.loads(result.output)["ok"] is False


@patch("gw.services.admin.build_service")
def test_whoami_does_not_disguise_a_bug_as_a_denied_api(mock_build_service: MagicMock):
    """A TypeError from a wrong parameter name is our bug, not Google saying no.

    The first version caught bare `Exception`, so a misspelled kwarg was reported as
    "API unreachable" — the one diagnostic that exists to tell those two apart.
    """
    service = MagicMock()
    service.users.return_value.list.side_effect = TypeError("gotmy an unexpected keyword argument")
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "whoami", "--json"])

    assert result.exit_code != 0
    assert "unreachable" not in result.output.lower()


# --------------------------------------------------------------------------- writes
#
# Victor's call, 2026-09-29: "eu quero gerir o workspace via GW". Writing is in scope.
# The guard rails below are what make it survivable, and each one is asserted here — a
# confirmation that only lives in a docstring is a confirmation nobody runs.


@patch("gw.services.admin.build_service")
def test_suspend_requires_confirmation_and_aborts_on_no(mock_build_service: MagicMock):
    service = MagicMock()
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "user-suspend", "a@x.com"], input="n\n")

    assert result.exit_code != 0
    service.users.return_value.update.assert_not_called()


@patch("gw.services.admin.build_service")
def test_suspend_applies_when_confirmed(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.update.return_value = _mock_execute(
        {"primaryEmail": "a@x.com", "suspended": True}
    )
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "user-suspend", "a@x.com", "--yes", "--json"])

    assert result.exit_code == 0
    kwargs = service.users.return_value.update.call_args.kwargs
    assert kwargs["userKey"] == "a@x.com"
    assert kwargs["body"] == {"suspended": True}
    assert json.loads(result.output)["suspended"] is True


@patch("gw.services.admin.build_service")
def test_dry_run_reports_without_calling_the_api(mock_build_service: MagicMock):
    """--dry-run must reach zero write calls, not merely print something reassuring."""
    service = MagicMock()
    mock_build_service.return_value = service

    result = runner.invoke(
        main, ["admin", "user-suspend", "a@x.com", "--dry-run", "--yes", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["dry_run"] is True
    service.users.return_value.update.assert_not_called()


@patch("gw.services.admin.build_service")
def test_user_create_sends_the_documented_body(mock_build_service: MagicMock):
    service = MagicMock()
    service.users.return_value.insert.return_value = _mock_execute(
        {"primaryEmail": "new@x.com", "id": "9"}
    )
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "admin",
            "user-create",
            "new@x.com",
            "--first-name",
            "Nova",
            "--last-name",
            "Pessoa",
            "--password",
            "s3cr3t-temp",
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 0
    body = service.users.return_value.insert.call_args.kwargs["body"]
    assert body["primaryEmail"] == "new@x.com"
    assert body["name"] == {"givenName": "Nova", "familyName": "Pessoa"}
    assert body["password"] == "s3cr3t-temp"
    assert body["changePasswordAtNextLogin"] is True


@patch("gw.services.admin.build_service")
def test_password_never_reaches_stdout(mock_build_service: MagicMock):
    """A created user's password must not land in a transcript, a log or a chat bubble."""
    service = MagicMock()
    service.users.return_value.insert.return_value = _mock_execute(
        {"primaryEmail": "new@x.com", "password": "s3cr3t-temp", "id": "9"}
    )
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "admin",
            "user-create",
            "new@x.com",
            "--first-name",
            "Nova",
            "--last-name",
            "Pessoa",
            "--password",
            "s3cr3t-temp",
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert "s3cr3t-temp" not in result.output


@patch("gw.services.admin.build_service")
def test_group_membership_add_and_remove(mock_build_service: MagicMock):
    service = MagicMock()
    service.members.return_value.insert.return_value = _mock_execute(
        {"email": "a@x.com", "role": "MEMBER"}
    )
    service.members.return_value.delete.return_value = _mock_execute({})
    mock_build_service.return_value = service

    added = runner.invoke(main, ["admin", "group-add", "ops@x.com", "a@x.com", "--yes", "--json"])
    assert added.exit_code == 0
    assert service.members.return_value.insert.call_args.kwargs["groupKey"] == "ops@x.com"

    removed = runner.invoke(
        main, ["admin", "group-remove", "ops@x.com", "a@x.com", "--yes", "--json"]
    )
    assert removed.exit_code == 0
    assert service.members.return_value.delete.call_args.kwargs["memberKey"] == "a@x.com"


@patch("gw.services.admin.build_service")
def test_device_action_needs_the_typed_serial_not_just_yes(mock_build_service: MagicMock):
    """Wiping a device has no undo, so --yes is not enough: the serial must be retyped.

    Every other write takes --yes. This one does not, because the failure mode is a wiped
    laptop belonging to someone who did nothing wrong.
    """
    service = MagicMock()
    mock_build_service.return_value = service

    result = runner.invoke(main, ["admin", "device-action", "d1", "wipe", "--yes", "--json"])

    assert result.exit_code != 0
    service.chromeosdevices.return_value.action.assert_not_called()


@patch("gw.services.admin.build_service")
def test_device_action_runs_when_the_serial_matches(mock_build_service: MagicMock):
    service = MagicMock()
    service.chromeosdevices.return_value.get.return_value = _mock_execute({"serialNumber": "SN1"})
    service.chromeosdevices.return_value.action.return_value = _mock_execute({})
    mock_build_service.return_value = service

    result = runner.invoke(
        main, ["admin", "device-action", "d1", "disable", "--confirm-serial", "SN1", "--json"]
    )

    assert result.exit_code == 0
    assert service.chromeosdevices.return_value.action.call_args.kwargs["body"] == {
        "action": "disable"
    }


@patch("gw.services.admin.build_service")
def test_device_action_refuses_a_serial_that_does_not_match(mock_build_service: MagicMock):
    service = MagicMock()
    service.chromeosdevices.return_value.get.return_value = _mock_execute({"serialNumber": "SN1"})
    mock_build_service.return_value = service

    result = runner.invoke(
        main, ["admin", "device-action", "d1", "wipe", "--confirm-serial", "WRONG", "--json"]
    )

    assert result.exit_code != 0
    service.chromeosdevices.return_value.action.assert_not_called()


def test_write_scopes_are_the_broad_ones():
    """Read-only scopes cannot perform a write; the write list must not quietly be readonly."""
    from gw.auth import ADMIN_SCOPES, ADMIN_WRITE_SCOPES

    assert all(scope.endswith(".readonly") for scope in ADMIN_SCOPES)
    directory_writes = [s for s in ADMIN_WRITE_SCOPES if "admin.directory" in s]
    assert directory_writes
    assert not any(scope.endswith(".readonly") for scope in directory_writes)
