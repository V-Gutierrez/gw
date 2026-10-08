from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from gw.auth import CHAT_SCOPES, DEFAULT_SCOPES
from gw.cli import main
from gw.config import GWConfig
from gw.errors import GwError
from gw.services import chat

runner = CliRunner()

ALL_CHAT = list(CHAT_SCOPES)


def _request(payload: dict) -> MagicMock:
    request = MagicMock()
    request.execute.return_value = payload
    return request


@pytest.fixture
def granted():
    with patch("gw.services.chat.granted_scopes", return_value=ALL_CHAT) as mock:
        yield mock


@pytest.fixture
def service():
    svc = MagicMock()
    with patch("gw.services.chat.build_service", return_value=svc):
        yield svc


# --- scopes -------------------------------------------------------------------------------


def test_chat_scopes_stay_out_of_the_default_set() -> None:
    """The personal @gmail.com profile has no Chat API; widening the default re-consents all."""
    assert CHAT_SCOPES
    for scope in CHAT_SCOPES:
        assert scope.startswith("https://www.googleapis.com/auth/chat.")
        assert scope not in DEFAULT_SCOPES


def test_chat_scopes_never_include_delete_or_admin() -> None:
    for scope in CHAT_SCOPES:
        assert ".delete" not in scope
        assert ".admin." not in scope
        assert ".import" not in scope


@patch("gw.auth.credential_status", return_value={"authenticated": True})
@patch("gw.auth.login")
def test_auth_login_chat_asks_default_plus_chat(mock_login: MagicMock, _status) -> None:
    mock_login.return_value = MagicMock()
    result = runner.invoke(main, ["auth", "login", "--chat", "--json"])

    assert result.exit_code == 0, result.output
    requested = mock_login.call_args.kwargs["scopes"]
    for scope in [*DEFAULT_SCOPES, *CHAT_SCOPES]:
        assert scope in requested


@patch("gw.auth.credential_status", return_value={"authenticated": True})
@patch("gw.auth.login")
def test_auth_login_chat_combines_with_admin(mock_login: MagicMock, _status) -> None:
    from gw.auth import ADMIN_SCOPES

    mock_login.return_value = MagicMock()
    result = runner.invoke(main, ["auth", "login", "--chat", "--admin", "--json"])

    assert result.exit_code == 0, result.output
    requested = mock_login.call_args.kwargs["scopes"]
    assert set(ADMIN_SCOPES) <= set(requested)
    assert set(CHAT_SCOPES) <= set(requested)


# --- scope gate ---------------------------------------------------------------------------


def test_command_without_chat_scope_names_the_fix_and_never_calls_google() -> None:
    with (
        patch("gw.services.chat.granted_scopes", return_value=list(DEFAULT_SCOPES)),
        patch("gw.services.chat.build_service") as build,
    ):
        result = runner.invoke(main, ["--profile", "controlspace", "chat", "spaces"])

    assert result.exit_code != 0
    assert build.call_count == 0
    assert "gw --profile controlspace auth login --chat" in str(result.exception)


def test_app_not_found_error_becomes_console_instruction(granted, service) -> None:
    service.spaces.return_value.list.return_value = MagicMock()
    with patch(
        "gw.services.chat.execute_google_request",
        side_effect=GwError(
            "Google API request failed (404): Google Chat app not found. To create a Chat app, "
            "you must turn on the Chat API and configure the app in the Google Cloud console."
        ),
    ):
        result = runner.invoke(main, ["chat", "spaces"])

    assert result.exit_code != 0
    assert "chat.googleapis.com" in str(result.exception)
    assert "Configuration" in str(result.exception)


# --- names --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AAAA123", "spaces/AAAA123"),
        ("spaces/AAAA123", "spaces/AAAA123"),
        (" AAAA ", "spaces/AAAA"),
    ],
)
def test_space_name_accepts_bare_id_or_full_name(raw: str, expected: str) -> None:
    assert chat.space_name(raw) == expected


def test_space_name_rejects_empty() -> None:
    with pytest.raises(GwError):
        chat.space_name("  ")


# --- spaces / messages / members ----------------------------------------------------------


def test_list_spaces_normalizes_and_paginates(granted, service) -> None:
    spaces_api = service.spaces.return_value
    spaces_api.list.side_effect = [
        _request(
            {
                "spaces": [{"name": "spaces/A", "displayName": "Tech", "spaceType": "SPACE"}],
                "nextPageToken": "t2",
            }
        ),
        _request({"spaces": [{"name": "spaces/B", "spaceType": "DIRECT_MESSAGE"}]}),
    ]

    data = chat.list_spaces(max_results=10, config=GWConfig())

    assert [s["name"] for s in data] == ["spaces/A", "spaces/B"]
    assert data[0]["display_name"] == "Tech"
    assert data[1]["type"] == "DIRECT_MESSAGE"
    assert spaces_api.list.call_args_list[1].kwargs["pageToken"] == "t2"


def test_list_spaces_stops_at_max(granted, service) -> None:
    service.spaces.return_value.list.side_effect = [
        _request({"spaces": [{"name": f"spaces/{i}"} for i in range(5)], "nextPageToken": "x"})
    ]
    data = chat.list_spaces(max_results=3, config=GWConfig())
    assert len(data) == 3
    assert service.spaces.return_value.list.call_count == 1


def test_list_messages_newest_first_and_filter(granted, service) -> None:
    messages_api = service.spaces.return_value.messages.return_value
    messages_api.list.return_value = _request(
        {
            "messages": [
                {
                    "name": "spaces/A/messages/m1",
                    "text": "olá",
                    "createTime": "2026-10-08T20:00:00Z",
                    "sender": {"name": "users/1", "displayName": "Ana", "type": "HUMAN"},
                    "thread": {"name": "spaces/A/threads/t1"},
                }
            ]
        }
    )

    data = chat.list_messages("A", max_results=5, after="2026-10-01", config=GWConfig())

    kwargs = messages_api.list.call_args.kwargs
    assert kwargs["parent"] == "spaces/A"
    assert kwargs["orderBy"] == "createTime desc"
    assert 'createTime > "2026-10-01T00:00:00Z"' in kwargs["filter"]
    assert data[0]["sender"] == "Ana"
    assert data[0]["thread"] == "spaces/A/threads/t1"


def test_read_message_by_full_name(granted, service) -> None:
    messages_api = service.spaces.return_value.messages.return_value
    messages_api.get.return_value = _request({"name": "spaces/A/messages/m1", "text": "x"})

    data = chat.get_message("spaces/A/messages/m1", config=GWConfig())

    assert messages_api.get.call_args.kwargs["name"] == "spaces/A/messages/m1"
    assert data["text"] == "x"


def test_find_dm_by_email(granted, service) -> None:
    spaces_api = service.spaces.return_value
    spaces_api.findDirectMessage.return_value = _request(
        {"name": "spaces/DM1", "spaceType": "DIRECT_MESSAGE"}
    )

    data = chat.find_direct_message("ana@controlspacestorage.com", config=GWConfig())

    assert spaces_api.findDirectMessage.call_args.kwargs["name"] == (
        "users/ana@controlspacestorage.com"
    )
    assert data["name"] == "spaces/DM1"


def test_list_members(granted, service) -> None:
    members_api = service.spaces.return_value.members.return_value
    members_api.list.return_value = _request(
        {
            "memberships": [
                {
                    "name": "spaces/A/members/1",
                    "role": "ROLE_MANAGER",
                    "state": "JOINED",
                    "member": {"name": "users/1", "displayName": "Ana", "type": "HUMAN"},
                }
            ]
        }
    )

    data = chat.list_members("A", config=GWConfig())

    assert members_api.list.call_args.kwargs["parent"] == "spaces/A"
    assert data[0]["display_name"] == "Ana"
    assert data[0]["role"] == "ROLE_MANAGER"


# --- send ---------------------------------------------------------------------------------


def test_send_posts_text(granted, service) -> None:
    messages_api = service.spaces.return_value.messages.return_value
    messages_api.create.return_value = _request(
        {"name": "spaces/A/messages/m9", "thread": {"name": "spaces/A/threads/t9"}}
    )

    result = chat.send_message("A", "bom dia", config=GWConfig())

    kwargs = messages_api.create.call_args.kwargs
    assert kwargs["parent"] == "spaces/A"
    assert kwargs["body"] == {"text": "bom dia"}
    assert "messageReplyOption" not in kwargs
    assert result["name"] == "spaces/A/messages/m9"


def test_send_into_thread_replies_there(granted, service) -> None:
    messages_api = service.spaces.return_value.messages.return_value
    messages_api.create.return_value = _request({"name": "spaces/A/messages/m9"})

    chat.send_message("A", "resposta", thread="spaces/A/threads/t1", config=GWConfig())

    kwargs = messages_api.create.call_args.kwargs
    assert kwargs["body"]["thread"] == {"name": "spaces/A/threads/t1"}
    assert kwargs["messageReplyOption"] == "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"


def test_send_rejects_empty_text(granted, service) -> None:
    with pytest.raises(GwError):
        chat.send_message("A", "   ", config=GWConfig())
    assert service.spaces.return_value.messages.return_value.create.call_count == 0


def test_cli_send_dry_run_never_sends(granted, service) -> None:
    result = runner.invoke(
        main, ["chat", "send", "A", "olá equipa", "--thread", "spaces/A/threads/t1", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert service.spaces.return_value.messages.return_value.create.call_count == 0
    assert "spaces/A" in result.output
    assert "olá equipa" in result.output
    assert "spaces/A/threads/t1" in result.output


def test_cli_send_dry_run_json(granted, service) -> None:
    result = runner.invoke(main, ["chat", "send", "A", "olá", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"dry_run": True, "space": "spaces/A", "text": "olá", "thread": None}


def test_cli_send_body_file(granted, service, tmp_path) -> None:
    body = tmp_path / "msg.txt"
    body.write_text("linha 1\nlinha 2 com $HOME e `aspas`\n", encoding="utf-8")
    messages_api = service.spaces.return_value.messages.return_value
    messages_api.create.return_value = _request({"name": "spaces/A/messages/m1"})

    result = runner.invoke(main, ["chat", "send", "A", "--body-file", str(body), "--json"])

    assert result.exit_code == 0, result.output
    assert messages_api.create.call_args.kwargs["body"]["text"] == (
        "linha 1\nlinha 2 com $HOME e `aspas`"
    )


def test_cli_send_text_and_body_file_conflict(granted, service, tmp_path) -> None:
    body = tmp_path / "msg.txt"
    body.write_text("x", encoding="utf-8")
    result = runner.invoke(main, ["chat", "send", "A", "y", "--body-file", str(body)])
    assert result.exit_code != 0


# --- create -------------------------------------------------------------------------------


def test_create_space_with_members(granted, service) -> None:
    spaces_api = service.spaces.return_value
    spaces_api.setup.return_value = _request({"name": "spaces/NEW", "displayName": "Ops"})

    data = chat.create_space(
        "Ops", members=["a@x.com", "b@x.com"], description="sala de ops", config=GWConfig()
    )

    body = spaces_api.setup.call_args.kwargs["body"]
    assert body["space"]["spaceType"] == "SPACE"
    assert body["space"]["displayName"] == "Ops"
    assert body["space"]["spaceDetails"] == {"description": "sala de ops"}
    assert body["memberships"] == [
        {"member": {"name": "users/a@x.com", "type": "HUMAN"}},
        {"member": {"name": "users/b@x.com", "type": "HUMAN"}},
    ]
    assert data["name"] == "spaces/NEW"


def test_cli_create_dry_run_never_creates(granted, service) -> None:
    result = runner.invoke(main, ["chat", "create", "Ops", "--member", "a@x.com", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert service.spaces.return_value.setup.call_count == 0
    assert "a@x.com" in result.output


# --- doctor -------------------------------------------------------------------------------


def test_doctor_skips_chat_without_scope_and_stays_green() -> None:
    from gw.doctor import run_doctor

    with (
        patch("gw.doctor.credential_status", return_value={"authenticated": True}),
        patch("gw.doctor._probe_api"),
        patch("gw.doctor.granted_scopes", return_value=list(DEFAULT_SCOPES)),
        patch("gw.config.GWConfig.credentials", MagicMock(exists=lambda: True)),
        patch("gw.config.GWConfig.token", MagicMock(exists=lambda: True)),
    ):
        report = run_doctor(GWConfig())

    checks = {c["name"]: c for c in report["checks"]}
    assert checks["api_chat"]["status"] == "skipped"
    assert "auth login --chat" in checks["api_chat"]["detail"]
    assert report["ok"] is True


def test_doctor_probes_chat_when_scope_granted() -> None:
    from gw.doctor import run_doctor

    probed: list[str] = []
    with (
        patch("gw.doctor.credential_status", return_value={"authenticated": True}),
        patch("gw.doctor._probe_api", side_effect=lambda api, cfg: probed.append(api)),
        patch("gw.doctor.granted_scopes", return_value=[*DEFAULT_SCOPES, *CHAT_SCOPES]),
    ):
        report = run_doctor(GWConfig())

    assert "chat" in probed
    checks = {c["name"]: c for c in report["checks"]}
    assert checks["api_chat"]["status"] == "ok"
