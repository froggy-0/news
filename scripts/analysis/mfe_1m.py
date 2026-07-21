"""P2/W4: MFE/MAE 1분 정밀화 — 청산 개선 스레드의 진위 판정.

배경(return-improvement-priorities-20260715.md P2, implementation-plan-w-series-20260715.md
W4): "청산이 이익을 흘린다"(arena_status.py 섹션3, MFE 포착률<30%) 진단이 Tier1(시간배리어)·
Tier2(ATR 목표가) 두 캠페인을 발동시켰고 둘 다 백테스트에서 기각됐다. 그 진단 자체가 4h봉
high/low 기반 보수 추정이라 해상도 문제일 가능성을 이 스크립트로 확인한다.

arena_realtime_feature_bars(1분, last_price)로 동일 거래의 MFE/MAE를 재계산해 4h 추정과
비교. last_price는 1분 윈도 종가 계열이라 4h high보다 더 보수적이지만, "1분 안에 반응해
실제로 잡을 수 있었던 가격"이라는 정의가 실행 가능성 관점에서 더 정합하다.

읽기 전용 — 트레이딩/스키마 변경 없음.

재현: .venv/bin/python3 scripts/analysis/mfe_1m.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import parameters, positions  # noqa: E402

ALGOS = ["regime_trend", "fng_contrarian", "vix_rsi", "macd_momentum", "multi_factor", "omnibus"]


def _dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except ValueError:
        return None


def _version_num(v: str | None) -> int:
    if not v:
        return -1
    try:
        return int(v.rsplit("v", 1)[-1])
    except ValueError:
        return -1


async def _closed_trades() -> list[dict]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select("algo_id,open_time,close_time,open_price,ret_pct,position_weight,params_version")
        .eq("status", "closed")
        .not_.is_("ret_pct", "null")
        .order("close_time")
        .limit(5000)
        .execute()
    )
    return res.data or []


async def _fetch_1m_bars(start: datetime, end: datetime) -> list[dict]:
    """arena_realtime_feature_bars window_start,last_price — 1000행/페이지 페이지네이션."""
    db = positions.db()
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        res = (
            await db.table("arena_realtime_feature_bars")
            .select("window_start,last_price")
            .gte("window_start", start.isoformat())
            .lte("window_start", end.isoformat())
            .order("window_start")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def _mfe_mae_1m(
    trade: dict, bars: list[tuple[datetime, float]]
) -> tuple[float, float, float] | None:
    """(MFE, MAE, coverage_pct) — long 기준. 커버리지 = 실제윈도 / 예상윈도(hold_hours*60)."""
    ot, ct = _dt(trade.get("open_time")), _dt(trade.get("close_time"))
    op = trade.get("open_price") or 0.0
    if not ot or not ct or op <= 0 or ct <= ot:
        return None
    prices = [p for (t, p) in bars if ot <= t <= ct and p]
    if not prices:
        return None
    expected_windows = max(
        (ct - ot).total_seconds() / parameters.REALTIME_FEATURE_WINDOW_SECONDS, 1.0
    )
    coverage = len(prices) / expected_windows * 100
    hi, lo = max(prices), min(prices)
    return hi / op - 1.0, lo / op - 1.0, coverage


async def main() -> int:
    await positions.init()
    closed = await _closed_trades()
    if not closed:
        print("청산 거래 없음")
        return 0

    open_dts = [d for d in (_dt(t.get("open_time")) for t in closed) if d]
    close_dts = [d for d in (_dt(t.get("close_time")) for t in closed) if d]
    if not open_dts or not close_dts:
        print("open_time/close_time 파싱 실패")
        return 1
    range_start = min(open_dts) - timedelta(minutes=2)
    range_end = max(close_dts) + timedelta(minutes=2)

    print(f"1m 봉 로드: {range_start} ~ {range_end}")
    raw_bars = await _fetch_1m_bars(range_start, range_end)
    bars = sorted(
        (d, float(r["last_price"]))
        for r in raw_bars
        if (d := _dt(r["window_start"])) and r.get("last_price")
    )
    print(f"1m 봉 {len(bars)}건 로드 (요청 범위 내 arena_realtime_feature_bars 전체)")

    current_ver = parameters.PARAMS_VERSION
    current_num = _version_num(current_ver)

    by_algo = defaultdict(list)
    for t in closed:
        by_algo[t["algo_id"]].append(t)

    COVERAGE_MIN = 80.0

    def _report(label: str, trades_filter) -> None:
        print(f"\n=== {label} ===")
        print("algo | n(1m가용) | 제외(커버리지<80%) | MFE_4h평균은 별도 arena_status 참조")
        print("algo | n | 평균MFE_1m% | 평균MAE_1m% | 포착률_1m% | 평균커버리지%")
        for a in ALGOS:
            ts = [t for t in by_algo.get(a, []) if trades_filter(t)]
            rows = []
            excluded = 0
            for t in ts:
                mm = _mfe_mae_1m(t, bars)
                if mm is None:
                    continue
                mfe, mae, cov = mm
                if cov < COVERAGE_MIN:
                    excluded += 1
                    continue
                ret = t.get("ret_pct") or 0.0
                rows.append((mfe, mae, ret, cov))
            if not rows and not ts:
                continue
            if not rows:
                print(f"{a} | n=0 (1m 데이터 없음 또는 전건 커버리지 미달, 제외={excluded})")
                continue
            avg_mfe = statistics.mean(r[0] for r in rows) * 100
            avg_mae = statistics.mean(r[1] for r in rows) * 100
            avg_cov = statistics.mean(r[3] for r in rows)
            caps = [r[2] / r[0] for r in rows if r[0] > 0.003]
            cap = statistics.mean(caps) * 100 if caps else float("nan")
            cap_str = f"{cap:+.0f}" if caps else "n/a(MFE전부<0.3%)"
            print(
                f"{a} | n={len(rows)}(제외{excluded}) | {avg_mfe:+.2f} | {avg_mae:+.2f} | "
                f"{cap_str} | {avg_cov:.0f}"
            )

    _report("전체 청산 거래 (4h 진단과 동일 모집단 — section3 직접 대조용)", lambda t: True)
    _report(
        f"현재 버전(`{current_ver}`) 이후만 (P0 정합)",
        lambda t: _version_num(t.get("params_version")) >= current_num,
    )

    print(
        "\n판정 가이드: 포착률_1m이 4h 대비(arena_status.py 섹션3, 대부분 알고 <30%·일부 음수) "
        "뚜렷이 개선되면(예: 0% 근접 이상) → 청산 개선 스레드 종결(진입 품질로 집중). "
        "1m에서도 명확히 음수/낮으면 → 4h 진단이 정확했다는 뜻, 1m 근거로 청산 메커니즘 재설계."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
