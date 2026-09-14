"""Account signature: read from Gmail settings, attached to everything gw sends.

The failure this covers: a signature configured in Gmail's web settings never showed
up in mail sent through gw, because the API sends the raw MIME untouched and gw never
asked for the signature.
"""

from __future__ import annotations

import base64
import json
import time
from email import message_from_bytes
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from gw.cli import main
from gw.config import GWConfig, load_config
from gw.services.gmail import (
    create_gmail_draft,
    forward_gmail_message,
    get_account_signature,
    send_gmail_message,
    update_gmail_draft,
)
from gw.signature import (
    AccountSignature,
    append_signature,
    html_to_text,
    pick_send_as,
    resolve_signature,
    signature_cache_path,
    signature_enabled,
    strip_signature,
)

runner = CliRunner()

SIG_HTML = (
    '<div dir="ltr"><div><br>Cumprimentos,&nbsp;<br><br></div>'
    '<div><font face="arial black, sans-serif">Victor Gutierrez</font>'
    "<div><b>Head of Technology</b></div>"
    '<div><a href="mailto:victor@example.com">victor@example.com</a></div>'
    '<div><img width="200" src="https://example.com/logo.png"></div>'
    '<div><a href="http://example.com/">controlspacestorage.com</a></div>'
    "</div></div>"
)

SIG_TEXT = (
    "Cumprimentos,\nVictor Gutierrez\nHead of Technology\nvictor@example.com\n"
    "controlspacestorage.com"
)


def _config(tmp_path: Path, **overrides: Any) -> GWConfig:
    values: dict[str, Any] = {
        "profile": "test",
        "signature_cache_path": str(tmp_path / "signature.json"),
    }
    values.update(overrides)
    return GWConfig(**values)


def _send_as(html: str, email: str = "victor@example.com", default: bool = True) -> dict[str, Any]:
    return {"sendAs": [{"sendAsEmail": email, "isDefault": default, "signature": html}]}


def _send_as_route(service: MagicMock) -> MagicMock:
    """The ``settings.sendAs.list`` resource, where the signature comes from.

    Returned one level above the request mock on purpose: ``call_count`` lives on the
    resource, while ``.return_value.execute`` is the request itself.
    """
    users = service.users.return_value
    return users.settings.return_value.sendAs.return_value.list


def _service(html: str = SIG_HTML, email: str = "victor@example.com") -> MagicMock:
    service = MagicMock()
    users = service.users.return_value
    _send_as_route(service).return_value.execute.return_value = _send_as(html, email)
    users.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1",
        "threadId": "thr-1",
    }
    users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft-1",
        "message": {"id": "msg-1"},
    }
    return service


def _raw(message: Message) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def _sent_message(service: MagicMock) -> Message:
    raw = service.users.return_value.messages.return_value.send.call_args.kwargs["body"]["raw"]
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def _bodies(message: Message) -> dict[str, str]:
    return {
        part.get_content_type(): part.get_payload(decode=True).decode("utf-8", "replace")
        for part in message.walk()
        if part.get_content_maintype() == "text"
    }


def _write_cache(
    tmp_path: Path, *, html: str, age_seconds: int = 0, email: str = "a@b.com"
) -> Path:
    path = tmp_path / "signature.json"
    path.write_text(
        json.dumps(
            {
                "email": email,
                "signature": html,
                "fetched_at": int(time.time()) - age_seconds,
                "source": "api",
            }
        ),
        encoding="utf-8",
    )
    return path


# ---------------- html -> text ----------------


def test_html_to_text_keeps_the_contact_block_and_drops_bare_images() -> None:
    assert html_to_text(SIG_HTML) == SIG_TEXT


def test_html_to_text_uses_alt_text_when_the_image_has_one() -> None:
    text = html_to_text('<div>Oi</div><div><img alt="Armazéns desde 1m²" src="x.png"></div>')

    assert text.splitlines() == ["Oi", "Armazéns desde 1m²"]


def test_html_to_text_is_empty_for_empty_markup() -> None:
    assert html_to_text("") == ""


# ---------------- assembling the body ----------------


def test_append_signature_keeps_the_body_and_adds_both_flavours() -> None:
    plain, html = append_signature("Segue o relatório.", AccountSignature("v@x.com", SIG_HTML))

    assert plain == f"Segue o relatório.\n\n{SIG_TEXT}"
    assert html.startswith('<div dir="ltr">Segue o relatório.</div>')
    assert SIG_HTML in html


def test_append_signature_escapes_html_in_the_body() -> None:
    _, html = append_signature("<script>alert(1)</script>", AccountSignature("v@x.com", SIG_HTML))

    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_strip_signature_removes_only_an_appended_one() -> None:
    signature = AccountSignature("v@x.com", SIG_HTML)

    assert strip_signature(f"corpo\n\n{SIG_TEXT}", signature) == "corpo"
    assert strip_signature("corpo", signature) == "corpo"


# ---------------- resolving ----------------


def test_resolve_reads_gmail_settings_and_caches(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = _service()

    signature = resolve_signature(config, service=service)

    assert signature is not None
    assert signature.email == "victor@example.com"
    assert signature.html == SIG_HTML
    assert signature.source == "api"
    assert signature_cache_path(config).is_file()
    assert json.loads(signature_cache_path(config).read_text())["signature"] == SIG_HTML


def test_resolve_serves_the_second_call_from_the_cache(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = _service()
    resolve_signature(config, service=service)

    from_cache = resolve_signature(config, service=service)

    assert _send_as_route(service).call_count == 1
    assert from_cache is not None
    assert from_cache.source == "cache"


def test_resolve_refreshes_a_cache_past_its_ttl(tmp_path: Path) -> None:
    _write_cache(tmp_path, html="<div>velha</div>", age_seconds=8 * 24 * 60 * 60)
    config = _config(tmp_path)

    signature = resolve_signature(config, service=_service())

    assert signature is not None
    assert signature.html == SIG_HTML
    assert signature.source == "api"


def test_resolve_falls_back_to_a_stale_cache_when_the_api_fails(tmp_path: Path) -> None:
    _write_cache(tmp_path, html="<div>velha</div>", age_seconds=30 * 24 * 60 * 60)
    service = _service()
    _send_as_route(service).return_value.execute.side_effect = RuntimeError("offline")

    signature = resolve_signature(_config(tmp_path), service=service)

    assert signature is not None
    assert signature.html == "<div>velha</div>"
    assert signature.source == "cache"


def test_resolve_returns_none_when_the_api_fails_without_a_cache(tmp_path: Path) -> None:
    service = _service()
    _send_as_route(service).return_value.execute.side_effect = RuntimeError("offline")

    assert resolve_signature(_config(tmp_path), service=service) is None


def test_resolve_returns_none_for_an_account_without_a_signature(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert resolve_signature(config, service=_service(html="")) is None
    # The empty result is cached too, so a signature-less account is asked once.
    assert json.loads(signature_cache_path(config).read_text())["signature"] == ""


def test_resolve_remembers_that_the_account_has_no_signature(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = _service(html="")
    resolve_signature(config, service=service)

    assert resolve_signature(config, service=service) is None
    assert _send_as_route(service).call_count == 1


def test_resolve_needs_a_config_so_library_calls_stay_untouched(tmp_path: Path) -> None:
    assert resolve_signature(None, service=_service()) is None


def test_resolve_is_off_when_the_config_disables_it(tmp_path: Path) -> None:
    service = _service()

    assert resolve_signature(_config(tmp_path, signature=False), service=service) is None
    assert _send_as_route(service).call_count == 0


def test_command_line_override_beats_the_config(tmp_path: Path) -> None:
    assert (
        resolve_signature(_config(tmp_path, signature=False), service=_service(), override=True)
        is not None
    )
    assert (
        resolve_signature(_config(tmp_path, signature=True), service=_service(), override=False)
        is None
    )


def test_signature_enabled_precedence(tmp_path: Path) -> None:
    assert signature_enabled(_config(tmp_path), None) is True
    assert signature_enabled(_config(tmp_path, signature=False), None) is False
    assert signature_enabled(_config(tmp_path, signature=False), True) is True
    assert signature_enabled(None) is False


def test_pick_send_as_prefers_the_named_address() -> None:
    entries: list[object] = [
        {"sendAsEmail": "alias@x.com", "isDefault": False, "signature": "alias"},
        {"sendAsEmail": "main@x.com", "isDefault": True, "signature": "main"},
    ]

    assert pick_send_as(entries, "alias@x.com") == entries[0]
    assert pick_send_as(entries, None) == entries[1]
    assert pick_send_as(entries, "nobody@x.com") is None
    assert pick_send_as([], None) is None


# ---------------- the MIME that goes out ----------------


def test_send_attaches_the_signature_as_multipart_alternative(tmp_path: Path) -> None:
    service = _service()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        send_gmail_message("dest@x.com", "Assunto", "corpo", config=_config(tmp_path))

    message = _sent_message(service)
    assert message.get_content_type() == "multipart/alternative"
    bodies = _bodies(message)
    assert bodies["text/plain"] == f"corpo\n\n{SIG_TEXT}"
    assert SIG_HTML in bodies["text/html"]


def test_send_without_a_signature_stays_a_single_text_part(tmp_path: Path) -> None:
    service = _service(html="")
    with patch("gw.services.gmail._gmail_service", return_value=service):
        send_gmail_message("dest@x.com", "Assunto", "corpo", config=_config(tmp_path))

    message = _sent_message(service)
    assert message.get_content_type() == "text/plain"
    assert not message.is_multipart()


def test_send_calls_without_config_keep_the_old_shape() -> None:
    service = _service()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        send_gmail_message("dest@x.com", "Assunto", "corpo")

    message = _sent_message(service)
    assert message.get_content_type() == "text/plain"
    assert message.get_payload() == "corpo"
    assert _send_as_route(service).call_count == 0


def test_no_signature_flag_sends_without_it(tmp_path: Path) -> None:
    service = _service()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        send_gmail_message(
            "dest@x.com", "Assunto", "corpo", signature=False, config=_config(tmp_path)
        )

    message = _sent_message(service)
    assert message.get_content_type() == "text/plain"
    assert _send_as_route(service).call_count == 0


def test_attachments_wrap_the_alternative_inside_mixed(tmp_path: Path) -> None:
    service = _service()
    pdf = tmp_path / "proposta.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("gw.services.gmail._gmail_service", return_value=service):
        send_gmail_message(
            "dest@x.com",
            "Assunto",
            "corpo",
            attachments=[pdf],
            config=_config(tmp_path / "cfg"),
        )

    message = _sent_message(service)
    assert message.get_content_type() == "multipart/mixed"
    assert [part.get_content_type() for part in message.walk()] == [
        "multipart/mixed",
        "multipart/alternative",
        "text/plain",
        "text/html",
        "application/pdf",
    ]


def test_draft_carries_the_signature(tmp_path: Path) -> None:
    service = _service()
    with patch("gw.services.gmail._gmail_service", return_value=service):
        create_gmail_draft("dest@x.com", "Assunto", "corpo", config=_config(tmp_path))

    body = service.users.return_value.drafts.return_value.create.call_args.kwargs["body"]
    message = message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]))
    assert SIG_HTML in _bodies(message)["text/html"]


def test_forward_carries_the_signature(tmp_path: Path) -> None:
    service = _service()
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "orig",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Assunto"},
                {"name": "From", "value": "quem@x.com"},
                {"name": "To", "value": "eu@x.com"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"antigo").decode()},
        },
    }

    with patch("gw.services.gmail._gmail_service", return_value=service):
        forward_gmail_message("orig", "dest@x.com", config=_config(tmp_path))

    forwarded = _sent_message(service)
    assert forwarded.get_content_type() == "multipart/alternative"
    assert SIG_HTML in _bodies(forwarded)["text/html"]


def test_editing_a_draft_does_not_double_the_signature(tmp_path: Path) -> None:
    config = _config(tmp_path)
    resolve_signature(config, service=_service())  # seed the cache the edit will read

    existing = Message()
    existing["To"] = "a@x.com"
    existing["Subject"] = "Assunto"
    existing.set_payload(f"corpo\n\n{SIG_TEXT}")

    service = _service()
    drafts = service.users.return_value.drafts.return_value
    drafts.get.return_value.execute.return_value = {"id": "d1", "message": {"raw": _raw(existing)}}
    drafts.update.return_value.execute.return_value = {"id": "d1", "message": {"id": "m2"}}

    with patch("gw.services.gmail._gmail_service", return_value=service):
        update_gmail_draft("d1", subject="Novo", config=config)

    raw = drafts.update.call_args.kwargs["body"]["message"]["raw"]
    bodies = _bodies(message_from_bytes(base64.urlsafe_b64decode(raw)))
    assert bodies["text/plain"].count("Cumprimentos,") == 1
    assert bodies["text/html"].count("Cumprimentos,") == 1


def test_get_account_signature_ignores_the_config_switch(tmp_path: Path) -> None:
    with patch("gw.signature.build_service", return_value=_service()):
        signature = get_account_signature(_config(tmp_path, signature=False))

    assert signature is not None
    assert signature.html == SIG_HTML


# ---------------- CLI ----------------


def test_cli_signature_json_uses_the_cache_on_the_second_run(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    with patch("gw.signature.build_service", return_value=_service()):
        result = runner.invoke(main, ["gmail", "signature", "--json"], env=env)

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["email"] == "victor@example.com"
    assert data["chars"] == len(SIG_HTML)
    assert data["enabled"] is True
    assert data["html"] == SIG_HTML

    # Second run: the cache written by the first answers without touching the API.
    with patch("gw.signature.build_service", side_effect=AssertionError("cache bypassed")):
        again = runner.invoke(main, ["gmail", "signature", "--json"], env=env)

    assert again.exit_code == 0
    assert json.loads(again.output)["source"] == "cache"


def test_cli_signature_human_output(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    with patch("gw.signature.build_service", return_value=_service()):
        result = runner.invoke(main, ["gmail", "signature"], env=env)

    assert "victor@example.com" in result.output
    assert "Cumprimentos," in result.output


def test_cli_no_signature_flag_exists_on_every_sending_command() -> None:
    for command in ("send", "draft", "draft-edit", "reply", "forward"):
        result = runner.invoke(main, ["gmail", command, "--help"])
        assert result.exit_code == 0
        assert "--signature / --no-signature" in result.output


# ---------------- config ----------------


def test_config_rejects_a_non_boolean_signature(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('signature = "yes"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="'signature' must be a boolean"):
        load_config(path)


def test_config_rejects_a_non_positive_signature_ttl(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("signature_cache_ttl_seconds = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="signature_cache_ttl_seconds"):
        load_config(path)


def test_config_reads_the_signature_block_from_a_profile(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
signature = false

[profiles.controlspace]
signature = true
signature_address = "victor@controlspacestorage.com"
signature_cache_ttl_seconds = 60
""",
        encoding="utf-8",
    )

    profile = load_config(path, profile="controlspace")
    assert profile.signature is True
    assert profile.signature_address == "victor@controlspacestorage.com"
    assert profile.signature_cache_ttl_seconds == 60
    assert load_config(path).signature is False


def test_config_defaults_keep_the_signature_on(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")

    assert config.signature is True
    assert config.signature_address is None
    assert config.signature_cache_ttl_seconds == 7 * 24 * 60 * 60
    assert config.as_dict()["signature"] is True
