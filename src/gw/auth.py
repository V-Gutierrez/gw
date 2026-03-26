from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import click
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from gw.config import GWConfig, load_config
from gw.output import json_option, print_json, print_success, use_json_output
from gw.utils import atomic_write

DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def _get_config() -> GWConfig:
    return load_config()


def save_credentials(creds: Credentials, path: Path | None = None) -> Path:
    token_path = path or _get_config().token
    atomic_write(token_path, creds.to_json())
    return token_path


def load_credentials(
    scopes: list[str] | None = None,
    token_path: Path | None = None,
) -> Credentials | None:
    resolved = token_path or _get_config().token
    target_scopes = scopes or DEFAULT_SCOPES

    if not resolved.exists():
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(resolved), target_scopes)
    except (json.JSONDecodeError, ValueError, KeyError):
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            return None
        save_credentials(creds, resolved)
        return creds

    return None


def login(
    scopes: list[str] | None = None,
    client_secrets: Path | None = None,
    token_path: Path | None = None,
) -> Credentials:
    target_scopes = scopes or DEFAULT_SCOPES
    cfg = _get_config()
    secrets = client_secrets or cfg.credentials
    resolved_token = token_path or cfg.token

    existing = load_credentials(target_scopes, resolved_token)
    if existing and existing.valid:
        return existing

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), target_scopes)
    creds = cast(Credentials, flow.run_local_server(port=0, open_browser=True))
    save_credentials(creds, resolved_token)
    return creds


def logout(token_path: Path | None = None) -> bool:
    resolved = token_path or _get_config().token
    if resolved.exists():
        resolved.unlink()
        return True
    return False


def credential_status(credentials: Credentials | None = None) -> dict[str, Any]:
    creds = credentials or load_credentials()
    cfg = _get_config()
    return {
        "authenticated": bool(creds and creds.valid),
        "token_path": str(cfg.token),
        "credentials_path": str(cfg.credentials),
        "expiry": creds.expiry.isoformat() if creds and creds.expiry else None,
        "scopes": list(creds.scopes or DEFAULT_SCOPES) if creds else DEFAULT_SCOPES,
    }


def build_service(
    api: str,
    version: str,
    credentials: Credentials | None = None,
    scopes: list[str] | None = None,
):
    creds = credentials or load_credentials(scopes)
    if creds is None:
        raise click.ClickException("Not authenticated. Run `gw auth login` first.")
    return build(api, version, credentials=creds)


def register_auth_commands(auth_group: click.Group) -> None:
    @auth_group.command("login")
    @json_option
    @click.pass_context
    def login_cmd(ctx: click.Context, json_output: bool | None) -> None:
        creds = login()
        status = credential_status(creds)
        if use_json_output(ctx, json_output):
            print_json(status)
        else:
            print_success("Authenticated")

    @auth_group.command("status")
    @json_option
    @click.pass_context
    def status_cmd(ctx: click.Context, json_output: bool | None) -> None:
        status = credential_status()
        if use_json_output(ctx, json_output):
            print_json(status)
        elif status["authenticated"]:
            print_success("Authenticated")
        else:
            click.echo("❌ Not authenticated")

    @auth_group.command("logout")
    @json_option
    @click.pass_context
    def logout_cmd(ctx: click.Context, json_output: bool | None) -> None:
        logged_out = logout()
        data = {"logged_out": logged_out}
        if use_json_output(ctx, json_output):
            print_json(data)
        elif logged_out:
            print_success("Logged out")
        else:
            click.echo("No active session")
