from __future__ import annotations

import io
import mimetypes
from pathlib import Path
from typing import Any

import click
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, print_success, use_json_output
from gw.utils import atomic_write

NATIVE_EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": {
        "txt": "text/plain",
        "html": "text/html",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    "application/vnd.google-apps.spreadsheet": {
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    },
}


def _drive_service(config: GWConfig | None = None):
    return build_service("drive", "v3", config=config)


def _download_request_bytes(request: Any) -> bytes:
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def _default_download_path(name: str, export_format: str | None) -> Path:
    if export_format is None:
        return Path(name)
    if name.endswith(f".{export_format}"):
        return Path(name)
    return Path(f"{name}.{export_format}")


def list_drive_files(
    max_results: int = 10, config: GWConfig | None = None
) -> list[dict[str, Any]]:
    service = _drive_service(config)
    response = execute_google_request(
        service.files().list(
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            corpora="allDrives",
        )
    )
    return response.get("files", [])


def _wrap_query_for_drive(query: str) -> str:
    """Wrap free-text query into Drive query syntax, or pass through if already Drive-formatted."""
    # Check if query already contains Drive operators
    drive_operators = (
        "name contains",
        "name =",
        "name !=",
        "mimeType",
        "trashed",
        "parents",
        "createdTime",
        "modifiedTime",
        "owners",
        "shared",
        "webViewLink",
        "=",
        "!=",
        "contains",
        "and",
        "or",
        "not",
    )
    query_lower = query.lower()
    if any(f" {op} " in query_lower or query_lower.startswith(op) for op in drive_operators):
        return query

    # Escape single quotes for Drive query syntax
    escaped_query = query.replace("'", "\\'")
    return f"name contains '{escaped_query}'"


def search_drive_files(
    query: str,
    max_results: int = 10,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _drive_service(config)
    wrapped_query = _wrap_query_for_drive(query)
    response = execute_google_request(
        service.files().list(
            q=wrapped_query,
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            corpora="allDrives",
        )
    )
    return response.get("files", [])


def upload_drive_file(
    file_path: str,
    name: str | None = None,
    folder_id: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    source = Path(file_path).expanduser()
    if not source.exists() or not source.is_file():
        raise click.ClickException(f"File not found: {source}")

    mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    metadata: dict[str, Any] = {"name": name or source.name}
    if folder_id:
        metadata["parents"] = [folder_id]

    service = _drive_service(config)
    uploaded = execute_google_request(
        service.files().create(
            body=metadata,
            media_body=MediaFileUpload(str(source), mimetype=mime_type),
            fields="id,name,mimeType,webViewLink",
        )
    )
    return {
        "id": uploaded.get("id"),
        "name": uploaded.get("name"),
        "mime_type": uploaded.get("mimeType"),
        "web_view_link": uploaded.get("webViewLink"),
    }


def download_drive_file(
    file_id: str,
    output_path: str | None = None,
    export_format: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    metadata = execute_google_request(
        service.files().get(
            fileId=file_id, fields="id,name,mimeType,size", supportsAllDrives=True
        )
    )
    name = metadata.get("name", file_id)
    mime_type = metadata.get("mimeType", "application/octet-stream")
    export_map = NATIVE_EXPORT_MIME_TYPES.get(mime_type)

    if export_map is not None:
        if export_format is None:
            supported = ", ".join(sorted(export_map))
            raise click.ClickException(
                f"Google-native files require --format. Supported formats: {supported}"
            )
        export_mime = export_map.get(export_format)
        if export_mime is None:
            supported = ", ".join(sorted(export_map))
            raise click.ClickException(
                f"Unsupported format {export_format!r} for this file. Supported: {supported}"
            )
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        if export_format is not None:
            raise click.ClickException("--format is only supported for Google-native Drive files.")
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    data = _download_request_bytes(request)
    target = (
        Path(output_path).expanduser()
        if output_path
        else _default_download_path(name, export_format)
    )
    atomic_write(target, data)
    return {
        "id": metadata.get("id", file_id),
        "name": name,
        "mime_type": mime_type,
        "path": str(target),
        "size": len(data),
        "format": export_format,
    }


def mkdir_drive_folder(
    name: str,
    parent_id: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    metadata: dict[str, Any] = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    created = execute_google_request(
        service.files().create(
            body=metadata,
            fields="id,name,mimeType,webViewLink",
        )
    )
    return {
        "id": created.get("id"),
        "name": created.get("name"),
        "mime_type": created.get("mimeType"),
        "web_view_link": created.get("webViewLink"),
    }


def share_drive_file(
    file_id: str,
    email: str,
    role: str = "reader",
    config: GWConfig | None = None,
) -> dict[str, Any]:
    if role not in ("reader", "writer", "commenter"):
        raise click.ClickException(f"Role must be reader, writer, or commenter. Got: {role}")

    service = _drive_service(config)
    permission = execute_google_request(
        service.permissions().create(
            fileId=file_id,
            body={"type": "user", "emailAddress": email, "role": role},
            fields="id,emailAddress,role,type",
        )
    )
    return {
        "id": permission.get("id"),
        "email": permission.get("emailAddress"),
        "role": permission.get("role"),
        "type": permission.get("type"),
    }


def delete_drive_file(
    file_id: str,
    permanent: bool = False,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Trash a file, or delete it for good with ``permanent``.

    Trashing is the default because a permanent delete cannot be undone — not
    even by the file owner.
    """
    service = _drive_service(config)
    if permanent:
        execute_google_request(service.files().delete(fileId=file_id, supportsAllDrives=True))
        return {"id": file_id, "name": None, "trashed": False, "permanent": True}

    updated = execute_google_request(
        service.files().update(
            fileId=file_id,
            body={"trashed": True},
            fields="id,name,trashed",
            supportsAllDrives=True,
        )
    )
    return {
        "id": updated.get("id", file_id),
        "name": updated.get("name"),
        "trashed": bool(updated.get("trashed", True)),
        "permanent": False,
    }


def rename_drive_file(
    file_id: str,
    name: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    updated = execute_google_request(
        service.files().update(
            fileId=file_id,
            body={"name": name},
            fields="id,name,mimeType,webViewLink",
            supportsAllDrives=True,
        )
    )
    return {
        "id": updated.get("id", file_id),
        "name": updated.get("name", name),
        "mime_type": updated.get("mimeType"),
        "web_view_link": updated.get("webViewLink"),
    }


def unshare_drive_file(
    file_id: str,
    email: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Remove one person's permission on a file, looked up by email."""
    service = _drive_service(config)
    permissions = execute_google_request(
        service.permissions().list(
            fileId=file_id,
            fields="permissions(id,emailAddress,role,type)",
            supportsAllDrives=True,
        )
    ).get("permissions", [])

    target = next(
        (
            permission
            for permission in permissions
            if (permission.get("emailAddress") or "").lower() == email.lower()
        ),
        None,
    )
    if target is None:
        raise click.ClickException(f"No permission found for {email} on file {file_id}.")

    execute_google_request(
        service.permissions().delete(
            fileId=file_id,
            permissionId=target["id"],
            supportsAllDrives=True,
        )
    )
    return {
        "file_id": file_id,
        "email": target.get("emailAddress", email),
        "permission_id": target["id"],
        "role": target.get("role"),
        "removed": True,
    }


def get_drive_file_info(
    file_id: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    file_info = execute_google_request(
        service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size,createdTime,modifiedTime,owners,webViewLink,shared,fileExtension,description",
            supportsAllDrives=True,
        )
    )
    return {
        "id": file_info.get("id"),
        "name": file_info.get("name"),
        "mime_type": file_info.get("mimeType"),
        "size": file_info.get("size"),
        "created_time": file_info.get("createdTime"),
        "modified_time": file_info.get("modifiedTime"),
        "owners": file_info.get("owners", []),
        "web_view_link": file_info.get("webViewLink"),
        "shared": file_info.get("shared", False),
        "file_extension": file_info.get("fileExtension"),
        "description": file_info.get("description"),
    }


def copy_drive_file(
    file_id: str,
    name: str | None = None,
    folder: str | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Duplicate a file. The original is untouched."""
    service = _drive_service(config)
    body: dict[str, Any] = {}
    if name:
        body["name"] = name
    if folder:
        body["parents"] = [folder]
    copied = execute_google_request(
        service.files().copy(
            fileId=file_id,
            body=body,
            fields="id,name,mimeType,webViewLink",
            supportsAllDrives=True,
        )
    )
    return {
        "id": copied.get("id"),
        "name": copied.get("name"),
        "mime_type": copied.get("mimeType"),
        "web_view_link": copied.get("webViewLink"),
        "copied_from": file_id,
    }


def move_drive_file(
    file_id: str,
    folder: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Move a file into another folder.

    Drive files can have several parents, so adding one without removing the old
    ones would leave the file showing up in both places. gw reads the current
    parents and swaps them out.
    """
    service = _drive_service(config)
    current = execute_google_request(
        service.files().get(fileId=file_id, fields="id,name,parents", supportsAllDrives=True)
    )
    parents = current.get("parents") or []
    if not parents:
        raise click.ClickException(
            f"File {file_id} has no parent folder to move it out of "
            "(it may be a shared drive root or shared with you only)."
        )

    updated = execute_google_request(
        service.files().update(
            fileId=file_id,
            addParents=folder,
            removeParents=",".join(parents),
            fields="id,name,parents,webViewLink",
            supportsAllDrives=True,
        )
    )
    return {
        "id": updated.get("id", file_id),
        "name": updated.get("name", current.get("name")),
        "moved_from": parents,
        "moved_to": folder,
        "web_view_link": updated.get("webViewLink"),
    }


def get_drive_about(config: GWConfig | None = None) -> dict[str, Any]:
    """Report the account's storage quota."""
    service = _drive_service(config)
    about = execute_google_request(
        service.about().get(fields="user(displayName,emailAddress),storageQuota")
    )
    quota = about.get("storageQuota", {})
    limit = int(quota["limit"]) if quota.get("limit") else None
    usage = int(quota.get("usage", 0))
    return {
        "email": about.get("user", {}).get("emailAddress"),
        "name": about.get("user", {}).get("displayName"),
        "limit": limit,
        "usage": usage,
        "usage_in_drive": int(quota.get("usageInDrive", 0)),
        "percent_used": round(usage / limit * 100, 1) if limit else None,
    }


def list_drive_revisions(
    file_id: str,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _drive_service(config)
    response = execute_google_request(
        service.revisions().list(
            fileId=file_id,
            fields="revisions(id,modifiedTime,lastModifyingUser,size,keepForever)",
        )
    )
    return [
        {
            "id": revision.get("id"),
            "modified_time": revision.get("modifiedTime"),
            "modified_by": revision.get("lastModifyingUser", {}).get("displayName", ""),
            "size": int(revision["size"]) if revision.get("size") else None,
            "keep_forever": revision.get("keepForever", False),
        }
        for revision in response.get("revisions", [])
    ]


def delete_drive_revision(
    file_id: str,
    revision_id: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    execute_google_request(
        service.revisions().delete(fileId=file_id, revisionId=revision_id)
    )
    return {"file_id": file_id, "revision_id": revision_id, "deleted": True}


def list_drive_comments(
    file_id: str,
    include_resolved: bool = False,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    """List comments on a file.

    Drive returns almost nothing here unless ``fields`` names what you want, so
    the field list is mandatory rather than optional.
    """
    service = _drive_service(config)
    response = execute_google_request(
        service.comments().list(
            fileId=file_id,
            fields=(
                "comments(id,content,author(displayName),createdTime,resolved,"
                "replies(id,content,author(displayName),createdTime))"
            ),
            includeDeleted=False,
        )
    )
    comments = []
    for comment in response.get("comments", []):
        if comment.get("resolved") and not include_resolved:
            continue
        comments.append(
            {
                "id": comment.get("id"),
                "content": comment.get("content", ""),
                "author": comment.get("author", {}).get("displayName", ""),
                "created_time": comment.get("createdTime"),
                "resolved": comment.get("resolved", False),
                "replies": [
                    {
                        "id": reply.get("id"),
                        "content": reply.get("content", ""),
                        "author": reply.get("author", {}).get("displayName", ""),
                    }
                    for reply in comment.get("replies", [])
                ],
            }
        )
    return comments


def add_drive_comment(
    file_id: str,
    content: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    comment = execute_google_request(
        service.comments().create(
            fileId=file_id,
            body={"content": content},
            fields="id,content,author(displayName),createdTime",
        )
    )
    return {
        "id": comment.get("id"),
        "content": comment.get("content", content),
        "author": comment.get("author", {}).get("displayName", ""),
        "file_id": file_id,
    }


def reply_to_drive_comment(
    file_id: str,
    comment_id: str,
    content: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    reply = execute_google_request(
        service.replies().create(
            fileId=file_id,
            commentId=comment_id,
            body={"content": content},
            fields="id,content,author(displayName)",
        )
    )
    return {
        "id": reply.get("id"),
        "content": reply.get("content", content),
        "comment_id": comment_id,
        "file_id": file_id,
    }


def resolve_drive_comment(
    file_id: str,
    comment_id: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    """Resolve a comment thread.

    Drive has no 'resolve' verb: a thread is resolved by posting a reply whose
    action is ``resolve``.
    """
    service = _drive_service(config)
    execute_google_request(
        service.replies().create(
            fileId=file_id,
            commentId=comment_id,
            body={"action": "resolve"},
            fields="id,action",
        )
    )
    return {"file_id": file_id, "comment_id": comment_id, "resolved": True}


def list_drive_permissions(
    file_id: str,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    """Show who has access to a file."""
    service = _drive_service(config)
    response = execute_google_request(
        service.permissions().list(
            fileId=file_id,
            fields="permissions(id,emailAddress,role,type,displayName)",
            supportsAllDrives=True,
        )
    )
    return [
        {
            "id": permission.get("id"),
            "email": permission.get("emailAddress", ""),
            "name": permission.get("displayName", ""),
            "role": permission.get("role"),
            "type": permission.get("type"),
        }
        for permission in response.get("permissions", [])
    ]


def list_shared_drives(
    max_results: int = 50,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _drive_service(config)
    response = execute_google_request(
        service.drives().list(pageSize=max_results, fields="drives(id,name,createdTime)")
    )
    return [
        {
            "id": drive.get("id"),
            "name": drive.get("name"),
            "created_time": drive.get("createdTime"),
        }
        for drive in response.get("drives", [])
    ]


def _human_bytes(value: int | None) -> str:
    if value is None:
        return "unlimited"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def register_drive_commands(group: click.Group) -> None:
    @group.command("copy")
    @click.argument("file_id")
    @click.option("--name", default=None, help="Name for the copy.")
    @click.option("--folder", default=None, help="Folder ID to put the copy in.")
    @json_option
    @click.pass_context
    def copy_command(
        ctx: click.Context,
        file_id: str,
        name: str | None,
        folder: str | None,
        json_output: bool | None,
    ) -> None:
        """Duplicate a file. The original is untouched."""
        data = copy_drive_file(file_id, name=name, folder=folder, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Copied to {data['name']} ({data['id']})")

    @group.command("move")
    @click.argument("file_id")
    @click.argument("folder")
    @json_option
    @click.pass_context
    def move_command(
        ctx: click.Context, file_id: str, folder: str, json_output: bool | None
    ) -> None:
        """Move a file into another folder."""
        data = move_drive_file(file_id, folder=folder, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Moved {data['name']} to folder {folder}.")

    @group.command("about")
    @json_option
    @click.pass_context
    def about_command(ctx: click.Context, json_output: bool | None) -> None:
        """Show the account's Drive storage quota."""
        data = get_drive_about(config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Drive: {data['email']}", emoji="💾")
            used = _human_bytes(data["usage"])
            limit = _human_bytes(data["limit"])
            percent = f" ({data['percent_used']}%)" if data["percent_used"] is not None else ""
            print_human(f"  Used: {used} of {limit}{percent}")

    @group.command("revisions")
    @click.argument("file_id")
    @json_option
    @click.pass_context
    def revisions_command(ctx: click.Context, file_id: str, json_output: bool | None) -> None:
        """List a file's version history."""
        data = list_drive_revisions(file_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        elif not data:
            print_human("No revisions found.", emoji="🕓")
        else:
            print_human(f"Revisions ({len(data)}):", emoji="🕓")
            for revision in data:
                size = _human_bytes(revision["size"]) if revision["size"] else "—"
                print_human(
                    f"  • {revision['modified_time']} — {revision['modified_by']} ({size})"
                )
                print_human(f"    ID: {revision['id']}")

    @group.command("revision-delete")
    @click.argument("file_id")
    @click.argument("revision_id")
    @click.option("-y", "--yes", is_flag=True, help="Skip the confirmation.")
    @json_option
    @click.pass_context
    def revision_delete_command(
        ctx: click.Context,
        file_id: str,
        revision_id: str,
        yes: bool,
        json_output: bool | None,
    ) -> None:
        """Delete one revision from a file's history. Cannot be undone."""
        if not yes:
            click.confirm(f"Delete revision {revision_id}? This cannot be undone.", abort=True)
        data = delete_drive_revision(file_id, revision_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Revision {revision_id} deleted.")

    @group.command("comments")
    @click.argument("file_id")
    @click.option("--include-resolved", is_flag=True, help="Also show resolved threads.")
    @json_option
    @click.pass_context
    def comments_command(
        ctx: click.Context, file_id: str, include_resolved: bool, json_output: bool | None
    ) -> None:
        """List the comments on a file."""
        data = list_drive_comments(
            file_id, include_resolved=include_resolved, config=ctx.obj["config"]
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        elif not data:
            print_human("No comments found.", emoji="💬")
        else:
            print_human(f"Comments ({len(data)}):", emoji="💬")
            for comment in data:
                mark = " [resolved]" if comment["resolved"] else ""
                print_human(f"  • {comment['author']}{mark}: {comment['content']}")
                print_human(f"    ID: {comment['id']}")
                for reply in comment["replies"]:
                    print_human(f"      ↳ {reply['author']}: {reply['content']}")

    @group.command("comment")
    @click.argument("file_id")
    @click.argument("content")
    @json_option
    @click.pass_context
    def comment_command(
        ctx: click.Context, file_id: str, content: str, json_output: bool | None
    ) -> None:
        """Add a comment to a file."""
        data = add_drive_comment(file_id, content, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Comment added ({data['id']}).")

    @group.command("comment-reply")
    @click.argument("file_id")
    @click.argument("comment_id")
    @click.argument("content")
    @json_option
    @click.pass_context
    def comment_reply_command(
        ctx: click.Context,
        file_id: str,
        comment_id: str,
        content: str,
        json_output: bool | None,
    ) -> None:
        """Reply to a comment thread."""
        data = reply_to_drive_comment(file_id, comment_id, content, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Replied to comment {comment_id}.")

    @group.command("comment-resolve")
    @click.argument("file_id")
    @click.argument("comment_id")
    @json_option
    @click.pass_context
    def comment_resolve_command(
        ctx: click.Context, file_id: str, comment_id: str, json_output: bool | None
    ) -> None:
        """Mark a comment thread as resolved."""
        data = resolve_drive_comment(file_id, comment_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Comment {comment_id} resolved.")

    @group.command("permissions")
    @click.argument("file_id")
    @json_option
    @click.pass_context
    def permissions_command(ctx: click.Context, file_id: str, json_output: bool | None) -> None:
        """Show who has access to a file."""
        data = list_drive_permissions(file_id, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        elif not data:
            print_human("No permissions found.", emoji="🔐")
        else:
            print_human(f"Permissions ({len(data)}):", emoji="🔐")
            for permission in data:
                who = permission["email"] or permission["name"] or permission["type"]
                print_human(f"  • {who} — {permission['role']}")

    @group.command("drives")
    @click.option("--max", "max_results", default=50, type=int, show_default=True)
    @json_option
    @click.pass_context
    def drives_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        """List the shared drives you can reach."""
        data = list_shared_drives(max_results=max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        elif not data:
            print_human("No shared drives found.", emoji="🗂️")
        else:
            print_human(f"Shared drives ({len(data)}):", emoji="🗂️")
            for drive in data:
                print_human(f"  • {drive['name']} — {drive['id']}")

    @group.command("list")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        files = list_drive_files(max_results=max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(files)
        else:
            if not files:
                print_human("No files found.", emoji="📂")
                return
            print_human(f"Recent files ({len(files)}):", emoji="📂")
            for item in files:
                print_human(f"  • {item.get('name')} ({item.get('mimeType')})")
                print_human(f"    ID: {item.get('id')}")
                print_human(f"    Modified: {item.get('modifiedTime')}")

    @group.command("search")
    @click.argument("query")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @json_option
    @click.pass_context
    def search_command(
        ctx: click.Context, query: str, max_results: int, json_output: bool | None
    ) -> None:
        files = search_drive_files(query=query, max_results=max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(files)
        else:
            if not files:
                print_human("No files matched the query.", emoji="📂")
                return
            print_human(f"Matching files ({len(files)}):", emoji="📂")
            for item in files:
                print_human(f"  • {item.get('name')} ({item.get('mimeType')})")
                print_human(f"    ID: {item.get('id')}")

    @group.command("upload")
    @click.argument("file_path")
    @click.option("--name", default=None, help="Name to use in Drive.")
    @click.option("--folder", "folder_id", default=None, help="Parent folder ID.")
    @json_option
    @click.pass_context
    def upload_command(
        ctx: click.Context,
        file_path: str,
        name: str | None,
        folder_id: str | None,
        json_output: bool | None,
    ) -> None:
        data = upload_drive_file(
            file_path=file_path,
            name=name,
            folder_id=folder_id,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Uploaded to Drive: {data['name']} ({data['id']})")

    @group.command("download")
    @click.argument("file_id")
    @click.option("--out", "output_path", default=None, help="Output path for downloaded content.")
    @click.option(
        "--format", "export_format", default=None, help="Export format for Google-native files."
    )
    @json_option
    @click.pass_context
    def download_command(
        ctx: click.Context,
        file_id: str,
        output_path: str | None,
        export_format: str | None,
        json_output: bool | None,
    ) -> None:
        data = download_drive_file(
            file_id=file_id,
            output_path=output_path,
            export_format=export_format,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Downloaded to: {data['path']}")

    @group.command("mkdir")
    @click.argument("name")
    @click.option("--parent", "parent_id", default=None, help="Parent folder ID.")
    @json_option
    @click.pass_context
    def mkdir_command(
        ctx: click.Context,
        name: str,
        parent_id: str | None,
        json_output: bool | None,
    ) -> None:
        data = mkdir_drive_folder(
            name=name,
            parent_id=parent_id,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Created folder: {data['name']} ({data['id']})")

    @group.command("share")
    @click.argument("file_id")
    @click.argument("email")
    @click.option(
        "--role",
        type=click.Choice(["reader", "writer", "commenter"]),
        default="reader",
        help="Permission role.",
    )
    @json_option
    @click.pass_context
    def share_command(
        ctx: click.Context,
        file_id: str,
        email: str,
        role: str,
        json_output: bool | None,
    ) -> None:
        data = share_drive_file(
            file_id=file_id,
            email=email,
            role=role,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Shared with {data['email']} as {data['role']}")

    @group.command("info")
    @click.argument("file_id")
    @json_option
    @click.pass_context
    def info_command(
        ctx: click.Context,
        file_id: str,
        json_output: bool | None,
    ) -> None:
        data = get_drive_file_info(
            file_id=file_id,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"📄 {data['name']}", emoji="")
            print_human(f"  ID: {data['id']}")
            print_human(f"  Type: {data['mime_type']}")
            if data.get("size"):
                print_human(f"  Size: {data['size']} bytes")
            if data.get("created_time"):
                print_human(f"  Created: {data['created_time']}")
            if data.get("modified_time"):
                print_human(f"  Modified: {data['modified_time']}")
            if data.get("web_view_link"):
                print_human(f"  Link: {data['web_view_link']}")
            if data.get("shared"):
                print_human("  Shared: Yes")
            if data.get("description"):
                print_human(f"  Description: {data['description']}")

    @group.command("delete")
    @click.argument("file_id")
    @click.option(
        "--permanent",
        is_flag=True,
        help="Delete for good instead of moving to the trash. Cannot be undone.",
    )
    @click.option("--yes", "-y", is_flag=True, help="Skip the confirmation for --permanent.")
    @json_option
    @click.pass_context
    def delete_command(
        ctx: click.Context,
        file_id: str,
        permanent: bool,
        yes: bool,
        json_output: bool | None,
    ) -> None:
        """Move a file to the trash. Use --permanent to delete it for good."""
        if permanent and not yes:
            click.confirm(
                f"Permanently delete {file_id}? This cannot be undone.",
                abort=True,
            )
        data = delete_drive_file(
            file_id=file_id,
            permanent=permanent,
            config=ctx.obj["config"],
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        elif data["permanent"]:
            print_success(f"Permanently deleted: {data['id']}")
        else:
            print_success(f"Moved to trash: {data.get('name') or data['id']}")

    @group.command("rename")
    @click.argument("file_id")
    @click.argument("name")
    @json_option
    @click.pass_context
    def rename_command(
        ctx: click.Context,
        file_id: str,
        name: str,
        json_output: bool | None,
    ) -> None:
        """Rename a file or folder."""
        data = rename_drive_file(file_id=file_id, name=name, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Renamed to: {data['name']}")

    @group.command("unshare")
    @click.argument("file_id")
    @click.argument("email")
    @json_option
    @click.pass_context
    def unshare_command(
        ctx: click.Context,
        file_id: str,
        email: str,
        json_output: bool | None,
    ) -> None:
        """Remove someone's access to a file."""
        data = unshare_drive_file(file_id=file_id, email=email, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            role = data.get("role") or "access"
            print_success(f"Removed {role} for {data['email']}")
