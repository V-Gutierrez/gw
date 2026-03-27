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
        service.files().get(fileId=file_id, fields="id,name,mimeType,size")
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
        request = service.files().get_media(fileId=file_id)

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


def get_drive_file_info(
    file_id: str,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    service = _drive_service(config)
    file_info = execute_google_request(
        service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size,createdTime,modifiedTime,owners,webViewLink,shared,fileExtension,description",
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


def register_drive_commands(group: click.Group) -> None:
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
