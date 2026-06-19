"""Walk-forward split generator for arena backtesting.

Generates non-overlapping expanding-anchor train/test windows from OHLCV data.
When data is insufficient for even one split, returns `insufficient_data` status
rather than raising — callers can inspect the result and decide what to do.

Split naming is deterministic per symbol/interval/wf_version so re-runs with
--save upsert safely on the unique split_name constraint.

Usage:
    PYTHONPATH=src .venv/bin/python -m arena.walk_forward --symbol BTCUSDT --interval 4h
    PYTHONPATH=src .venv/bin/python -m arena.walk_forward --save
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from . import execution_rules, parameters

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WalkForwardSplit:
    split_id: str
    split_name: str
    split_num: int
    symbol: str
    interval: str
    strategy_version: str
    params_version: str
    risk_model_version: str
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    embargo_bars: int
    train_bar_count: int
    test_bar_count: int

    def as_row(self) -> dict[str, Any]:
        ts = execution_rules.format_utc_timestamp
        return {
            "split_id": self.split_id,
            "split_name": self.split_name,
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy_version,
            "params_version": self.params_version,
            "risk_model_version": self.risk_model_version,
            "train_start": ts(self.train_start),
            "train_end": ts(self.train_end),
            "test_start": ts(self.test_start),
            "test_end": ts(self.test_end),
            "embargo_bars": self.embargo_bars,
            "notes": json.dumps(
                {
                    "split_num": self.split_num,
                    "train_bar_count": self.train_bar_count,
                    "test_bar_count": self.test_bar_count,
                    "wf_version": parameters.WF_VERSION,
                }
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        ts = execution_rules.format_utc_timestamp
        return {
            "split_id": self.split_id,
            "split_name": self.split_name,
            "split_num": self.split_num,
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy_version,
            "params_version": self.params_version,
            "risk_model_version": self.risk_model_version,
            "train_start": ts(self.train_start),
            "train_end": ts(self.train_end),
            "test_start": ts(self.test_start),
            "test_end": ts(self.test_end),
            "embargo_bars": self.embargo_bars,
            "train_bar_count": self.train_bar_count,
            "test_bar_count": self.test_bar_count,
        }


@dataclass(frozen=True)
class WalkForwardResult:
    status: str  # "ok" | "insufficient_data"
    message: str
    symbol: str
    interval: str
    available_bars: int
    min_required_bars: int
    warmup_bars: int
    splits: list[WalkForwardSplit] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "symbol": self.symbol,
            "interval": self.interval,
            "available_bars": self.available_bars,
            "min_required_bars": self.min_required_bars,
            "warmup_bars": self.warmup_bars,
            "split_count": len(self.splits),
            "splits": [s.as_dict() for s in self.splits],
        }


def _parse_ts(value: Any) -> datetime:
    return execution_rules.parse_utc_datetime(value)


def generate_splits(
    bars: list[dict[str, Any]],
    *,
    warmup_bars: int = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD,
    train_bars: int = parameters.WF_TRAIN_BARS,
    test_bars: int = parameters.WF_TEST_BARS,
    step_bars: int = parameters.WF_STEP_BARS,
    embargo_bars: int = parameters.WF_EMBARGO_BARS,
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    strategy_version: str = parameters.STRATEGY_VERSION,
    params_version: str = parameters.PARAMS_VERSION,
    risk_model_version: str = parameters.RISK_MODEL_VERSION,
) -> WalkForwardResult:
    """Generate expanding-anchor walk-forward splits from a sorted bar list.

    Bars must be sorted by close_time ascending. The first `warmup_bars` are
    excluded from all windows (they exist only to warm up indicators).

    Train windows are anchored at the first usable bar and expand with each split.
    Test windows are non-overlapping and always lie entirely in the future relative
    to their corresponding train window.

    Returns WalkForwardResult with status="insufficient_data" (not an exception)
    when there are not enough usable bars for a complete first split.
    """
    min_required = train_bars + embargo_bars + test_bars
    usable = bars[warmup_bars:]
    available = len(usable)

    if available < min_required:
        return WalkForwardResult(
            status="insufficient_data",
            message=(
                f"need {min_required} usable bars "
                f"(train={train_bars} + embargo={embargo_bars} + test={test_bars}), "
                f"have {available} after {warmup_bars} warmup bars"
            ),
            symbol=symbol,
            interval=interval,
            available_bars=available,
            min_required_bars=min_required,
            warmup_bars=warmup_bars,
            splits=[],
        )

    splits: list[WalkForwardSplit] = []
    split_num = 0
    # test_end is always the exclusive upper bound (bar index into usable[])
    test_end_idx = train_bars + embargo_bars + test_bars

    while test_end_idx <= available:
        # train: usable[0 .. train_end_idx - 1]  (expanding anchor)
        train_end_idx = test_end_idx - test_bars - embargo_bars
        # test:  usable[test_start_idx .. test_end_idx - 1]
        test_start_idx = test_end_idx - test_bars

        split_name = f"{symbol}_{interval}_{parameters.WF_VERSION}_s{split_num:02d}"

        splits.append(
            WalkForwardSplit(
                split_id=str(uuid4()),
                split_name=split_name,
                split_num=split_num,
                symbol=symbol,
                interval=interval,
                strategy_version=strategy_version,
                params_version=params_version,
                risk_model_version=risk_model_version,
                train_start=_parse_ts(usable[0]["close_time"]),
                train_end=_parse_ts(usable[train_end_idx - 1]["close_time"]),
                test_start=_parse_ts(usable[test_start_idx]["close_time"]),
                test_end=_parse_ts(usable[test_end_idx - 1]["close_time"]),
                embargo_bars=embargo_bars,
                train_bar_count=train_end_idx,
                test_bar_count=test_bars,
            )
        )

        split_num += 1
        test_end_idx += step_bars

    return WalkForwardResult(
        status="ok",
        message=f"generated {len(splits)} split(s) from {available} usable bars",
        symbol=symbol,
        interval=interval,
        available_bars=available,
        min_required_bars=min_required,
        warmup_bars=warmup_bars,
        splits=splits,
    )


async def load_bars_from_supabase(
    db: Any,
    *,
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    res = (
        await db.table("arena_ohlcv_bars")
        .select("open_time,close_time")
        .eq("symbol", symbol)
        .eq("interval", interval)
        .order("open_time")
        .limit(limit)
        .execute()
    )
    return res.data or []


async def save_splits_to_supabase(
    db: Any,
    result: WalkForwardResult,
) -> list[dict[str, Any]]:
    """Upsert splits on split_name. Logs and returns error info on failure."""
    if not result.splits:
        return []

    errors: list[dict[str, Any]] = []
    for split in result.splits:
        row = split.as_row()
        try:
            await (
                db.table("arena_walk_forward_splits")
                .upsert(row, on_conflict="split_name")
                .execute()
            )
        except Exception as exc:
            logger.warning("walk_forward save failed: %s (%s)", split.split_name, exc)
            errors.append({"split_name": split.split_name, "error": str(exc)})
    return errors


async def _amain(args: argparse.Namespace) -> int:
    from . import positions

    await positions.init()
    db = positions.db()

    bars = await load_bars_from_supabase(db, symbol=args.symbol, interval=args.interval)
    result = generate_splits(
        bars,
        symbol=args.symbol,
        interval=args.interval,
    )

    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))

    if result.status == "insufficient_data":
        logger.warning("walk_forward: %s", result.message)
        return 0

    if args.save:
        errors = await save_splits_to_supabase(db, result)
        if errors:
            print(
                json.dumps({"save_errors": errors}, ensure_ascii=False, indent=2),
                flush=True,
            )
            return 1
        print(f"saved {len(result.splits)} split(s) to arena_walk_forward_splits", flush=True)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate arena walk-forward splits.")
    parser.add_argument("--symbol", default=parameters.BINANCE_SYMBOL)
    parser.add_argument("--interval", default=parameters.BINANCE_KLINE_INTERVAL)
    parser.add_argument("--save", action="store_true", help="Upsert splits to Supabase.")
    return asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
