"""Meridian 역발산 leg 모멘텀 게이트(2026-08-16) sanity 체크 — 그리드 튜닝 아님.

목적: MERIDIAN_REVERSION_STABILIZATION_ENABLED on/off 두 사양만 비교해 (1) 3자산
동시진입(같은 4h bar에 2개+ 자산이 reversion leg로 동시 진입) 빈도가 실제로
줄어드는지, (2) 거래수·가중합%가 붕괴하지 않는지 확인한다. 그리드 탐색이
아니므로 DSR/PBO 대상 아님 — 구조적 수정의 회귀 확인용.

재현:
  .venv/bin/python3 scripts/analysis/meridian_reversion_correlation_check.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _profile_for(symbol: str) -> frequency.FrequencyProfile:
    profile_id = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    return frequency.get_frequency_profile(profile_id)


def _settings_for(symbol: str) -> backtest.BacktestSettings:
    profile = _profile_for(symbol)
    cost = frequency.get_cost_scenario(profile.frequency_profile_id, "base")
    return backtest.BacktestSettings(
        frequency_profile_id=profile.frequency_profile_id,
        indicator_profile_id=profile.default_indicator_profile_id,
        cost_model_version=cost.cost_model_version,
        cost_scenario_id=cost.cost_scenario_id,
        symbol=symbol,
        interval=profile.interval,
        fee_bps=cost.fee_bps,
        slippage_bps=cost.slippage_bps,
        spread_bps_round_trip=cost.spread_bps_round_trip,
        funding_buffer_bps_per_8h=cost.funding_buffer_bps_per_8h,
        min_hold_hours=dict(profile.min_hold_hours),
        min_hold_fallback_hours=profile.min_hold_fallback_hours,
    )


async def _load_all_frames(macro_rows: list[dict]) -> dict[str, list]:
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    out: dict[str, list] = {}
    for symbol in ASSETS:
        profile = _profile_for(symbol)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=profile.interval,
            limit=5000,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
        )
        out[symbol] = frames
        print(f"  {symbol}: {len(frames)} frames")
    return out


def _run_meridian(frames_by_symbol: dict[str, list], *, gate_enabled: bool) -> dict[str, list]:
    parameters.MERIDIAN_REVERSION_STABILIZATION_ENABLED = gate_enabled
    trades_by_symbol: dict[str, list] = {}
    for symbol, frames in frames_by_symbol.items():
        if not frames:
            trades_by_symbol[symbol] = []
            continue
        result = backtest.run_replay(
            frames,
            strategy_fns={"meridian": algorithms.meridian_long},
            settings=_settings_for(symbol),
        )
        trades_by_symbol[symbol] = list(result.trades)
    return trades_by_symbol


def _classify_leg(trade) -> str | None:
    return algorithms.meridian_active_leg(trade.macro_snapshot, trade.indicator_snapshot)


def _summarize(label: str, trades_by_symbol: dict[str, list]) -> None:
    print(f"\n=== {label} ===")
    leg_opens: dict[str, dict[str, set]] = {"reversion": {}, "trend": {}}
    for symbol, trades in trades_by_symbol.items():
        n = len(trades)
        sum_w = sum(t.ret_pct * t.position_weight for t in trades) * 100
        win = sum(1 for t in trades if t.ret_pct > 0)
        win_pct = 100.0 * win / n if n else 0.0
        legs = [_classify_leg(t) for t in trades]
        n_reversion = sum(1 for leg in legs if leg == "reversion")
        n_trend = sum(1 for leg in legs if leg == "trend")
        for leg_name in ("reversion", "trend"):
            leg_opens[leg_name][symbol] = {
                t.open_time for t, leg in zip(trades, legs, strict=True) if leg == leg_name
            }
        print(
            f"  {symbol}: n={n} (reversion={n_reversion} trend={n_trend} "
            f"unclassified={n - n_reversion - n_trend}) win%={win_pct:.0f} sum_w%={sum_w:.2f}"
        )

    from collections import Counter

    for leg_name in ("reversion", "trend"):
        counter: Counter = Counter()
        for symbol, times in leg_opens[leg_name].items():
            for t in times:
                counter[t] += 1
        simultaneous = sum(1 for t, c in counter.items() if c >= 2)
        all_three = sum(1 for t, c in counter.items() if c >= 3)
        total_bars = len(counter)
        rate = 100.0 * simultaneous / total_bars if total_bars else 0.0
        print(
            f"  동시진입({leg_name} leg, 2자산+ 같은 bar): {simultaneous}/{total_bars} bars "
            f"({rate:.1f}%, 3자산 동시: {all_three})"
        )


def _simulate_concurrency_cap(
    trades_by_symbol: dict[str, list], *, leg_name: str, cap: int
) -> dict[str, list]:
    """사후 시뮬레이션(정확한 조인 백테스트 아님) — 이미 독립적으로 계산된 3자산
    거래를 open_time 순으로 정렬해, 같은 leg로 동시에 열려있는 거래 수가 cap 이상이면
    그 신규 거래를 통째로 제거한다. 자산 내부의 나머지 거래 시퀀스는 원본 그대로
    유지(제거된 거래가 같은 자산의 후속 거래 타이밍을 바꾸는 효과는 반영 안 됨 —
    라이브 스케줄러 캡의 방향성 근사치로만 사용)."""
    all_trades = []
    for symbol, trades in trades_by_symbol.items():
        for t in trades:
            leg = _classify_leg(t)
            eff_leg = "short" if t.direction == "short" else leg
            all_trades.append((symbol, t, eff_leg))
    all_trades.sort(key=lambda item: item[1].open_time)

    open_until: list = []  # close_time of currently-open same-leg trades
    kept: dict[str, list] = {s: [] for s in trades_by_symbol}
    for symbol, t, eff_leg in all_trades:
        if eff_leg != leg_name:
            kept[symbol].append(t)
            continue
        open_until = [ct for ct in open_until if ct > t.open_time]
        if len(open_until) >= cap:
            continue  # blocked by cap
        open_until.append(t.close_time)
        kept[symbol].append(t)
    return kept


def _print_cap_scenarios(trades_by_symbol: dict[str, list]) -> None:
    for leg_name in ("reversion", "trend"):
        print(f"\n--- {leg_name} leg 상관캡 시뮬레이션(사후 근사) ---")
        for cap in (None, 2, 1):
            if cap is None:
                scenario = trades_by_symbol
                label = "cap=off"
            else:
                scenario = _simulate_concurrency_cap(trades_by_symbol, leg_name=leg_name, cap=cap)
                label = f"cap={cap}"
            total_n = sum(len(v) for v in scenario.values())
            total_sum_w = sum(
                sum(t.ret_pct * t.position_weight for t in v) * 100 for v in scenario.values()
            )
            # 동시진입 재계산(해당 leg만)
            opens = {}
            for symbol, trades in scenario.items():
                opens[symbol] = {
                    t.open_time
                    for t in trades
                    if ("short" if t.direction == "short" else _classify_leg(t)) == leg_name
                }
            from collections import Counter

            counter: Counter = Counter()
            for symbol, times in opens.items():
                for t in times:
                    counter[t] += 1
            simultaneous = sum(1 for c in counter.values() if c >= 2)
            total_bars = len(counter)
            rate = 100.0 * simultaneous / total_bars if total_bars else 0.0
            print(
                f"  {label:8} n_total={total_n:4} sum_w_total%={total_sum_w:7.2f} "
                f"동시진입={simultaneous}/{total_bars}({rate:.1f}%)"
            )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    print(f"macro rows: {len(macro_rows)}")

    await positions.init()
    frames_by_symbol = await _load_all_frames(macro_rows)

    legacy_trades = _run_meridian(frames_by_symbol, gate_enabled=False)
    _summarize("레거시(게이트 off, 기존 동작)", legacy_trades)

    new_trades = _run_meridian(frames_by_symbol, gate_enabled=True)
    _summarize("신규(게이트 on, 2026-08-16 수정)", new_trades)

    print("\n\n### 상관캡 시뮬레이션 (모멘텀게이트 on 기준, 신규 거래셋에 적용) ###")
    _print_cap_scenarios(new_trades)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
