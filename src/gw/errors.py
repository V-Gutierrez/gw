from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_GENERAL = 1
EXIT_AUTH = 2
EXIT_CONFIG = 3


class GwError(Exception):
    exit_code = EXIT_GENERAL

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GwAuthError(GwError):
    exit_code = EXIT_AUTH


class GwConfigError(GwError):
    exit_code = EXIT_CONFIG
