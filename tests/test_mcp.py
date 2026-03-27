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
        "calendar_create",
        "calendar_delete",
        "calendar_list",
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
        "drive_list",
        "drive_search",
        "drive_upload",
        "gmail_archive",
        "gmail_forward",
        "gmail_label",
        "gmail_list",
        "gmail_read",
        "gmail_reply",
        "gmail_send",
        "gmail_star",
        "gmail_trash",
        "sheets_read",
        "sheets_write",
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
