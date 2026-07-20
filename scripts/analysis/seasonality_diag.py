"""R6: 시간대·요일 시즌럴리티 진단 (분석 전용, 코드 동작 변경 없음).

두 관점:
  (A) 시장 레벨 — arena_ohlcv_bars 4h봉 수익률을 진입 UTC hour(0/4/8/12/16/20)·요일별 분해.
      "Monday Asia Open Effect"(Concretum) 등 알려진 패턴이 이 데이터에도 있는지.
  (B) 거래 레벨 — paper_positions 청산 거래를 진입 시각별 성과 분해(표본 적으면 참고용).

유의 패턴 발견 시에만 소프트 사이징(열위 시간대 ×0.7 등) 실험으로 승격. 지금은 진단만.

재현: .venv/bin/python3 scripts/analysis/seasonality_diag.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import positions  # noqa: E402

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _dt(ts: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except (ValueError, TypeError):
        return None


async def _ohlcv() -> list[dict]:
    res = (
        await positions.db()
        .table("arena_ohlcv_bars")
        .select("open_time,open,close")
        .eq("symbol", "BTCUSDT")
        .eq("interval", "4h")
        .order("open_time")
        .limit(20000)
        .execute()
    )
    seen: dict[str, dict] = {}
    for r in res.data or []:
        seen[r["open_time"]] = r  # dedup(run별 중복)
    return sorted(seen.values(), key=lambda r: r["open_time"])


async def _closed() -> list[dict]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select("algo_id,open_time,ret_pct,position_weight")
        .eq("status", "closed")
        .not_.is_("ret_pct", "null")
        .limit(5000)
        .execute()
    )
    return res.data or []


def _fmt_row(label: str, rets: list[float]) -> str:
    n = len(rets)
    if n == 0:
        return f"  {label:10} n=0"
    mean = statistics.mean(rets) * 100
    win = sum(1 for r in rets if r > 0) / n * 100
    return f"  {label:10} n={n:>4}  평균={mean:+.3f}%  승률={win:.0f}%"


async def main() -> int:
    await positions.init()
    bars, closed = await asyncio.gather(_ohlcv(), _closed())

    print(f"# 시즌럴리티 진단 @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # (A) 시장 레벨 — 봉 수익률(다음봉 방향은 open→close)
    print(f"\n## A. 시장 4h봉 수익률 by UTC hour ({len(bars)}봉)")
    by_hour: dict[int, list[float]] = defaultdict(list)
    by_dow: dict[int, list[float]] = defaultdict(list)
    for b in bars:
        t = _dt(b["open_time"])
        o, c = float(b["open"]), float(b["close"])
        if not t or o <= 0:
            continue
        ret = c / o - 1.0
        by_hour[t.hour].append(ret)
        by_dow[t.weekday()].append(ret)
    print("  [UTC hour]")
    for h in sorted(by_hour):
        print(_fmt_row(f"{h:02d}:00", by_hour[h]))
    print("  [요일]")
    for d in sorted(by_dow):
        print(_fmt_row(_DOW[d], by_dow[d]))

    # (B) 거래 레벨 — 진입 시각별 성과
    print(f"\n## B. 청산 거래 진입 시각별 성과 ({len(closed)}건, 표본 적으면 참고용)")
    t_hour: dict[int, list[float]] = defaultdict(list)
    t_dow: dict[int, list[float]] = defaultdict(list)
    for tr in closed:
        t = _dt(tr["open_time"])
        if not t:
            continue
        r = (tr.get("ret_pct") or 0.0) * (tr.get("position_weight") or 1.0)
        t_hour[t.hour].append(r)
        t_dow[t.weekday()].append(r)
    print("  [진입 UTC hour]")
    for h in sorted(t_hour):
        print(_fmt_row(f"{h:02d}:00", t_hour[h]))
    print("  [진입 요일]")
    for d in sorted(t_dow):
        print(_fmt_row(_DOW[d], t_dow[d]))

    # 간이 해석 힌트 (시장 레벨 최고/최악 hour)
    hour_means = {h: statistics.mean(v) for h, v in by_hour.items() if v}
    if hour_means:
        best = max(hour_means, key=hour_means.get)
        worst = min(hour_means, key=hour_means.get)
        print(
            f"\n힌트: 시장 최고 hour={best:02d}:00({hour_means[best] * 100:+.3f}%) / "
            f"최악={worst:02d}:00({hour_means[worst] * 100:+.3f}%). "
            "차이가 크고 표본 충분하면 진입시각 소프트 게이트 실험 후보."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
