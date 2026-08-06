"""P2 후속 — 고정 사양의 1d 봉 주기 경제성 감사.

p2-edge-cost-audit-20260804.md §4가 정한 다음 단계: "다음 의사결정은 새 4h 파라미터가
아니라 고정된 1d 주기 비교다. 1d에서도 양쪽 창 edge/cost ≥3과 통계 구간을 확보하지
못하면 현재 전략군의 확장 연구를 종료하는 것이 맞다."

알고리즘 사양(진입조건·MIN_HOLD·비용모형)은 전혀 새로 튜닝하지 않는다. 판정 빈도만
4h→1d로 낮춰 거래빈도/비용비중이 줄었을 때 edge/cost가 개선되는지만 본다.

arena_ohlcv_bars에는 1d interval이 없다(4h/1h/15m만 수집·백필됨, 2026-08-06 확인).
신규 Binance 수집 대신 이미 백필된 4h bar를 완전한 UTC 캘린더데이(4h봉 6개)로
재표본화한다 — 가격 데이터 자체는 4h 감사와 동일하므로 "같은 시장, 다른 판정 빈도"만
순수하게 분리해서 본다. 불완전한 경계일(6개 미만)은 버린다.

재현:
  .venv/bin/python3 scripts/analysis/daily_frequency_audit.py \
      --bear-parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from p2_edge_cost_audit import (  # noqa: E402
    ALGOS,
    ASSETS,
    EDGE_COST_THRESHOLD,
    _cross_window_algo_verdict,
    _cross_window_verdict,
    _parse_date,
    build_bull_macro_rows,
    edge_cost_metrics,
)

from arena import backtest, execution_rules, frequency, parameters, positions  # noqa: E402


def resample_4h_bars_to_daily(bar_rows: list[dict]) -> list[dict]:
    """완전한 UTC 캘린더데이(4h봉 정확히 6개)만 1d bar로 합성한다.

    부분일(첫/끝 경계) 왜곡을 피하려고 6개 미만인 날은 버린다 — Binance 4h 봉은
    00/04/08/12/16/20시 UTC에 마감하므로 정상적인 하루는 항상 6개다.
    """
    buckets: dict[date, list[dict]] = defaultdict(list)
    for row in bar_rows:
        day = execution_rules.parse_utc_datetime(row["open_time"]).date()
        buckets[day].append(row)

    daily_rows: list[dict] = []
    for day in sorted(buckets):
        rows = sorted(buckets[day], key=lambda r: r["open_time"])
        if len(rows) != 6:
            continue
        daily_rows.append(
            {
                "open_time": rows[0]["open_time"],
                "close_time": rows[-1]["close_time"],
                "open": float(rows[0]["open"]),
                "high": max(float(r["high"]) for r in rows),
                "low": min(float(r["low"]) for r in rows),
                "close": float(rows[-1]["close"]),
                "volume": sum(float(r.get("volume") or 0.0) for r in rows),
            }
        )
    return daily_rows


async def _fetch_raw_4h_bars(db, *, symbol: str, start: datetime, end: datetime) -> list[dict]:
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        res = await (
            db.table("arena_ohlcv_bars")
            .select("open_time,close_time,open,high,low,close,volume")
            .eq("symbol", symbol)
            .eq("interval", "4h")
            .gte("open_time", execution_rules.format_utc_timestamp(start))
            .lte("close_time", execution_rules.format_utc_timestamp(end))
            .order("open_time", desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return sorted(rows, key=lambda row: row["open_time"])


async def load_daily_frames(
    db,
    *,
    symbol: str,
    from_date: datetime,
    to_date: datetime,
    warmup_bars: int,
    indicator_profile_id: str,
    macro_rows: list[dict],
) -> list[backtest.ReplayFrame]:
    # 1d 웜업 warmup_bars일 + 안전마진 5일치 4h 원자재를 추가로 끌어온다
    # (load_frames_from_supabase의 hours=interval_hours*(warmup_bars+5) 관례와 동일 산식).
    pre_start = from_date - timedelta(days=warmup_bars + 5)
    raw_4h = await _fetch_raw_4h_bars(db, symbol=symbol, start=pre_start, end=to_date)
    daily_rows = resample_4h_bars_to_daily(raw_4h)
    return backtest.build_frames_from_bar_rows(
        daily_rows,
        interval="1d",
        warmup_bars=warmup_bars,
        indicator_profile_id=indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_date,
        to_date=to_date,
    )


def _daily_profile_for(symbol: str) -> frequency.FrequencyProfile:
    return frequency.get_frequency_profile(frequency.daily_research_profile_id(symbol))


def _daily_settings_for(symbol: str) -> backtest.BacktestSettings:
    profile = _daily_profile_for(symbol)
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


async def _run_window(
    *,
    label: str,
    start: datetime,
    end: datetime,
    macro_rows: list[dict],
) -> dict[str, dict]:
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    output: dict[str, dict] = {}
    for symbol in ASSETS:
        profile = _daily_profile_for(symbol)
        frames = await load_daily_frames(
            db,
            symbol=symbol,
            from_date=start,
            to_date=end,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
        )
        if not frames:
            output[symbol] = {"frames": 0, "algorithms": {}, "portfolio": edge_cost_metrics([])}
            continue

        result = backtest.run_replay(frames, settings=_daily_settings_for(symbol))
        by_algo = {
            algo_id: edge_cost_metrics(
                [trade for trade in result.trades if trade.algo_id == algo_id],
                seed=20260806 + index,
            )
            for index, algo_id in enumerate(ALGOS)
        }
        output[symbol] = {
            "frames": len(frames),
            "start": frames[0].bar.close_time.isoformat(),
            "end": frames[-1].bar.close_time.isoformat(),
            "buy_and_hold_pct": (frames[-1].bar.close / frames[0].bar.open - 1.0) * 100,
            "algorithms": by_algo,
            "portfolio": edge_cost_metrics(result.trades),
        }
        portfolio = output[symbol]["portfolio"]
        print(
            f"{label:5} {symbol} frames={len(frames):4} trades={portfolio['trades']:3} "
            f"edge/cost={portfolio['edge_cost_ratio']!s:>6} "
            f"CI95=[{portfolio['edge_cost_ci95_low']}, {portfolio['edge_cost_ci95_high']}]"
        )
    return output


async def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--bull-from", default="2023-08-04")
    ap.add_argument("--bull-to", default="2024-07-31")
    ap.add_argument("--bear-from", default="2024-11-09")
    ap.add_argument("--bear-to", default="2026-07-25")
    ap.add_argument("--bear-parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument(
        "--out",
        default="docs/arena/research/p2-1d-frequency-audit-results-20260806.json",
    )
    args = ap.parse_args()

    bear_parquet = Path(args.bear_parquet)
    if not bear_parquet.exists():
        print(f"parquet 없음: {bear_parquet}")
        return 1

    bull_start, bull_end = _parse_date(args.bull_from), _parse_date(args.bull_to)
    bear_start, bear_end = _parse_date(args.bear_from), _parse_date(args.bear_to)
    print("상승장 FNG+funding macro 재구성 중...")
    bull_macro, bull_coverage = build_bull_macro_rows(start=bull_start, end=bull_end)
    bear_macro = build_macro_rows(bear_parquet)
    print(
        f"macro rows: bull={len(bull_macro)} bear={len(bear_macro)} bull_coverage={bull_coverage}"
    )

    await positions.init()
    windows = {
        "bull": await _run_window(
            label="bull", start=bull_start, end=bull_end, macro_rows=bull_macro
        ),
        "bear": await _run_window(
            label="bear", start=bear_start, end=bear_end, macro_rows=bear_macro
        ),
    }
    output = {
        "method": {
            "threshold": EDGE_COST_THRESHOLD,
            "cost_model": "arena-cost-v2/base, 봉 주기 무관 거래당 산식 (fixed spec)",
            "interval": "1d (4h 원자재를 완전한 UTC 캘린더데이로 재표본화)",
            "returns": "trade gross_ret_pct and trading_cost_pct times position_weight",
            "bootstrap": "trade resampling, 5000 draws, deterministic seeds",
            "fixed_specification": True,
            "bull_macro_coverage": bull_coverage,
        },
        "windows": windows,
        "cross_window_portfolio_verdict": _cross_window_verdict(windows),
        "cross_window_algorithm_verdict": _cross_window_algo_verdict(windows),
    }
    out = Path(args.out)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
