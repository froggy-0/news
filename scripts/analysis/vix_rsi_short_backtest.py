"""vix_rsi 숏 진입 후보 격리 백테스트 (Phase B §3.5/§1원칙3 5순위).

배경: docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md §3.5.
`macd_momentum`(§8)·`omnibus`(§9)·`regime_trend`(§10)·`multi_factor`(§11) 숏 후보가
모두 기각된 뒤 순서상 다음 알고. §3.5가 명시하듯 vix_rsi는 "VIX가 낮을 때 진입하는"
역발산 전략이라 **롱 조건의 부호 반전이 숏의 자연스러운 거울이 아니다** — "VIX가
높을 때 공포 숏"은 롱과 별개의 진입 가설이라 이 스크립트는 §3.5 원문 그대로
새 가설을 세운다: VIX **고조**(calm의 정반대) + RSI **과열 진입**(과매도 진입의 대칭).

핵심 조건: VIX 고조(vix_now >= vix_q40 * VIX_CALM_TOLERANCE_BAND, 미수집 시 vix_now
>= 20.0 fallback) + RSI > (100 - VIX_RSI_LONG_MAX) = RSI > 50(대칭). risk-off veto는
§3.1/§3.4와 동일한 미해결 질문이라 두 변형(유지/제거)을 비교한다(그리드 아닌 사전
설계값 2개). 환경필터 2개(breadth/stablecoin)는 방향 무관 건전성 신호라 롱과 동일하게
N-of-M(1-of-2, VIX_RSI_ENTRY_MIN_SECONDARY_VOTES 재사용) 유지. `momentum_not_worsening`
(칼받기 방지, v26 정량검증 완료)의 거울인 `momentum_not_improving`(MACD 히스토그램이
직전봉보다 커지지 않을 때만 숏 — 상승 가속이 이미 멈췄는지 확인, "고점 추격 매도"
회피)도 적용한다.

ALGORITHMS dict·PERP_SHORT_ENABLED_TRACKS·algorithms.py 어느 것도 건드리지 않음 —
backtest.run_replay(strategy_fns=...)로 algo_id="vix_rsi"만 오버라이드해
product_type="usdm_perp" 상태머신에 태운다.

재현:
  .venv/bin/python3 scripts/analysis/vix_rsi_short_backtest.py
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


def _momentum_not_improving(ind: dict) -> bool:
    """`_momentum_not_worsening`(algorithms.py)의 거울 — 상승 가속이 아직 안 멈췄으면
    False(숏 보류). MACD 히스토그램이 직전봉보다 커지지 않을 때만 True."""
    mh = ind.get("macd_hist")
    mhp = ind.get("macd_hist_prev")
    if mh is None or mhp is None:
        return True
    try:
        mh_f, mhp_f = float(mh), float(mhp)
    except (TypeError, ValueError):
        return True
    return mh_f <= mhp_f


def _vix_rsi_short_env_ok(macro: dict) -> bool:
    votes = {
        "breadth_not_collapsed": not algorithms._breadth_collapsed(macro),
        "stablecoin_not_contracting": not algorithms._stablecoin_contracting(macro),
    }
    return sum(votes.values()) >= parameters.VIX_RSI_ENTRY_MIN_SECONDARY_VOTES


def _vix_rsi_short_core(macro: dict, ind: dict) -> bool:
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    rsi = ind.get("rsi", 50.0)
    if vix_now is None:
        return False
    if not _vix_rsi_short_env_ok(macro):
        return False
    if not _momentum_not_improving(ind):
        return False
    vix_elevated = (
        (vix_now >= vix_q40 * parameters.VIX_CALM_TOLERANCE_BAND) if vix_q40 else (vix_now >= 20.0)
    )
    if not vix_elevated:
        return False
    return rsi > (100.0 - parameters.VIX_RSI_LONG_MAX)


def vix_rsi_short_veto_kept(macro: dict, ind: dict) -> str | None:
    if _is_risk_off(_regime_state(macro)):
        return None
    return "short" if _vix_rsi_short_core(macro, ind) else None


def vix_rsi_short_veto_removed(macro: dict, ind: dict) -> str | None:
    return "short" if _vix_rsi_short_core(macro, ind) else None


VARIANTS_VETO_KEPT: dict[str, backtest.StrategyFn] = {"vix_rsi": vix_rsi_short_veto_kept}
VARIANTS_VETO_REMOVED: dict[str, backtest.StrategyFn] = {"vix_rsi": vix_rsi_short_veto_removed}


def _summarize(label: str, symbol: str, trades: list) -> dict:
    algo_trades = [t for t in trades if t.algo_id == "vix_rsi"]
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
            ("veto유지", VARIANTS_VETO_KEPT),
            ("veto제거", VARIANTS_VETO_REMOVED),
        ):
            result = backtest.run_replay(frames, strategy_fns=variant_fns, settings=settings_perp)
            results.append(_summarize(f"vix_rsi_short[{label}]", symbol, result.trades))

    print(f"\n{'=' * 70}\n요약표\n{'=' * 70}")
    header = (
        f"{'label':28s} {'symbol':10s} {'n':>4s} {'win%':>6s} {'sum_w%':>8s} {'PF':>6s} "
        f"{'CI_lo%':>8s} {'CI_hi%':>8s} {'전반%':>7s} {'후반%':>7s} {'DSR':>6s}"
    )
    print(header)
    for r in results:
        if r.get("n", 0) == 0:
            print(f"{r['label']:28s} {r['symbol']:10s} {0:>4d}  거래없음")
            continue
        print(
            f"{r['label']:28s} {r['symbol']:10s} {r['n']:>4d} {r['win_rate']:>6.1f} "
            f"{r['sum_w_pct']:>+8.2f} {(r['pf'] if math.isfinite(r['pf']) else 99.99):>6.2f} "
            f"{r['ci_lo_pct']:>+8.2f} {r['ci_hi_pct']:>+8.2f} "
            f"{r['split_first_pct']:>+7.2f} {r['split_second_pct']:>+7.2f} {r['dsr']:>6.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
