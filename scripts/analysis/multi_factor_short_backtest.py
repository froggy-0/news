"""multi_factor 숏 진입 후보 격리 백테스트 (Phase B §3.4/§1원칙3 4순위).

배경: docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md §3.4.
`macd_momentum`(§8)·`omnibus`(§9)·`regime_trend`(§10) 숏 후보가 모두 기각된 뒤 순서상
다음 알고. §3.4가 명시하듯 5개 하드 veto(risk-off/ETF유출/LSR과밀/breadth/스테이블코인)
중 방향 재해석 여지가 가장 큰 알고라, 단순 거울반전이 아니라 예정된 두 변형을 비교한다
(그리드 아닌 사전 설계값 2개).

**variant A(direction_soft)**: WI-1(2026-07-09) 이전의 원래 multi_factor 설계로 되돌아가
레짐을 5팩터 중 하나(소프트 투표)로만 쓰고, risk-off veto와 ETF/LSR veto는 롱과 동일한
정의로 그대로 유지한다. 5팩터 거울(약세 레짐/FNG>40/VIX 고조/RSI>45/펀딩 not-cold)
합산 ≥4면 숏.
  - 이 변형을 만든 이유: 만약 "약세 레짐"을 hard 방향 요구조건으로 쓰면서 동시에
    risk-off veto(bear_trend/stress/BearPanic)를 그대로 두면 논리적으로 항상
    상호배타(약세=risk-off 어휘 재사용이라 모순)라 거래가 아예 안 나온다 — 이 변형은
    그 충돌을 피하기 위해 레짐을 hard 요구조건에서 빼고 소프트 투표로만 쓴다.

**variant B(direction_hard_reinterpreted)**: WI-1처럼 레짐(f1)을 hard 요구조건으로
승격하되(약세 레짐=`_is_risk_off` 재사용), 그러면 기존 risk-off veto는 제거해야
모순이 안 생긴다(variant A의 문제를 반대로 해결). 나머지 4팩터 중 2표 이상
(MULTI_FACTOR_MIN_VOTES_EX_REGIME과 동일 값 재사용). §3.4가 제안한 veto 재해석도
반영: `etf_outflow_heavy`(기관 대량유출)는 숏에는 veto가 아니라 오히려 진입 근거에
가까울 수 있다는 가설 그대로 **팩터로 편입**(veto 제거, 5번째 팩터로 승격),
`lsr_crowded`(과밀 롱)도 숏스퀴즈 리스크가 아니라 **청산 취약성 신호로 팩터 편입**
(veto 제거, 6번째 팩터). breadth_collapsed·stablecoin_contracting은 §3.4 원문이
"방향 무관 건전성 신호"라 명시한 대로 **veto 그대로 유지**.

ALGORITHMS dict·PERP_SHORT_ENABLED_TRACKS·algorithms.py 어느 것도 건드리지 않음 —
backtest.run_replay(strategy_fns=...)로 algo_id="multi_factor"만 오버라이드해
product_type="usdm_perp" 상태머신에 태운다.

재현:
  .venv/bin/python3 scripts/analysis/multi_factor_short_backtest.py
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from collections import defaultdict
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from macd_momentum_short_backtest import _bootstrap_ci, _split_half  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402
from arena.algorithms import _is_risk_off, _regime_state  # noqa: E402


def _z(macro: dict, key: str) -> float | None:
    v = macro.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _multi_factor_short_votes(macro: dict, ind: dict) -> dict[str, bool]:
    """5팩터 거울(§3.4) — 롱의 부호 대칭. rsi/vix/fng는 50 중심 대칭 임계값."""
    state = _regime_state(macro)
    fng = macro.get("fng")
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    rsi = ind.get("rsi", 50.0)
    funding_z = _z(macro, "funding_zscore")
    return {
        "bearish_regime": _is_risk_off(state),
        "fng_above_40": fng is not None and fng > 40.0,
        "vix_elevated_or_missing": (
            vix_now is None
            or (vix_q40 is not None and vix_now >= vix_q40 * parameters.VIX_CALM_TOLERANCE_BAND)
            or (vix_q40 is None and vix_now >= 20.0)
        ),
        "rsi_above_short_min": rsi > (100.0 - parameters.MULTI_FACTOR_LONG_RSI_MAX),
        "funding_not_cold": not (
            funding_z is not None and funding_z <= -parameters.FUNDING_HOT_ZSCORE
        ),
    }


def multi_factor_short_direction_soft(macro: dict, ind: dict) -> str | None:
    """variant A — 레짐은 소프트 투표, 기존 veto(risk-off 포함) 전부 그대로."""
    if (
        _is_risk_off(_regime_state(macro))
        or algorithms._etf_outflow_heavy(macro)
        or algorithms._lsr_crowded(macro)
        or algorithms._breadth_collapsed(macro)
        or algorithms._stablecoin_contracting(macro)
    ):
        return None
    votes = _multi_factor_short_votes(macro, ind)
    return "short" if sum(votes.values()) >= 4 else None


def multi_factor_short_direction_hard_reinterpreted(macro: dict, ind: dict) -> str | None:
    """variant B — 약세 레짐 hard 요구(risk-off veto는 모순이라 제거), ETF유출/LSR과밀은
    veto에서 팩터로 편입, breadth/stablecoin veto는 그대로 유지."""
    if algorithms._breadth_collapsed(macro) or algorithms._stablecoin_contracting(macro):
        return None
    state = _regime_state(macro)
    if not _is_risk_off(state):
        return None
    votes = _multi_factor_short_votes(macro, ind)
    etf_z = _z(macro, "etf_flow_zscore")
    lsr_z = _z(macro, "long_short_ratio_zscore")
    extra_votes = {
        "etf_inflow_or_outflow_heavy": (
            (etf_z is not None and etf_z >= abs(parameters.ETF_OUTFLOW_HEAVY_Z))
            or (etf_z is not None and etf_z <= parameters.ETF_OUTFLOW_HEAVY_Z)
        ),
        "lsr_crowded_long": lsr_z is not None and lsr_z >= parameters.LSR_CROWDED_ZSCORE,
    }
    other_votes = sum(v for k, v in votes.items() if k != "bearish_regime") + sum(
        extra_votes.values()
    )
    return "short" if other_votes >= parameters.MULTI_FACTOR_MIN_VOTES_EX_REGIME else None


VARIANTS_A: dict[str, backtest.StrategyFn] = {"multi_factor": multi_factor_short_direction_soft}
VARIANTS_B: dict[str, backtest.StrategyFn] = {
    "multi_factor": multi_factor_short_direction_hard_reinterpreted
}


def _summarize(label: str, symbol: str, trades: list) -> dict:
    algo_trades = [t for t in trades if t.algo_id == "multi_factor"]
    n = len(algo_trades)
    print(f"\n--- {label} / {symbol} (n={n}) ---")
    if n == 0:
        print("  거래 없음")
        return {"label": label, "symbol": symbol, "n": 0}
    wins = [t for t in algo_trades if t.ret_pct > 0]
    losses = [t for t in algo_trades if t.ret_pct <= 0]
    win_rate = len(wins) / n * 100
    sum_w = sum(t.ret_pct * t.position_weight for t in algo_trades) * 100
    gross_win = sum(t.ret_pct for t in wins)
    gross_loss = -sum(t.ret_pct for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    avg_hold = sum(t.hold_hours for t in algo_trades) / n
    exits = defaultdict(int)
    for t in algo_trades:
        exits[t.exit_reason] += 1
    print(
        f"  win%={win_rate:.1f}  sum_w%={sum_w:+.2f}  PF={pf:.2f}  "
        f"avg_hold={avg_hold:.0f}h  exits={dict(exits)}"
    )
    point, lo, hi = _bootstrap_ci(algo_trades)
    print(
        f"  가중합 부트스트랩95%CI: [{lo * 100:+.2f}%, {hi * 100:+.2f}%] (point={point * 100:+.2f}%)"
    )
    first = second = 0.0
    if n >= 6:
        first, second = _split_half(algo_trades)
        print(f"  전/후반 분할: 전반={first:+.2f}%  후반={second:+.2f}%")
    returns = np.array([t.ret_pct for t in algo_trades])
    dsr = deflated_sharpe_ratio(returns, n_trials=2)
    print(f"  DSR(n_trials=2)={dsr['dsr']:.3f}  sharpe={dsr['sharpe']:.3f}")
    return {
        "label": label,
        "symbol": symbol,
        "n": n,
        "win_rate": win_rate,
        "sum_w_pct": sum_w,
        "pf": pf,
        "ci_lo_pct": lo * 100,
        "ci_hi_pct": hi * 100,
        "split_first_pct": first,
        "split_second_pct": second,
        "dsr": dsr["dsr"],
    }


async def _run_symbol(db, symbol: str, macro_rows: list[dict], from_dt, to_dt) -> list:
    warmup = 220
    profile_id = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    profile = frequency.get_frequency_profile(profile_id)
    return await backtest.load_frames_from_supabase(
        db,
        symbol=symbol,
        interval=profile.interval,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_dt,
        to_date=to_dt,
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows[-1]["reference_date"], tz=timezone.utc).to_pydatetime()
    print(
        f"macro 백필: {len(macro_rows)}일 {macro_rows[0]['reference_date']}~"
        f"{macro_rows[-1]['reference_date']}"
    )

    settings_perp = backtest.BacktestSettings(product_type="usdm_perp")

    await positions.init()
    db = positions.db()

    results: list[dict] = []
    for symbol in args.symbols:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")
        frames = await _run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        if not frames:
            print(f"  frames 없음 — {symbol} 히스토리 확인 필요")
            continue
        print(
            f"  frames={len(frames)}  {frames[0].bar.close_time.date()}~"
            f"{frames[-1].bar.close_time.date()}"
        )
        buy_hold = (frames[-1].bar.close / frames[0].bar.close - 1.0) * 100
        print(f"  buy&hold(구간 전체): {buy_hold:+.2f}%")

        for label, variant_fns in (
            ("direction_soft", VARIANTS_A),
            ("direction_hard_reint", VARIANTS_B),
        ):
            result = backtest.run_replay(frames, strategy_fns=variant_fns, settings=settings_perp)
            results.append(_summarize(f"multi_factor_short[{label}]", symbol, result.trades))

    print(f"\n{'=' * 70}\n요약표\n{'=' * 70}")
    header = (
        f"{'label':38s} {'symbol':10s} {'n':>4s} {'win%':>6s} {'sum_w%':>8s} {'PF':>6s} "
        f"{'CI_lo%':>8s} {'CI_hi%':>8s} {'전반%':>7s} {'후반%':>7s} {'DSR':>6s}"
    )
    print(header)
    for r in results:
        if r.get("n", 0) == 0:
            print(f"{r['label']:38s} {r['symbol']:10s} {0:>4d}  거래없음")
            continue
        print(
            f"{r['label']:38s} {r['symbol']:10s} {r['n']:>4d} {r['win_rate']:>6.1f} "
            f"{r['sum_w_pct']:>+8.2f} {(r['pf'] if math.isfinite(r['pf']) else 99.99):>6.2f} "
            f"{r['ci_lo_pct']:>+8.2f} {r['ci_hi_pct']:>+8.2f} "
            f"{r['split_first_pct']:>+7.2f} {r['split_second_pct']:>+7.2f} {r['dsr']:>6.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
