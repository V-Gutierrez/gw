"""Allow running gw as `python -m gw`."""

import sys

from gw.cli import run_cli


if __name__ == "__main__":
    sys.exit(run_cli())
