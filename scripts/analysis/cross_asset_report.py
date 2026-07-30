"""BTC·ETH·SOL Track A/B 교차자산 성과 리포트 (P1-6).

설계: docs/arena/research/structural-priority-multi-asset-expansion-20260730.md
계획: docs/arena/research/multi-asset-implementation-plan-20260731.md

Track A(순수 가격·로컬레짐): regime_trend, macd_momentum, omnibus.
Track B(글로벌 컨텍스트+자산고유 타이밍): fng_contrarian, vix_rsi, multi_factor.

⚠️ 2026-07-31 코드검증 결과(설계문서 §3.1/§3.3): Track A 3개 알고도 funding_zscore·
long_short_ratio_zscore·etf_flow_zscore·btc_above_ma200 veto를 통해 BTC 전용
R2 파이프라인 산출물에 의존한다 — 3자산 전부 BTC 값을 공유(자산고유 아님). Track A를
"순수 자산고유 검증"으로 오독하지 말 것. arena_regime_state만 자산별 로컬 재계산.

실험원칙(설계문서 §4): 자산별 성과를 평균 내어 하나의 숫자로 합치지 않는다(원칙6) —
이 스크립트는 Algorithm × Asset 조합을 전부 개별 행으로 출력하고, Track A/B 결과를
섞지 않는다(원칙 3.2 disclosure).

재현:
  .venv/bin/python3 scripts/analysis/cross_asset_report.py \
      --parquet data/sentiment_join/master_20260710.parquet

선결: arena_ohlcv_bars에 ETHUSDT/SOLUSDT 히스토리가 있어야 함
      (scripts/analysis/backfill_ohlcv_symbol.py로 먼저 백필).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

TRACK_A = ("regime_trend", "macd_momentum", "omnibus")
TRACK_B = ("fng_contrarian", "vix_rsi", "multi_factor")
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _profile_for(symbol: str) -> frequency.FrequencyProfile:
    profile_id = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    return frequency.get_frequency_profile(profile_id)


def _buy_and_hold_pct(frames: list) -> float:
    if not frames:
        return 0.0
    return (frames[-1].bar.close / frames[0].bar.open - 1.0) * 100


def _mfe_mae_pct(frames_by_close: dict, trade) -> tuple[float, float]:
    """보유 구간 중 최대유리(MFE)·최대불리(MAE) — 4H봉 high/low 기준(보수적 근사, long-only)."""
    window = [
        f
        for f in frames_by_close["_sorted"]
        if trade.open_time <= f.bar.close_time <= trade.close_time
    ]
    if not window:
        return 0.0, 0.0
    highest = max(f.bar.high for f in window)
    lowest = min(f.bar.low for f in window)
    mfe = (highest / trade.open_price - 1.0) * 100
    mae = (lowest / trade.open_price - 1.0) * 100
    return mfe, mae


def _metrics_for_algo(algo_id: str, trades: list, frames: list, bh_pct: float) -> dict:
    algo_trades = [t for t in trades if t.algo_id == algo_id]
    n = len(algo_trades)
    if n == 0:
        return {"algo_id": algo_id, "n": 0}

    wins = [t for t in algo_trades if t.net_ret_pct > 0]
    losses = [t for t in algo_trades if t.net_ret_pct <= 0]
    win_pct = len(wins) / n * 100
    avg_win = (sum(t.net_ret_pct for t in wins) / len(wins) * 100) if wins else 0.0
    avg_loss = (sum(t.net_ret_pct for t in losses) / len(losses) * 100) if losses else 0.0
    expectancy = (len(wins) / n) * avg_win + (len(losses) / n) * avg_loss
    gross_profit = sum(t.net_ret_pct * t.position_weight for t in wins if t.net_ret_pct > 0)
    gross_loss = -sum(t.net_ret_pct * t.position_weight for t in losses if t.net_ret_pct <= 0)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    sum_w_ret = sum(t.net_ret_pct * t.position_weight for t in algo_trades) * 100

    # 누적 equity로 최대낙폭 계산 (거래 순서대로 복리).
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in sorted(algo_trades, key=lambda x: x.close_time):
        equity *= 1.0 + t.net_ret_pct * t.position_weight
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)

    frames_by_close = {"_sorted": sorted(frames, key=lambda f: f.bar.close_time)}
    mfe_list, mae_list = [], []
    for t in algo_trades:
        mfe, mae = _mfe_mae_pct(frames_by_close, t)
        mfe_list.append(mfe)
        mae_list.append(mae)
    avg_mfe = sum(mfe_list) / n
    avg_mae = sum(mae_list) / n

    total_hold_hours = sum(t.hold_hours for t in algo_trades)
    period_hours = (
        (frames[-1].bar.close_time - frames[0].bar.close_time).total_seconds() / 3600
        if len(frames) > 1
        else 1.0
    )
    exposure_pct = total_hold_hours / period_hours * 100 if period_hours > 0 else 0.0

    return {
        "algo_id": algo_id,
        "n": n,
        "win_pct": win_pct,
        "expectancy_pct": expectancy,
        "profit_factor": profit_factor,
        "sum_w_ret_pct": sum_w_ret,
        "excess_vs_bh_pct": sum_w_ret - bh_pct,
        "max_dd_pct": max_dd * 100,
        "avg_mfe_pct": avg_mfe,
        "avg_mae_pct": avg_mae,
        "exposure_pct": exposure_pct,
        "single_trade_dominance": (
            max((abs(t.net_ret_pct * t.position_weight) for t in algo_trades), default=0.0)
            / max(sum(abs(t.net_ret_pct * t.position_weight) for t in algo_trades), 1e-9)
            * 100
        ),
    }


def _print_track(label: str, track_algos: tuple[str, ...], results: dict) -> None:
    print(f"\n{'=' * 100}\nTrack {label}\n{'=' * 100}")
    header = (
        f"{'algo':16} {'asset':9} {'n':>4} {'win%':>6} {'expct%':>7} {'PF':>6} "
        f"{'sum_w%':>8} {'vsBH%':>8} {'maxDD%':>7} {'avgMFE%':>8} {'avgMAE%':>8} "
        f"{'expo%':>6} {'단일거래%':>8}"
    )
    print(header)
    for algo_id in track_algos:
        for symbol in ASSETS:
            m = results[symbol].get(algo_id, {"algo_id": algo_id, "n": 0})
            if m["n"] == 0:
                print(f"{algo_id:16} {symbol:9} {0:>4}  (거래 없음)")
                continue
            pf = m["profit_factor"]
            pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
            print(
                f"{algo_id:16} {symbol:9} {m['n']:>4} {m['win_pct']:>6.1f} "
                f"{m['expectancy_pct']:>+7.2f} {pf_str:>6} {m['sum_w_ret_pct']:>+8.2f} "
                f"{m['excess_vs_bh_pct']:>+8.2f} {m['max_dd_pct']:>7.2f} "
                f"{m['avg_mfe_pct']:>+8.2f} {m['avg_mae_pct']:>+8.2f} "
                f"{m['exposure_pct']:>6.1f} {m['single_trade_dominance']:>8.1f}"
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
    print(
        f"macro 스냅샷: {len(macro_rows)}일  "
        f"{macro_rows[0]['reference_date']} ~ {macro_rows[-1]['reference_date']}  "
        "(3자산 공유 — Track A/B 무관하게 BTC 시장전체 regimeRaw 재사용)"
    )

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    results: dict[str, dict[str, dict]] = {}
    bh_by_symbol: dict[str, float] = {}
    for symbol in ASSETS:
        profile = _profile_for(symbol)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=profile.interval,
            limit=4000,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
        )
        if not frames:
            print(f"⚠️ {symbol}: frames 없음 — arena_ohlcv_bars 백필 확인 필요. 스킵.")
            results[symbol] = {}
            bh_by_symbol[symbol] = 0.0
            continue
        res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        bh_pct = _buy_and_hold_pct(frames)
        bh_by_symbol[symbol] = bh_pct
        print(
            f"{symbol}: frames={len(frames)}  {frames[0].bar.close_time.date()} ~ "
            f"{frames[-1].bar.close_time.date()}  trades={len(res.trades)}  "
            f"buy&hold={bh_pct:+.2f}%"
        )
        results[symbol] = {
            algo_id: _metrics_for_algo(algo_id, res.trades, frames, bh_pct)
            for algo_id in TRACK_A + TRACK_B
        }

    _print_track(
        "A — 가격·로컬레짐 기반 (funding/LSR/MA200/ETF유출 veto는 BTC 공유값, §3.1 참조)",
        TRACK_A,
        results,
    )
    _print_track(
        "B — 글로벌 컨텍스트 공유 + 자산고유 타이밍 (FNG/VIX/ETF/breadth/stablecoin 전부 BTC 공유)",
        TRACK_B,
        results,
    )

    print(
        "\n※ Track A와 Track B 결과를 합쳐 '동일 룰의 일반화'로 해석하지 말 것"
        "(설계문서 원칙). 자산별 결과를 평균 내어 단일 판정하지 않음 — "
        "Algorithm×Asset 개별 행으로만 판단."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
