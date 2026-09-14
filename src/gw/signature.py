"""Account signature, straight from Gmail settings.

The Gmail signature is a *compose-time* setting: the web UI appends it, the Gmail
API does not. gw builds the raw MIME itself, so a message sent as a bare
``MIMEText(body)`` reads exactly like Gmail's settings page — signature configured,
signature missing — because nothing ever asked for it.

This module fetches the signature from ``users.settings.sendAs`` and caches it, so
every outbound path can attach it without a round-trip per message. The cached copy
is what the account actually shows in Gmail, not a second copy kept in a config file.

Passing ``config=None`` disables the feature on purpose: without a profile there is
no cache to read and no place to write, and the pre-0.8.0 byte-for-byte output is
preserved.
"""

from __future__ import annotations

import html as html_lib
import json
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from gw.auth import build_service, execute_google_request
from gw.config import DEFAULT_SIGNATURE_CACHE_TTL_SECONDS, GWConfig, get_config_dir
from gw.utils import atomic_write

# Tags that end a rendered visual line, so their text version breaks there too.
_BLOCK_TAGS = frozenset(
    {
        "br",
        "div",
        "p",
        "li",
        "tr",
        "table",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
    }
)

SEND_AS_FIELDS = "sendAsEmail,isDefault,signature"


@dataclass(frozen=True)
class AccountSignature:
    """The signature configured for one Gmail account."""

    email: str
    html: str
    source: str = "api"

    @property
    def plain_text(self) -> str:
        return html_to_text(self.html)


class _HTMLTextExtractor(HTMLParser):
    """Flatten the signature HTML into the lines a plain-text client would show.

    Opening a block breaks the line; closing it does not, so ``<div>a</div><div>b</div>``
    reads as two lines rather than four. Images are dropped unless they carry alt text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(alt)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Render signature HTML as plain text, one line per rendered line.

    A signature is line-shaped — name, role, address, site — so the text version keeps
    exactly those lines instead of carrying the markup's empty boxes across as blanks.
    """
    if not markup:
        return ""
    extractor = _HTMLTextExtractor()
    extractor.feed(markup)
    extractor.close()

    raw = "".join(extractor.parts).replace("\xa0", " ")
    return "\n".join(line.strip() for line in raw.split("\n") if line.strip())


def signature_cache_path(config: GWConfig) -> Path:
    """Where this profile's signature is cached."""
    if config.signature_cache_path:
        return Path(config.signature_cache_path).expanduser()
    return get_config_dir() / f"signature-{config.profile or 'default'}.json"


def signature_enabled(config: GWConfig | None, override: bool | None = None) -> bool:
    """A command-line override wins over the config switch."""
    if override is not None:
        return override
    return bool(config.signature) if config is not None else False


def _read_cache(path: Path, ttl: int, *, allow_stale: bool = False) -> AccountSignature | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    markup = data.get("signature")
    if not isinstance(markup, str):
        return None

    if not allow_stale:
        fetched_at = data.get("fetched_at")
        age = time.time() - (fetched_at if isinstance(fetched_at, int | float) else 0)
        if age > ttl:
            return None

    email = data.get("email")
    return AccountSignature(
        email=email if isinstance(email, str) else "", html=markup, source="cache"
    )


def cached_signature(config: GWConfig) -> AccountSignature | None:
    """Read the cache whatever its age — used to strip, never to attach."""
    path = signature_cache_path(config)
    return _read_cache(path, DEFAULT_SIGNATURE_CACHE_TTL_SECONDS, allow_stale=True)


def _write_cache(path: Path, signature: AccountSignature) -> None:
    payload = {
        "email": signature.email,
        "signature": signature.html,
        "fetched_at": int(time.time()),
        "source": signature.source,
    }
    try:
        atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError:
        # An unwritable cache is not worth failing a send over.
        return


def pick_send_as(entries: list[object], address: str | None) -> dict[str, object] | None:
    """Choose the sending identity: the named address, else the account default."""
    tables = [entry for entry in entries if isinstance(entry, dict)]
    if not tables:
        return None
    if address:
        for entry in tables:
            if entry.get("sendAsEmail") == address:
                return entry
        return None
    for entry in tables:
        if entry.get("isDefault"):
            return entry
    return tables[0]


def fetch_signature(service: object, address: str | None = None) -> AccountSignature | None:
    """Read the signature from Gmail's own settings."""
    response = execute_google_request(
        service.users().settings().sendAs().list(userId="me")  # type: ignore[attr-defined]
    )
    entries = response.get("sendAs", []) if isinstance(response, dict) else []
    chosen = pick_send_as(list(entries), address)
    if chosen is None:
        return None

    email = chosen.get("sendAsEmail")
    markup = chosen.get("signature")
    return AccountSignature(
        email=email if isinstance(email, str) else "",
        html=markup if isinstance(markup, str) else "",
    )


def resolve_signature(
    config: GWConfig | None,
    *,
    service: object | None = None,
    override: bool | None = None,
    refresh: bool = False,
    use_cache: bool = True,
) -> AccountSignature | None:
    """Resolve the signature to attach, or ``None`` when there is nothing to attach.

    Order: the cache while it is fresh, then the API, then the cache again whatever
    its age if the API is unreachable. An account with no signature configured is
    cached as empty, so the API is asked once rather than on every send.
    """
    if config is None or not signature_enabled(config, override):
        return None

    path = signature_cache_path(config)
    if use_cache and not refresh:
        fresh = _read_cache(path, config.signature_cache_ttl_seconds)
        if fresh is not None:
            return fresh if fresh.html else None

    try:
        resolved_service = service or build_service("gmail", "v1", config=config)
        fetched = fetch_signature(resolved_service, config.signature_address)
    # A missing signature must never cost you the message: whichever way the API
    # fails, fall through to what we already have instead of raising on send.
    except Exception:  # noqa: BLE001 - a missing signature must never cost the message
        stale = _read_cache(path, config.signature_cache_ttl_seconds, allow_stale=True)
        return stale if stale and stale.html else None

    if fetched is None:
        return None

    _write_cache(path, fetched)
    return fetched if fetched.html else None


def append_signature(body: str, signature: AccountSignature) -> tuple[str, str]:
    """Return the message body as ``(plain_text, html)`` with the signature attached."""
    plain = f"{body.rstrip(chr(10))}\n\n{signature.plain_text}".rstrip()
    escaped_body = html_lib.escape(body).replace("\n", "<br>")
    return plain, f'<div dir="ltr">{escaped_body}</div>{signature.html}'


def strip_signature(body: str, signature: AccountSignature | None) -> str:
    """Drop a signature gw already appended, so editing a draft never doubles it."""
    if signature is None:
        return body
    marker = signature.plain_text
    if not marker:
        return body

    trimmed = body.rstrip()
    if not trimmed.endswith(marker):
        return body
    return trimmed[: -len(marker)].rstrip()
