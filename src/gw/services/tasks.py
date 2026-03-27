from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, print_success, use_json_output


def _tasks_service(config: GWConfig | None = None):
    return build_service("tasks", "v1", config=config)


def _format_due_date(value: str) -> str:
    text = value.strip()
    try:
        if len(text) == 10:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        else:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise click.ClickException(
            "--due must use YYYY-MM-DD or ISO 8601 datetime format."
        ) from exc

    return f"{parsed.date().isoformat()}T00:00:00.000Z"


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "notes": task.get("notes"),
        "due": task.get("due"),
        "completed": task.get("completed"),
        "updated": task.get("updated"),
        "deleted": bool(task.get("deleted", False)),
        "hidden": bool(task.get("hidden", False)),
        "web_view_link": task.get("webViewLink"),
    }


def list_task_lists(
    max_results: int = 100,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _tasks_service(config)
    response = execute_google_request(service.tasklists().list(maxResults=max_results))
    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "updated": item.get("updated"),
        }
        for item in response.get("items", [])
    ]


def list_tasks(
    list_id: str = "@default",
    max_results: int = 100,
    show_completed: bool = True,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _tasks_service(config)
    response = execute_google_request(
        service.tasks().list(
            tasklist=list_id,
            maxResults=max_results,
            showCompleted=show_completed,
            showHidden=False,
        )
    )
    return [_normalize_task(task) for task in response.get("items", [])]


def add_task(
    title: str,
    notes: str | None = None,
    due: str | None = None,
    list_id: str = "@default",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _tasks_service(config)
    body: dict[str, Any] = {"title": title, "status": "needsAction"}
    if notes:
        body["notes"] = notes
    if due:
        body["due"] = _format_due_date(due)

    created = execute_google_request(service.tasks().insert(tasklist=list_id, body=body))
    return _normalize_task(created)


def complete_task(
    task_id: str,
    list_id: str = "@default",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _tasks_service(config)
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    updated = execute_google_request(
        service.tasks().patch(
            tasklist=list_id,
            task=task_id,
            body={"status": "completed", "completed": completed_at},
        )
    )
    return _normalize_task(updated)


def delete_task(
    task_id: str,
    list_id: str = "@default",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _tasks_service(config)
    execute_google_request(service.tasks().delete(tasklist=list_id, task=task_id))
    return {"deleted": True, "task_id": task_id, "list_id": list_id}


def register_tasks_commands(group: click.Group) -> None:
    @group.command("lists")
    @click.option("--max", "max_results", default=100, type=int, show_default=True)
    @json_option
    @click.pass_context
    def lists_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        data = list_task_lists(max_results=max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            if not data:
                print_human("No task lists found.", emoji="✅")
                return
            print_human(f"Task lists ({len(data)}):", emoji="✅")
            for item in data:
                print_human(f"  • {item.get('title')}")
                print_human(f"    ID: {item.get('id')}")

    @group.command("list")
    @click.option("--list", "list_id", default="@default", show_default=True, help="Task list ID.")
    @click.option("--max", "max_results", default=100, type=int, show_default=True)
    @click.option("--pending-only", is_flag=True, help="Hide completed tasks.")
    @json_option
    @click.pass_context
    def list_command(
        ctx: click.Context,
        list_id: str,
        max_results: int,
        pending_only: bool,
        json_output: bool | None,
    ) -> None:
        data = list_tasks(
            list_id=list_id,
            max_results=max_results,
            show_completed=not pending_only,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            if not data:
                print_human("No tasks found.", emoji="✅")
                return
            print_human(f"Tasks ({len(data)}):", emoji="✅")
            for item in data:
                marker = "✓" if item.get("status") == "completed" else "•"
                print_human(f"  {marker} {item.get('title')}")
                print_human(f"    ID: {item.get('id')}")
                if item.get("due"):
                    print_human(f"    Due: {item.get('due')}")

    @group.command("add")
    @click.argument("title")
    @click.option("--notes", default=None, help="Task notes.")
    @click.option("--due", default=None, help="Due date (YYYY-MM-DD or ISO 8601).")
    @click.option("--list", "list_id", default="@default", show_default=True, help="Task list ID.")
    @json_option
    @click.pass_context
    def add_command(
        ctx: click.Context,
        title: str,
        notes: str | None,
        due: str | None,
        list_id: str,
        json_output: bool | None,
    ) -> None:
        data = add_task(
            title=title,
            notes=notes,
            due=due,
            list_id=list_id,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Task created: {data.get('title')} ({data.get('id')})")

    @group.command("complete")
    @click.argument("task_id")
    @click.option("--list", "list_id", default="@default", show_default=True, help="Task list ID.")
    @json_option
    @click.pass_context
    def complete_command(
        ctx: click.Context,
        task_id: str,
        list_id: str,
        json_output: bool | None,
    ) -> None:
        data = complete_task(task_id=task_id, list_id=list_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Task completed: {data.get('title', task_id)}")

    @group.command("delete")
    @click.argument("task_id")
    @click.option("--list", "list_id", default="@default", show_default=True, help="Task list ID.")
    @json_option
    @click.pass_context
    def delete_command(
        ctx: click.Context,
        task_id: str,
        list_id: str,
        json_output: bool | None,
    ) -> None:
        data = delete_task(task_id=task_id, list_id=list_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Task deleted: {data['task_id']}")
