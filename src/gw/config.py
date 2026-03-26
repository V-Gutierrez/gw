from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _detect_timezone() -> str:
    """Auto-detect system timezone, fallback to UTC."""
    try:
        from datetime import datetime, timezone
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        tz_name = str(local_tz)
        if tz_name and tz_name != "UTC" and len(tz_name) > 2:
            return tz_name
    except Exception:
        pass
    try:
        import time
        if hasattr(time, 'tzname') and time.tzname[0]:
            return time.tzname[0]
    except Exception:
        pass
    return "UTC"


def get_config_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "gw"
    return Path.home() / ".config" / "gw"


def get_config_path() -> Path:
    return get_config_dir() / "config.toml"


CONFIG_DIR = get_config_dir()
CONFIG_PATH = get_config_path()


def _default_path(filename: str) -> str:
    if os.environ.get("XDG_CONFIG_HOME"):
        return str(get_config_dir() / filename)
    return f"~/.config/gw/{filename}"


DEFAULTS: dict[str, Any] = {
    "timezone": "auto",
    "default_calendar": "primary",
    "credentials_path": _default_path("credentials.json"),
    "token_path": _default_path("token.json"),
}


@dataclass
class GWConfig:
    timezone: str = DEFAULTS["timezone"]
    default_calendar: str = DEFAULTS["default_calendar"]
    credentials_path: str = DEFAULTS["credentials_path"]
    token_path: str = DEFAULTS["token_path"]
    _extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timezone == "auto":
            self.timezone = _detect_timezone()

    @property
    def credentials(self) -> Path:
        return Path(self.credentials_path).expanduser()

    @property
    def token(self) -> Path:
        return Path(self.token_path).expanduser()

    def as_dict(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "default_calendar": self.default_calendar,
            "credentials_path": self.credentials_path,
            "token_path": self.token_path,
            **self._extra,
        }


def load_config(path: Path | None = None) -> GWConfig:
    path = path or get_config_path()
    if not path.exists():
        return GWConfig()

    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a TOML object.")

    known_keys = {"timezone", "default_calendar", "credentials_path", "token_path"}
    known = {k: v for k, v in data.items() if k in known_keys}
    extra = {k: v for k, v in data.items() if k not in known_keys}

    for key, value in known.items():
        if not isinstance(value, str):
            raise ValueError(f"Config value {key!r} must be a string.")

    return GWConfig(**known, _extra=extra)
