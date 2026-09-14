from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.services.calendar import (
    create_calendar,
    list_calendar_acl,
    list_event_instances,
    move_calendar_event,
    query_freebusy,
    quick_add_event,
    share_calendar,
    unshare_calendar,
)


def _service() -> MagicMock:
    service = MagicMock()
    service.freebusy.return_value.query.return_value.execute.return_value = {
        "calendars": {
            "ana@x.com": {
                "busy": [{"start": "2026-09-10T09:00:00Z", "end": "2026-09-10T10:00:00Z"}]
            },
            "bob@x.com": {"busy": []},
        }
    }
    service.events.return_value.quickAdd.return_value.execute.return_value = {
        "id": "e1",
        "summary": "Almoço com Ana",
        "htmlLink": "https://cal/e1",
        "start": {"dateTime": "2026-09-10T12:00:00Z"},
    }
    service.events.return_value.move.return_value.execute.return_value = {
        "id": "e1",
        "summary": "Movido",
        "htmlLink": "https://cal/e1",
    }
    service.events.return_value.instances.return_value.execute.return_value = {
        "items": [
            {
                "id": "e1_20260910",
                "summary": "Weekly",
                "start": {"dateTime": "2026-09-10T10:00:00Z"},
                "end": {"dateTime": "2026-09-10T11:00:00Z"},
                "status": "confirmed",
            }
        ]
    }
    service.calendars.return_value.insert.return_value.execute.return_value = {
        "id": "cal_new",
        "summary": "Projetos",
    }
    service.acl.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "user:ana@x.com",
                "role": "writer",
                "scope": {"type": "user", "value": "ana@x.com"},
            }
        ]
    }
    service.acl.return_value.insert.return_value.execute.return_value = {
        "id": "user:bob@x.com",
        "role": "reader",
    }
    return service


def test_freebusy_reports_busy_and_free_per_person() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        data = query_freebusy(
            emails=["ana@x.com", "bob@x.com"], start="2026-09-10", end="2026-09-11"
        )

    body = service.freebusy.return_value.query.call_args.kwargs["body"]
    assert [item["id"] for item in body["items"]] == ["ana@x.com", "bob@x.com"]
    by_email = {entry["email"]: entry for entry in data["calendars"]}
    assert len(by_email["ana@x.com"]["busy"]) == 1
    assert by_email["bob@x.com"]["busy"] == []


def test_quick_add_passes_natural_language_straight_through() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        data = quick_add_event("Almoço com Ana amanhã às 12h")

    kwargs = service.events.return_value.quickAdd.call_args.kwargs
    assert kwargs["text"] == "Almoço com Ana amanhã às 12h"
    assert kwargs["calendarId"] == "primary"
    assert data["id"] == "e1"


def test_move_event_sends_source_and_destination() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        move_calendar_event("e1", destination="work@group.calendar.google.com", calendar="primary")

    kwargs = service.events.return_value.move.call_args.kwargs
    assert kwargs["calendarId"] == "primary"
    assert kwargs["eventId"] == "e1"
    assert kwargs["destination"] == "work@group.calendar.google.com"


def test_instances_expands_a_recurring_event() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        data = list_event_instances("e1", max_results=5)

    assert service.events.return_value.instances.call_args.kwargs["eventId"] == "e1"
    assert data[0]["id"] == "e1_20260910"


def test_create_calendar_returns_the_new_id() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        data = create_calendar("Projetos", timezone="Europe/Lisbon")

    body = service.calendars.return_value.insert.call_args.kwargs["body"]
    assert body["summary"] == "Projetos"
    assert body["timeZone"] == "Europe/Lisbon"
    assert data["id"] == "cal_new"


def test_acl_list_shows_who_has_access() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        data = list_calendar_acl("primary")

    assert data[0]["email"] == "ana@x.com"
    assert data[0]["role"] == "writer"


def test_share_calendar_inserts_a_user_scoped_rule() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        share_calendar("primary", "bob@x.com", role="reader")

    body = service.acl.return_value.insert.call_args.kwargs["body"]
    assert body == {"role": "reader", "scope": {"type": "user", "value": "bob@x.com"}}


def test_unshare_calendar_deletes_the_rule_by_scope_id() -> None:
    service = _service()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        unshare_calendar("primary", "ana@x.com")

    kwargs = service.acl.return_value.delete.call_args.kwargs
    assert kwargs["ruleId"] == "user:ana@x.com"


def test_unshare_calendar_errors_when_the_person_has_no_access() -> None:
    service = _service()
    with (
        patch("gw.services.calendar._calendar_service", return_value=service),
        pytest.raises(click.ClickException, match="ninguem@x.com"),
    ):
        unshare_calendar("primary", "ninguem@x.com")


def test_calendar_commands_are_wired() -> None:
    service = _service()
    runner = CliRunner()
    with patch("gw.services.calendar._calendar_service", return_value=service):
        assert (
            runner.invoke(
                main,
                [
                    "calendar",
                    "freebusy",
                    "ana@x.com",
                    "--start",
                    "2026-09-10",
                    "--end",
                    "2026-09-11",
                ],
            ).exit_code
            == 0
        )
        assert runner.invoke(main, ["calendar", "quick-add", "Almoço amanhã 12h"]).exit_code == 0
        assert runner.invoke(main, ["calendar", "move", "e1", "work@g.com"]).exit_code == 0
        assert runner.invoke(main, ["calendar", "instances", "e1"]).exit_code == 0
        assert runner.invoke(main, ["calendar", "create-calendar", "Projetos"]).exit_code == 0
        assert runner.invoke(main, ["calendar", "acl", "--calendar", "primary"]).exit_code == 0
        assert runner.invoke(main, ["calendar", "share", "bob@x.com"]).exit_code == 0
        assert runner.invoke(main, ["calendar", "unshare", "ana@x.com", "--yes"]).exit_code == 0
