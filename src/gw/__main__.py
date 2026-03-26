"""Allow running gw as `python -m gw`."""

from gw.cli import main_group


if __name__ == "__main__":
    main_group(prog_name="gw")
