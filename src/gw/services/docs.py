from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from gw.auth import build_service
from gw.output import json_option, print_human, print_json, print_success, use_json_output
from gw.utils import atomic_write

EXPORT_MIME_TYPES = {
    "txt": "text/plain",
    "html": "text/html",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
}


def _extract_doc_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in document.get("body", {}).get("content", []):
        paragraph = block.get("paragraph")
        if not paragraph:
            continue
        for element in paragraph.get("elements", []):
            text_run = element.get("textRun")
            if text_run:
                parts.append(text_run.get("content", ""))
    return "".join(parts).strip()


def read_doc(document_id: str) -> dict[str, Any]:
    service = build_service("docs", "v1")
    document = service.documents().get(documentId=document_id).execute()
    return {
        "id": document_id,
        "title": document.get("title", "Untitled"),
        "content": _extract_doc_text(document),
    }


def export_doc(
    document_id: str, export_format: str = "txt", output_path: str | None = None
) -> dict[str, Any]:
    mime_type = EXPORT_MIME_TYPES.get(export_format)
    if not mime_type:
        raise click.ClickException(
            f"Unsupported format: {export_format}. Supported: {', '.join(sorted(EXPORT_MIME_TYPES))}"
        )

    service = build_service("drive", "v3")
    data = service.files().export_media(fileId=document_id, mimeType=mime_type).execute()
    if output_path:
        target = Path(output_path).expanduser()
        atomic_write(target, data)
        return {"document_id": document_id, "format": export_format, "path": str(target)}

    if export_format in {"txt", "html"}:
        text = data.decode("utf-8", errors="replace")
        return {"document_id": document_id, "format": export_format, "content": text}

    raise click.ClickException("Binary exports require --out.")


def list_docs(max_results: int = 10) -> list[dict[str, Any]]:
    service = build_service("drive", "v3")
    return (
        service.files()
        .list(
            q="mimeType='application/vnd.google-apps.document'",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, modifiedTime)",
        )
        .execute()
        .get("files", [])
    )


def register_docs_commands(group: click.Group) -> None:
    @group.command("read")
    @click.argument("document_id")
    @json_option
    @click.pass_context
    def read_command(ctx: click.Context, document_id: str, json_output: bool | None) -> None:
        data = read_doc(document_id=document_id)
        if use_json_output(ctx, json_output):
            print_json(data)
        else:
            print_human(f"Document: {data['title']}", emoji="📄")
            print_human("")
            print_human(data["content"])

    @group.command("export")
    @click.argument("document_id")
    @click.option("--format", "export_format", default="txt", show_default=True)
    @click.option("--out", "output_path", default=None, help="Output path for exported content.")
    @json_option
    @click.pass_context
    def export_command(
        ctx: click.Context,
        document_id: str,
        export_format: str,
        output_path: str | None,
        json_output: bool | None,
    ) -> None:
        payload = export_doc(
            document_id=document_id, export_format=export_format, output_path=output_path
        )
        if use_json_output(ctx, json_output):
            print_json(payload)
        elif "path" in payload:
            print_success(f"Exported to: {payload['path']}")
        else:
            print_human(str(payload["content"]))

    @group.command("list")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        files = list_docs(max_results=max_results)
        if use_json_output(ctx, json_output):
            print_json(files)
        else:
            if not files:
                print_human("No documents found.", emoji="📄")
                return
            print_human(f"Recent documents ({len(files)}):", emoji="📄")
            for item in files:
                print_human(f"  • {item.get('name')}")
                print_human(f"    ID: {item.get('id')}")
                print_human(f"    Modified: {item.get('modifiedTime')}")
