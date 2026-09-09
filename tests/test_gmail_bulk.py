from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gw.cli import main
from gw.services.gmail import (
    bulk_modify_gmail_messages,
    get_gmail_history,
    get_gmail_profile,
    modify_gmail_thread,
    trash_gmail_thread,
    untrash_gmail_message,
    untrash_gmail_thread,
)


def _service_with_labels() -> MagicMock:
    service = MagicMock()
    users = service.users.return_value
    users.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": "Label_7", "name": "Seguros"}]
    }
    users.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "m1"}, {"id": "m2"}]
    }
    users.threads.return_value.modify.return_value.execute.return_value = {
        "id": "t1",
        "messages": [{"id": "m1"}],
    }
    users.threads.return_value.trash.return_value.execute.return_value = {"id": "t1"}
    users.threads.return_value.untrash.return_value.execute.return_value = {"id": "t1"}
    users.messages.return_value.untrash.return_value.execute.return_value = {"id": "m1"}
    users.getProfile.return_value.execute.return_value = {
        "emailAddress": "victor@example.com",
        "messagesTotal": 1234,
        "threadsTotal": 567,
        "historyId": "99",
    }
    users.history.return_value.list.return_value.execute.return_value = {
        "history": [{"id": "100", "messagesAdded": [{"message": {"id": "m3"}}]}],
        "historyId": "101",
    }
    return service


# ---------------- threads ----------------


def test_thread_modify_resolves_label_names_to_ids() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        modify_gmail_thread("t1", add_labels=["Seguros"], remove_labels=["UNREAD"])

    kwargs = service.users.return_value.threads.return_value.modify.call_args.kwargs
    assert kwargs["id"] == "t1"
    assert kwargs["body"] == {"addLabelIds": ["Label_7"], "removeLabelIds": ["UNREAD"]}


def test_thread_trash_and_untrash_hit_the_thread_endpoints() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        trash_gmail_thread("t1")
        untrash_gmail_thread("t1")

    threads = service.users.return_value.threads.return_value
    assert threads.trash.call_args.kwargs["id"] == "t1"
    assert threads.untrash.call_args.kwargs["id"] == "t1"


def test_untrash_message_restores_a_single_message() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        untrash_gmail_message("m1")

    assert service.users.return_value.messages.return_value.untrash.call_args.kwargs["id"] == "m1"


# ---------------- bulk ----------------


def test_bulk_uses_one_batch_call_not_one_per_message() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = bulk_modify_gmail_messages(query="from:x@y.com", mark_read=True)

    messages = service.users.return_value.messages.return_value
    assert messages.batchModify.call_count == 1
    assert messages.modify.call_count == 0
    kwargs = messages.batchModify.call_args.kwargs
    assert kwargs["body"]["ids"] == ["m1", "m2"]
    assert kwargs["body"]["removeLabelIds"] == ["UNREAD"]
    assert result["count"] == 2


def test_bulk_archive_and_label_combine_in_one_body() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        bulk_modify_gmail_messages(query="older_than:1y", archive=True, add_label="Seguros")

    body = service.users.return_value.messages.return_value.batchModify.call_args.kwargs["body"]
    assert body["addLabelIds"] == ["Label_7"]
    assert body["removeLabelIds"] == ["INBOX"]


def test_bulk_with_no_matches_does_not_call_the_api() -> None:
    service = _service_with_labels()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {}
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = bulk_modify_gmail_messages(query="nada", mark_read=True)

    assert result["count"] == 0
    assert service.users.return_value.messages.return_value.batchModify.call_count == 0


def test_bulk_without_any_action_is_rejected() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = CliRunner().invoke(main, ["gmail", "bulk", "--query", "x", "--yes"])

    assert result.exit_code != 0


def test_bulk_command_requires_confirmation_without_yes() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = CliRunner().invoke(
            main, ["gmail", "bulk", "--query", "x", "--mark-read"], input="n\n"
        )

    assert result.exit_code != 0
    assert service.users.return_value.messages.return_value.batchModify.call_count == 0


# ---------------- profile / history ----------------


def test_profile_returns_mailbox_totals() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        data = get_gmail_profile()

    assert data["email"] == "victor@example.com"
    assert data["messages_total"] == 1234
    assert data["history_id"] == "99"


def test_history_lists_changes_since_a_history_id() -> None:
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        data = get_gmail_history(start_history_id="99")

    kwargs = service.users.return_value.history.return_value.list.call_args.kwargs
    assert kwargs["startHistoryId"] == "99"
    assert data["history_id"] == "101"
    assert data["changes"][0]["id"] == "100"


def test_doctor_now_actually_calls_the_api() -> None:
    """A local-only doctor cannot tell you auth works; it must reach Google."""
    service = _service_with_labels()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = CliRunner().invoke(main, ["--json", "doctor"])

    assert service.users.return_value.getProfile.call_count == 1
    assert "api_reachable" in result.output


def test_gmail_thread_and_profile_commands_are_wired() -> None:
    service = _service_with_labels()
    runner = CliRunner()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        assert runner.invoke(main, ["gmail", "thread-trash", "t1", "--yes"]).exit_code == 0
        assert runner.invoke(main, ["gmail", "thread-untrash", "t1"]).exit_code == 0
        assert runner.invoke(main, ["gmail", "thread-archive", "t1"]).exit_code == 0
        assert runner.invoke(main, ["gmail", "untrash", "m1"]).exit_code == 0
        assert runner.invoke(main, ["gmail", "profile"]).exit_code == 0
        assert runner.invoke(main, ["gmail", "history", "--since", "99"]).exit_code == 0
