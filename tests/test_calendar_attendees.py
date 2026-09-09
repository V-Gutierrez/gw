"""Attendees, location and reminders on calendar create/update."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.services.calendar import create_calendar_event, update_calendar_event

runner = CliRunner()


def _mock_execute(payload: Any) -> MagicMock:
    request = MagicMock()
    request.execute.return_value = payload
    return request


def _service() -> MagicMock:
    service = MagicMock()
    service.events.return_value.insert.return_value = _mock_execute(
        {"id": "evt-1", "htmlLink": "https://calendar/event/evt-1"}
    )
    service.events.return_value.patch.return_value = _mock_execute(
        {"id": "evt-1", "htmlLink": "https://calendar/event/evt-1"}
    )
    return service


def _inserted_body(service: MagicMock) -> dict[str, Any]:
    _, kwargs = service.events.return_value.insert.call_args
    return kwargs["body"]


def _patched_body(service: MagicMock) -> dict[str, Any]:
    _, kwargs = service.events.return_value.patch.call_args
    return kwargs["body"]


# --- create ----------------------------------------------------------------


@patch("gw.services.calendar.build_service")
def test_create_event_with_attendees_and_location(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    create_calendar_event(
        title="Reuniao",
        start="2026-09-10T10:00",
        end="2026-09-10T11:00",
        timezone="Europe/Lisbon",
        default_calendar="primary",
        attendees=("a@example.com", "b@example.com"),
        location="Rua X, Lisboa",
    )

    body = _inserted_body(service)
    assert body["attendees"] == [{"email": "a@example.com"}, {"email": "b@example.com"}]
    assert body["location"] == "Rua X, Lisboa"


@patch("gw.services.calendar.build_service")
def test_create_event_defaults_to_no_invitation_emails(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    create_calendar_event(
        title="Reuniao",
        start="2026-09-10T10:00",
        end="2026-09-10T11:00",
        timezone="Europe/Lisbon",
        default_calendar="primary",
        attendees=("a@example.com",),
    )

    _, kwargs = service.events.return_value.insert.call_args
    assert kwargs["sendUpdates"] == "none"


@patch("gw.services.calendar.build_service")
def test_create_event_can_notify_attendees(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    create_calendar_event(
        title="Reuniao",
        start="2026-09-10T10:00",
        end="2026-09-10T11:00",
        timezone="Europe/Lisbon",
        default_calendar="primary",
        attendees=("a@example.com",),
        send_updates="all",
    )

    _, kwargs = service.events.return_value.insert.call_args
    assert kwargs["sendUpdates"] == "all"


@patch("gw.services.calendar.build_service")
def test_create_event_without_attendees_omits_the_key(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    create_calendar_event(
        title="Bloco",
        start="2026-09-10T10:00",
        end="2026-09-10T11:00",
        timezone="Europe/Lisbon",
        default_calendar="primary",
    )

    body = _inserted_body(service)
    assert "attendees" not in body
    assert "location" not in body


# --- update ----------------------------------------------------------------


@patch("gw.services.calendar.build_service")
def test_update_event_sets_location_attendees_and_reminder(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    data = update_calendar_event(
        event_id="evt-1",
        timezone="Europe/Lisbon",
        default_calendar="primary",
        location="Sala 2",
        attendees=("c@example.com",),
        reminder=15,
    )

    body = _patched_body(service)
    assert body["location"] == "Sala 2"
    assert body["attendees"] == [{"email": "c@example.com"}]
    assert body["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 15}],
    }
    assert data["updated_fields"] == ["attendees", "location", "reminders"]


@patch("gw.services.calendar.build_service")
def test_update_event_still_rejects_empty_patch(mock_build_service: MagicMock):
    mock_build_service.return_value = _service()

    with pytest.raises(click.ClickException, match="at least one field"):
        update_calendar_event(
            event_id="evt-1",
            timezone="Europe/Lisbon",
            default_calendar="primary",
        )


# --- CLI -------------------------------------------------------------------


@patch("gw.services.calendar.build_service")
def test_cli_create_accepts_repeated_attendees(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "calendar",
            "create",
            "Reuniao",
            "2026-09-10T10:00",
            "2026-09-10T11:00",
            "--attendees",
            "a@example.com",
            "--attendees",
            "b@example.com",
            "--location",
            "Lisboa",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["id"] == "evt-1"
    body = _inserted_body(service)
    assert [entry["email"] for entry in body["attendees"]] == [
        "a@example.com",
        "b@example.com",
    ]
    assert body["location"] == "Lisboa"


@patch("gw.services.calendar.build_service")
def test_cli_create_send_updates_flag(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "calendar",
            "create",
            "Reuniao",
            "2026-09-10T10:00",
            "2026-09-10T11:00",
            "--attendees",
            "a@example.com",
            "--send-updates",
            "all",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    _, kwargs = service.events.return_value.insert.call_args
    assert kwargs["sendUpdates"] == "all"


@patch("gw.services.calendar.build_service")
def test_cli_update_accepts_location_attendees_reminder(mock_build_service: MagicMock):
    service = _service()
    mock_build_service.return_value = service

    result = runner.invoke(
        main,
        [
            "calendar",
            "update",
            "evt-1",
            "--location",
            "Sala 2",
            "--attendees",
            "c@example.com",
            "--reminder",
            "15",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    body = _patched_body(service)
    assert body["location"] == "Sala 2"
    assert body["attendees"] == [{"email": "c@example.com"}]
    assert body["reminders"]["overrides"] == [{"method": "popup", "minutes": 15}]
