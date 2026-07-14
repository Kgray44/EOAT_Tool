from __future__ import annotations

import ctypes
import os
import sys

from . import LAUNCHER_NAME

MB_ICONERROR = 0x00000010
MB_ICONWARNING = 0x00000030
MB_ICONINFORMATION = 0x00000040
MB_RETRYCANCEL = 0x00000005
IDRETRY = 4


class Notifier:
    def __init__(self, *, no_ui: bool = False):
        self.no_ui = no_ui

    def info(self, title: str, message: str) -> None:
        self._show(title, message, MB_ICONINFORMATION)

    def warning(self, title: str, message: str) -> None:
        self._show(title, message, MB_ICONWARNING)

    def error(self, title: str, message: str) -> None:
        self._show(title, message, MB_ICONERROR)

    def ask_retry(self, title: str, message: str) -> bool:
        if self.no_ui or os.name != "nt":
            print(f"{title}: {message}", file=sys.stderr)
            return False
        result = ctypes.windll.user32.MessageBoxW(None, message, title, MB_RETRYCANCEL | MB_ICONWARNING)
        return result == IDRETRY

    def _show(self, title: str, message: str, flags: int) -> None:
        if self.no_ui or os.name != "nt":
            stream = sys.stderr if flags in (MB_ICONERROR, MB_ICONWARNING) else sys.stdout
            print(f"{title}: {message}", file=stream)
            return
        ctypes.windll.user32.MessageBoxW(None, message, title or LAUNCHER_NAME, flags)
