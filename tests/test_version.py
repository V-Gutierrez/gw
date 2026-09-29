"""A versão vive em dois sítios, e eles têm de concordar.

`pyproject.toml` decide o que o Homebrew instala; `gw/__init__.py` decide o que
`gw --version` responde. Em 2026-09-29 a v0.9.0 saiu com os dois em desacordo: o brew
instalou 0.9.0 e o binário respondeu 0.8.3, porque o ritual de release só mandava bumpar
o `pyproject.toml`. O `brew test` apanhou-o — depois de a release já estar publicada.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from gw import __version__

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert __version__ == declared, (
        f"gw/__init__.py diz {__version__!r} e pyproject.toml diz {declared!r}. "
        "Bumpar os dois faz parte do release."
    )


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__
