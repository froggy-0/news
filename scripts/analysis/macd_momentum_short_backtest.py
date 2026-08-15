"""macd_momentum 숏 진입 후보 격리 백테스트 (Phase B §3.1/§7).

배경: docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md §3.1.
Nonlinear TSMOM(TSMOM_NL_ENABLED=True, 라이브 기본)의 연속·부호형 신호
s = T봉누적수익률/(√T·σ̂)를 그대로 대칭 반전 — s < -TSMOM_NL_MIN_SIGNAL이면 숏,
사이징은 f(s)=s/(s²+1)의 절댓값. risk-off veto 유지/제거 두 변형을 비교한다.

ALGORITHMS dict·PERP_LIVE_ENABLED_ALGOS·algorithms.py 어느 것도 건드리지 않음 —
backtest.run_replay(strategy_fns=...) 오버라이드 + product_type="usdm_perp"로만
검증(§4 방법론). algo_id를 "macd_momentum"으로 재사용해야 backtest._open_position의
TSMOM_NL 사이징 배선(algorithms.py:387-388)이 그대로 걸리는데, 그 함수는 음수 신호를
0으로 클립하도록 하드코딩돼 있다(§2 — "아레나는 스팟 롱온리라 숏 미실행"). 이 스크립트는
그 클립을 런타임에만 우회하도록 arena.algorithms.tsmom_nl_position_multiplier를
abs(f(s)) 버전으로 몽키패치한다(프로세스 로컬, 소스 파일 무변경) — 이 백테스트가
단일방향(숏 후보만 신호를 냄)이라 부작용 없음. 실제 채택 시엔 §2가 요구하는 대로
product_type 분기를 코드에 반영해야 한다(이 스크립트는 그 전 단계의 검증용).

재현:
  .venv/bin/python3 scripts/analysis/macd_momentum_short_backtest.py
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
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402
from arena.algorithms import _is_risk_off, _regime_state, _tsmom_nl_signal  # noqa: E402

# ── 사이징 몽키패치: f(s)의 절댓값(부호 대칭). 소스(algorithms.py) 무변경, 프로세스 로컬. ──


def _tsmom_nl_position_multiplier_abs(macro: dict, ind: dict) -> float:
    if not parameters.TSMOM_NL_ENABLED:
        return 1.0
    s = _tsmom_nl_signal(ind)
    if s is None:
        return 0.0
    f = s / (s * s + 1.0)
    return max(0.0, min(parameters.TSMOM_NL_WEIGHT_CAP, abs(f)))


# ── 숏 후보 신호 함수 (§3.1 설계값, 그리드 아님) ──────────────────────────────


def macd_momentum_short_veto(macro: dict, ind: dict) -> str | None:
    """risk-off veto 유지 변형 — 롱 로직과 동일하게 risk-off면 무조건 보류."""
    if _is_risk_off(_regime_state(macro)):
        return None
    s = _tsmom_nl_signal(ind)
    if s is None:
        return None
    return "short" if s < -parameters.TSMOM_NL_MIN_SIGNAL else None


def macd_momentum_short_noveto(macro: dict, ind: dict) -> str | None:
    """risk-off veto 제거 변형 — 급락 지속(risk-off)에서도 숏 허용."""
    s = _tsmom_nl_signal(ind)
    if s is None:
        return None
    return "short" if s < -parameters.TSMOM_NL_MIN_SIGNAL else None


VARIANTS: dict[str, backtest.StrategyFn] = {
    "macd_momentum": macd_momentum_short_veto,  # veto유지: algo_id 재사용(사이징 배선 태움)
}
VARIANTS_NOVETO: dict[str, backtest.StrategyFn] = {
    "macd_momentum": macd_momentum_short_noveto,
}


def _bootstrap_ci(
    trades: list, n_resamples: int = 3000, seed: int = 42
) -> tuple[float, float, float]:
    if not trades:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    weighted = np.array([t.ret_pct * t.position_weight for t in trades])
    point = weighted.sum()
    n = len(weighted)
    resampled = rng.choice(weighted, size=(n_resamples, n), replace=True).sum(axis=1)
    lo, hi = np.percentile(resampled, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def _split_half(trades: list) -> tuple[float, float]:
    ts = sorted(trades, key=lambda t: t.open_time)
    mid = len(ts) // 2
    if mid == 0:
        return 0.0, 0.0
    first = sum(t.ret_pct * t.position_weight for t in ts[:mid]) * 100
    second = sum(t.ret_pct * t.position_weight for t in ts[mid:]) * 100
    return first, second


def _summarize(label: str, symbol: str, trades: list) -> dict:
    algo_trades = [t for t in trades if t.algo_id == "macd_momentum"]
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
    dsr = deflated_sharpe_ratio(returns, n_trials=1)
    print(f"  DSR(n_trials=1)={dsr['dsr']:.3f}  sharpe={dsr['sharpe']:.3f}")
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
    warmup = (
        parameters.MACD_SLOW_PERIOD
        + parameters.MACD_SIGNAL_PERIOD
        + parameters.TSMOM_NL_LOOKBACK_BARS
    )
    profile_id = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    profile = frequency.get_frequency_profile(profile_id)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=symbol,
        interval=profile.interval,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_dt,
        to_date=to_dt,
    )
    return frames


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
    print(
        f"TSMOM_NL_ENABLED={parameters.TSMOM_NL_ENABLED} "
        f"lookback={parameters.TSMOM_NL_LOOKBACK_BARS} vol_mode={parameters.TSMOM_NL_VOL_MODE} "
        f"min_signal={parameters.TSMOM_NL_MIN_SIGNAL} weight_cap={parameters.TSMOM_NL_WEIGHT_CAP}"
    )

    # 몽키패치 적용 확인(assert로 원본 함수가 여전히 존재하는지만 체크 — 코드 앵커 회귀 감지)
    assert hasattr(algorithms, "tsmom_nl_position_multiplier")
    algorithms.tsmom_nl_position_multiplier = _tsmom_nl_position_multiplier_abs

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
            ("veto유지", VARIANTS),
            ("veto제거", VARIANTS_NOVETO),
        ):
            result = backtest.run_replay(frames, strategy_fns=variant_fns, settings=settings_perp)
            results.append(_summarize(f"macd_momentum_short[{label}]", symbol, result.trades))

    print(f"\n{'=' * 70}\n요약표\n{'=' * 70}")
    header = f"{'label':32s} {'symbol':10s} {'n':>4s} {'win%':>6s} {'sum_w%':>8s} {'PF':>6s} {'CI_lo%':>8s} {'CI_hi%':>8s} {'전반%':>7s} {'후반%':>7s} {'DSR':>6s}"
    print(header)
    for r in results:
        if r.get("n", 0) == 0:
            print(f"{r['label']:32s} {r['symbol']:10s} {0:>4d}  거래없음")
            continue
        print(
            f"{r['label']:32s} {r['symbol']:10s} {r['n']:>4d} {r['win_rate']:>6.1f} "
            f"{r['sum_w_pct']:>+8.2f} {(r['pf'] if math.isfinite(r['pf']) else 99.99):>6.2f} "
            f"{r['ci_lo_pct']:>+8.2f} {r['ci_hi_pct']:>+8.2f} "
            f"{r['split_first_pct']:>+7.2f} {r['split_second_pct']:>+7.2f} {r['dsr']:>6.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
