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


def register_calendar_commands(group: click.Group) -> None:
    @group.command("today")
    @click.option("--all", "all_calendars", is_flag=True, help="Include all calendars.")
    @json_option
    @click.pass_context
    def today_command(ctx: click.Context, all_calendars: bool, json_output: bool | None) -> None:
        config = ctx.obj["config"]
        start, end = date_range_today(config.timezone)
        events = _fetch_events(
            to_rfc3339(start),
            to_rfc3339(end),
            all_calendars,
            config.default_calendar,
        )
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
        start, end = date_range_today(config.timezone)
        start += timedelta(days=1)
        end += timedelta(days=1)
        events = _fetch_events(
            to_rfc3339(start),
            to_rfc3339(end),
            all_calendars,
            config.default_calendar,
        )
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
        start, end = date_range_week(config.timezone)
        events = _fetch_events(
            to_rfc3339(start),
            to_rfc3339(end),
            all_calendars,
            config.default_calendar,
        )
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
        service = _calendar_service()
        target_calendar = calendar_id or config.default_calendar
        start_dt = parse_date(start, config.timezone)
        end_dt = parse_date(end, config.timezone)

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
                "start": {"dateTime": to_rfc3339(start_dt), "timeZone": config.timezone},
                "end": {"dateTime": to_rfc3339(end_dt), "timeZone": config.timezone},
            }

        if recurrence:
            event["recurrence"] = list(recurrence)
        if reminder is not None:
            event["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": reminder}],
            }

        created = service.events().insert(calendarId=target_calendar, body=event).execute()
        data = {
            "id": created.get("id"),
            "html_link": created.get("htmlLink"),
            "calendar": target_calendar,
        }
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(
                f"Event created: {created.get('htmlLink', created.get('id', 'unknown'))}"
            )

    @group.command("list")
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, json_output: bool | None) -> None:
        service = _calendar_service()
        calendars = service.calendarList().list().execute().get("items", [])
        data = [
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "primary": bool(item.get("primary")),
            }
            for item in calendars
        ]
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Available calendars ({len(data)}):", emoji="📅")
            for item in data:
                suffix = " [PRIMARY]" if item["primary"] else ""
                print_human(f"  • {item['summary']}{suffix}")
                print_human(f"    ID: {item['id']}")

    @group.command("calendars", hidden=True)
    @json_option
    @click.pass_context
    def calendars_alias(ctx: click.Context, json_output: bool | None) -> None:
        ctx.invoke(list_command, json_output=json_output)
