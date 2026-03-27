from __future__ import annotations

import io
import mimetypes
from pathlib import Path
from typing import Any

import click
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from gw.auth import build_service
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


def _drive_service():
    return build_service("drive", "v3")


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


def list_drive_files(max_results: int = 10) -> list[dict[str, Any]]:
    service = _drive_service()
    return (
        service.files()
        .list(
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime)",
        )
        .execute()
        .get("files", [])
    )


def search_drive_files(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    service = _drive_service()
    return (
        service.files()
        .list(
            q=query,
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime)",
        )
        .execute()
        .get("files", [])
    )


def upload_drive_file(
    file_path: str, name: str | None = None, folder_id: str | None = None
) -> dict[str, Any]:
    source = Path(file_path).expanduser()
    if not source.exists() or not source.is_file():
        raise click.ClickException(f"File not found: {source}")

    mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    metadata: dict[str, Any] = {"name": name or source.name}
    if folder_id:
        metadata["parents"] = [folder_id]

    service = _drive_service()
    uploaded = (
        service.files()
        .create(
            body=metadata,
            media_body=MediaFileUpload(str(source), mimetype=mime_type),
            fields="id,name,mimeType,webViewLink",
        )
        .execute()
    )
    return {
        "id": uploaded.get("id"),
        "name": uploaded.get("name"),
        "mime_type": uploaded.get("mimeType"),
        "web_view_link": uploaded.get("webViewLink"),
    }


def download_drive_file(
    file_id: str, output_path: str | None = None, export_format: str | None = None
) -> dict[str, Any]:
    service = _drive_service()
    metadata = service.files().get(fileId=file_id, fields="id,name,mimeType,size").execute()
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


def register_drive_commands(group: click.Group) -> None:
    @group.command("list")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        files = list_drive_files(max_results=max_results)
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
        files = search_drive_files(query=query, max_results=max_results)
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
        data = upload_drive_file(file_path=file_path, name=name, folder_id=folder_id)
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
        )
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_success(f"Downloaded to: {data['path']}")
