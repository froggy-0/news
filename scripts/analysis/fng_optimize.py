"""fng_contrarian 수익 극대화 실험 매트릭스.

진단(문제1 물타기·문제2 조기 flat 청산)에 대응하는 파라미터 변형을 동일 프레임에
run_replay로 돌려 비교. 지표: fng 복리 종가자산(weight 가중) + 승률 + 최악 트레이드.
파라미터 변조만 사용(코드 변경 없음) → 가장 유망한 설정을 코드에 반영하기 전 정량 검증.

재현: .venv/bin/python3 scripts/analysis/fng_optimize.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path("/Users/giwon/code/news/src")))
sys.path.insert(0, str(Path("/Users/giwon/code/news/scripts/analysis")))
from backtest_with_macro_backfill import build_macro_rows

from arena import backtest, frequency, parameters, positions

T3 = ((0.0, 0.15), (-0.03, 0.25), (-0.06, 0.30))  # 현행 3단 물타기
S15 = ((0.0, 0.15),)  # 단일 트랜치 w=0.15 (물타기 제거)
S40 = ((0.0, 0.40),)  # 단일 트랜치 w=0.40 (물타기 제거 + 사이즈 업)
S55 = ((0.0, 0.55),)  # 단일 트랜치 w=0.55

# (label, tranches, time_stop_h, min_hold_h) — 승자(3단·오래보유) 주변 정밀 탐색
CONFIGS = [
    ("B0 현행 v21 (3단·ts48·mh24)", T3, 48, 24),
    ("3단 ts60·mh36", T3, 60, 36),
    ("3단 ts72·mh36", T3, 72, 36),
    ("3단 ts72·mh48", T3, 72, 48),
    ("3단 ts84·mh48", T3, 84, 48),
    ("3단 ts96·mh48", T3, 96, 48),
    ("3단 ts96·mh60", T3, 96, 60),
    ("3단 ts120·mh48", T3, 120, 48),
    ("3단 ts120·mh72", T3, 120, 72),
    ("물타기off 0.15 ts72·mh48", S15, 72, 48),
]


def fng_metrics(trades):
    fng = [t for t in trades if t.algo_id == "fng_contrarian"]
    if not fng:
        return None
    eq = 1.0
    peak = 1.0
    maxdd = 0.0
    for t in sorted(fng, key=lambda x: x.close_time):
        eq *= 1.0 + t.position_weight * t.ret_pct
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1.0)
    wins = sum(1 for t in fng if t.ret_pct > 0)
    worst = min(t.ret_pct for t in fng) * 100
    return dict(n=len(fng), eq=eq, win=wins / len(fng) * 100, maxdd=maxdd * 100, worst=worst)


async def main():
    macro_rows = build_macro_rows(
        Path("/Users/giwon/code/news/data/sentiment_join/master_20260710.parquet")
    )
    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )

    # 원복용 백업
    o_tr = parameters.FNG_CONTRARIAN_PRICE_TRANCHES
    o_ts = parameters.TIME_STOP_HOURS_BY_ALGO.get("fng_contrarian")
    o_mh = parameters.MIN_HOLD_HOURS.get("fng_contrarian")

    rows = []
    for label, tr, ts, mh in CONFIGS:
        parameters.FNG_CONTRARIAN_PRICE_TRANCHES = tr
        parameters.TIME_STOP_HOURS_BY_ALGO["fng_contrarian"] = float(ts)
        parameters.MIN_HOLD_HOURS["fng_contrarian"] = float(mh)
        res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        m = fng_metrics(res.trades)
        rows.append((label, m))

    parameters.FNG_CONTRARIAN_PRICE_TRANCHES = o_tr
    parameters.TIME_STOP_HOURS_BY_ALGO["fng_contrarian"] = o_ts
    parameters.MIN_HOLD_HOURS["fng_contrarian"] = o_mh

    print(f"\n{'config':40} {'n':>3} {'종가자산':>8} {'승률':>6} {'MaxDD':>7} {'최악':>7}")
    print("-" * 78)
    for label, m in sorted(rows, key=lambda r: -r[1]["eq"]):
        print(
            f"{label:40} {m['n']:>3} {m['eq']:>8.4f} {m['win']:>5.1f}% {m['maxdd']:>+6.1f}% {m['worst']:>+6.1f}%"
        )


asyncio.run(main())
