from __future__ import annotations

import pytest

from arena import short_signals


def test_disabled_short_path_keeps_long_contract(monkeypatch) -> None:
    def fail_if_called(_macro, _ind):
        raise AssertionError("short function must not run")

    monkeypatch.setitem(short_signals.PERP_SHORT_ALGORITHMS, "omnibus", fail_if_called)

    decision = short_signals.resolve(
        algo_id="omnibus",
        long_signal="long",
        macro={},
        indicators={},
        short_enabled=False,
    )

    assert decision.resolved_signal == "long"
    assert decision.short_signal is None


def test_enabled_short_path_uses_separate_registry(monkeypatch) -> None:
    monkeypatch.setitem(
        short_signals.PERP_SHORT_ALGORITHMS,
        "omnibus",
        lambda _macro, _ind: "short",
    )

    decision = short_signals.resolve(
        algo_id="omnibus",
        long_signal=None,
        macro={},
        indicators={},
        short_enabled=True,
    )

    assert decision.resolved_signal == "short"
    assert decision.long_signal is None
    assert decision.short_signal == "short"


def test_long_short_conflict_holds_existing_position(monkeypatch) -> None:
    monkeypatch.setitem(
        short_signals.PERP_SHORT_ALGORITHMS,
        "omnibus",
        lambda _macro, _ind: "short",
    )

    decision = short_signals.resolve(
        algo_id="omnibus",
        long_signal="long",
        macro={},
        indicators={},
        short_enabled=True,
        current_direction="short",
    )

    assert decision.conflict is True
    assert decision.resolved_signal == "short"


def test_long_enabled_false_forces_long_signal_to_none(monkeypatch) -> None:
    # v42(숏 전용 트랙) — long_enabled=False면 fn()이 "long"을 반환해도 무시된다.
    monkeypatch.setitem(
        short_signals.PERP_SHORT_ALGORITHMS,
        "macd_momentum",
        lambda _macro, _ind: "short",
    )

    decision = short_signals.resolve(
        algo_id="macd_momentum",
        long_signal="long",
        macro={},
        indicators={},
        short_enabled=True,
        long_enabled=False,
    )

    assert decision.long_signal is None
    assert decision.resolved_signal == "short"
    assert decision.conflict is False


def test_long_enabled_defaults_to_true() -> None:
    decision = short_signals.resolve(
        algo_id="omnibus",
        long_signal="long",
        macro={},
        indicators={},
        short_enabled=False,
    )

    assert decision.long_signal == "long"
    assert decision.resolved_signal == "long"


def test_enabled_pair_requires_registered_short_function(monkeypatch) -> None:
    monkeypatch.delitem(short_signals.PERP_SHORT_ALGORITHMS, "omnibus", raising=False)

    with pytest.raises(ValueError, match="no registered short signal"):
        short_signals.resolve(
            algo_id="omnibus",
            long_signal=None,
            macro={},
            indicators={},
            short_enabled=True,
        )
