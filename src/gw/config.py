from __future__ import annotations

import os
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _detect_timezone() -> str:
    """Auto-detect system timezone, fallback to UTC."""
    env_timezone = os.environ.get("TZ")
    if env_timezone and "/" in env_timezone:
        return env_timezone

    localtime = Path("/etc/localtime")
    try:
        resolved = localtime.resolve()
        parts = resolved.parts
        if "zoneinfo" in parts:
            zoneinfo_index = parts.index("zoneinfo")
            detected = "/".join(parts[zoneinfo_index + 1 :])
            if "/" in detected:
                return detected
    except OSError:
        pass

    try:
        from datetime import datetime, timezone

        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        tz_name = str(local_tz)
        if tz_name and "/" in tz_name:
            return tz_name
    except Exception:
        pass

    try:
        if hasattr(time, "tzname") and time.tzname[0] and "/" in time.tzname[0]:
            return time.tzname[0]
    except Exception:
        pass

    return "America/Sao_Paulo"


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
    "timezone": "America/Sao_Paulo",
    "default_calendar": "primary",
    "credentials_path": _default_path("credentials.json"),
    "token_path": _default_path("token.json"),
    "timeout_seconds": 30,
}


@dataclass
class GWConfig:
    profile: str | None = None
    timezone: str = DEFAULTS["timezone"]
    default_calendar: str = DEFAULTS["default_calendar"]
    credentials_path: str = DEFAULTS["credentials_path"]
    token_path: str = DEFAULTS["token_path"]
    timeout_seconds: int = DEFAULTS["timeout_seconds"]
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
        data = {
            "timezone": self.timezone,
            "default_calendar": self.default_calendar,
            "credentials_path": self.credentials_path,
            "token_path": self.token_path,
            "timeout_seconds": self.timeout_seconds,
            **self._extra,
        }
        if self.profile is not None:
            data["profile"] = self.profile
        return data


def _profile_token_path(token_path: str, profile: str) -> str:
    path = Path(token_path)
    suffix = "".join(path.suffixes)
    base_name = path.name[: -len(suffix)] if suffix else path.name
    profile_name = f"{base_name}-{profile}{suffix}"
    return str(path.with_name(profile_name))


def _parse_known_values(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    known_keys = {
        "timezone",
        "default_calendar",
        "credentials_path",
        "token_path",
        "timeout_seconds",
    }
    known = {key: value for key, value in data.items() if key in known_keys}
    extra = {key: value for key, value in data.items() if key not in known_keys}

    string_keys = {"timezone", "default_calendar", "credentials_path", "token_path"}
    for key in string_keys:
        if key in known and not isinstance(known[key], str):
            raise ValueError(f"Config value {key!r} must be a string.")

    if "timeout_seconds" in known:
        timeout_value = known["timeout_seconds"]
        if not isinstance(timeout_value, int) or timeout_value <= 0:
            raise ValueError("Config value 'timeout_seconds' must be a positive integer.")

    return known, extra


def load_config(path: Path | None = None, profile: str | None = None) -> GWConfig:
    path = path or get_config_path()
    if not path.exists():
        defaults = dict(DEFAULTS)
        if profile is not None:
            defaults["token_path"] = _profile_token_path(str(defaults["token_path"]), profile)
        return GWConfig(profile=profile, **defaults)

    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a TOML object.")

    known, extra = _parse_known_values(data)

    selected_profile: dict[str, Any] = {}
    if profile is not None:
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("Config value 'profiles' must be a TOML table.")
        if profile in profiles:
            selected_profile = profiles[profile]
            if not isinstance(selected_profile, dict):
                raise ValueError(f"Profile {profile!r} must be a TOML table.")

    profile_known, profile_extra = _parse_known_values(selected_profile)
    merged = {**DEFAULTS, **known, **profile_known}

    if profile is not None and "token_path" not in profile_known:
        merged["token_path"] = _profile_token_path(str(merged["token_path"]), profile)

    return GWConfig(profile=profile, **merged, _extra={**extra, **profile_extra})
