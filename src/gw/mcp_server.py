from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from gw.auth import _get_config
from gw.services.calendar import (
    create_calendar_event,
    delete_calendar_event,
    get_calendar_today,
    get_calendar_tomorrow,
    get_calendar_week,
    list_calendars,
    update_calendar_event,
)
from gw.services.contacts import list_contacts, search_contacts
from gw.services.docs import export_doc, list_docs, read_doc
from gw.services.drive import (
    download_drive_file,
    list_drive_files,
    search_drive_files,
    upload_drive_file,
)
from gw.services.gmail import (
    archive_gmail_message,
    forward_gmail_message,
    label_gmail_message,
    list_gmail_messages,
    read_gmail_messages,
    reply_to_gmail_message,
    send_gmail_message,
    star_gmail_message,
    trash_gmail_message,
)
from gw.services.sheets import read_sheet_values, write_sheet_value

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

mcp_server = FastMCP("gw")


def _config():
    return _get_config()


@mcp_server.tool()
def gmail_send(
    to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None
) -> dict:
    return send_gmail_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc)


@mcp_server.tool()
def gmail_reply(message_id: str, body: str) -> dict:
    return reply_to_gmail_message(message_id=message_id, body=body)


@mcp_server.tool()
def gmail_forward(message_id: str, to: str) -> dict:
    return forward_gmail_message(message_id=message_id, to=to)


@mcp_server.tool()
def gmail_list(
    max_results: int = 10, query: str | None = None, unread: bool = False, after: str | None = None
) -> list[dict]:
    return list_gmail_messages(max_results=max_results, query=query, unread=unread, after=after)


@mcp_server.tool()
def gmail_read(
    message_id: str | None = None, query: str | None = None, max_results: int = 1
) -> list[dict]:
    return read_gmail_messages(message_id=message_id, query=query, max_results=max_results)


@mcp_server.tool()
def gmail_trash(message_id: str) -> dict:
    return trash_gmail_message(message_id=message_id)


@mcp_server.tool()
def gmail_archive(message_id: str) -> dict:
    return archive_gmail_message(message_id=message_id)


@mcp_server.tool()
def gmail_label(message_id: str, label_name: str, remove: bool = False) -> dict:
    return label_gmail_message(message_id=message_id, label_name=label_name, remove=remove)


@mcp_server.tool()
def gmail_star(message_id: str, remove: bool = False) -> dict:
    return star_gmail_message(message_id=message_id, remove=remove)


@mcp_server.tool()
def calendar_today(all_calendars: bool = False) -> list[dict]:
    config = _config()
    return get_calendar_today(config.timezone, config.default_calendar, all_calendars)


@mcp_server.tool()
def calendar_tomorrow(all_calendars: bool = False) -> list[dict]:
    config = _config()
    return get_calendar_tomorrow(config.timezone, config.default_calendar, all_calendars)


@mcp_server.tool()
def calendar_week(all_calendars: bool = False) -> list[dict]:
    config = _config()
    return get_calendar_week(config.timezone, config.default_calendar, all_calendars)


@mcp_server.tool()
def calendar_create(
    title: str,
    start: str,
    end: str,
    description: str = "",
    all_day: bool = False,
    recurrence: list[str] | None = None,
    calendar_id: str | None = None,
    reminder: int | None = None,
) -> dict:
    config = _config()
    return create_calendar_event(
        title=title,
        start=start,
        end=end,
        timezone=config.timezone,
        default_calendar=config.default_calendar,
        description=description,
        all_day=all_day,
        recurrence=tuple(recurrence or []),
        calendar_id=calendar_id,
        reminder=reminder,
    )


@mcp_server.tool()
def calendar_list() -> list[dict]:
    return list_calendars()


@mcp_server.tool()
def calendar_delete(event_id: str, calendar_id: str | None = None) -> dict:
    config = _config()
    return delete_calendar_event(
        event_id=event_id,
        default_calendar=config.default_calendar,
        calendar_id=calendar_id,
    )


@mcp_server.tool()
def calendar_update(
    event_id: str,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    calendar_id: str | None = None,
) -> dict:
    config = _config()
    return update_calendar_event(
        event_id=event_id,
        timezone=config.timezone,
        default_calendar=config.default_calendar,
        calendar_id=calendar_id,
        title=title,
        start=start,
        end=end,
        description=description,
    )


@mcp_server.tool()
def contacts_search(query: str, max_results: int = 10) -> list[dict]:
    return search_contacts(query=query, max_results=max_results)


@mcp_server.tool()
def contacts_list(max_results: int = 100) -> list[dict]:
    return list_contacts(max_results=max_results)


@mcp_server.tool()
def drive_list(max_results: int = 10) -> list[dict]:
    return list_drive_files(max_results=max_results)


@mcp_server.tool()
def drive_search(query: str, max_results: int = 10) -> list[dict]:
    return search_drive_files(query=query, max_results=max_results)


@mcp_server.tool()
def drive_upload(file_path: str, name: str | None = None, folder_id: str | None = None) -> dict:
    return upload_drive_file(file_path=file_path, name=name, folder_id=folder_id)


@mcp_server.tool()
def drive_download(
    file_id: str, output_path: str | None = None, export_format: str | None = None
) -> dict:
    return download_drive_file(
        file_id=file_id,
        output_path=output_path,
        export_format=export_format,
    )


@mcp_server.tool()
def sheets_read(spreadsheet_id: str, range_name: str) -> dict:
    return read_sheet_values(spreadsheet_id=spreadsheet_id, range_name=range_name)


@mcp_server.tool()
def sheets_write(spreadsheet_id: str, range_name: str, value: str, raw: bool = False) -> dict:
    return write_sheet_value(
        spreadsheet_id=spreadsheet_id,
        range_name=range_name,
        value=value,
        raw=raw,
    )


@mcp_server.tool()
def docs_read(document_id: str) -> dict:
    return read_doc(document_id=document_id)


@mcp_server.tool()
def docs_export(
    document_id: str, export_format: str = "txt", output_path: str | None = None
) -> dict:
    return export_doc(
        document_id=document_id, export_format=export_format, output_path=output_path
    )


@mcp_server.tool()
def docs_list(max_results: int = 10) -> list[dict]:
    return list_docs(max_results=max_results)


def run_mcp_server() -> None:
    mcp_server.run(transport="stdio")
