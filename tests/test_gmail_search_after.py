from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gw.cli import main
from gw.services.gmail import search_gmail_messages


def _gmail_service_returning_nothing() -> MagicMock:
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": []
    }
    return service


def _query_sent_to_gmail(service: MagicMock) -> str | None:
    call = service.users.return_value.messages.return_value.list.call_args
    return call.kwargs["q"]


def test_search_service_combines_query_with_after() -> None:
    service = _gmail_service_returning_nothing()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        search_gmail_messages(query="from:jose@x.com", after="7d")

    assert _query_sent_to_gmail(service) == "from:jose@x.com newer_than:7d"


def test_search_without_after_keeps_the_bare_query() -> None:
    service = _gmail_service_returning_nothing()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        search_gmail_messages(query="from:jose@x.com")

    assert _query_sent_to_gmail(service) == "from:jose@x.com"


def test_search_command_accepts_after_flag() -> None:
    service = _gmail_service_returning_nothing()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        result = CliRunner().invoke(main, ["gmail", "search", "invoice", "--after", "24h"])

    assert result.exit_code == 0, result.output
    assert _query_sent_to_gmail(service) == "invoice newer_than:24h"


def test_search_rejects_a_malformed_after_exactly_like_list_does() -> None:
    """--after is one contract; `search` must fail the same way `list` already fails."""
    service = _gmail_service_returning_nothing()
    runner = CliRunner()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        searched = runner.invoke(main, ["gmail", "search", "invoice", "--after", "tomorrow"])
        listed = runner.invoke(main, ["gmail", "list", "--after", "tomorrow"])

    assert searched.exit_code == listed.exit_code != 0
    assert isinstance(searched.exception, ValueError)
    assert str(searched.exception) == str(listed.exception)
    assert "6h, 24h, or 7d" in str(searched.exception)
