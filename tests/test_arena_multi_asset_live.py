from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arena import config, slack_notify, state, stream


def setup_function() -> None:
    state.open_positions.clear()
    state.current_price.clear()


def test_state_positions_are_isolated_per_symbol() -> None:
    state.set_position("BTCUSDT", "regime_trend", {"id": 1})
    state.set_position("ETHUSDT", "regime_trend", {"id": 2})

    assert state.get_position("BTCUSDT", "regime_trend") == {"id": 1}
    assert state.get_position("ETHUSDT", "regime_trend") == {"id": 2}
    assert state.get_position("SOLUSDT", "regime_trend") is None


def test_state_price_is_isolated_per_symbol() -> None:
    state.set_price("BTCUSDT", 65000.0)
    state.set_price("ETHUSDT", 3200.0)

    assert state.get_price("BTCUSDT") == 65000.0
    assert state.get_price("ETHUSDT") == 3200.0
    assert state.get_price("SOLUSDT") == 0.0


def test_state_positions_for_returns_live_mutable_reference() -> None:
    positions = state.positions_for("BTCUSDT")
    positions["macd_momentum"] = {"id": 9}

    assert state.get_position("BTCUSDT", "macd_momentum") == {"id": 9}


def test_parse_tick_handles_combined_stream_wrapper() -> None:
    raw = json.dumps({"stream": "ethusdt@kline_1m", "data": {"k": {"c": "3200.50"}}})

    result = stream._parse_tick(raw, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))

    assert result == ("ETHUSDT", 3200.50)


def test_parse_tick_handles_single_symbol_legacy_format() -> None:
    raw = json.dumps({"k": {"c": "65000.00"}})

    result = stream._parse_tick(raw, ("BTCUSDT",))

    assert result == ("BTCUSDT", 65000.00)


def test_parse_tick_ignores_zero_price() -> None:
    raw = json.dumps({"stream": "btcusdt@kline_1m", "data": {"k": {"c": "0"}}})

    assert stream._parse_tick(raw, ("BTCUSDT",)) is None


def test_combined_stream_url_lists_all_symbols_lowercase() -> None:
    url = stream._combined_stream_url(("BTCUSDT", "ETHUSDT", "SOLUSDT"))

    assert url == (
        f"{config.BINANCE_COMBINED_WS_URL}?streams="
        "btcusdt@kline_1m/ethusdt@kline_1m/solusdt@kline_1m"
    )


def test_symbol_label_maps_known_symbols_and_falls_back() -> None:
    assert slack_notify._symbol_label("BTCUSDT") == "BTC"
    assert slack_notify._symbol_label("ETHUSDT") == "ETH"
    assert slack_notify._symbol_label("SOLUSDT") == "SOL"
    assert slack_notify._symbol_label("DOGEUSDT") == "DOGE"


def test_arena_live_symbols_always_includes_btc_first() -> None:
    from arena import parameters

    # 플래그 값과 무관하게(로컬 .env override 여부 상관없이) BTC가 항상 포함·항상 첫 항목.
    assert config.ARENA_LIVE_SYMBOLS[0] == parameters.BINANCE_SYMBOL
    assert len(config.ARENA_LIVE_SYMBOLS) == len(set(config.ARENA_LIVE_SYMBOLS))  # 중복 없음
