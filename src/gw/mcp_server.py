from __future__ import annotations

import logging
import sys
from typing import cast

from mcp.server.fastmcp import FastMCP

from gw.auth import _get_config
from gw.config import GWConfig
from gw.services.admin import (
    add_admin_group_member,
    admin_whoami,
    create_admin_group,
    create_admin_orgunit,
    create_admin_user,
    get_admin_user,
    list_admin_chromeos,
    list_admin_group_members,
    list_admin_groups,
    list_admin_mobile,
    list_admin_orgunits,
    list_admin_reports,
    list_admin_roles,
    list_admin_telemetry,
    list_admin_users,
    move_admin_user,
    remove_admin_group_member,
    rename_admin_user,
    set_admin_user_admin,
    set_admin_user_suspended,
)
from gw.services.calendar import (
    create_calendar_event,
    create_instant_meet,
    delete_calendar_event,
    get_calendar_agenda,
    get_calendar_next,
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
    get_drive_file_info,
    list_drive_files,
    mkdir_drive_folder,
    search_drive_files,
    share_drive_file,
    upload_drive_file,
)
from gw.services.gmail import (
    archive_gmail_message,
    count_gmail_messages,
    create_gmail_draft,
    download_gmail_attachments,
    forward_gmail_message,
    get_gmail_thread,
    label_gmail_message,
    list_gmail_attachments,
    list_gmail_messages,
    mark_gmail_read,
    mark_gmail_unread,
    read_gmail_messages,
    reply_to_gmail_message,
    search_gmail_messages,
    send_gmail_message,
    star_gmail_message,
    trash_gmail_message,
)
from gw.services.sheets import read_sheet_values, write_sheet_value
from gw.services.tasks import add_task, complete_task, delete_task, list_task_lists, list_tasks

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

mcp_server = FastMCP("gw")
_ACTIVE_MCP_CONFIG: GWConfig | None = None


def _config():
    if _ACTIVE_MCP_CONFIG is not None:
        return cast(GWConfig, _ACTIVE_MCP_CONFIG)
    return _get_config()


def set_mcp_config(config: GWConfig) -> None:
    global _ACTIVE_MCP_CONFIG
    _ACTIVE_MCP_CONFIG = config


@mcp_server.tool()
def gmail_send(
    to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None
) -> dict:
    """Send a plain-text email.

    Attachments are not exposed over MCP; use `gw gmail send --attachment PATH`.
    """
    return send_gmail_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc, config=_config())


@mcp_server.tool()
def gmail_draft(
    to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None
) -> dict:
    """Create a plain-text draft.

    Attachments are not exposed over MCP; use `gw gmail draft --attachment PATH`.
    """
    return create_gmail_draft(to=to, subject=subject, body=body, cc=cc, bcc=bcc, config=_config())


@mcp_server.tool()
def gmail_reply(message_id: str, body: str) -> dict:
    """Reply in thread.

    Cc/Bcc and attachments are not exposed over MCP; use `gw gmail reply --attachment PATH`.
    """
    return reply_to_gmail_message(message_id=message_id, body=body, config=_config())


@mcp_server.tool()
def gmail_forward(message_id: str, to: str) -> dict:
    """Forward a message.

    Cc/Bcc and attachments are not exposed over MCP; use `gw gmail forward --attachment PATH`.
    """
    return forward_gmail_message(message_id=message_id, to=to, config=_config())


@mcp_server.tool()
def gmail_list(
    max_results: int = 10, query: str | None = None, unread: bool = False, after: str | None = None
) -> list[dict]:
    return list_gmail_messages(
        max_results=max_results,
        query=query,
        unread=unread,
        after=after,
        config=_config(),
    )


@mcp_server.tool()
def gmail_search(query: str, max_results: int = 10) -> list[dict]:
    return search_gmail_messages(query=query, max_results=max_results, config=_config())


@mcp_server.tool()
def gmail_thread(message_id: str) -> dict:
    return get_gmail_thread(message_id=message_id, config=_config())


@mcp_server.tool()
def gmail_count(query: str | None = None) -> dict:
    return count_gmail_messages(query=query, config=_config())


@mcp_server.tool()
def gmail_read(
    message_id: str | None = None, query: str | None = None, max_results: int = 1
) -> list[dict]:
    return read_gmail_messages(
        message_id=message_id,
        query=query,
        max_results=max_results,
        config=_config(),
    )


@mcp_server.tool()
def gmail_attachments(message_id: str) -> dict:
    """List the attachments of a Gmail message, with their IDs, names, and sizes."""
    return list_gmail_attachments(message_id=message_id, config=_config())


@mcp_server.tool()
def gmail_download_attachments(
    message_id: str,
    attachment_id: str | None = None,
    filename: str | None = None,
    output_path: str | None = None,
    directory: str | None = None,
) -> dict:
    """Download attachments from a Gmail message to disk. Downloads all of them by default."""
    return download_gmail_attachments(
        message_id=message_id,
        attachment_id=attachment_id,
        filename=filename,
        output_path=output_path,
        directory=directory,
        config=_config(),
    )


@mcp_server.tool()
def gmail_trash(message_id: str) -> dict:
    return trash_gmail_message(message_id=message_id, config=_config())


@mcp_server.tool()
def gmail_archive(message_id: str) -> dict:
    return archive_gmail_message(message_id=message_id, config=_config())


@mcp_server.tool()
def gmail_label(message_id: str, label_name: str, remove: bool = False) -> dict:
    return label_gmail_message(
        message_id=message_id,
        label_name=label_name,
        remove=remove,
        config=_config(),
    )


@mcp_server.tool()
def gmail_star(message_id: str, remove: bool = False) -> dict:
    return star_gmail_message(message_id=message_id, remove=remove, config=_config())


@mcp_server.tool()
def gmail_mark_read(message_id: str) -> dict:
    return mark_gmail_read(message_id=message_id, config=_config())


@mcp_server.tool()
def gmail_mark_unread(message_id: str) -> dict:
    return mark_gmail_unread(message_id=message_id, config=_config())


@mcp_server.tool()
def calendar_today(all_calendars: bool = False) -> list[dict]:
    config = _config()
    return get_calendar_today(
        config.timezone, config.default_calendar, all_calendars, config=config
    )


@mcp_server.tool()
def calendar_tomorrow(all_calendars: bool = False) -> list[dict]:
    config = _config()
    return get_calendar_tomorrow(
        config.timezone,
        config.default_calendar,
        all_calendars,
        config=config,
    )


@mcp_server.tool()
def calendar_week(all_calendars: bool = False) -> list[dict]:
    config = _config()
    return get_calendar_week(
        config.timezone, config.default_calendar, all_calendars, config=config
    )


@mcp_server.tool()
def calendar_agenda(days: int = 7, all_calendars: bool = False) -> list[dict]:
    config = _config()
    return get_calendar_agenda(
        config.timezone,
        config.default_calendar,
        days=days,
        all_calendars=all_calendars,
        config=config,
    )


@mcp_server.tool()
def calendar_next(all_calendars: bool = False) -> dict | None:
    config = _config()
    return get_calendar_next(
        config.timezone,
        config.default_calendar,
        all_calendars=all_calendars,
        config=config,
    )


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
        config=config,
    )


@mcp_server.tool()
def meet_create(title: str = "Instant Meeting") -> dict:
    config = _config()
    return create_instant_meet(
        title=title,
        timezone_name=config.timezone,
        default_calendar=config.default_calendar,
        config=config,
    )


@mcp_server.tool()
def calendar_list() -> list[dict]:
    return list_calendars(config=_config())


@mcp_server.tool()
def calendar_delete(event_id: str, calendar_id: str | None = None) -> dict:
    config = _config()
    return delete_calendar_event(
        event_id=event_id,
        default_calendar=config.default_calendar,
        calendar_id=calendar_id,
        config=config,
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
        config=config,
    )


@mcp_server.tool()
def contacts_search(query: str, max_results: int = 10) -> list[dict]:
    return search_contacts(query=query, max_results=max_results, config=_config())


@mcp_server.tool()
def contacts_list(max_results: int = 100) -> list[dict]:
    return list_contacts(max_results=max_results, config=_config())


@mcp_server.tool()
def drive_list(max_results: int = 10) -> list[dict]:
    return list_drive_files(max_results=max_results, config=_config())


@mcp_server.tool()
def drive_search(query: str, max_results: int = 10) -> list[dict]:
    return search_drive_files(query=query, max_results=max_results, config=_config())


@mcp_server.tool()
def drive_mkdir(name: str, parent_id: str | None = None) -> dict:
    return mkdir_drive_folder(name=name, parent_id=parent_id, config=_config())


@mcp_server.tool()
def drive_share(file_id: str, email: str, role: str = "reader") -> dict:
    return share_drive_file(file_id=file_id, email=email, role=role, config=_config())


@mcp_server.tool()
def drive_info(file_id: str) -> dict:
    return get_drive_file_info(file_id=file_id, config=_config())


@mcp_server.tool()
def drive_upload(file_path: str, name: str | None = None, folder_id: str | None = None) -> dict:
    return upload_drive_file(file_path=file_path, name=name, folder_id=folder_id, config=_config())


@mcp_server.tool()
def drive_download(
    file_id: str, output_path: str | None = None, export_format: str | None = None
) -> dict:
    return download_drive_file(
        file_id=file_id,
        output_path=output_path,
        export_format=export_format,
        config=_config(),
    )


@mcp_server.tool()
def sheets_read(spreadsheet_id: str, range_name: str) -> dict:
    return read_sheet_values(
        spreadsheet_id=spreadsheet_id, range_name=range_name, config=_config()
    )


@mcp_server.tool()
def sheets_write(spreadsheet_id: str, range_name: str, value: str, raw: bool = False) -> dict:
    return write_sheet_value(
        spreadsheet_id=spreadsheet_id,
        range_name=range_name,
        value=value,
        raw=raw,
        config=_config(),
    )


@mcp_server.tool()
def docs_read(document_id: str) -> dict:
    return read_doc(document_id=document_id, config=_config())


@mcp_server.tool()
def docs_export(
    document_id: str, export_format: str = "txt", output_path: str | None = None
) -> dict:
    return export_doc(
        document_id=document_id,
        export_format=export_format,
        output_path=output_path,
        config=_config(),
    )


@mcp_server.tool()
def docs_list(max_results: int = 10) -> list[dict]:
    return list_docs(max_results=max_results, config=_config())


@mcp_server.tool()
def tasks_lists(max_results: int = 100) -> list[dict]:
    return list_task_lists(max_results=max_results, config=_config())


@mcp_server.tool()
def tasks_list(
    list_id: str = "@default", max_results: int = 100, show_completed: bool = True
) -> list[dict]:
    return list_tasks(
        list_id=list_id,
        max_results=max_results,
        show_completed=show_completed,
        config=_config(),
    )


@mcp_server.tool()
def tasks_add(
    title: str,
    notes: str | None = None,
    due: str | None = None,
    list_id: str = "@default",
) -> dict:
    return add_task(title=title, notes=notes, due=due, list_id=list_id, config=_config())


@mcp_server.tool()
def tasks_complete(task_id: str, list_id: str = "@default") -> dict:
    return complete_task(task_id=task_id, list_id=list_id, config=_config())


@mcp_server.tool()
def tasks_delete(task_id: str, list_id: str = "@default") -> dict:
    return delete_task(task_id=task_id, list_id=list_id, config=_config())


# --------------------------------------------------------------------------- admin
#
# Read-only by construction: the `admin` service exposes no mutating function, so there is
# nothing here that could suspend a user or wipe a device by chat. `limit=0` means every
# page, which is the point — a partial inventory reads like a complete one.


@mcp_server.tool()
def admin_users(query: str | None = None, org_unit: str | None = None, limit: int = 0) -> list:
    """List Workspace users. `query` takes Directory API syntax, e.g. isSuspended=true."""
    return list_admin_users(query=query, org_unit=org_unit, limit=limit, config=_config())


@mcp_server.tool()
def admin_groups(limit: int = 0) -> list:
    """List Workspace groups with their direct member counts."""
    return list_admin_groups(limit=limit, config=_config())


@mcp_server.tool()
def admin_orgunits() -> list:
    """List the whole org unit tree."""
    return list_admin_orgunits(config=_config())


@mcp_server.tool()
def admin_chromeos(limit: int = 0) -> list:
    """List ChromeOS and managed Chrome devices: serial, status, last sync."""
    return list_admin_chromeos(limit=limit, config=_config())


@mcp_server.tool()
def admin_mobile(limit: int = 0) -> list:
    """List managed mobile devices: model, OS, owner."""
    return list_admin_mobile(limit=limit, config=_config())


@mcp_server.tool()
def admin_telemetry(limit: int = 0) -> list:
    """Device telemetry from Chrome Management: CPU model and total RAM per serial."""
    return list_admin_telemetry(limit=limit, config=_config())


@mcp_server.tool()
def admin_check_access() -> dict:
    """Probe each admin API and report which ones answer. Never raises on a denied API."""
    return admin_whoami(config=_config())


# --------------------------------------------------------------------------- admin writes
#
# Reversible operations only. `act_on_chromeos_device` is deliberately NOT exposed here:
# a wipe has no undo, and its rail is a serial retyped by a human at a terminal — which is
# exactly the thing an MCP caller cannot be asked to do. It stays CLI-only on purpose.


@mcp_server.tool()
def admin_user_create(
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    org_unit: str | None = None,
    dry_run: bool = True,
) -> dict:
    """Create a Workspace user. Defaults to dry_run=True — pass dry_run=False to apply.

    The password is redacted from the result; it never comes back through this channel.
    """
    return create_admin_user(
        email=email,
        first_name=first_name,
        last_name=last_name,
        password=password,
        org_unit=org_unit,
        dry_run=dry_run,
        config=_config(),
    )


@mcp_server.tool()
def admin_user_suspend(email: str, dry_run: bool = True) -> dict:
    """Suspend a user. Reversible with admin_user_restore. Defaults to dry_run=True."""
    return set_admin_user_suspended(email=email, suspended=True, dry_run=dry_run, config=_config())


@mcp_server.tool()
def admin_user_restore(email: str, dry_run: bool = True) -> dict:
    """Un-suspend a user. Defaults to dry_run=True."""
    return set_admin_user_suspended(
        email=email, suspended=False, dry_run=dry_run, config=_config()
    )


@mcp_server.tool()
def admin_user_move(email: str, org_unit: str, dry_run: bool = True) -> dict:
    """Move a user to another org unit. Defaults to dry_run=True."""
    return move_admin_user(email=email, org_unit=org_unit, dry_run=dry_run, config=_config())


@mcp_server.tool()
def admin_group_add(group: str, member: str, role: str = "MEMBER", dry_run: bool = True) -> dict:
    """Add a member to a group. Defaults to dry_run=True."""
    return add_admin_group_member(
        group=group, member=member, role=role, dry_run=dry_run, config=_config()
    )


@mcp_server.tool()
def admin_group_remove(group: str, member: str, dry_run: bool = True) -> dict:
    """Remove a member from a group. Defaults to dry_run=True."""
    return remove_admin_group_member(group=group, member=member, dry_run=dry_run, config=_config())


@mcp_server.tool()
def admin_user_get(email: str) -> dict:
    """One user's record: org unit, admin flag, suspension, last login."""
    return get_admin_user(email, config=_config())


@mcp_server.tool()
def admin_group_members(group: str, limit: int = 0) -> list:
    """Who is in a group, with each member's role."""
    return list_admin_group_members(group, limit=limit, config=_config())


@mcp_server.tool()
def admin_roles() -> list:
    """Who holds which admin role, with the role name joined onto the assignment."""
    return list_admin_roles(config=_config())


@mcp_server.tool()
def admin_reports(app: str = "login", limit: int = 0) -> list:
    """Audit activity: login, admin, drive, token, groups, mobile, user_accounts."""
    return list_admin_reports(app=app, limit=limit, config=_config())


@mcp_server.tool()
def admin_user_rename(email: str, first_name: str, last_name: str, dry_run: bool = True) -> dict:
    """Change a user's display name. Defaults to dry_run=True."""
    return rename_admin_user(
        email=email, first_name=first_name, last_name=last_name, dry_run=dry_run, config=_config()
    )


@mcp_server.tool()
def admin_user_set_admin(email: str, grant: bool, dry_run: bool = True) -> dict:
    """Grant or revoke super admin. Reversible by calling again with the opposite grant."""
    return set_admin_user_admin(email=email, grant=grant, dry_run=dry_run, config=_config())


@mcp_server.tool()
def admin_group_create(
    email: str, name: str, description: str | None = None, dry_run: bool = True
) -> dict:
    """Create a group. Defaults to dry_run=True."""
    return create_admin_group(
        email=email, name=name, description=description, dry_run=dry_run, config=_config()
    )


@mcp_server.tool()
def admin_orgunit_create(name: str, parent: str = "/", dry_run: bool = True) -> dict:
    """Create an org unit under `parent`. Defaults to dry_run=True."""
    return create_admin_orgunit(name=name, parent=parent, dry_run=dry_run, config=_config())


def run_mcp_server() -> None:
    mcp_server.run(transport="stdio")
