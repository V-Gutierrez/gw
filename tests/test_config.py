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
    assert cfg.timeout_seconds == 30


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


def test_load_profile_uses_profile_token_suffix(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('timezone = "America/Manaus"\n')

    cfg = load_config(config_file, profile="work")

    assert cfg.profile == "work"
    assert cfg.timezone == "America/Manaus"
    assert cfg.token_path.endswith("token-work.json")


def test_load_profile_merges_profile_table_overrides(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "\n".join(
            [
                'timezone = "America/Sao_Paulo"',
                'token_path = "/tmp/base-token.json"',
                "timeout_seconds = 45",
                "",
                "[profiles.work]",
                'timezone = "Europe/London"',
                'credentials_path = "/tmp/work-creds.json"',
            ]
        )
    )

    cfg = load_config(config_file, profile="work")

    assert cfg.timezone == "Europe/London"
    assert cfg.credentials_path == "/tmp/work-creds.json"
    assert cfg.token_path == "/tmp/base-token-work.json"
    assert cfg.timeout_seconds == 45


def test_load_profile_respects_explicit_profile_token_path(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "\n".join(
            [
                "[profiles.work]",
                'token_path = "/tmp/custom-work-token.json"',
            ]
        )
    )

    cfg = load_config(config_file, profile="work")

    assert cfg.token_path == "/tmp/custom-work-token.json"


def test_invalid_timeout_raises_value_error(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("timeout_seconds = 0\n")

    try:
        load_config(config_file)
    except ValueError as exc:
        assert "timeout_seconds" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid timeout_seconds")


@patch("gw.config.Path.resolve")
def test_detect_timezone_from_zoneinfo_path(mock_resolve):
    mock_resolve.return_value = Path("/usr/share/zoneinfo/America/Manaus")
    cfg = GWConfig(timezone="auto")
    assert cfg.timezone == "America/Manaus"
