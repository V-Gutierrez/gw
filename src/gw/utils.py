from __future__ import annotations

import base64
import os
import tempfile
from datetime import datetime, timedelta
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def atomic_write(path: Path, content: str | bytes, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        if isinstance(content, bytes):
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
        else:
            with os.fdopen(fd, "wb") as raw_handle:
                with TextIOWrapper(raw_handle, encoding=encoding) as handle:
                    handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def now_in_tz(timezone: str = "UTC") -> datetime:
    return datetime.now(tz=ZoneInfo(timezone))


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def date_range_today(timezone: str = "UTC") -> tuple[datetime, datetime]:
    today = now_in_tz(timezone)
    return start_of_day(today), end_of_day(today)


def date_range_week(timezone: str = "UTC") -> tuple[datetime, datetime]:
    today = now_in_tz(timezone)
    start = start_of_day(today)
    end = end_of_day(today + timedelta(days=6))
    return start, end


def to_rfc3339(dt: datetime) -> str:
    return dt.isoformat()


def parse_date(value: str, timezone: str = "UTC") -> datetime:
    tz = ZoneInfo(timezone)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {value!r}")


def build_query(**kwargs: str | None) -> str:
    parts = []
    for key, value in kwargs.items():
        if value:
            parts.append(f"{key}:{value}")
    return " ".join(parts)


def parse_after_flag(value: str) -> str:
    unit = value[-1:].lower()
    amount_text = value[:-1]
    if unit not in {"h", "d"} or not amount_text.isdigit():
        raise ValueError("--after must use formats like 6h, 24h, or 7d.")

    amount = int(amount_text)
    delta = timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
    threshold = datetime.now() - delta
    return f"after:{threshold.strftime('%Y/%m/%d')}"


def header_map(headers: list[dict[str, Any]] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers or []:
        name = header.get("name")
        value = header.get("value")
        if isinstance(name, str) and isinstance(value, str):
            result[name.lower()] = value
    return result


def decode_base64url(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(data + padding)
    return decoded.decode("utf-8", errors="replace")


def extract_message_body(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""

    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")
    if mime_type == "text/plain" and body_data:
        return decode_base64url(body_data)

    for part in payload.get("parts", []) or []:
        text = extract_message_body(part)
        if text:
            return text

    if mime_type.startswith("text/") and body_data:
        return decode_base64url(body_data)
    return ""


def clean_message_body(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        cleaned.append(line)
        previous_blank = is_blank
    return "\n".join(cleaned).strip()


def format_event_time(event: dict[str, Any]) -> str:
    start_data = event.get("start", {})
    if "date" in start_data:
        return start_data["date"]
    date_time = start_data.get("dateTime", "")
    if not date_time:
        return "Unknown time"
    try:
        parsed = datetime.fromisoformat(date_time.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return date_time
