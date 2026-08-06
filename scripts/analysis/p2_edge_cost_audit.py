"""P2 경제적 생존성 감사: 고정 사양의 gross edge / trading cost를 시장창·자산별 비교.

새 파라미터 탐색 없이 현재 기본 설정만 재생한다. 상승장은 역사 검증 문서의 FNG+funding
매크로 재구성 명세를 코드화하고, 하락장은 보존된 sentiment_join parquet를 사용한다.

재현:
  .venv/bin/python3 scripts/analysis/p2_edge_cost_audit.py \
      --bear-parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402
from morning_brief.analysis.sentiment_join import risk_overlay  # noqa: E402
from morning_brief.analysis.sentiment_join.sources.fng import fetch_fng  # noqa: E402
from morning_brief.analysis.sentiment_join.sources.futures import (  # noqa: E402
    _aggregate_daily_funding,
    _fetch_funding_rate_history,
)

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
ALGOS = (
    "regime_trend",
    "fng_contrarian",
    "vix_rsi",
    "macd_momentum",
    "multi_factor",
    "omnibus",
)
EDGE_COST_THRESHOLD = 3.0
MIN_TRADES_FOR_INFERENCE = 20


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


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


def edge_cost_metrics(
    trades: list,
    *,
    n_boot: int = 5000,
    seed: int = 20260804,
) -> dict[str, float | int | bool | None]:
    """거래별 포지션 가중 gross/cost로 경제성과 부트스트랩 구간을 계산."""
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "gross_return_pct": 0.0,
            "trading_cost_pct": 0.0,
            "net_return_pct": 0.0,
            "gross_edge_per_trade_bps": None,
            "cost_per_trade_bps": None,
            "edge_cost_ratio": None,
            "edge_cost_ci95_low": None,
            "edge_cost_ci95_high": None,
            "point_pass": False,
            "inference_ready": False,
        }

    gross_bps = np.asarray(
        [trade.gross_ret_pct * trade.position_weight * 10_000 for trade in trades],
        dtype=float,
    )
    cost_bps = np.asarray(
        [trade.trading_cost_pct * trade.position_weight * 10_000 for trade in trades],
        dtype=float,
    )
    gross_sum = float(gross_bps.sum())
    cost_sum = float(cost_bps.sum())
    ratio = gross_sum / cost_sum if cost_sum > 0 else None

    ci_low: float | None = None
    ci_high: float | None = None
    if n >= 2 and cost_sum > 0 and n_boot > 0:
        rng = np.random.default_rng(seed)
        indices = rng.integers(0, n, size=(n_boot, n))
        boot_gross = gross_bps[indices].sum(axis=1)
        boot_cost = cost_bps[indices].sum(axis=1)
        valid = boot_cost > 0
        if valid.any():
            ci_low, ci_high = (
                float(value)
                for value in np.percentile(boot_gross[valid] / boot_cost[valid], [2.5, 97.5])
            )

    return {
        "trades": n,
        "gross_return_pct": gross_sum / 100,
        "trading_cost_pct": cost_sum / 100,
        "net_return_pct": sum(trade.net_ret_pct * trade.position_weight for trade in trades) * 100,
        "gross_edge_per_trade_bps": gross_sum / n,
        "cost_per_trade_bps": cost_sum / n,
        "edge_cost_ratio": ratio,
        "edge_cost_ci95_low": ci_low,
        "edge_cost_ci95_high": ci_high,
        "point_pass": ratio is not None and ratio >= EDGE_COST_THRESHOLD,
        "inference_ready": n >= MIN_TRADES_FOR_INFERENCE,
    }


def _timestamp_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def build_bull_macro_rows(*, start: datetime, end: datetime) -> tuple[list[dict], dict[str, float]]:
    """역사 상승장 문서 §1.2의 FNG+funding 일간 macro를 재구성."""
    warmup_start = start - timedelta(days=100)
    lookback_days = (datetime.now(timezone.utc).date() - warmup_start.date()).days + 7
    fng = fetch_fng(lookback_days).copy()
    fng["date"] = pd.to_datetime(fng["date"])

    funding_rows = _fetch_funding_rate_history(
        _timestamp_ms(warmup_start),
        _timestamp_ms(end + timedelta(days=1)) - 1,
    )
    daily_funding = _aggregate_daily_funding(funding_rows)
    dates = pd.date_range(warmup_start.date(), end.date(), freq="D")
    df = pd.DataFrame({"date": dates})
    df = df.merge(fng[["date", "fng_value"]], on="date", how="left")
    df["funding_rate"] = [daily_funding.get(day.date().isoformat(), np.nan) for day in dates]
    funding = pd.to_numeric(df["funding_rate"], errors="coerce")
    rolling = funding.shift(1).rolling(30, min_periods=20)
    df["funding_rate_zscore_30d"] = (funding - rolling.mean()) / rolling.std()

    audit_mask = (df["date"] >= start.replace(tzinfo=None)) & (
        df["date"] <= end.replace(tzinfo=None)
    )
    coverage = {
        "fng": float(df.loc[audit_mask, "fng_value"].notna().mean()),
        "funding": float(df.loc[audit_mask, "funding_rate"].notna().mean()),
        "funding_zscore": float(df.loc[audit_mask, "funding_rate_zscore_30d"].notna().mean()),
    }
    if coverage["fng"] < 0.95 or coverage["funding"] < 0.95:
        raise RuntimeError(f"bull macro coverage below 95%: {coverage}")

    rows: list[dict] = []
    for index in range(len(df)):
        if df.loc[index, "date"].to_pydatetime().replace(tzinfo=timezone.utc) < start:
            continue
        window = df.iloc[: index + 1]
        regime_state = risk_overlay.compute_regime_state(window)
        vol_environment = risk_overlay.compute_vol_environment(window)
        day = df.loc[index, "date"].to_pydatetime().replace(tzinfo=timezone.utc)
        fetched = day + timedelta(days=1)
        rows.append(
            {
                "fetched_at": fetched.isoformat(),
                "reference_date": day.date().isoformat(),
                "stale_hours": 0,
                "risk_overlay": {
                    "regimeState": regime_state.label,
                    "regimeRaw": regime_state.raw,
                    "volLevel": vol_environment.level,
                    "volTrend": vol_environment.trend,
                },
            }
        )
    return rows, coverage


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
        profile = _profile_for(symbol)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=profile.interval,
            limit=5000,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            from_date=start,
            to_date=end,
            macro_rows=macro_rows,
        )
        if not frames:
            output[symbol] = {"frames": 0, "algorithms": {}, "portfolio": edge_cost_metrics([])}
            continue

        result = backtest.run_replay(frames, settings=_settings_for(symbol))
        by_algo = {
            algo_id: edge_cost_metrics(
                [trade for trade in result.trades if trade.algo_id == algo_id],
                seed=20260804 + index,
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
            f"edge/cost={portfolio['edge_cost_ratio']:.2f} "
            f"CI95=[{portfolio['edge_cost_ci95_low']:.2f}, {portfolio['edge_cost_ci95_high']:.2f}]"
        )
    return output


def _cross_window_verdict(windows: dict[str, dict]) -> dict[str, dict]:
    verdict: dict[str, dict] = {}
    for symbol in ASSETS:
        bull = windows["bull"].get(symbol, {}).get("portfolio", {})
        bear = windows["bear"].get(symbol, {}).get("portfolio", {})
        bull_pass = bool(bull.get("point_pass"))
        bear_pass = bool(bear.get("point_pass"))
        verdict[symbol] = {
            "bull_point_pass": bull_pass,
            "bear_point_pass": bear_pass,
            "both_windows_pass": bull_pass and bear_pass,
            "inference_ready_both": bool(bull.get("inference_ready"))
            and bool(bear.get("inference_ready")),
        }
    return verdict


def _cross_window_algo_verdict(windows: dict[str, dict]) -> dict[str, dict[str, dict]]:
    verdict: dict[str, dict[str, dict]] = {}
    for symbol in ASSETS:
        verdict[symbol] = {}
        for algo_id in ALGOS:
            bull = windows["bull"].get(symbol, {}).get("algorithms", {}).get(algo_id, {})
            bear = windows["bear"].get(symbol, {}).get("algorithms", {}).get(algo_id, {})
            point_both = bool(bull.get("point_pass")) and bool(bear.get("point_pass"))
            inference_both = bool(bull.get("inference_ready")) and bool(bear.get("inference_ready"))
            ci_both = (
                bull.get("edge_cost_ci95_low") is not None
                and bear.get("edge_cost_ci95_low") is not None
                and bull["edge_cost_ci95_low"] >= EDGE_COST_THRESHOLD
                and bear["edge_cost_ci95_low"] >= EDGE_COST_THRESHOLD
            )
            status = (
                "robust_pass"
                if point_both and inference_both and ci_both
                else "point_pass_unconfirmed"
                if point_both
                else "fail"
            )
            verdict[symbol][algo_id] = {
                "both_windows_point_pass": point_both,
                "inference_ready_both": inference_both,
                "both_windows_ci95_low_pass": ci_both,
                "status": status,
            }
    return verdict


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bull-from", default="2023-08-04")
    ap.add_argument("--bull-to", default="2024-07-31")
    ap.add_argument("--bear-from", default="2024-11-09")
    ap.add_argument("--bear-to", default="2026-07-25")
    ap.add_argument("--bear-parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument(
        "--out",
        default="docs/arena/research/p2-edge-cost-audit-results-20260804.json",
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
            "minimum_trades_for_inference": MIN_TRADES_FOR_INFERENCE,
            "cost_model": "arena-cost-v2/base (13bps round trip before position weighting)",
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
