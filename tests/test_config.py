from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from gw.config import GWConfig, load_config, DEFAULTS


def test_defaults():
    cfg = GWConfig()
    assert cfg.timezone == "America/Sao_Paulo"
    assert cfg.default_calendar == "primary"
    assert cfg.credentials_path == "~/.config/gw/credentials.json"
    assert cfg.token_path == "~/.config/gw/token.json"


def test_path_expansion():
    cfg = GWConfig()
    assert cfg.credentials == Path.home() / ".config" / "gw" / "credentials.json"
    assert cfg.token == Path.home() / ".config" / "gw" / "token.json"


def test_as_dict_matches_defaults():
    cfg = GWConfig()
    d = cfg.as_dict()
    for key, value in DEFAULTS.items():
        assert d[key] == value


def test_load_missing_file(tmp_path: Path):
    missing = tmp_path / "nonexistent.toml"
    cfg = load_config(missing)
    assert cfg.timezone == "America/Sao_Paulo"
    assert cfg.default_calendar == "primary"


def test_load_with_overrides(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('timezone = "America/Sao_Paulo"\ndefault_calendar = "work"\n')
    cfg = load_config(config_file)
    assert cfg.timezone == "America/Sao_Paulo"
    assert cfg.default_calendar == "work"
    assert cfg.credentials_path == DEFAULTS["credentials_path"]


def test_load_partial_override(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('timezone = "Europe/London"\n')
    cfg = load_config(config_file)
    assert cfg.timezone == "Europe/London"
    assert cfg.default_calendar == "primary"


def test_extra_keys_preserved(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('timezone = "America/Sao_Paulo"\ncustom_setting = "hello"\n')
    cfg = load_config(config_file)
    d = cfg.as_dict()
    assert d["custom_setting"] == "hello"
    assert cfg.timezone == "America/Sao_Paulo"


def test_custom_credentials_path(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('credentials_path = "/tmp/my-creds.json"\n')
    cfg = load_config(config_file)
    assert cfg.credentials == Path("/tmp/my-creds.json")


@patch("gw.config.Path.resolve")
def test_detect_timezone_from_zoneinfo_path(mock_resolve):
    mock_resolve.return_value = Path("/usr/share/zoneinfo/America/Manaus")
    cfg = GWConfig(timezone="auto")
    assert cfg.timezone == "America/Manaus"
