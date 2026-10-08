from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import click

from gw.auth import CHAT_SCOPES, build_service, execute_google_request, granted_scopes
from gw.config import GWConfig
from gw.errors import GwAuthError, GwError
from gw.output import json_option, print_human, print_json, print_success, use_json_output

_PAGE_MAX = 1000
_APP_NOT_FOUND = "chat app not found"


def _chat_service(config: GWConfig | None = None):
    return build_service("chat", "v1", config=config)


def require_chat_scopes(config: GWConfig | None) -> None:
    """Fail before calling Google when the token was never granted Chat.

    Without this, Google answers a 403 "insufficient authentication scopes" that does not
    say which login fixes it.
    """
    granted = set(granted_scopes(config) if config is not None else [])
    missing = [scope for scope in CHAT_SCOPES if scope not in granted]
    if not missing:
        return
    profile = getattr(config, "profile", None)
    command = f"gw --profile {profile} auth login --chat" if profile else "gw auth login --chat"
    raise GwAuthError(
        f"This token has no Google Chat permission ({len(missing)} scope(s) missing). "
        f"Run: {command}"
    )


def _execute(request: Any) -> Any:
    """Run a Chat request, turning the unconfigured-app 404 into the step that fixes it."""
    try:
        return execute_google_request(request)
    except GwError as exc:
        if _APP_NOT_FOUND in exc.message.lower():
            raise GwError(
                "The Chat API is on but no Chat app is configured in this Cloud project. "
                "Open https://console.cloud.google.com/apis/api/chat.googleapis.com, "
                "tab Configuration, and fill in app name, avatar and description."
            ) from exc
        raise


def _service(config: GWConfig | None):
    require_chat_scopes(config)
    return _chat_service(config)


def space_name(value: str) -> str:
    text = value.strip()
    if not text:
        raise GwError("A space is required: `spaces/AAAA…` or just `AAAA…`.")
    return text if text.startswith("spaces/") else f"spaces/{text}"


def _user_name(email_or_id: str) -> str:
    text = email_or_id.strip()
    return text if text.startswith("users/") else f"users/{text}"


def _after_timestamp(value: str) -> str:
    """`6h`/`7d` relative to now, `YYYY-MM-DD` (UTC midnight) or an ISO 8601 instant."""
    text = value.strip()
    unit, amount = text[-1:].lower(), text[:-1]
    if unit in {"h", "d"} and amount.isdigit():
        delta = timedelta(hours=int(amount)) if unit == "h" else timedelta(days=int(amount))
        moment = datetime.now(UTC) - delta
    else:
        try:
            moment = (
                datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
                if len(text) == 10
                else datetime.fromisoformat(text)
            )
        except ValueError as exc:
            raise GwError("--after must be 6h, 7d, YYYY-MM-DD or ISO 8601.") from exc
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _paginate(method: Any, key: str, max_results: int, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    token: str | None = None
    while len(items) < max_results:
        page_size = min(max_results - len(items), _PAGE_MAX)
        kwargs = {**params, "pageSize": page_size}
        if token:
            kwargs["pageToken"] = token
        response = _execute(method(**kwargs))
        items.extend(response.get(key, []))
        token = response.get("nextPageToken")
        if not token:
            break
    return items[:max_results]


def _normalize_space(space: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": space.get("name"),
        "display_name": space.get("displayName"),
        "type": space.get("spaceType"),
        "threaded": space.get("spaceThreadingState"),
        "last_active": space.get("lastActiveTime"),
        "uri": space.get("spaceUri"),
    }


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    sender = message.get("sender") or {}
    return {
        "name": message.get("name"),
        "created": message.get("createTime"),
        "sender": sender.get("displayName") or sender.get("name"),
        "sender_type": sender.get("type"),
        "text": message.get("text"),
        "thread": (message.get("thread") or {}).get("name"),
        "attachments": len(message.get("attachment") or []),
    }


def _normalize_member(membership: dict[str, Any]) -> dict[str, Any]:
    member = membership.get("member") or {}
    return {
        "name": membership.get("name"),
        "user": member.get("name"),
        "display_name": member.get("displayName"),
        "type": member.get("type"),
        "role": membership.get("role"),
        "state": membership.get("state"),
    }


def list_spaces(
    max_results: int = 100,
    space_type: str | None = None,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _service(config)
    params: dict[str, Any] = {}
    if space_type:
        params["filter"] = f'spaceType = "{space_type}"'
    spaces = _paginate(service.spaces().list, "spaces", max_results, **params)
    return [_normalize_space(space) for space in spaces]


def get_space(space: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _service(config)
    return _normalize_space(_execute(service.spaces().get(name=space_name(space))))


def find_direct_message(user: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _service(config)
    found = _execute(service.spaces().findDirectMessage(name=_user_name(user)))
    return _normalize_space(found)


def list_messages(
    space: str,
    max_results: int = 25,
    after: str | None = None,
    thread: str | None = None,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _service(config)
    filters: list[str] = []
    if after:
        filters.append(f'createTime > "{_after_timestamp(after)}"')
    if thread:
        filters.append(f'thread.name = "{thread.strip()}"')
    params: dict[str, Any] = {"parent": space_name(space), "orderBy": "createTime desc"}
    if filters:
        params["filter"] = " AND ".join(filters)
    messages = _paginate(service.spaces().messages().list, "messages", max_results, **params)
    return [_normalize_message(message) for message in messages]


def get_message(name: str, config: GWConfig | None = None) -> dict[str, Any]:
    service = _service(config)
    return _normalize_message(_execute(service.spaces().messages().get(name=name.strip())))


def list_members(
    space: str, max_results: int = 100, config: GWConfig | None = None
) -> list[dict[str, Any]]:
    service = _service(config)
    members = _paginate(
        service.spaces().members().list,
        "memberships",
        max_results,
        parent=space_name(space),
    )
    return [_normalize_member(member) for member in members]


def _clean_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise GwError("The message is empty.")
    return cleaned


def send_message(
    space: str,
    text: str,
    thread: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"text": _clean_text(text)}
    service = _service(config)
    params: dict[str, Any] = {"parent": space_name(space), "body": body}
    if thread:
        body["thread"] = {"name": thread.strip()}
        params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    return _normalize_message(_execute(service.spaces().messages().create(**params)))


def _setup_body(display_name: str, members: list[str], description: str | None) -> dict[str, Any]:
    space: dict[str, Any] = {"spaceType": "SPACE", "displayName": display_name.strip()}
    if description:
        space["spaceDetails"] = {"description": description}
    return {
        "space": space,
        "memberships": [
            {"member": {"name": _user_name(member), "type": "HUMAN"}} for member in members
        ],
    }


def create_space(
    display_name: str,
    members: list[str] | None = None,
    description: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    if not display_name.strip():
        raise GwError("A space needs a name.")
    service = _service(config)
    body = _setup_body(display_name, members or [], description)
    return _normalize_space(_execute(service.spaces().setup(body=body)))


def _read_text(text: str | None, body_file: Path | None) -> str:
    if text and body_file:
        raise click.UsageError("Pass the text or --body-file, not both.")
    if body_file:
        return body_file.read_text(encoding="utf-8")
    if text:
        return text
    raise click.UsageError("Nothing to send: pass the text or --body-file.")


def register_chat_commands(group: click.Group) -> None:
    @group.command("spaces")
    @click.option("--max", "max_results", default=100, type=int, show_default=True)
    @click.option(
        "--type",
        "space_type",
        type=click.Choice(["SPACE", "GROUP_CHAT", "DIRECT_MESSAGE"]),
        default=None,
        help="Only spaces of this type.",
    )
    @json_option
    @click.pass_context
    def spaces_command(
        ctx: click.Context, max_results: int, space_type: str | None, json_output: bool | None
    ) -> None:
        """List the spaces, group chats and DMs this account belongs to."""
        data = list_spaces(max_results, space_type, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
            return
        if not data:
            print_human("No spaces.", emoji="💬")
            return
        print_human(f"Spaces ({len(data)}):", emoji="💬")
        for space in data:
            label = space["display_name"] or "(direct message)"
            print_human(f"  • {label} [{space['type']}]  {space['name']}")

    @group.command("space")
    @click.argument("space")
    @json_option
    @click.pass_context
    def space_command(ctx: click.Context, space: str, json_output: bool | None) -> None:
        """Show one space."""
        data = get_space(space, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
            return
        for key, value in data.items():
            print_human(f"{key}: {value}")

    @group.command("dm")
    @click.argument("user")
    @json_option
    @click.pass_context
    def dm_command(ctx: click.Context, user: str, json_output: bool | None) -> None:
        """Find the direct-message space with USER (email or users/ID)."""
        data = find_direct_message(user, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(data["name"] or "", emoji="💬")

    @group.command("messages")
    @click.argument("space")
    @click.option("--max", "max_results", default=25, type=int, show_default=True)
    @click.option("--after", default=None, help="6h, 7d, YYYY-MM-DD or ISO 8601.")
    @click.option("--thread", default=None, help="Only this thread (spaces/…/threads/…).")
    @json_option
    @click.pass_context
    def messages_command(
        ctx: click.Context,
        space: str,
        max_results: int,
        after: str | None,
        thread: str | None,
        json_output: bool | None,
    ) -> None:
        """Messages in SPACE, newest first."""
        data = list_messages(space, max_results, after, thread, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
            return
        if not data:
            print_human("No messages.", emoji="💬")
            return
        for message in data:
            print_human(f"[{message['created']}] {message['sender']}: {message['text'] or ''}")
            print_human(f"    {message['name']}")

    @group.command("read")
    @click.argument("message")
    @json_option
    @click.pass_context
    def read_command(ctx: click.Context, message: str, json_output: bool | None) -> None:
        """One message by its full name (spaces/…/messages/…)."""
        data = get_message(message, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
            return
        print_human(f"From: {data['sender']}  ({data['created']})")
        print_human(f"Thread: {data['thread']}")
        print_human("")
        print_human(data["text"] or "")

    @group.command("members")
    @click.argument("space")
    @click.option("--max", "max_results", default=100, type=int, show_default=True)
    @json_option
    @click.pass_context
    def members_command(
        ctx: click.Context, space: str, max_results: int, json_output: bool | None
    ) -> None:
        """Who is in SPACE."""
        data = list_members(space, max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
            return
        print_human(f"Members ({len(data)}):", emoji="👥")
        for member in data:
            print_human(f"  • {member['display_name'] or member['user']} [{member['role']}]")

    @group.command("send")
    @click.argument("space")
    @click.argument("text", required=False)
    @click.option(
        "--body-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
        help="Read the message text from a file.",
    )
    @click.option("--thread", default=None, help="Reply in this thread (spaces/…/threads/…).")
    @click.option("--dry-run", is_flag=True, help="Show exactly what would be sent; send nothing.")
    @json_option
    @click.pass_context
    def send_command(
        ctx: click.Context,
        space: str,
        text: str | None,
        body_file: Path | None,
        thread: str | None,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        """Send TEXT to SPACE as this user (plain text; cards need a Chat app)."""
        message = _clean_text(_read_text(text, body_file))
        if dry_run:
            preview = {
                "dry_run": True,
                "space": space_name(space),
                "text": message,
                "thread": thread,
            }
            if use_json_output(ctx, json_output):
                print_json(preview)
                return
            print_human("Dry run — nothing was sent.", emoji="🔎")
            print_human(f"Space:  {preview['space']}")
            print_human(f"Thread: {thread or '(new thread)'}")
            print_human("")
            print_human(message)
            return
        data = send_message(space, message, thread, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Sent: {data['name']}")

    @group.command("create")
    @click.argument("display_name")
    @click.option("--member", "members", multiple=True, help="Email to add. Repeatable.")
    @click.option("--description", default=None, help="Space description.")
    @click.option("--dry-run", is_flag=True, help="Show the space that would be created.")
    @json_option
    @click.pass_context
    def create_command(
        ctx: click.Context,
        display_name: str,
        members: tuple[str, ...],
        description: str | None,
        dry_run: bool,
        json_output: bool | None,
    ) -> None:
        """Create a named space and add members to it."""
        if dry_run:
            preview = {"dry_run": True, **_setup_body(display_name, list(members), description)}
            if use_json_output(ctx, json_output):
                print_json(preview)
                return
            print_human("Dry run — nothing was created.", emoji="🔎")
            print_human(f"Space:   {display_name}")
            print_human(f"Members: {', '.join(members) or '(only you)'}")
            return
        data = create_space(display_name, list(members), description, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Created {data['display_name']}: {data['name']}")
