from __future__ import annotations

from datetime import timedelta
from typing import Any

import click

from gw.auth import build_service
from gw.output import json_option, print_human, print_json, print_success, use_json_output
from gw.utils import date_range_today, date_range_week, format_event_time, parse_date, to_rfc3339


def _calendar_service():
    return build_service("calendar", "v3")


def _fetch_events(
    start: str, end: str, all_calendars: bool, default_calendar: str
) -> list[dict[str, Any]]:
    service = _calendar_service()
    calendars: list[dict[str, Any]]
    if all_calendars:
        calendars = service.calendarList().list().execute().get("items", [])
    else:
        calendars = [
            {
                "id": default_calendar,
                "summary": default_calendar,
                "primary": default_calendar == "primary",
            }
        ]

    items: list[dict[str, Any]] = []
    for calendar in calendars:
        response = (
            service.events()
            .list(
                calendarId=calendar["id"],
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        for event in response.get("items", []):
            items.append(
                {
                    "id": event.get("id"),
                    "summary": event.get("summary", "(No title)"),
                    "start": event.get("start", {}),
                    "end": event.get("end", {}),
                    "calendar": calendar.get("summary", calendar["id"]),
                    "calendar_id": calendar["id"],
                    "html_link": event.get("htmlLink"),
                }
            )
    return items


def _print_events(events: list[dict[str, Any]], label: str, include_calendar: bool) -> None:
    if not events:
        print_human(f"No events {label.lower()}.", emoji="📅")
        return
    print_human(f"{label} ({len(events)}):", emoji="📅")
    for event in events:
        suffix = f" [{event['calendar']}]" if include_calendar else ""
        print_human(f"  • {format_event_time(event)}: {event['summary']}{suffix}")


def get_calendar_today(
    timezone: str, default_calendar: str, all_calendars: bool = False
) -> list[dict[str, Any]]:
    start, end = date_range_today(timezone)
    return _fetch_events(to_rfc3339(start), to_rfc3339(end), all_calendars, default_calendar)


def get_calendar_tomorrow(
    timezone: str,
    default_calendar: str,
    all_calendars: bool = False,
) -> list[dict[str, Any]]:
    start, end = date_range_today(timezone)
    start += timedelta(days=1)
    end += timedelta(days=1)
    return _fetch_events(to_rfc3339(start), to_rfc3339(end), all_calendars, default_calendar)


def get_calendar_week(
    timezone: str, default_calendar: str, all_calendars: bool = False
) -> list[dict[str, Any]]:
    start, end = date_range_week(timezone)
    return _fetch_events(to_rfc3339(start), to_rfc3339(end), all_calendars, default_calendar)


def create_calendar_event(
    title: str,
    start: str,
    end: str,
    timezone: str,
    default_calendar: str,
    description: str = "",
    all_day: bool = False,
    recurrence: tuple[str, ...] = (),
    calendar_id: str | None = None,
    reminder: int | None = None,
) -> dict[str, Any]:
    service = _calendar_service()
    target_calendar = calendar_id or default_calendar
    start_dt = parse_date(start, timezone)
    end_dt = parse_date(end, timezone)

    if all_day:
        event: dict[str, Any] = {
            "summary": title,
            "description": description,
            "start": {"date": start_dt.date().isoformat()},
            "end": {"date": end_dt.date().isoformat()},
        }
    else:
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": to_rfc3339(start_dt), "timeZone": timezone},
            "end": {"dateTime": to_rfc3339(end_dt), "timeZone": timezone},
        }

    if recurrence:
        event["recurrence"] = list(recurrence)
    if reminder is not None:
        event["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": reminder}],
        }

    created = service.events().insert(calendarId=target_calendar, body=event).execute()
    return {
        "id": created.get("id"),
        "html_link": created.get("htmlLink"),
        "calendar": target_calendar,
    }


def list_calendars() -> list[dict[str, Any]]:
    service = _calendar_service()
    calendars = service.calendarList().list().execute().get("items", [])
    return [
        {
            "id": item.get("id"),
            "summary": item.get("summary"),
            "primary": bool(item.get("primary")),
        }
        for item in calendars
    ]


def delete_calendar_event(
    event_id: str, default_calendar: str, calendar_id: str | None = None
) -> dict[str, Any]:
    service = _calendar_service()
    target_calendar = calendar_id or default_calendar
    service.events().delete(calendarId=target_calendar, eventId=event_id).execute()
    return {"deleted": True, "event_id": event_id, "calendar": target_calendar}


def update_calendar_event(
    event_id: str,
    timezone: str,
    default_calendar: str,
    calendar_id: str | None = None,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    if (start is None) != (end is None):
        raise click.ClickException("Provide both --start and --end together.")

    patch: dict[str, Any] = {}
    if title is not None:
        patch["summary"] = title
    if description is not None:
        patch["description"] = description
    if start is not None and end is not None:
        start_dt = parse_date(start, timezone)
        end_dt = parse_date(end, timezone)
        patch["start"] = {"dateTime": to_rfc3339(start_dt), "timeZone": timezone}
        patch["end"] = {"dateTime": to_rfc3339(end_dt), "timeZone": timezone}

    if not patch:
        raise click.ClickException("Provide at least one field to update.")

    service = _calendar_service()
    target_calendar = calendar_id or default_calendar
    updated = (
        service.events().patch(calendarId=target_calendar, eventId=event_id, body=patch).execute()
    )
    return {
        "id": updated.get("id", event_id),
        "html_link": updated.get("htmlLink"),
        "calendar": target_calendar,
        "updated_fields": sorted(patch.keys()),
    }


def register_calendar_commands(group: click.Group) -> None:
    @group.command("today")
    @click.option("--all", "all_calendars", is_flag=True, help="Include all calendars.")
    @json_option
    @click.pass_context
    def today_command(ctx: click.Context, all_calendars: bool, json_output: bool | None) -> None:
        config = ctx.obj["config"]
        events = get_calendar_today(config.timezone, config.default_calendar, all_calendars)
        if use_json_output(ctx, json_output):
            print_json(events)
        else:
            _print_events(events, "Today's events", all_calendars)

    @group.command("tomorrow")
    @click.option("--all", "all_calendars", is_flag=True, help="Include all calendars.")
    @json_option
    @click.pass_context
    def tomorrow_command(
        ctx: click.Context, all_calendars: bool, json_output: bool | None
    ) -> None:
        config = ctx.obj["config"]
        events = get_calendar_tomorrow(config.timezone, config.default_calendar, all_calendars)
        if use_json_output(ctx, json_output):
            print_json(events)
        else:
            _print_events(events, "Tomorrow's events", all_calendars)

    @group.command("week")
    @click.option("--all", "all_calendars", is_flag=True, help="Include all calendars.")
    @json_option
    @click.pass_context
    def week_command(ctx: click.Context, all_calendars: bool, json_output: bool | None) -> None:
        config = ctx.obj["config"]
        events = get_calendar_week(config.timezone, config.default_calendar, all_calendars)
        if use_json_output(ctx, json_output):
            print_json(events)
        else:
            _print_events(events, "This week's events", all_calendars)

    @group.command("create")
    @click.argument("title")
    @click.argument("start")
    @click.argument("end")
    @click.option("--description", default="", help="Event description.")
    @click.option("--all-day", is_flag=True, help="Create an all-day event.")
    @click.option("--recurrence", multiple=True, help="Add one RRULE recurrence value.")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar ID to use.")
    @click.option("--reminder", default=None, type=int, help="Popup reminder in minutes.")
    @json_option
    @click.pass_context
    def create_command(
        ctx: click.Context,
        title: str,
        start: str,
        end: str,
        description: str,
        all_day: bool,
        recurrence: tuple[str, ...],
        calendar_id: str | None,
        reminder: int | None,
        json_output: bool | None,
    ) -> None:
        config = ctx.obj["config"]
        data = create_calendar_event(
            title=title,
            start=start,
            end=end,
            timezone=config.timezone,
            default_calendar=config.default_calendar,
            description=description,
            all_day=all_day,
            recurrence=recurrence,
            calendar_id=calendar_id,
            reminder=reminder,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Event created: {data.get('html_link', data.get('id', 'unknown'))}")

    @group.command("list")
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, json_output: bool | None) -> None:
        data = list_calendars()
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Available calendars ({len(data)}):", emoji="📅")
            for item in data:
                suffix = " [PRIMARY]" if item["primary"] else ""
                print_human(f"  • {item['summary']}{suffix}")
                print_human(f"    ID: {item['id']}")

    @group.command("delete")
    @click.argument("event_id")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar containing the event.")
    @json_option
    @click.pass_context
    def delete_command(
        ctx: click.Context, event_id: str, calendar_id: str | None, json_output: bool | None
    ) -> None:
        config = ctx.obj["config"]
        data = delete_calendar_event(
            event_id=event_id,
            default_calendar=config.default_calendar,
            calendar_id=calendar_id,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Event deleted: {data['event_id']}")

    @group.command("update")
    @click.argument("event_id")
    @click.option("--title", default=None, help="Updated event title.")
    @click.option("--start", default=None, help="Updated event start datetime.")
    @click.option("--end", default=None, help="Updated event end datetime.")
    @click.option("--description", default=None, help="Updated event description.")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar containing the event.")
    @json_option
    @click.pass_context
    def update_command(
        ctx: click.Context,
        event_id: str,
        title: str | None,
        start: str | None,
        end: str | None,
        description: str | None,
        calendar_id: str | None,
        json_output: bool | None,
    ) -> None:
        config = ctx.obj["config"]
        data = update_calendar_event(
            event_id=event_id,
            timezone=config.timezone,
            default_calendar=config.default_calendar,
            calendar_id=calendar_id,
            title=title,
            start=start,
            end=end,
            description=description,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Event updated: {data['id']}")

    @group.command("calendars", hidden=True)
    @json_option
    @click.pass_context
    def calendars_alias(ctx: click.Context, json_output: bool | None) -> None:
        ctx.invoke(list_command, json_output=json_output)
