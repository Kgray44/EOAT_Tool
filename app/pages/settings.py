from __future__ import annotations

from app.settings_page.page import SettingsPage as _SettingsPage
from core.config import load_config, save_config
from core.openers import open_path


class SettingsPage(_SettingsPage):
    def __init__(self, config, parent=None):
        super().__init__(
            config,
            parent,
            config_loader=lambda: load_config(),
            config_saver=lambda current_config: save_config(current_config),
            path_opener=lambda path: open_path(path),
        )


__all__ = ["SettingsPage", "load_config", "open_path", "save_config"]
