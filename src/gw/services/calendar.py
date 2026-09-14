from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, print_success, use_json_output
from gw.utils import (
    date_range_days,
    date_range_today,
    date_range_week,
    format_event_time,
    now_in_tz,
    parse_date,
    to_rfc3339,
)


def _calendar_service(config: GWConfig | None = None):
    return build_service("calendar", "v3", config=config)


def _fetch_events(
    start: str,
    end: str,
    all_calendars: bool,
    default_calendar: str,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _calendar_service(config)
    calendars: list[dict[str, Any]]
    if all_calendars:
        calendars = execute_google_request(service.calendarList().list()).get("items", [])
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
        response = execute_google_request(
            service.events().list(
                calendarId=calendar["id"],
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            )
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
    items.sort(key=_event_sort_key)
    return items


def _event_sort_key(event: dict[str, Any]) -> tuple[datetime, str]:
    start_data = event.get("start", {})
    value = start_data.get("dateTime") or start_data.get("date")
    if not value:
        return (datetime.max.replace(tzinfo=UTC), event.get("id") or "")

    if "dateTime" in start_data:
        parsed = datetime.fromisoformat(value)
    else:
        parsed = datetime.fromisoformat(f"{value}T00:00:00+00:00")
    return (parsed, event.get("id") or "")


def _print_events(events: list[dict[str, Any]], label: str, include_calendar: bool) -> None:
    if not events:
        print_human(f"No events {label.lower()}.", emoji="📅")
        return
    print_human(f"{label} ({len(events)}):", emoji="📅")
    for event in events:
        suffix = f" [{event['calendar']}]" if include_calendar else ""
        print_human(f"  • {format_event_time(event)}: {event['summary']}{suffix}")


def get_calendar_today(
    timezone: str,
    default_calendar: str,
    all_calendars: bool = False,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    start, end = date_range_today(timezone)
    return _fetch_events(
        to_rfc3339(start), to_rfc3339(end), all_calendars, default_calendar, config=config
    )


def get_calendar_tomorrow(
    timezone: str,
    default_calendar: str,
    all_calendars: bool = False,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    start, end = date_range_today(timezone)
    start += timedelta(days=1)
    end += timedelta(days=1)
    return _fetch_events(
        to_rfc3339(start), to_rfc3339(end), all_calendars, default_calendar, config=config
    )


def get_calendar_week(
    timezone: str,
    default_calendar: str,
    all_calendars: bool = False,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    start, end = date_range_week(timezone)
    return _fetch_events(
        to_rfc3339(start), to_rfc3339(end), all_calendars, default_calendar, config=config
    )


def get_calendar_agenda(
    timezone: str,
    default_calendar: str,
    days: int = 7,
    all_calendars: bool = False,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    if days < 1:
        raise click.ClickException("--days must be greater than or equal to 1.")
    start, end = date_range_days(timezone, days)
    return _fetch_events(
        to_rfc3339(start),
        to_rfc3339(end),
        all_calendars,
        default_calendar,
        config=config,
    )


def get_calendar_next(
    timezone: str,
    default_calendar: str,
    all_calendars: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any] | None:
    events = get_calendar_agenda(
        timezone,
        default_calendar,
        days=30,
        all_calendars=all_calendars,
        config=config,
    )
    now = now_in_tz(timezone)
    for event in events:
        start_data = event.get("start", {})
        if "dateTime" in start_data:
            start = datetime.fromisoformat(start_data["dateTime"])
            if start >= now:
                return event
        elif "date" in start_data:
            start = datetime.fromisoformat(f"{start_data['date']}T00:00:00").replace(
                tzinfo=now.tzinfo
            )
            if start >= now.replace(hour=0, minute=0, second=0, microsecond=0):
                return event
    return None


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
    attendees: tuple[str, ...] = (),
    location: str | None = None,
    send_updates: str = "none",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _calendar_service(config)
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
    if attendees:
        event["attendees"] = [{"email": email} for email in attendees]
    if location:
        event["location"] = location

    created = execute_google_request(
        service.events().insert(
            calendarId=target_calendar,
            body=event,
            sendUpdates=send_updates,
        )
    )
    return {
        "id": created.get("id"),
        "html_link": created.get("htmlLink"),
        "calendar": target_calendar,
    }


def list_calendars(config: GWConfig | None = None) -> list[dict[str, Any]]:
    service = _calendar_service(config)
    calendars = execute_google_request(service.calendarList().list()).get("items", [])
    return [
        {
            "id": item.get("id"),
            "summary": item.get("summary"),
            "primary": bool(item.get("primary")),
        }
        for item in calendars
    ]


def delete_calendar_event(
    event_id: str,
    default_calendar: str,
    calendar_id: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _calendar_service(config)
    target_calendar = calendar_id or default_calendar
    execute_google_request(service.events().delete(calendarId=target_calendar, eventId=event_id))
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
    location: str | None = None,
    attendees: tuple[str, ...] = (),
    reminder: int | None = None,
    send_updates: str = "none",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    if (start is None) != (end is None):
        raise click.ClickException("Provide both --start and --end together.")

    patch: dict[str, Any] = {}
    if title is not None:
        patch["summary"] = title
    if description is not None:
        patch["description"] = description
    if location is not None:
        patch["location"] = location
    if attendees:
        # Google replaces the whole list on patch, so this overwrites the guests.
        patch["attendees"] = [{"email": email} for email in attendees]
    if reminder is not None:
        patch["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": reminder}],
        }
    if start is not None and end is not None:
        start_dt = parse_date(start, timezone)
        end_dt = parse_date(end, timezone)
        patch["start"] = {"dateTime": to_rfc3339(start_dt), "timeZone": timezone}
        patch["end"] = {"dateTime": to_rfc3339(end_dt), "timeZone": timezone}

    if not patch:
        raise click.ClickException("Provide at least one field to update.")

    service = _calendar_service(config)
    target_calendar = calendar_id or default_calendar
    updated = execute_google_request(
        service.events().patch(
            calendarId=target_calendar,
            eventId=event_id,
            body=patch,
            sendUpdates=send_updates,
        )
    )
    return {
        "id": updated.get("id", event_id),
        "html_link": updated.get("htmlLink"),
        "calendar": target_calendar,
        "updated_fields": sorted(patch.keys()),
    }


def create_instant_meet(
    title: str = "Instant Meeting",
    timezone_name: str = "UTC",
    default_calendar: str = "primary",
    duration_minutes: int = 30,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """
    Create an instant Google Meet event.

    Creates a short calendar event starting now with a conference request.
    Returns event details including the meet_link.
    """
    service = _calendar_service(config)
    now = now_in_tz(timezone_name)
    end = now + timedelta(minutes=duration_minutes)

    request_id = str(uuid4())

    event: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": to_rfc3339(now), "timeZone": timezone_name},
        "end": {"dateTime": to_rfc3339(end), "timeZone": timezone_name},
        "conferenceData": {
            "createRequest": {
                "requestId": request_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    created = execute_google_request(
        service.events().insert(
            calendarId=default_calendar,
            body=event,
            conferenceDataVersion=1,
        )
    )

    meet_link = None
    if "conferenceData" in created and "entryPoints" in created["conferenceData"]:
        for entry in created["conferenceData"]["entryPoints"]:
            if entry.get("entryPointType") == "video":
                meet_link = entry.get("uri")
                break

    return {
        "id": created.get("id"),
        "title": created.get("summary"),
        "start": created.get("start"),
        "end": created.get("end"),
        "meet_link": meet_link,
        "html_link": created.get("htmlLink"),
        "calendar": default_calendar,
    }


def query_freebusy(
    emails: Sequence[str],
    start: str,
    end: str,
    timezone: str = "UTC",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Ask Google when each person is busy between two instants."""
    service = _calendar_service(config)
    response = execute_google_request(
        service.freebusy().query(
            body={
                "timeMin": to_rfc3339(parse_date(start, timezone)),
                "timeMax": to_rfc3339(parse_date(end, timezone)),
                "items": [{"id": email} for email in emails],
            }
        )
    )
    calendars = []
    for email in emails:
        entry = response.get("calendars", {}).get(email, {})
        calendars.append(
            {
                "email": email,
                "busy": entry.get("busy", []),
                "errors": entry.get("errors", []),
            }
        )
    return {"start": start, "end": end, "calendars": calendars}


def quick_add_event(
    text: str,
    calendar_id: str | None = None,
    send_updates: str = "none",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Create an event from a natural-language phrase, parsed by Google."""
    service = _calendar_service(config)
    event = execute_google_request(
        service.events().quickAdd(
            calendarId=calendar_id or "primary",
            text=text,
            sendUpdates=send_updates,
        )
    )
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": event.get("start", {}),
        "html_link": event.get("htmlLink"),
    }


def move_calendar_event(
    event_id: str,
    destination: str,
    calendar: str | None = None,
    send_updates: str = "none",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Move an event to another calendar, keeping its id."""
    service = _calendar_service(config)
    event = execute_google_request(
        service.events().move(
            calendarId=calendar or "primary",
            eventId=event_id,
            destination=destination,
            sendUpdates=send_updates,
        )
    )
    return {
        "id": event.get("id", event_id),
        "summary": event.get("summary"),
        "destination": destination,
        "html_link": event.get("htmlLink"),
    }


def list_event_instances(
    event_id: str,
    calendar_id: str | None = None,
    max_results: int = 25,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    """Expand a recurring event into its individual occurrences."""
    service = _calendar_service(config)
    response = execute_google_request(
        service.events().instances(
            calendarId=calendar_id or "primary",
            eventId=event_id,
            maxResults=max_results,
        )
    )
    return [
        {
            "id": item.get("id"),
            "summary": item.get("summary", "(No title)"),
            "start": item.get("start", {}),
            "end": item.get("end", {}),
            "status": item.get("status"),
        }
        for item in response.get("items", [])
    ]


def create_calendar(
    summary: str,
    timezone: str,
    description: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Create a brand new secondary calendar."""
    service = _calendar_service(config)
    body: dict[str, Any] = {"summary": summary, "timeZone": timezone}
    if description:
        body["description"] = description
    created = execute_google_request(service.calendars().insert(body=body))
    return {
        "id": created.get("id"),
        "summary": created.get("summary", summary),
        "timezone": timezone,
    }


def delete_calendar(calendar_id: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _calendar_service(config)
    execute_google_request(service.calendars().delete(calendarId=calendar_id))
    return {"id": calendar_id, "deleted": True}


def list_calendar_acl(
    calendar_id: str | None = None,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    """Show who has access to a calendar."""
    service = _calendar_service(config)
    response = execute_google_request(service.acl().list(calendarId=calendar_id or "primary"))
    rules = []
    for item in response.get("items", []):
        scope = item.get("scope", {})
        rules.append(
            {
                "rule_id": item.get("id"),
                "email": scope.get("value", ""),
                "scope_type": scope.get("type"),
                "role": item.get("role"),
            }
        )
    return rules


def share_calendar(
    calendar_id: str | None,
    email: str,
    role: str = "reader",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _calendar_service(config)
    rule = execute_google_request(
        service.acl().insert(
            calendarId=calendar_id or "primary",
            body={"role": role, "scope": {"type": "user", "value": email}},
        )
    )
    return {"rule_id": rule.get("id"), "email": email, "role": rule.get("role", role)}


def unshare_calendar(
    calendar_id: str | None,
    email: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Revoke someone's access, resolving their rule id first."""
    target = calendar_id or "primary"
    rules = list_calendar_acl(target, config=config)
    match = next((rule for rule in rules if rule["email"] == email), None)
    if match is None:
        raise click.ClickException(f"{email} has no access to calendar {target!r}.")

    service = _calendar_service(config)
    execute_google_request(service.acl().delete(calendarId=target, ruleId=match["rule_id"]))
    return {"email": email, "calendar": target, "removed": True}


def register_calendar_commands(group: click.Group) -> None:
    @group.command("freebusy")
    @click.argument("emails", nargs=-1, required=True)
    @click.option("--start", required=True, help="Window start (YYYY-MM-DD or ISO 8601).")
    @click.option("--end", required=True, help="Window end (YYYY-MM-DD or ISO 8601).")
    @json_option
    @click.pass_context
    def freebusy_command(
        ctx: click.Context,
        emails: tuple[str, ...],
        start: str,
        end: str,
        json_output: bool | None,
    ) -> None:
        """Show when people are busy. Pass one or more emails."""
        config = ctx.obj["config"]
        data = query_freebusy(
            emails=list(emails),
            start=start,
            end=end,
            timezone=config.timezone,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
            return
        print_human(f"Free/busy {start} → {end}:", emoji="🗓️")
        for entry in data["calendars"]:
            if entry["errors"]:
                detail = entry["errors"][0].get("reason", "error")
                print_human(f"  • {entry['email']}: ⚠️  {detail}")
            elif not entry["busy"]:
                print_human(f"  • {entry['email']}: free all window")
            else:
                print_human(f"  • {entry['email']}: {len(entry['busy'])} busy block(s)")
                for slot in entry["busy"]:
                    print_human(f"      {slot.get('start')} → {slot.get('end')}")

    @group.command("quick-add")
    @click.argument("text")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar ID to use.")
    @click.option(
        "--send-updates",
        type=click.Choice(["none", "all", "externalOnly"]),
        default="none",
        show_default=True,
        help="Whether Google emails the guests.",
    )
    @json_option
    @click.pass_context
    def quick_add_command(
        ctx: click.Context,
        text: str,
        calendar_id: str | None,
        send_updates: str,
        json_output: bool | None,
    ) -> None:
        """Create an event from plain language, e.g. "Lunch with Ana tomorrow 12pm"."""
        config = ctx.obj["config"]
        data = quick_add_event(
            text=text,
            calendar_id=calendar_id or config.default_calendar,
            send_updates=send_updates,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Event created: {data['summary']} ({data['id']})")
            if data.get("html_link"):
                print_human(f"  {data['html_link']}")

    @group.command("move")
    @click.argument("event_id")
    @click.argument("destination")
    @click.option("--calendar", default=None, help="Calendar the event is in now.")
    @click.option(
        "--send-updates",
        type=click.Choice(["none", "all", "externalOnly"]),
        default="none",
        show_default=True,
        help="Whether Google emails the guests.",
    )
    @json_option
    @click.pass_context
    def move_command(
        ctx: click.Context,
        event_id: str,
        destination: str,
        calendar: str | None,
        send_updates: str,
        json_output: bool | None,
    ) -> None:
        """Move an event to another calendar. The event keeps its ID."""
        config = ctx.obj["config"]
        data = move_calendar_event(
            event_id=event_id,
            destination=destination,
            calendar=calendar or config.default_calendar,
            send_updates=send_updates,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Event {data['id']} moved to {destination}.")

    @group.command("instances")
    @click.argument("event_id")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar containing the event.")
    @click.option("--max", "max_results", default=25, type=int, show_default=True)
    @json_option
    @click.pass_context
    def instances_command(
        ctx: click.Context,
        event_id: str,
        calendar_id: str | None,
        max_results: int,
        json_output: bool | None,
    ) -> None:
        """List the individual occurrences of a recurring event."""
        config = ctx.obj["config"]
        data = list_event_instances(
            event_id=event_id,
            calendar_id=calendar_id or config.default_calendar,
            max_results=max_results,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        elif not data:
            print_human("No instances found.", emoji="📅")
        else:
            print_human(f"Instances ({len(data)}):", emoji="📅")
            for item in data:
                when = item["start"].get("dateTime") or item["start"].get("date", "")
                cancelled = " [CANCELLED]" if item.get("status") == "cancelled" else ""
                print_human(f"  • {when}{cancelled} — {item['summary']}")
                print_human(f"    ID: {item['id']}")

    @group.command("create-calendar")
    @click.argument("summary")
    @click.option("--description", default=None, help="Calendar description.")
    @click.option("--timezone", "timezone_override", default=None, help="Calendar timezone.")
    @json_option
    @click.pass_context
    def create_calendar_command(
        ctx: click.Context,
        summary: str,
        description: str | None,
        timezone_override: str | None,
        json_output: bool | None,
    ) -> None:
        """Create a new secondary calendar."""
        config = ctx.obj["config"]
        data = create_calendar(
            summary=summary,
            timezone=timezone_override or config.timezone,
            description=description,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Calendar created: {data['summary']}")
            print_human(f"  ID: {data['id']}")

    @group.command("delete-calendar")
    @click.argument("calendar_id")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def delete_calendar_command(
        ctx: click.Context, calendar_id: str, yes: bool, json_output: bool | None
    ) -> None:
        """Delete a secondary calendar and every event in it. Cannot be undone."""
        if not yes:
            click.confirm(
                f"Delete calendar {calendar_id} and all its events? This cannot be undone.",
                abort=True,
            )
        data = delete_calendar(calendar_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Calendar {calendar_id} deleted.")

    @group.command("acl")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar to inspect.")
    @json_option
    @click.pass_context
    def acl_command(ctx: click.Context, calendar_id: str | None, json_output: bool | None) -> None:
        """Show who has access to a calendar."""
        config = ctx.obj["config"]
        data = list_calendar_acl(calendar_id or config.default_calendar, config=config)
        if use_json_output(ctx, json_output):
            print_json(data)
        elif not data:
            print_human("No access rules found.", emoji="🔐")
        else:
            print_human(f"Access rules ({len(data)}):", emoji="🔐")
            for rule in data:
                who = rule["email"] or rule["scope_type"]
                print_human(f"  • {who} — {rule['role']}")

    @group.command("share")
    @click.argument("email")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar to share.")
    @click.option(
        "--role",
        type=click.Choice(["reader", "writer", "owner", "freeBusyReader"]),
        default="reader",
        show_default=True,
    )
    @json_option
    @click.pass_context
    def share_calendar_command(
        ctx: click.Context,
        email: str,
        calendar_id: str | None,
        role: str,
        json_output: bool | None,
    ) -> None:
        """Give someone access to a calendar."""
        config = ctx.obj["config"]
        data = share_calendar(
            calendar_id or config.default_calendar, email, role=role, config=config
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"{email} can now access the calendar as {data['role']}.")

    @group.command("unshare")
    @click.argument("email")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar to revoke access to.")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def unshare_calendar_command(
        ctx: click.Context,
        email: str,
        calendar_id: str | None,
        yes: bool,
        json_output: bool | None,
    ) -> None:
        """Revoke someone's access to a calendar."""
        config = ctx.obj["config"]
        if not yes:
            click.confirm(f"Remove {email}'s access?", abort=True)
        data = unshare_calendar(calendar_id or config.default_calendar, email, config=config)
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"{email} no longer has access.")

    @group.command("today")
    @click.option("--all", "all_calendars", is_flag=True, help="Include all calendars.")
    @json_option
    @click.pass_context
    def today_command(ctx: click.Context, all_calendars: bool, json_output: bool | None) -> None:
        config = ctx.obj["config"]
        events = get_calendar_today(
            config.timezone,
            config.default_calendar,
            all_calendars,
            config=config,
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
        events = get_calendar_tomorrow(
            config.timezone,
            config.default_calendar,
            all_calendars,
            config=config,
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
        events = get_calendar_week(
            config.timezone,
            config.default_calendar,
            all_calendars,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(events)
        else:
            _print_events(events, "This week's events", all_calendars)

    @group.command("agenda")
    @click.option("--days", default=7, type=int, show_default=True, help="Number of days to show.")
    @click.option("--all", "all_calendars", is_flag=True, help="Include all calendars.")
    @json_option
    @click.pass_context
    def agenda_command(
        ctx: click.Context,
        days: int,
        all_calendars: bool,
        json_output: bool | None,
    ) -> None:
        config = ctx.obj["config"]
        events = get_calendar_agenda(
            config.timezone,
            config.default_calendar,
            days=days,
            all_calendars=all_calendars,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(events)
        else:
            _print_events(events, f"Next {days} day(s)", all_calendars)

    @group.command("next")
    @click.option("--all", "all_calendars", is_flag=True, help="Include all calendars.")
    @json_option
    @click.pass_context
    def next_command(ctx: click.Context, all_calendars: bool, json_output: bool | None) -> None:
        config = ctx.obj["config"]
        event = get_calendar_next(
            config.timezone,
            config.default_calendar,
            all_calendars=all_calendars,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(event)
        elif event is None:
            print_human("No upcoming events.", emoji="📅")
        else:
            _print_events([event], "Next event", all_calendars)

    @group.command("create")
    @click.argument("title")
    @click.argument("start")
    @click.argument("end")
    @click.option("--description", default="", help="Event description.")
    @click.option("--all-day", is_flag=True, help="Create an all-day event.")
    @click.option("--recurrence", multiple=True, help="Add one RRULE recurrence value.")
    @click.option("--calendar", "calendar_id", default=None, help="Calendar ID to use.")
    @click.option("--reminder", default=None, type=int, help="Popup reminder in minutes.")
    @click.option("--attendees", multiple=True, help="Guest email. Repeat for several.")
    @click.option("--location", default=None, help="Event location.")
    @click.option(
        "--send-updates",
        "send_updates",
        type=click.Choice(["none", "all", "externalOnly"]),
        default="none",
        show_default=True,
        help="Whether Google emails the guests.",
    )
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
        attendees: tuple[str, ...],
        location: str | None,
        send_updates: str,
        json_output: bool | None,
    ) -> None:
        """Create an event. Invite guests with --attendees (repeatable)."""
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
            attendees=attendees,
            location=location,
            send_updates=send_updates,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Event created: {data.get('html_link', data.get('id', 'unknown'))}")

    @group.command("list")
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, json_output: bool | None) -> None:
        data = list_calendars(config=ctx.obj["config"])
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
            config=config,
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
    @click.option("--location", default=None, help="Updated event location.")
    @click.option(
        "--attendees",
        multiple=True,
        help="Guest email. Repeat for several. Replaces the whole guest list.",
    )
    @click.option("--reminder", default=None, type=int, help="Popup reminder in minutes.")
    @click.option(
        "--send-updates",
        "send_updates",
        type=click.Choice(["none", "all", "externalOnly"]),
        default="none",
        show_default=True,
        help="Whether Google emails the guests.",
    )
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
        location: str | None,
        attendees: tuple[str, ...],
        reminder: int | None,
        send_updates: str,
        json_output: bool | None,
    ) -> None:
        """Update an event. --attendees replaces the whole guest list."""
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
            location=location,
            attendees=attendees,
            reminder=reminder,
            send_updates=send_updates,
            config=config,
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


def register_meet_commands(group: click.Group) -> None:
    @group.command("create")
    @click.option("--title", default="Instant Meeting", help="Meeting title.")
    @json_option
    @click.pass_context
    def create_meet(ctx: click.Context, title: str, json_output: bool | None) -> None:
        config = ctx.obj["config"]
        data = create_instant_meet(
            title=title,
            timezone_name=config.timezone,
            default_calendar=config.default_calendar,
            config=config,
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            if data.get("meet_link"):
                print_success(f"Meeting created: {data['meet_link']}")
            else:
                print_human(f"Meeting created (ID: {data.get('id')})", emoji="📞")
