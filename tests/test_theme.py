from __future__ import annotations

from app.theme import REQUIRED_THEME_TOKENS, THEME_TOKENS, app_stylesheet, normalized_theme, theme_tokens


def test_light_and_dark_theme_tokens_complete():
    assert {"light", "dark"}.issubset(THEME_TOKENS)
    for theme in ["light", "dark"]:
        tokens = theme_tokens(theme)
        for key in REQUIRED_THEME_TOKENS:
            assert key in tokens
            assert tokens[key]


def test_stylesheet_generation_for_supported_themes():
    for theme in ["light", "dark"]:
        stylesheet = app_stylesheet(theme)
        assert "QWidget" in stylesheet
        assert "QTableWidget" in stylesheet
        assert "QTreeWidget#SidebarNav" in stylesheet


def test_unknown_theme_falls_back_to_light():
    assert normalized_theme("mystery") == "light"
