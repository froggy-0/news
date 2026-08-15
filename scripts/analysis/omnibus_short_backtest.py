"""Omnibus STRUCTURAL_DOWN short candidate backtest using public Binance bars.

This is an isolated Phase B test. It does not change the live registry or write
to Supabase. Two predeclared variants are compared: the existing downtrend
classifier alone, and the same classifier with bearish EMA/MA confirmation.

Run:
  UV_CACHE_DIR=.cache/uv uv run python scripts/analysis/omnibus_short_backtest.py
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from macd_momentum_short_backtest import _bootstrap_ci, _split_half  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import algorithms, backtest, frequency, parameters  # noqa: E402

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
PAGE_LIMIT = 1000
INDICATOR_WARMUP_BARS = 220


def omnibus_short_structural(macro: dict, ind: dict) -> str | None:
    if algorithms._omnibus_regime(macro, ind) != algorithms._OMNIBUS_DOWN_TREND:
        return None
    sub_state, _ = algorithms._downtrend_sub_state(ind)
    return "short" if sub_state == algorithms._OMNIBUS_STRUCTURAL_DOWN else None


def omnibus_short_confirmed(macro: dict, ind: dict) -> str | None:
    if omnibus_short_structural(macro, ind) is None:
        return None
    ema_fast = float(ind.get("ema_fast") or 0.0)
    ema_slow = float(ind.get("ema_slow") or 0.0)
    ema_fast_slope = float(ind.get("ema_fast_slope") or 0.0)
    if not (ema_fast < ema_slow and ema_fast_slope < 0):
        return None
    if not algorithms._below_ema_trend(ind) or not algorithms._below_ma200(macro):
        return None
    return "short"


VARIANTS: dict[str, backtest.StrategyFn] = {
    "structural": omnibus_short_structural,
    "confirmed": omnibus_short_confirmed,
}


async def _fetch_bar_rows(symbol: str, start: datetime, end: datetime) -> list[dict]:
    rows: list[dict] = []
    cursor_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    async with httpx.AsyncClient(timeout=30.0) as client:
        while cursor_ms < end_ms:
            response = await client.get(
                BINANCE_KLINES_URL,
                params={
                    "symbol": symbol,
                    "interval": "4h",
                    "startTime": cursor_ms,
                    "endTime": end_ms,
                    "limit": PAGE_LIMIT,
                },
            )
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            for item in page:
                rows.append(
                    {
                        "open_time": datetime.fromtimestamp(int(item[0]) / 1000, tz=timezone.utc),
                        "close_time": datetime.fromtimestamp(int(item[6]) / 1000, tz=timezone.utc),
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                    }
                )
            if len(page) < PAGE_LIMIT:
                break
            cursor_ms = int(page[-1][0]) + 1
    return rows


def _summarize(label: str, symbol: str, trades: list) -> dict:
    selected = [trade for trade in trades if trade.algo_id == "omnibus"]
    if not selected:
        return {"label": label, "symbol": symbol, "n": 0}
    weighted = [trade.ret_pct * trade.position_weight for trade in selected]
    wins = [trade for trade in selected if trade.ret_pct > 0]
    losses = [trade for trade in selected if trade.ret_pct <= 0]
    gross_win = sum(trade.ret_pct for trade in wins)
    gross_loss = -sum(trade.ret_pct for trade in losses)
    point, ci_lo, ci_hi = _bootstrap_ci(selected)
    first, second = _split_half(selected) if len(selected) >= 6 else (0.0, 0.0)
    dsr = deflated_sharpe_ratio(np.array([trade.ret_pct for trade in selected]), n_trials=2)
    return {
        "label": label,
        "symbol": symbol,
        "n": len(selected),
        "win_rate": len(wins) / len(selected) * 100,
        "sum_w_pct": sum(weighted) * 100,
        "pf": gross_win / gross_loss if gross_loss else math.inf,
        "ci_lo_pct": ci_lo * 100,
        "ci_hi_pct": ci_hi * 100,
        "split_first_pct": first,
        "split_second_pct": second,
        "dsr": dsr["dsr"],
        "point_pct": point * 100,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = parser.parse_args()

    macro_rows = build_macro_rows(Path(args.parquet))
    from_date = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_date = pd.Timestamp(
        macro_rows[-1]["reference_date"], tz=timezone.utc
    ).to_pydatetime() + timedelta(days=2)
    fetch_start = from_date - timedelta(hours=4 * (INDICATOR_WARMUP_BARS + 5))
    settings = backtest.BacktestSettings(
        product_type="usdm_perp",
        position_semantics="usdm_perp_long_short",
        warmup_bars=INDICATOR_WARMUP_BARS,
    )

    results: list[dict] = []
    for symbol in args.symbols:
        rows = await _fetch_bar_rows(symbol, fetch_start, to_date)
        profile_id = (
            frequency.LIVE_4H_PROFILE_ID
            if symbol == parameters.BINANCE_SYMBOL
            else frequency.multi_asset_shadow_profile_id(symbol)
        )
        profile = frequency.get_frequency_profile(profile_id)
        frames = backtest.build_frames_from_bar_rows(
            rows,
            interval="4h",
            warmup_bars=INDICATOR_WARMUP_BARS,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
            from_date=from_date,
            to_date=to_date,
        )
        print(
            f"{symbol}: bars={len(rows)} frames={len(frames)} "
            f"{frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
        )
        for label, strategy in VARIANTS.items():
            result = backtest.run_replay(
                frames,
                strategy_fns={"omnibus": strategy},
                settings=settings,
            )
            results.append(_summarize(label, symbol, result.trades))

    print(
        f"{'variant':12} {'symbol':10} {'n':>4} {'win%':>6} {'sum_w%':>8} "
        f"{'PF':>6} {'CI_lo':>8} {'CI_hi':>8} {'first':>8} {'second':>8} {'DSR':>6}"
    )
    for item in results:
        if item["n"] == 0:
            print(f"{item['label']:12} {item['symbol']:10} {0:>4} no_trades")
            continue
        pf = item["pf"] if math.isfinite(item["pf"]) else 99.99
        print(
            f"{item['label']:12} {item['symbol']:10} {item['n']:>4} "
            f"{item['win_rate']:>6.1f} {item['sum_w_pct']:>+8.2f} {pf:>6.2f} "
            f"{item['ci_lo_pct']:>+8.2f} {item['ci_hi_pct']:>+8.2f} "
            f"{item['split_first_pct']:>+8.2f} {item['split_second_pct']:>+8.2f} "
            f"{item['dsr']:>6.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
