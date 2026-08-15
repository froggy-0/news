"""실행게이트 depth_10bp 임계값 자산별 재보정 (2026-08-14).

배경: execution_gate.py의 min_depth_10bp_usd(EXEC_GATE_MIN_DEPTH_10BP_USD)가 BTC 하나로
캘리브레이션된 전역 상수(=$1,000,000)라 SOL 신호의 62.5%가 "체결 나빠서"가 아니라
"SOL이라서" depth_too_thin으로 거부되고 있었다(arena_execution_gates 실측). 이 스크립트는
(1) arena_execution_gates.feature_snapshot에 실제로 기록된 depth_10bp_bid/ask_usd로
자산별 정상 유동성 분포를 계산하고, (2) 새 자산별 임계값(parameters.
EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL)을 과거 데이터에 재적용해 거부율이 의도대로
바뀌는지 검증한다.

⚠️ 2026-07-30 REST depth limit 수정(20→1000) 이전 데이터는 다른 측정치라 섞으면 왜곡됨
(limit=20 시절 BTC 관측치가 $38K~$97K로 나와 분포가 이중모드가 됨) — 반드시 그 이후만 사용.

재현: .venv/bin/python3 scripts/analysis/exec_gate_depth_calibration.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import parameters, positions  # noqa: E402

DEPTH_FIX_DATE = "2026-07-31"  # EXEC_GATE_DEPTH_SNAPSHOT_LIMIT 20→1000 수정 다음날부터


def _infer_symbol(price: float | None) -> str | None:
    if price is None:
        return None
    if price > 10_000:
        return "BTCUSDT"
    if 500 < price <= 10_000:
        return "ETHUSDT"
    if price <= 500:
        return "SOLUSDT"
    return None


async def _fetch_rows(db) -> list[dict]:
    rows: list[dict] = []
    for start in range(0, 20_000, 1000):
        res = (
            await db.table("arena_execution_gates")
            .select("created_at,feature_snapshot")
            .gte("created_at", DEPTH_FIX_DATE)
            .order("created_at", desc=False)
            .range(start, start + 999)
            .execute()
        )
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
    return rows


async def main() -> int:
    await positions.init()
    db = positions.db()
    rows = await _fetch_rows(db)
    print(f"post-fix({DEPTH_FIX_DATE}~) rows: {len(rows)}")

    by_symbol: dict[str, list[float]] = {"BTCUSDT": [], "ETHUSDT": [], "SOLUSDT": []}
    for r in rows:
        fs = r.get("feature_snapshot") or {}
        symbol = _infer_symbol(fs.get("last_price"))
        if symbol is None:
            continue
        bid = fs.get("depth_10bp_bid_usd")
        ask = fs.get("depth_10bp_ask_usd")
        if bid is None or ask is None:
            continue
        by_symbol[symbol].append(min(bid, ask))

    print("\n=== 실측 분포 (min(bid,ask), 10bp 밴드 USD) ===")
    for symbol, vals in by_symbol.items():
        if not vals:
            print(f"{symbol}: n=0")
            continue
        arr = np.array(vals)
        pct = np.percentile(arr, [5, 10, 25, 50, 90])
        threshold = parameters.EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL.get(
            symbol, parameters.EXEC_GATE_MIN_DEPTH_10BP_USD
        )
        margin = arr.min() / threshold if threshold else float("inf")
        print(
            f"{symbol}: n={len(arr)} min={arr.min():,.0f} p5={pct[0]:,.0f} p10={pct[1]:,.0f} "
            f"median={pct[3]:,.0f} p90={pct[4]:,.0f}  |  신threshold={threshold:,.0f} "
            f"margin(min/threshold)={margin:.2f}x"
        )

    print("\n=== 거부율 재시뮬레이션: 기존 전역값 vs 신 자산별값 ===")
    old_threshold = parameters.EXEC_GATE_MIN_DEPTH_10BP_USD
    for symbol, vals in by_symbol.items():
        if not vals:
            continue
        arr = np.array(vals)
        new_threshold = parameters.EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL.get(symbol, old_threshold)
        old_reject_rate = (arr < old_threshold).mean() * 100
        new_reject_rate = (arr < new_threshold).mean() * 100
        print(
            f"{symbol}: n={len(arr)}  구threshold(${old_threshold:,.0f}) 거부율={old_reject_rate:.1f}%  "
            f"신threshold(${new_threshold:,.0f}) 거부율={new_reject_rate:.1f}%"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
