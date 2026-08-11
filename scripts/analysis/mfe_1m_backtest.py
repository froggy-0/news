"""P2 1분 MFE/MAE 재검증 — 전체 백테스트 구간 확장판 (D5, 2026-08-11 카탈로그 감사 후속).

배경: 2026-07-21 P2(§9, arena-status-review-20260721.md)가 `arena_realtime_feature_bars`
(라이브 가동 이후만 존재, last_price만 기록)로 1분 MFE를 재검증해 `vix_rsi`의 4h 진단이
해상도 아티팩트였음을 밝혔지만(포착률 -7%→+51%), 라이브 구간이 짧아 `fng_contrarian`(n
적음)·`multi_factor`는 결론 신뢰도가 낮았다. spot 1m klines 아카이브(2017-08~, **실제
high/low 포함** — 라이브 last_price 샘플링보다 정밀)로 같은 분석을 백테스트 전체 구간
(master_20260710.parquet macro 백필 창)에서 재현한다.

방법: `backtest_with_macro_backfill.build_macro_rows` + `backtest.load_frames_from_supabase`
+ `backtest.run_replay`로 BTC 백테스트 거래를 생성 → 각 거래의 [open_time, close_time]
구간에 걸리는 1m 아카이브 high/low로 MFE(=max(high)/open_price-1)·MAE(=min(low)/open_price-1)
산출 → 4h봉 기반 기존 진단(exit_tuning.py 계열, arena_status.py 섹션3)과 대조.

재현:
  .venv/bin/python3 scripts/analysis/mfe_1m_backtest.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from spot_klines_1m_archive import load_range  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGOS = ["regime_trend", "fng_contrarian", "vix_rsi", "macd_momentum", "multi_factor", "omnibus"]
COVERAGE_MIN = 80.0


def _mfe_mae_1m(trade, klines_1m) -> tuple[float, float, float] | None:
    op = trade.open_price
    if op <= 0 or trade.close_time <= trade.open_time:
        return None
    window = klines_1m[
        (klines_1m["open_time"] >= trade.open_time) & (klines_1m["open_time"] <= trade.close_time)
    ]
    if window.empty:
        return None
    expected_minutes = max((trade.close_time - trade.open_time).total_seconds() / 60.0, 1.0)
    coverage = len(window) / expected_minutes * 100
    mfe = float(window["high"].max()) / op - 1.0
    mae = float(window["low"].min()) / op - 1.0
    return mfe, mae, coverage


def _mfe_mae_4h(trade, frames) -> tuple[float, float] | None:
    """동일 거래를 백테스트가 실제로 쓰는 4h봉 high/low로 계산 — 1m과 직접 대조용
    (arena_status.py 섹션3·exit_tuning.py가 쓰는 것과 동일 해상도/정의)."""
    op = trade.open_price
    if op <= 0:
        return None
    bars = [f.bar for f in frames if trade.open_time <= f.bar.close_time <= trade.close_time]
    if not bars:
        return None
    mfe = max(b.high for b in bars) / op - 1.0
    mae = min(b.low for b in bars) / op - 1.0
    return mfe, mae


def _capture(rows: list[tuple[float, float, float]]) -> tuple[float, float, float | None]:
    avg_mfe = statistics.mean(r[0] for r in rows) * 100
    avg_mae = statistics.mean(r[1] for r in rows) * 100
    caps = [r[2] / r[0] for r in rows if r[0] > 0.003]
    cap = statistics.mean(caps) * 100 if caps else None
    return avg_mfe, avg_mae, cap


def _report(label: str, trades: list, klines_1m, frames) -> dict:
    print(f"\n=== {label} ===")
    print(
        "algo | n(1m usable) | MFE_4h% | 포착률_4h% || MFE_1m% | MAE_1m% | 포착률_1m% | 평균커버리지%"
    )
    by_algo = defaultdict(list)
    for t in trades:
        by_algo[t.algo_id].append(t)
    out: dict = {}
    for algo in ALGOS:
        ts = by_algo.get(algo, [])
        rows_1m = []
        rows_4h = []
        excluded = 0
        for t in ts:
            mm = _mfe_mae_1m(t, klines_1m)
            if mm is None:
                continue
            mfe_1m, mae_1m, cov = mm
            if cov < COVERAGE_MIN:
                excluded += 1
                continue
            rows_1m.append((mfe_1m, mae_1m, t.ret_pct, cov))
            mm4h = _mfe_mae_4h(t, frames)
            if mm4h is not None:
                rows_4h.append((mm4h[0], mm4h[1], t.ret_pct))
        if not rows_1m:
            print(f"{algo} | n=0 (usable 없음, 제외={excluded}, 전체={len(ts)})")
            out[algo] = {"n": 0, "total": len(ts), "excluded": excluded}
            continue
        avg_mfe_1m, avg_mae_1m, cap_1m = _capture([(r[0], r[1], r[2]) for r in rows_1m])
        avg_cov = statistics.mean(r[3] for r in rows_1m)
        avg_mfe_4h, _, cap_4h = _capture(rows_4h) if rows_4h else (float("nan"), float("nan"), None)
        cap_1m_str = f"{cap_1m:+.0f}" if cap_1m is not None else "n/a"
        cap_4h_str = f"{cap_4h:+.0f}" if cap_4h is not None else "n/a"
        print(
            f"{algo} | n={len(rows_1m)}(제외{excluded}) | {avg_mfe_4h:+.2f} | {cap_4h_str} || "
            f"{avg_mfe_1m:+.2f} | {avg_mae_1m:+.2f} | {cap_1m_str} | {avg_cov:.0f}"
        )
        out[algo] = {
            "n": len(rows_1m),
            "excluded": excluded,
            "avg_mfe_4h_pct": round(avg_mfe_4h, 3) if rows_4h else None,
            "capture_rate_4h_pct": round(cap_4h, 1) if cap_4h is not None else None,
            "avg_mfe_1m_pct": round(avg_mfe_1m, 3),
            "avg_mae_1m_pct": round(avg_mae_1m, 3),
            "capture_rate_1m_pct": round(cap_1m, 1) if cap_1m is not None else None,
            "avg_coverage_pct": round(avg_cov, 1),
        }
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--limit", type=int, default=5000)
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
    result = backtest.run_replay(frames, settings=backtest.BacktestSettings())
    trades = result.trades
    print(f"trades={len(trades)}")

    range_start = min(t.open_time for t in trades).date()
    range_end = max(t.close_time for t in trades).date() + timedelta(days=1)
    print(f"1m 아카이브 로드: {args.symbol} {range_start} ~ {range_end}")
    klines_1m = load_range(args.symbol, range_start, range_end)
    print(f"1m 봉 {len(klines_1m)}건 로드")

    results = _report(
        f"전체 백테스트 구간 ({frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}, "
        f"동일 거래셋의 4h vs 1m 해상도 직접 대조)",
        trades,
        klines_1m,
        frames,
    )

    print(
        "\n판정 가이드: 4h 포착률과 1m 포착률이 같은 방향(둘 다 음수/둘 다 양수)이면 해상도는"
        " 무관하고 진입/청산 설계가 진짜 원인. 부호가 뒤집히면(4h 음수→1m 양수) 4h 진단이"
        " 해상도 아티팩트였다는 뜻(2026-07-21 P2가 vix_rsi에서 발견한 패턴)."
    )

    out = (
        Path(__file__).resolve().parents[2] / "docs/arena/research/d5-mfe-1m-backtest-results.json"
    )
    import json

    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
