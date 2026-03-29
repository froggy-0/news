from __future__ import annotations

from morning_brief.emailer import _load_mail_theme


def test_load_mail_theme_returns_quiet_signal_contract() -> None:
    theme = _load_mail_theme()

    assert theme["name"] == "quiet-signal"
    assert theme["colors"]["shellBg"] == "#050505"
    assert theme["colors"]["accentCyan"] == "#00ffff"
    assert theme["colors"]["accentGreen"] == "#00ff66"
    assert theme["rhythm"] == {
        "hero": "signal-rail",
        "narrative": "open-stack",
        "data": "panel-split",
        "utility": "compressed",
    }
    assert theme["mood"]["signalRail"] is True
    assert theme["mood"]["panelDepth"] is True
    assert theme["mood"]["subtleGlow"] is False


def test_load_mail_theme_includes_required_string_maps() -> None:
    theme = _load_mail_theme()

    for section in ("colors", "typography", "spacing", "layout"):
        values = theme[section]
        assert isinstance(values, dict)
        assert values
        assert all(isinstance(value, str) for value in values.values())

    for section in ("pill", "badge", "cta", "footerLink"):
        values = theme["components"][section]
        assert isinstance(values, dict)
        assert values
        assert all(isinstance(value, str) for value in values.values())
