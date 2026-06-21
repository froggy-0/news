"""Arena strategy roster diagnostics.

Usage:
  PYTHONPATH=src .venv/bin/python -m arena.roster_diagnostics --source both --limit 1000
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from typing import Any

from . import algorithms, backtest, frequency, positions, regime


def _new_algo_summary() -> dict[str, Any]:
    return {
        "evaluations": 0,
        "raw_signal_counts": Counter(),
        "veto_counts": Counter(),
        "failed_condition_counts": Counter(),
        "passed_condition_counts": Counter(),
        "factor_true_counts": Counter(),
        "factor_false_counts": Counter(),
        "diagnostics_source_counts": Counter(),
    }


def _add_diagnostic(
    summary: dict[str, dict[str, Any]],
    algo_id: str,
    diagnostic: dict[str, Any],
    *,
    source: str,
) -> None:
    item = summary.setdefault(algo_id, _new_algo_summary())
    item["evaluations"] += 1
    item["raw_signal_counts"][str(diagnostic.get("raw_signal"))] += 1
    item["diagnostics_source_counts"][source] += 1
    for name in diagnostic.get("vetoes") or []:
        item["veto_counts"][str(name)] += 1
    for name in diagnostic.get("failed_conditions") or []:
        item["failed_condition_counts"][str(name)] += 1
    for name in diagnostic.get("passed_conditions") or []:
        item["passed_condition_counts"][str(name)] += 1
    for name, value in (diagnostic.get("factors") or {}).items():
        if value is True:
            item["factor_true_counts"][str(name)] += 1
        elif value is False:
            item["factor_false_counts"][str(name)] += 1


def _json_ready(value: Any) -> Any:
    if isinstance(value, Counter):
        return dict(value.most_common())
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _macro_ind_from_reason(reason: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    inputs = reason.get("inputs") or {}
    macro = {
        "arena_regime_state": inputs.get("regime_state"),
        "regime_state": inputs.get("overlay_regime_state"),
        "fng": inputs.get("fng"),
        "vix_now": inputs.get("vix_now"),
        "vix_q40": inputs.get("vix_q40"),
        "funding_zscore": inputs.get("funding_zscore"),
        "oi_divergence_flag": inputs.get("oi_divergence_flag"),
        "etf_flow_zscore": inputs.get("etf_flow_zscore"),
        "btc_above_ma200": inputs.get("btc_above_ma200"),
        "long_short_ratio_zscore": inputs.get("long_short_ratio_zscore"),
        "taker_imbalance_zscore": inputs.get("taker_imbalance_zscore"),
        "breadth_up_ratio": inputs.get("breadth_up_ratio"),
        "stablecoin_supply_zscore": inputs.get("stablecoin_supply_zscore"),
        "btc_drawdown_90d": inputs.get("btc_drawdown_90d"),
    }
    ind = dict(inputs)
    return macro, ind


async def summarize_live_decisions(db: Any, *, limit: int) -> dict[str, Any]:
    rows = (
        await db.table("arena_decisions")
        .select("algo_id,raw_signal,signal,action,skipped_reason,reason,created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []
    summary: dict[str, dict[str, Any]] = {}
    action_counts: Counter[str] = Counter()
    skipped_counts: Counter[str] = Counter()
    for row in rows:
        algo_id = row.get("algo_id")
        if algo_id not in algorithms.ALGORITHMS:
            continue
        action_counts[f"{algo_id}:{row.get('action')}"] += 1
        skipped_counts[f"{algo_id}:{row.get('skipped_reason')}"] += 1
        reason = row.get("reason") or {}
        diagnostic = reason.get("diagnostics")
        source = "stored_reason_diagnostics"
        if not diagnostic:
            macro, ind = _macro_ind_from_reason(reason)
            diagnostic = algorithms.explain_signal(algo_id, macro, ind)
            source = "derived_from_reason_inputs"
        _add_diagnostic(summary, algo_id, diagnostic, source=source)
    return {
        "source": "live_decisions",
        "row_count": len(rows),
        "action_counts": action_counts,
        "skipped_reason_counts": skipped_counts,
        "by_algo": summary,
    }


async def summarize_backtest_frames(
    db: Any,
    *,
    symbol: str,
    profile_id: str,
    indicator_profile_id: str | None,
    regime_variant: str,
    limit: int,
) -> dict[str, Any]:
    profile = frequency.get_frequency_profile(profile_id)
    indicator_profile = indicator_profile_id or profile.default_indicator_profile_id
    interval = profile.interval
    settings = backtest.BacktestSettings(
        frequency_profile_id=profile.frequency_profile_id,
        indicator_profile_id=indicator_profile,
        symbol=symbol,
        interval=interval,
        regime_variant=regime_variant,
    )
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=symbol,
        interval=interval,
        limit=limit,
        warmup_bars=settings.warmup_bars,
        indicator_profile_id=indicator_profile,
    )
    summary: dict[str, dict[str, Any]] = {}
    for frame in frames:
        macro = backtest._clean_macro(frame.macro, frame.data_timestamp, settings)
        macro["arena_regime_state"] = regime.classify_regime_variant(
            frame.indicators,
            frame.market_features,
            macro,
            variant=regime_variant,
        ).regime_state
        for algo_id in algorithms.ALGORITHMS:
            diagnostic = algorithms.explain_signal(algo_id, macro, frame.indicators)
            _add_diagnostic(summary, algo_id, diagnostic, source="backtest_frame")
    return {
        "source": "backtest_frames",
        "symbol": symbol,
        "profile": profile_id,
        "interval": interval,
        "indicator_profile": indicator_profile,
        "regime_variant": regime_variant,
        "frame_count": len(frames),
        "by_algo": summary,
    }


async def _amain(args: argparse.Namespace) -> int:
    await positions.init()
    db = positions.db()
    result: dict[str, Any] = {}
    if args.source in {"live", "both"}:
        result["live"] = await summarize_live_decisions(db, limit=args.limit)
    if args.source in {"backtest", "both"}:
        result["backtest"] = await summarize_backtest_frames(
            db,
            symbol=args.symbol,
            profile_id=args.profile,
            indicator_profile_id=args.indicator_profile,
            regime_variant=args.regime_variant,
            limit=args.limit,
        )
    print(json.dumps(_json_ready(result), ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Arena algorithm roster vetoes.")
    parser.add_argument("--source", choices=["live", "backtest", "both"], default="both")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--profile", default=frequency.LIVE_4H_PROFILE_ID)
    parser.add_argument("--indicator-profile", default=None)
    parser.add_argument(
        "--regime-variant",
        choices=[regime.REGIME_VARIANT_STRICT, regime.REGIME_VARIANT_RELAXED_2OF3],
        default=regime.REGIME_VARIANT_STRICT,
    )
    return asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
