from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gw.cli import main
from gw.config import GWConfig
from gw.doctor import run_doctor


def _reachable(_api: str, config: GWConfig) -> None:
    return None


def test_doctor_reports_a_disabled_api_by_name() -> None:
    """Sheets and Tasks were disabled in the Cloud project for months and nothing said so."""

    def probe(api: str, config: GWConfig) -> None:
        if api in {"sheets", "tasks"}:
            raise RuntimeError(
                f"Google {api} API has not been used in project 123 before or it is disabled."
            )

    with (
        patch("gw.doctor.credential_status", return_value={"authenticated": True}),
        patch("gw.doctor._probe_api", side_effect=probe),
    ):
        report = run_doctor(GWConfig())

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["api_sheets"]["status"] == "error"
    assert "not enabled" in checks["api_sheets"]["detail"].lower()
    assert checks["api_gmail"]["status"] == "ok"
    assert report["ok"] is False


def test_doctor_is_green_when_every_api_answers() -> None:
    with (
        patch("gw.doctor.credential_status", return_value={"authenticated": True}),
        patch("gw.doctor._probe_api", side_effect=_reachable),
        patch("gw.config.GWConfig.credentials", MagicMock(exists=lambda: True)),
        patch("gw.config.GWConfig.token", MagicMock(exists=lambda: True)),
    ):
        report = run_doctor(GWConfig())

    api_checks = [c for c in report["checks"] if c["name"].startswith("api_")]
    assert len(api_checks) >= 5
    assert all(check["status"] == "ok" for check in api_checks)


def test_doctor_skips_api_checks_when_not_authenticated() -> None:
    with (
        patch("gw.doctor.credential_status", return_value={"authenticated": False}),
        patch("gw.doctor._probe_api") as probe,
    ):
        report = run_doctor(GWConfig())

    assert probe.call_count == 0
    assert any(c["name"].startswith("api_") and "Skipped" in c["detail"] for c in report["checks"])


def test_doctor_command_still_runs_end_to_end() -> None:
    with (
        patch("gw.doctor.credential_status", return_value={"authenticated": True}),
        patch("gw.doctor._probe_api", side_effect=_reachable),
    ):
        result = CliRunner().invoke(main, ["--json", "doctor"])

    assert result.exit_code == 0
    assert "api_drive" in result.output
