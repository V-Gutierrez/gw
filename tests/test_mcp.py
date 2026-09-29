from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import anyio

from gw.mcp_server import mcp_server


def test_mcp_lists_expected_tools() -> None:
    async def run() -> list[str]:
        tools = await mcp_server.list_tools()
        return sorted(tool.name for tool in tools)

    tool_names = anyio.run(run)

    assert tool_names == [
        "admin_check_access",
        "admin_chromeos",
        "admin_group_add",
        "admin_group_create",
        "admin_group_members",
        "admin_group_remove",
        "admin_groups",
        "admin_mobile",
        "admin_orgunit_create",
        "admin_orgunits",
        "admin_reports",
        "admin_roles",
        "admin_telemetry",
        "admin_transfer",
        "admin_transfer_apps",
        "admin_transfer_status",
        "admin_transfers",
        "admin_user_create",
        "admin_user_get",
        "admin_user_move",
        "admin_user_rename",
        "admin_user_restore",
        "admin_user_set_admin",
        "admin_user_suspend",
        "admin_users",
        "calendar_agenda",
        "calendar_create",
        "calendar_delete",
        "calendar_list",
        "calendar_next",
        "calendar_today",
        "calendar_tomorrow",
        "calendar_update",
        "calendar_week",
        "contacts_list",
        "contacts_search",
        "docs_export",
        "docs_list",
        "docs_read",
        "drive_download",
        "drive_info",
        "drive_list",
        "drive_mkdir",
        "drive_search",
        "drive_share",
        "drive_upload",
        "gmail_archive",
        "gmail_attachments",
        "gmail_count",
        "gmail_download_attachments",
        "gmail_draft",
        "gmail_forward",
        "gmail_label",
        "gmail_list",
        "gmail_mark_read",
        "gmail_mark_unread",
        "gmail_read",
        "gmail_reply",
        "gmail_search",
        "gmail_send",
        "gmail_star",
        "gmail_thread",
        "gmail_trash",
        "meet_create",
        "sheets_read",
        "sheets_write",
        "tasks_add",
        "tasks_complete",
        "tasks_delete",
        "tasks_list",
        "tasks_lists",
    ]


def test_mcp_calls_tool_and_returns_json_text() -> None:
    async def run() -> Any:
        with patch("gw.mcp_server.list_drive_files", return_value=[{"id": "1", "name": "Doc"}]):
            return await mcp_server.call_tool("drive_list", {"max_results": 5})

    content, structured = anyio.run(run)

    assert len(content) == 1
    payload = json.loads(content[0].text)
    assert payload["id"] == "1"
    assert payload["name"] == "Doc"
    assert structured["result"][0]["id"] == "1"


def test_destructive_device_action_is_not_exposed_over_mcp() -> None:
    """A wipe's only rail is a serial retyped by a human; MCP has nobody to ask.

    Every other admin write is reversible and ships with dry_run=True by default. This one
    is not reversible, so it stays CLI-only — the absence is the safety property.
    """

    async def run() -> list[str]:
        tools = await mcp_server.list_tools()
        return [tool.name for tool in tools]

    names = anyio.run(run)

    assert not any("device_action" in name or "wipe" in name for name in names)
