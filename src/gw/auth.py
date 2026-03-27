from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, cast

import click
import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gw.config import GWConfig, load_config
from gw.errors import GwAuthError, GwConfigError, GwError
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
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1.0


def _get_config(profile: str | None = None) -> GWConfig:
    try:
        return load_config(profile=profile)
    except ValueError as exc:
        raise GwConfigError(str(exc)) from exc


def _retryable_http_error(exc: HttpError) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {429, 500, 502, 503, 504}:
        return True
    if status != 403:
        return False

    reasons: set[str] = set()
    details = getattr(exc, "error_details", None)
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict):
                reason = detail.get("reason")
                if isinstance(reason, str):
                    reasons.add(reason)

    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                nested_errors = error_payload.get("errors", [])
                if isinstance(nested_errors, list):
                    for item in nested_errors:
                        if isinstance(item, dict):
                            reason = item.get("reason")
                            if isinstance(reason, str):
                                reasons.add(reason)

    return bool(reasons & {"rateLimitExceeded", "userRateLimitExceeded"})


def _retry_after_seconds(exc: HttpError) -> float | None:
    response = getattr(exc, "resp", None)
    if response is None:
        return None

    header_value = None
    if hasattr(response, "get"):
        header_value = response.get("retry-after") or response.get("Retry-After")
    elif hasattr(response, "__getitem__"):
        try:
            header_value = response["retry-after"]
        except KeyError:
            try:
                header_value = response["Retry-After"]
            except KeyError:
                header_value = None

    if header_value is None:
        return None

    try:
        seconds = float(header_value)
    except (TypeError, ValueError):
        return None
    return max(seconds, 0.0)


def _http_error_message(exc: HttpError) -> str:
    status = getattr(exc, "status_code", None)
    message = getattr(exc, "reason", None) or str(exc)
    if status is None:
        return f"Google API request failed: {message}"
    return f"Google API request failed ({status}): {message}"


def execute_google_request(request: Any, *, attempts: int = RETRY_ATTEMPTS) -> Any:
    for attempt in range(1, attempts + 1):
        try:
            return request.execute(num_retries=0)
        except RefreshError as exc:
            raise GwAuthError("Authentication refresh failed. Run `gw auth login` again.") from exc
        except TransportError as exc:
            if attempt == attempts:
                raise GwError(f"Network error while calling Google API: {exc}") from exc
            time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
        except HttpError as exc:
            status = getattr(exc, "status_code", None)
            if status == 401:
                raise GwAuthError("Authentication expired. Run `gw auth login` again.") from exc
            if attempt == attempts or not _retryable_http_error(exc):
                raise GwError(_http_error_message(exc)) from exc
            retry_after = _retry_after_seconds(exc)
            delay = (
                retry_after
                if retry_after is not None
                else RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            )
            time.sleep(delay)

    raise GwError("Google API request failed after retries.")


def save_credentials(
    creds: Credentials,
    path: Path | None = None,
    config: GWConfig | None = None,
) -> Path:
    token_path = path or (config or _get_config()).token
    atomic_write(token_path, creds.to_json())
    return token_path


def save_client_secrets(
    data: dict[str, Any],
    path: Path | None = None,
    config: GWConfig | None = None,
) -> Path:
    config = config or _get_config()
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
    config: GWConfig | None = None,
) -> Credentials | None:
    active_config = config or _get_config()
    resolved = token_path or active_config.token
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
        save_credentials(creds, resolved, config=active_config)
        return creds

    return None


def login(
    scopes: list[str] | None = None,
    client_secrets: Path | None = None,
    token_path: Path | None = None,
    headless: bool = False,
    config: GWConfig | None = None,
) -> Credentials:
    target_scopes = scopes or DEFAULT_SCOPES
    cfg = config or _get_config()
    secrets = client_secrets or cfg.credentials
    resolved_token = token_path or cfg.token

    if not secrets.exists():
        raise GwConfigError(f"Credentials file not found: {secrets}")

    existing = load_credentials(target_scopes, resolved_token, config=cfg)
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
    save_credentials(creds, resolved_token, config=cfg)
    return creds


def logout(token_path: Path | None = None, config: GWConfig | None = None) -> bool:
    resolved = token_path or (config or _get_config()).token
    if resolved.exists():
        resolved.unlink()
        return True
    return False


def credential_status(
    credentials: Credentials | None = None,
    config: GWConfig | None = None,
) -> dict[str, Any]:
    cfg = config or _get_config()
    creds = credentials or load_credentials(config=cfg)
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
    config: GWConfig | None = None,
):
    active_config = config or _get_config()
    creds = credentials or load_credentials(scopes, config=active_config)
    if creds is None:
        raise GwAuthError("Not authenticated. Run `gw auth login` first.")
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=active_config.timeout_seconds))
    return build(api, version, http=http, cache_discovery=False)


def setup_auth(*, login_headless: bool = False, config: GWConfig | None = None) -> dict[str, Any]:
    active_config = config or _get_config()
    credentials_path = active_config.credentials

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

        saved_path = save_client_secrets(data, credentials_path, config=active_config)
        print_success(f"Saved credentials to {saved_path}")

    creds = login(headless=login_headless, config=active_config)
    status = credential_status(creds, config=active_config)
    status["headless"] = login_headless
    return status


def register_auth_commands(auth_group: click.Group) -> None:
    @auth_group.command("login")
    @click.option("--headless", is_flag=True, help="Run OAuth flow without opening a browser.")
    @json_option
    @click.pass_context
    def login_cmd(ctx: click.Context, headless: bool, json_output: bool | None) -> None:
        config = cast(GWConfig, ctx.obj["config"])
        creds = login(headless=headless, config=config)
        status = credential_status(creds, config=config)
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
        config = cast(GWConfig, ctx.obj["config"])
        status = setup_auth(login_headless=headless, config=config)
        if use_json_output(ctx, json_output):
            print_json(status)
        else:
            print_success("Setup complete")

    @auth_group.command("status")
    @json_option
    @click.pass_context
    def status_cmd(ctx: click.Context, json_output: bool | None) -> None:
        config = cast(GWConfig, ctx.obj["config"])
        status = credential_status(config=config)
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
        config = cast(GWConfig, ctx.obj["config"])
        logged_out = logout(config=config)
        data = {"logged_out": logged_out}
        if use_json_output(ctx, json_output):
            print_json(data)
        elif logged_out:
            print_success("Logged out")
        else:
            click.echo("No active session")
