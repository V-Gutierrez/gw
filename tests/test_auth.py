from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import click
from click.testing import CliRunner

from gw.auth import (
    DEFAULT_SCOPES,
    build_service,
    load_credentials,
    login,
    logout,
    register_auth_commands,
    save_credentials,
    setup_auth,
)
from gw.errors import GwAuthError, GwConfigError


FAKE_TOKEN_DATA = {
    "token": "fake-access-token",
    "refresh_token": "fake-refresh-token",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake-client-id.apps.googleusercontent.com",
    "client_secret": "fake-client-secret",
    "scopes": DEFAULT_SCOPES,
}

FAKE_CLIENT_SECRETS = {
    "installed": {
        "client_id": "fake-client-id.apps.googleusercontent.com",
        "client_secret": "fake-client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


@pytest.fixture()
def token_dir(tmp_path: Path) -> Path:
    return tmp_path / "gw"


@pytest.fixture()
def token_path(token_dir: Path) -> Path:
    return token_dir / "token.json"


@pytest.fixture()
def secrets_path(token_dir: Path) -> Path:
    token_dir.mkdir(parents=True, exist_ok=True)
    p = token_dir / "client_secret.json"
    p.write_text(json.dumps(FAKE_CLIENT_SECRETS))
    return p


@pytest.fixture()
def _patch_config(token_path: Path, secrets_path: Path):
    mock_cfg = MagicMock()
    mock_cfg.token = token_path
    mock_cfg.credentials = secrets_path
    with patch("gw.auth._get_config", return_value=mock_cfg):
        yield mock_cfg


def _write_token(token_path: Path, data: dict | None = None) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(data or FAKE_TOKEN_DATA))


def _make_creds(valid: bool = True, expired: bool = False, refresh_token: str | None = "rt"):
    creds = MagicMock()
    creds.valid = valid
    creds.expired = expired
    creds.refresh_token = refresh_token
    creds.to_json.return_value = json.dumps(FAKE_TOKEN_DATA)
    return creds


class TestSaveCredentials:
    @pytest.mark.usefixtures("_patch_config")
    def test_creates_token_file(self, token_path: Path) -> None:
        creds = _make_creds()
        result = save_credentials(creds, token_path)

        assert result == token_path
        assert token_path.exists()
        saved = json.loads(token_path.read_text())
        assert saved["token"] == "fake-access-token"

    @pytest.mark.usefixtures("_patch_config")
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep_path = tmp_path / "a" / "b" / "token.json"
        creds = _make_creds()
        save_credentials(creds, deep_path)
        assert deep_path.exists()

    @pytest.mark.usefixtures("_patch_config")
    def test_uses_config_default(self, token_path: Path) -> None:
        creds = _make_creds()
        result = save_credentials(creds)
        assert result == token_path


class TestLoadCredentials:
    @pytest.mark.usefixtures("_patch_config")
    def test_returns_none_when_no_file(self, token_path: Path) -> None:
        assert load_credentials(token_path=token_path) is None

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.Credentials.from_authorized_user_file")
    def test_loads_valid_token(self, mock_from_file: MagicMock, token_path: Path) -> None:
        _write_token(token_path)
        mock_creds = _make_creds(valid=True)
        mock_from_file.return_value = mock_creds

        result = load_credentials(token_path=token_path)

        assert result is mock_creds
        mock_from_file.assert_called_once_with(str(token_path), DEFAULT_SCOPES)

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.Request")
    @patch("gw.auth.Credentials.from_authorized_user_file")
    def test_expired_token_refreshes_and_saves(
        self, mock_from_file: MagicMock, mock_request_cls: MagicMock, token_path: Path
    ) -> None:
        _write_token(token_path)
        mock_creds = _make_creds(valid=False, expired=True, refresh_token="rt")
        mock_from_file.return_value = mock_creds

        result = load_credentials(token_path=token_path)

        assert result is mock_creds
        mock_creds.refresh.assert_called_once_with(mock_request_cls())
        assert token_path.exists()

    @pytest.mark.usefixtures("_patch_config")
    def test_corrupt_token_returns_none(self, token_path: Path) -> None:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("NOT VALID JSON {{{")

        result = load_credentials(token_path=token_path)
        assert result is None

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.Credentials.from_authorized_user_file")
    def test_expired_no_refresh_token_returns_none(
        self, mock_from_file: MagicMock, token_path: Path
    ) -> None:
        _write_token(token_path)
        mock_creds = _make_creds(valid=False, expired=True, refresh_token=None)
        mock_from_file.return_value = mock_creds

        assert load_credentials(token_path=token_path) is None


class TestLogin:
    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.Credentials.from_authorized_user_file")
    def test_returns_existing_valid_creds(
        self, mock_from_file: MagicMock, token_path: Path, secrets_path: Path
    ) -> None:
        _write_token(token_path)
        mock_creds = _make_creds(valid=True)
        mock_from_file.return_value = mock_creds

        result = login(token_path=token_path, client_secrets=secrets_path)
        assert result is mock_creds

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.InstalledAppFlow")
    def test_runs_oauth_flow_and_saves(
        self, mock_flow_cls: MagicMock, token_path: Path, secrets_path: Path
    ) -> None:
        mock_creds = _make_creds(valid=True)
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        result = login(token_path=token_path, client_secrets=secrets_path)

        assert result is mock_creds
        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            str(secrets_path), DEFAULT_SCOPES
        )
        mock_flow.run_local_server.assert_called_once_with(port=0, open_browser=True)
        assert token_path.exists()

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.click.prompt", return_value="auth-code")
    @patch("gw.auth.click.echo")
    @patch("gw.auth.InstalledAppFlow")
    def test_runs_headless_oauth_flow_and_saves(
        self,
        mock_flow_cls: MagicMock,
        mock_echo: MagicMock,
        mock_prompt: MagicMock,
        token_path: Path,
        secrets_path: Path,
    ) -> None:
        mock_creds = _make_creds(valid=True)
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://example.com/auth", None)
        mock_flow.credentials = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        result = login(token_path=token_path, client_secrets=secrets_path, headless=True)

        assert result is mock_creds
        mock_flow.authorization_url.assert_called_once_with(prompt="consent")
        mock_echo.assert_called_once_with("https://example.com/auth")
        mock_prompt.assert_called_once_with("Paste the authorization code", type=str)
        mock_flow.fetch_token.assert_called_once_with(code="auth-code")
        mock_flow.run_local_server.assert_not_called()
        assert token_path.exists()


class TestLogout:
    @pytest.mark.usefixtures("_patch_config")
    def test_deletes_existing_token(self, token_path: Path) -> None:
        _write_token(token_path)
        assert logout(token_path=token_path) is True
        assert not token_path.exists()

    @pytest.mark.usefixtures("_patch_config")
    def test_returns_false_when_no_token(self, token_path: Path) -> None:
        assert logout(token_path=token_path) is False


class TestBuildService:
    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.build")
    def test_builds_with_given_creds(self, mock_build: MagicMock) -> None:
        creds = _make_creds(valid=True)
        build_service("gmail", "v1", credentials=creds)
        mock_build.assert_called_once_with("gmail", "v1", credentials=creds)

    @pytest.mark.usefixtures("_patch_config")
    def test_raises_when_not_authenticated(self, token_path: Path) -> None:
        with pytest.raises(GwAuthError, match="Not authenticated"):
            build_service("gmail", "v1")

    @pytest.mark.usefixtures("_patch_config")
    def test_login_raises_config_error_when_credentials_missing(self, token_path: Path) -> None:
        missing = token_path.parent / "missing.json"

        with pytest.raises(GwConfigError, match="Credentials file not found"):
            login(token_path=token_path, client_secrets=missing)


class TestSetupAuth:
    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.login")
    def test_uses_existing_credentials_and_runs_login(
        self, mock_login: MagicMock, secrets_path: Path
    ) -> None:
        creds = _make_creds(valid=True)
        creds.expiry = None
        creds.scopes = DEFAULT_SCOPES
        mock_login.return_value = creds

        result = setup_auth(login_headless=True)

        assert result["authenticated"] is True
        assert result["headless"] is True
        mock_login.assert_called_once_with(headless=True)

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.login")
    @patch("gw.auth.click.prompt")
    @patch("gw.auth.click.confirm", return_value=False)
    def test_builds_credentials_from_manual_input(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_login: MagicMock,
        token_path: Path,
    ) -> None:
        credentials_path = token_path.parent / "client_secret.json"
        if credentials_path.exists():
            credentials_path.unlink()

        creds = _make_creds(valid=True)
        creds.expiry = None
        creds.scopes = DEFAULT_SCOPES
        mock_login.return_value = creds
        mock_prompt.side_effect = ["client-id", "client-secret"]

        result = setup_auth(login_headless=False)

        assert result["authenticated"] is True
        saved = json.loads(credentials_path.read_text())
        assert saved["installed"]["client_id"] == "client-id"
        assert saved["installed"]["client_secret"] == "client-secret"
        mock_confirm.assert_called_once_with(
            "Do you want to use an existing credentials.json file?", default=True
        )
        mock_login.assert_called_once_with(headless=False)

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.login")
    @patch("gw.auth.click.prompt", return_value="/tmp/credentials.json")
    @patch("gw.auth.click.confirm", return_value=True)
    def test_reads_credentials_from_provided_path(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_login: MagicMock,
        token_path: Path,
        tmp_path: Path,
    ) -> None:
        credentials_path = token_path.parent / "client_secret.json"
        if credentials_path.exists():
            credentials_path.unlink()

        source = tmp_path / "imported-credentials.json"
        source.write_text(json.dumps(FAKE_CLIENT_SECRETS))
        mock_prompt.return_value = str(source)
        creds = _make_creds(valid=True)
        creds.expiry = None
        creds.scopes = DEFAULT_SCOPES
        mock_login.return_value = creds

        result = setup_auth(login_headless=True)

        assert result["authenticated"] is True
        saved = json.loads(credentials_path.read_text())
        assert saved["installed"]["client_id"] == FAKE_CLIENT_SECRETS["installed"]["client_id"]
        mock_confirm.assert_called_once_with(
            "Do you want to use an existing credentials.json file?", default=True
        )
        mock_prompt.assert_called_once_with("Path to credentials.json", type=str)
        mock_login.assert_called_once_with(headless=True)


class TestCLICommands:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    @pytest.fixture()
    def auth_group(self) -> click.Group:
        @click.group()
        def auth():
            pass

        register_auth_commands(auth)
        return auth

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.login")
    def test_login_command(self, mock_login: MagicMock, runner: CliRunner, auth_group) -> None:
        mock_login.return_value = _make_creds(valid=True)

        result = runner.invoke(auth_group, ["login"])

        assert result.exit_code == 0
        assert "Authenticated" in result.output
        mock_login.assert_called_once()

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.login")
    def test_login_command_headless(
        self, mock_login: MagicMock, runner: CliRunner, auth_group
    ) -> None:
        mock_login.return_value = _make_creds(valid=True)

        result = runner.invoke(auth_group, ["login", "--headless"])

        assert result.exit_code == 0
        mock_login.assert_called_once_with(headless=True)

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.load_credentials")
    def test_status_authenticated(
        self, mock_load: MagicMock, runner: CliRunner, auth_group
    ) -> None:
        mock_load.return_value = _make_creds(valid=True)

        result = runner.invoke(auth_group, ["status"])

        assert result.exit_code == 0
        assert "Authenticated" in result.output

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.load_credentials")
    def test_status_unauthenticated(
        self, mock_load: MagicMock, runner: CliRunner, auth_group
    ) -> None:
        mock_load.return_value = None

        result = runner.invoke(auth_group, ["status"])

        assert result.exit_code == 0
        assert "Not authenticated" in result.output

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.logout")
    def test_logout_command(self, mock_logout: MagicMock, runner: CliRunner, auth_group) -> None:
        mock_logout.return_value = True

        result = runner.invoke(auth_group, ["logout"])

        assert result.exit_code == 0
        assert "Logged out" in result.output

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.logout")
    def test_logout_no_session(
        self, mock_logout: MagicMock, runner: CliRunner, auth_group
    ) -> None:
        mock_logout.return_value = False

        result = runner.invoke(auth_group, ["logout"])

        assert result.exit_code == 0
        assert "No active session" in result.output

    @pytest.mark.usefixtures("_patch_config")
    @patch("gw.auth.setup_auth")
    def test_setup_command(self, mock_setup: MagicMock, runner: CliRunner, auth_group) -> None:
        mock_setup.return_value = {"authenticated": True, "headless": True}

        result = runner.invoke(auth_group, ["setup", "--headless", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.output)["authenticated"] is True
        mock_setup.assert_called_once_with(login_headless=True)
