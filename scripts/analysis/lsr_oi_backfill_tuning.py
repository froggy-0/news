"""LSR(글로벌 롱숏비)·OI 다이버전스 4h 아카이브 백필 A/B — D1 후속 (2026-08-11).

배경: docs/arena/research/binance-data-catalog-audit-20260811.md D1 + metrics_archive_features.py.
`_lsr_crowded`(macro['long_short_ratio_zscore'])와 `_oi_diverged`(macro['oi_divergence_flag'])는
지금까지 sentiment_join parquet의 일간 lag1 z(2025-01~)로만 백테스트됐다 — 그 이전 구간은
macro 자체가 없어 두 게이트가 항상 통과(None→graceful)였고, 있는 구간도 일간 해상도라 4h 봉
안에서는 하루 종일 값이 고정된다. futures/um/daily/metrics 아카이브(5분)로 재구성한 진짜 4h
해상도 값으로 교체했을 때 regime_trend(WI-1 secondary vote)·macd_momentum(secondary vote)·
multi_factor(hard veto)·omnibus(UP_TREND hard veto)가 달라지는지 검증한다.

⚠️ taker_ratio_4h(WI-10)는 이 아카이브로 재현 불가능함이 실측으로 확정됐다(metrics_archive_
features.py 모듈 docstring 참조) — 이 스크립트는 LSR·OI만 다룬다.

방법: baseline은 기존 macro_rows(일간 lag1) 그대로. variant는 각 프레임의 macro 중
long_short_ratio_zscore/oi_divergence_flag만 아카이브 4h 값으로 덮어쓴다(다른 macro 키는
그대로 — daily fng/vix 등은 애초에 일간 해상도가 본질이라 대상 아님). ReplayFrame이 frozen
dataclass라 dataclasses.replace로 새 macro dict를 가진 새 프레임을 만들어 baseline frames는
전혀 건드리지 않는다.

재현:
  .venv/bin/python3 scripts/analysis/lsr_oi_backfill_tuning.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from metrics_archive_features import (  # noqa: E402
    OI_DIVERGENCE_LOOKBACK_BARS,
    build_symbol_features,
)
from validation_stats import deflated_sharpe_ratio, effective_trial_count  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

TARGET_ALGOS = ["regime_trend", "macd_momentum", "multi_factor", "omnibus"]
ALL_ALGOS = [*TARGET_ALGOS, "fng_contrarian", "vix_rsi"]


def _algo_stats(trades: list, algo_id: str) -> dict:
    ts = [t for t in trades if t.algo_id == algo_id]
    n = len(ts)
    if n == 0:
        return {"n": 0, "sum_w_ret": 0.0, "win": 0.0, "rets": []}
    sum_w = sum(t.ret_pct * t.position_weight for t in ts) * 100
    win = sum(1 for t in ts if t.ret_pct > 0) / n * 100
    return {"n": n, "sum_w_ret": sum_w, "win": win, "rets": [t.ret_pct for t in ts]}


def _line(label: str, base: dict, var: dict) -> str:
    d = var["sum_w_ret"] - base["sum_w_ret"]
    flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
    return (
        f"  {flag} {label:16} n {base['n']:>3}→{var['n']:<3} "
        f"win {base['win']:>4.0f}→{var['win']:<4.0f} "
        f"sum_w_ret {base['sum_w_ret']:>+6.2f}→{var['sum_w_ret']:<+6.2f}  Δ{d:+.2f}"
    )


def _bucket_key(close_time) -> "pd.Timestamp":
    """arena_ohlcv_bars.close_time은 다음 4h 경계 -1초(예: 23:59:59)로 저장된다 —
    아카이브 bar_close(정확히 0/4/8..시 경계)와 정렬하려면 +1초로 경계에 맞춘다."""
    return pd.Timestamp(close_time) + pd.Timedelta(seconds=1)


def build_overlay(frames: list, symbol: str) -> tuple[pd.Series, pd.Series]:
    """archive 4h LSR z-score + 가격-OI 다이버전스 플래그를 프레임 close 시각 인덱스로 반환."""
    start = frames[0].bar.close_time.date() - timedelta(days=45)  # 롤링 z 워밍업 여유
    end = frames[-1].bar.close_time.date()
    feats = build_symbol_features(symbol, start, end)

    keys = [_bucket_key(f.bar.close_time) for f in frames]
    closes = pd.Series({k: f.bar.close for k, f in zip(keys, frames, strict=True)}).sort_index()
    price_ret_7d = closes.pct_change(OI_DIVERGENCE_LOOKBACK_BARS)
    oi_change = feats["oi_change_7d_4h"].reindex(closes.index)
    divergence_flag = ((price_ret_7d > 0) != (oi_change > 0)).astype(float)
    divergence_flag[price_ret_7d.isna() | oi_change.isna()] = float("nan")

    lsr_z = feats["long_short_ratio_zscore_4h"].reindex(closes.index)
    return lsr_z, divergence_flag


def overlay_frames(frames: list, lsr_z: pd.Series, oi_flag: pd.Series) -> list:
    out = []
    for f in frames:
        ts = _bucket_key(f.bar.close_time)
        overrides = {}
        if ts in lsr_z.index and pd.notna(lsr_z.loc[ts]):
            overrides["long_short_ratio_zscore"] = float(lsr_z.loc[ts])
        if ts in oi_flag.index and pd.notna(oi_flag.loc[ts]):
            overrides["oi_divergence_flag"] = float(oi_flag.loc[ts])
        if overrides:
            new_macro = {**f.macro, **overrides}
            out.append(dataclasses.replace(f, macro=new_macro))
        else:
            out.append(f)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--limit", type=int, default=2000)
    args = ap.parse_args()
    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=args.symbol,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=args.limit,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ "
        f"{frames[-1].bar.close_time.date()}"
    )

    # baseline macro 커버리지 확인(참고용)
    lsr_base_n = sum(1 for f in frames if f.macro.get("long_short_ratio_zscore") is not None)
    oi_base_n = sum(1 for f in frames if f.macro.get("oi_divergence_flag") is not None)
    print(
        f"baseline(일간 lag1 parquet) 커버리지: lsr {lsr_base_n}/{len(frames)}  "
        f"oi {oi_base_n}/{len(frames)}"
    )

    lsr_z, oi_flag = build_overlay(frames, args.symbol)
    lsr_arc_n = int(lsr_z.notna().sum())
    oi_arc_n = int(oi_flag.notna().sum())
    print(f"archive(4h) 커버리지: lsr {lsr_arc_n}/{len(frames)}  oi {oi_arc_n}/{len(frames)}")

    variant_frames = overlay_frames(frames, lsr_z, oi_flag)

    base_trades = backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades
    var_trades = backtest.run_replay(variant_frames, settings=backtest.BacktestSettings()).trades

    print("\n=== LSR·OI 4h 아카이브 백필 (baseline=일간 lag1 → variant=4h 아카이브) ===")
    decisions = {}
    for algo in TARGET_ALGOS:
        b = _algo_stats(base_trades, algo)
        v = _algo_stats(var_trades, algo)
        print(_line(algo, b, v))
        decisions[algo] = {
            "baseline": {
                "n": b["n"],
                "win": round(b["win"], 1),
                "sum_w_ret": round(b["sum_w_ret"], 3),
            },
            "variant": {
                "n": v["n"],
                "win": round(v["win"], 1),
                "sum_w_ret": round(v["sum_w_ret"], 3),
            },
        }
        usable = {"baseline": b["rets"], "variant": v["rets"]}
        usable = {k: r for k, r in usable.items() if len(r) >= 5}
        if len(usable) == 2:
            best = "variant" if v["sum_w_ret"] > b["sum_w_ret"] else "baseline"
            n_trials = effective_trial_count(2, algo_id=algo)
            dsr = deflated_sharpe_ratio(np.asarray(usable[best]), n_trials)
            print(
                f"      best={best}  DSR sharpe={dsr['sharpe']:.3f} "
                f"dsr={dsr['dsr']:.3f} n_trials={n_trials}"
            )
            decisions[algo]["dsr"] = round(dsr["dsr"], 3)

    # 비대상 알고 무회귀 확인(fng_contrarian/vix_rsi는 lsr/oi 게이트 미사용)
    print("\n비대상 알고 무회귀 확인:")
    for algo in ["fng_contrarian", "vix_rsi"]:
        b = _algo_stats(base_trades, algo)
        v = _algo_stats(var_trades, algo)
        d = v["sum_w_ret"] - b["sum_w_ret"]
        tag = "OK" if abs(d) < 0.01 else "⚠️ 변화 감지(버그 의심)"
        print(f"  {algo:16} Δ{d:+.4f}  {tag}")

    out = (
        Path(__file__).resolve().parents[2]
        / "docs/arena/research/lsr-oi-backfill-tuning-results.json"
    )
    import json

    out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
