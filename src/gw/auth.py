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
from gw.errors import GwAuthError, GwConfigError
from gw.output import (
    json_option,
    print_info,
    print_json,
    print_success,
    print_warning,
    use_json_output,
)
from gw.utils import atomic_write

DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def _get_config() -> GWConfig:
    try:
        return load_config()
    except ValueError as exc:
        raise GwConfigError(str(exc)) from exc


def save_credentials(creds: Credentials, path: Path | None = None) -> Path:
    token_path = path or _get_config().token
    atomic_write(token_path, creds.to_json())
    return token_path


def save_client_secrets(data: dict[str, Any], path: Path | None = None) -> Path:
    config = _get_config()
    credentials_path = path or config.credentials
    atomic_write(credentials_path, json.dumps(data, indent=2))
    return credentials_path


def _validate_client_secrets(data: dict[str, Any]) -> dict[str, Any]:
    installed = data.get("installed")
    if not isinstance(installed, dict):
        raise GwConfigError("Credentials file must contain an 'installed' OAuth client.")

    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")
    if not client_id or not client_secret:
        raise GwConfigError("Credentials file is missing client_id or client_secret.")

    normalized = dict(installed)
    normalized.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    normalized.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    normalized.setdefault("redirect_uris", ["http://localhost"])
    return {"installed": normalized}


def _read_client_secrets(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GwConfigError(f"Credentials file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GwConfigError(f"Credentials file is not valid JSON: {path}") from exc

    if not isinstance(data, dict):
        raise GwConfigError("Credentials file must be a JSON object.")
    return _validate_client_secrets(data)


def _manual_client_secrets(client_id: str, client_secret: str) -> dict[str, Any]:
    return _validate_client_secrets(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    )


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
    headless: bool = False,
) -> Credentials:
    target_scopes = scopes or DEFAULT_SCOPES
    cfg = _get_config()
    secrets = client_secrets or cfg.credentials
    resolved_token = token_path or cfg.token

    if not secrets.exists():
        raise GwConfigError(f"Credentials file not found: {secrets}")

    existing = load_credentials(target_scopes, resolved_token)
    if existing and existing.valid:
        return existing

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), target_scopes)
    if headless:
        auth_url, _ = flow.authorization_url(prompt="consent")
        click.echo(auth_url)
        code = click.prompt("Paste the authorization code", type=str).strip()
        flow.fetch_token(code=code)
        creds = cast(Credentials, flow.credentials)
    else:
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
        raise GwAuthError("Not authenticated. Run `gw auth login` first.")
    return build(api, version, credentials=creds)


def setup_auth(*, login_headless: bool = False) -> dict[str, Any]:
    config = _get_config()
    credentials_path = config.credentials

    if credentials_path.exists():
        print_info(f"Using existing credentials file: {credentials_path}")
    else:
        print_warning("Credentials file not found.")
        print_info(
            "Create an OAuth Desktop app in Google Cloud Console if you do not have one yet."
        )
        print_info(
            "You can paste a credentials.json path or enter client_id/client_secret manually."
        )

        use_path = click.confirm(
            "Do you want to use an existing credentials.json file?", default=True
        )
        if use_path:
            source_path = Path(click.prompt("Path to credentials.json", type=str)).expanduser()
            data = _read_client_secrets(source_path)
        else:
            client_id = click.prompt("Google OAuth client_id", type=str).strip()
            client_secret = click.prompt(
                "Google OAuth client_secret", type=str, hide_input=True
            ).strip()
            data = _manual_client_secrets(client_id, client_secret)

        saved_path = save_client_secrets(data, credentials_path)
        print_success(f"Saved credentials to {saved_path}")

    creds = login(headless=login_headless)
    status = credential_status(creds)
    status["headless"] = login_headless
    return status


def register_auth_commands(auth_group: click.Group) -> None:
    @auth_group.command("login")
    @click.option("--headless", is_flag=True, help="Run OAuth flow without opening a browser.")
    @json_option
    @click.pass_context
    def login_cmd(ctx: click.Context, headless: bool, json_output: bool | None) -> None:
        creds = login(headless=headless)
        status = credential_status(creds)
        status["headless"] = headless
        if use_json_output(ctx, json_output):
            print_json(status)
        else:
            print_success("Authenticated")

    @auth_group.command("setup")
    @click.option("--headless", is_flag=True, help="Run login step without opening a browser.")
    @json_option
    @click.pass_context
    def setup_cmd(ctx: click.Context, headless: bool, json_output: bool | None) -> None:
        status = setup_auth(login_headless=headless)
        if use_json_output(ctx, json_output):
            print_json(status)
        else:
            print_success("Setup complete")

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
