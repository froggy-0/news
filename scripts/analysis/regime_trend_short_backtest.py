"""regime_trend 숏 진입 후보 격리 백테스트 (Phase B §3.3/§1원칙3 3순위).

배경: docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md §3.3.
`macd_momentum`(§8)·`omnibus`(§9) 숏 후보가 모두 기각된 뒤 순서상 다음 알고.

숏 설계안(§3.3 표 그대로, 1차는 대칭 임계값 가정):
  핵심 4조건(전부 hard, 완화 대상 아님) — 롱의 거울:
    ① 약세 레짐 — `_is_bearish`는 신규 헬퍼 없이 기존 `_is_risk_off`(bear_trend/
       stress/BearPanic)를 그대로 재사용한다. 이 프로젝트의 레짐 어휘에 "약세이되
       risk-off는 아닌" 별도 상태 라벨이 없어(BullQuiet의 반대짝이 없음), 새 상태를
       발명하는 대신 기존 risk-off 버킷을 약세 정의로 채택 — 별도 가정 추가 없음.
    ② Donchian(20) **하단** 돌파(신저가, `close < donchian_lower`)
    ③ ADX ≥ 20(방향 무관 추세강도, 그대로 재사용)
    ④ EMA **역배열**(`ema_fast < ema_slow and ema_fast_slope < 0`)
  부차 8조건(품질필터, RELAXED 모드에서만 N-of-M 투표) — §3.3 표 미러:
    rsi_above_short_min(RSI>30, TREND_CORE_RSI_LONG_MAX의 대칭), funding_not_cold,
    etf_inflow_not_heavy, below_ema200_4h(`_below_ema_trend_strict` 그대로 재사용),
    taker_confirms_short(z 부호 대칭), volume_confirms(방향 무관, 그대로 재사용),
    lsr_not_crowded_short(z 부호 대칭), oi_not_diverged(**부호 재정의 보류** — §3.3이
    "부호 재정의 필요"라 명시했고 이 스크립트 시점엔 미확정이라 롱과 동일한 불리언을
    그대로 재사용하는 1차 대칭 가정을 씀. 결과가 통과선에 근접하면 재검토 대상).

STRICT(8개 전부)와 RELAXED(REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES=4/8, 라이브 롱과
동일 임계값) 두 변형을 비교한다 — 그리드가 아니라 두 사전 설계값.

ALGORITHMS dict·PERP_SHORT_ENABLED_TRACKS·algorithms.py 어느 것도 건드리지 않음 —
backtest.run_replay(strategy_fns=...)로 algo_id="regime_trend"만 오버라이드해
product_type="usdm_perp" 상태머신(§4)에 태운다. 사이징은 regime_trend에 전용 곡선이
없어(연속신호 아님) 몽키패치 불필요 — 기존 combined_position_weight 그대로.

재현:
  .venv/bin/python3 scripts/analysis/regime_trend_short_backtest.py
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

# ── 약세 레짐 판정 — 신규 헬퍼 없이 기존 risk-off 어휘 재사용(파일 docstring 참조) ──


def _is_bearish(state: str | None) -> bool:
    return algorithms._is_risk_off(state)


# ── 부차 8조건 숏 미러 (§3.3 표, 1차 대칭 임계값 가정) ──────────────────────────


def _regime_trend_short_secondary_votes(macro: dict, ind: dict) -> dict[str, bool]:
    rsi = ind.get("rsi", 50.0)

    def _z(key: str) -> float | None:
        v = macro.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    funding_z = _z("funding_zscore")
    etf_z = _z("etf_flow_zscore")
    lsr_z = _z("long_short_ratio_zscore")
    taker_z = _z("taker_imbalance_zscore")

    return {
        # 롱 rsi_below_long_max(<70)의 50 중심 대칭: RSI>30(과매도 진입 전).
        "rsi_above_short_min": rsi > (100.0 - parameters.TREND_CORE_RSI_LONG_MAX),
        # 롱 funding_not_hot(z<1.5)의 부호 대칭: 숏 과밀(cold) 아님.
        "funding_not_cold": not (
            funding_z is not None and funding_z <= -parameters.FUNDING_HOT_ZSCORE
        ),
        # 롱 etf_outflow_not_heavy(z>=-1.5)의 부호 대칭: 대량 유입 아님.
        "etf_inflow_not_heavy": not (
            etf_z is not None and etf_z >= abs(parameters.ETF_OUTFLOW_HEAVY_Z)
        ),
        # 그대로 재사용(§3.3: "직접 요구") — bull_trend 예외는 약세 레짐에서 발동 안 함.
        "below_ema200_4h": algorithms._below_ema_trend_strict(ind, macro),
        # 롱 taker_confirms(z>-0.5)의 부호 대칭: z<0.5(매수우위 과대 아님).
        "taker_confirms_short": not (
            taker_z is not None and taker_z >= -parameters.TAKER_CONFIRM_ZSCORE
        ),
        # 방향 무관 — 그대로 재사용(현재 VOLUME_CONFIRM_ENABLED=False라 백테스트 무효과).
        "volume_confirms": algorithms._volume_confirms(ind),
        # 롱 lsr_not_crowded(z<2.0)의 부호 대칭: 숏 과밀 아님.
        "lsr_not_crowded_short": not (
            lsr_z is not None and lsr_z <= -parameters.LSR_CROWDED_ZSCORE
        ),
        # 부호 재정의 보류 — 1차는 롱과 동일 불리언 재사용(파일 docstring 참조).
        "oi_not_diverged": not algorithms._oi_diverged(macro),
    }


def _regime_trend_short_core(macro: dict, ind: dict) -> bool:
    state = algorithms._regime_state(macro)
    close = ind.get("close", 0.0)
    dc_lower = ind.get("donchian_lower", 0.0)
    adx = ind.get("adx", 0.0)
    ema_fast = ind.get("ema_fast", 0.0)
    ema_slow = ind.get("ema_slow", 0.0)
    ema_fast_slope = ind.get("ema_fast_slope", 0.0)

    breakdown = dc_lower > 0 and close < dc_lower
    trending = adx >= parameters.ADX_TREND_MIN
    ema_reversed = ema_fast < ema_slow and ema_fast_slope < 0
    return _is_bearish(state) and breakdown and trending and ema_reversed


def regime_trend_short_strict(macro: dict, ind: dict) -> str | None:
    if not _regime_trend_short_core(macro, ind):
        return None
    secondary = _regime_trend_short_secondary_votes(macro, ind)
    return "short" if all(secondary.values()) else None


def regime_trend_short_relaxed(macro: dict, ind: dict) -> str | None:
    if not _regime_trend_short_core(macro, ind):
        return None
    secondary = _regime_trend_short_secondary_votes(macro, ind)
    ok = sum(secondary.values()) >= parameters.REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES
    return "short" if ok else None


VARIANTS_STRICT: dict[str, backtest.StrategyFn] = {"regime_trend": regime_trend_short_strict}
VARIANTS_RELAXED: dict[str, backtest.StrategyFn] = {"regime_trend": regime_trend_short_relaxed}


def _summarize(label: str, symbol: str, trades: list) -> dict:
    algo_trades = [t for t in trades if t.algo_id == "regime_trend"]
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
    dsr = deflated_sharpe_ratio(returns, n_trials=2)  # 사전 변형 2개(strict/relaxed)
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
    warmup = 220  # Donchian(20)/ADX/EMA200 워밍업 여유 — omnibus 스크립트와 동일 값
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
        f"REGIME_TREND_ENTRY_RELAXED_ENABLED(live long)={parameters.REGIME_TREND_ENTRY_RELAXED_ENABLED} "
        f"min_secondary_votes={parameters.REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES}/8"
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
            ("strict_8of8", VARIANTS_STRICT),
            ("relaxed_4of8", VARIANTS_RELAXED),
        ):
            result = backtest.run_replay(frames, strategy_fns=variant_fns, settings=settings_perp)
            results.append(_summarize(f"regime_trend_short[{label}]", symbol, result.trades))

    print(f"\n{'=' * 70}\n요약표\n{'=' * 70}")
    header = (
        f"{'label':34s} {'symbol':10s} {'n':>4s} {'win%':>6s} {'sum_w%':>8s} {'PF':>6s} "
        f"{'CI_lo%':>8s} {'CI_hi%':>8s} {'전반%':>7s} {'후반%':>7s} {'DSR':>6s}"
    )
    print(header)
    for r in results:
        if r.get("n", 0) == 0:
            print(f"{r['label']:34s} {r['symbol']:10s} {0:>4d}  거래없음")
            continue
        print(
            f"{r['label']:34s} {r['symbol']:10s} {r['n']:>4d} {r['win_rate']:>6.1f} "
            f"{r['sum_w_pct']:>+8.2f} {(r['pf'] if math.isfinite(r['pf']) else 99.99):>6.2f} "
            f"{r['ci_lo_pct']:>+8.2f} {r['ci_hi_pct']:>+8.2f} "
            f"{r['split_first_pct']:>+7.2f} {r['split_second_pct']:>+7.2f} {r['dsr']:>6.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
