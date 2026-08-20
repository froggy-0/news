"""피라미딩(승자 불타기) 사후 시뮬레이션 — 미검증 축 1차 타당성 (2026-08-20).

배경: 이 저장소는 **물타기(averaging down)만** 구현돼 있다(`fng_contrarian` 가격 트랜치,
v22). 추세계열(regime_trend/macd_momentum·TSMOM_NL/meridian 추세leg)에는 사이징을
키우는 메커니즘이 아예 없다 — 진입 시 정한 weight로 끝까지 간다.

문헌 정합성: 추세추종/돌파는 피라미딩이 적합하고 평균회귀는 부적합하다는 게 통설
(turtletrader 등 실무 문헌). 이 저장소는 **정확히 반대 배치** — 평균회귀에만 스케일인이
있고 추세엔 없다. root-cause-diagnosis-20260803이 진단한 "추세추종은 소수 대형승리로
사는데 구조가 그걸 못 만든다"와도 맞물린다.

⚠️ 이건 **사후 시뮬레이션**이지 진짜 조인 백테스트가 아니다(meridian v40과 동일 등급):
청산 시점·청산가는 baseline 그대로 두고 진입 트랜치만 추가한다. 실제 구현 시엔 평단이
바뀌어 트레일링 스톱 거리(=|평단-손절|)도 달라지므로 결과가 이동할 수 있다. 여기서
유망하면 그때 src/에 플래그로 구현해 정식 A/B를 돌린다.

설계(자유도 최소):
  - 추가 트리거: 진입가에서 **유리한 방향으로** 0.5d / 1.0d (d = |진입가 − 초기손절가|,
    저장소가 이미 쓰는 ATR×2.5 클램핑 거리 재사용 — 신규 파라미터 없음)
  - 체결가: 한계가(그 레벨) — fng 가격 트랜치와 동일 규약
  - 도달 판정: 보유기간 4h봉 high(롱)/low(숏) — 인트라바 경로는 낙관 가능(주의)
  - 비중: 각 추가 트랜치 +Δw, 총합 VOL_WEIGHT_MAX(0.7) 캡
  - 비용: 트랜치마다 왕복비용 전액 부과(진입·청산 각 1회)

재현:
  .venv/bin/python3 scripts/analysis/pyramiding_feasibility.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

# 추세계열만 — 문헌상 평균회귀엔 부적합하므로 fng_contrarian/vix_rsi는 대상 아님
TREND_ALGOS = ("macd_momentum", "regime_trend", "omnibus", "multi_factor")
ADD_LEVELS = (0.5, 1.0)  # d 배수
# 비용은 backtest와 동일 출처(frequency 비용 시나리오) — 상수 재정의 금지
RT_COST = frequency.get_cost_scenario(
    cost_scenario_id=frequency.DEFAULT_COST_SCENARIO_ID
).all_in_round_trip_cost_pct


async def _bars(db, symbol: str) -> list[dict]:
    rows: list[dict] = []
    page = 0
    while True:
        res = (
            await db.table("arena_ohlcv_bars")
            .select("open_time,high,low,close")
            .eq("symbol", symbol)
            .eq("interval", "4h")
            .order("open_time")
            .range(page * 1000, page * 1000 + 999)
            .execute()
        )
        if not res.data:
            break
        rows.extend(res.data)
        if len(res.data) < 1000:
            break
        page += 1
    seen = {r["open_time"]: r for r in rows}
    return [seen[k] for k in sorted(seen)]


def _ts(v):
    from datetime import datetime, timezone

    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def simulate(trade, bars: list[dict], add_w: float) -> tuple[float, float, int]:
    """(baseline 가중수익, 피라미딩 가중수익, 추가체결 수). 수익은 소수(0.01=1%)."""
    sign = -1.0 if trade.direction == "short" else 1.0
    entry, exit_p = trade.open_price, trade.close_price
    w0 = trade.position_weight
    base = w0 * ((exit_p / entry - 1.0) * sign - RT_COST)

    d = abs(entry - trade.stop_loss_price)
    if d <= 0:
        return base, base, 0

    # 보유 구간 봉에서 각 레벨 도달 여부 — 롱은 high, 숏은 low
    span = [b for b in bars if trade.open_time <= _ts(b["open_time"]) <= trade.close_time]
    tranches = [(entry, w0)]
    total_w = w0
    for mult in ADD_LEVELS:
        level = entry + sign * mult * d
        touched = any(
            (float(b["high"]) >= level) if sign > 0 else (float(b["low"]) <= level) for b in span
        )
        if not touched:
            break  # 순차 도달 — 0.5d를 못 넘었으면 1.0d도 없음
        w = min(add_w, parameters.VOL_WEIGHT_MAX - total_w)
        if w <= 0:
            break
        tranches.append((level, w))
        total_w += w

    pyr = sum(w * ((exit_p / p - 1.0) * sign - RT_COST) for p, w in tranches)
    return base, pyr, len(tranches) - 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--add-weights", nargs="*", type=float, default=[0.1, 0.15, 0.2])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1
    macro_rows = build_macro_rows(parquet)
    print(f"백필 macro: {len(macro_rows)}일 왕복비용 {RT_COST * 10000:.0f}bps")
    print(
        f"추가 레벨: 진입가 ± {ADD_LEVELS} × d (d=|진입가-초기손절가|), 총비중 캡 {parameters.VOL_WEIGHT_MAX}\n"
    )

    await positions.init()
    db = positions.db()
    warm = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    totals: dict[tuple[str, float], float] = defaultdict(float)
    base_totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    adds: dict[tuple[str, float], int] = defaultdict(int)
    per_trade: dict[tuple[str, float], list[float]] = defaultdict(list)
    per_trade_base: dict[str, list[float]] = defaultdict(list)

    for symbol in args.symbols:
        pid = (
            frequency.LIVE_4H_PROFILE_ID
            if symbol == parameters.BINANCE_SYMBOL
            else frequency.multi_asset_shadow_profile_id(symbol)
        )
        prof = frequency.get_frequency_profile(pid)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=prof.interval,
            limit=2000,
            warmup_bars=warm,
            indicator_profile_id=prof.default_indicator_profile_id,
            macro_rows=macro_rows,
        )
        if not frames:
            continue
        res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        bars = await _bars(db, symbol)
        print(f"########## {symbol} — 거래 {len(res.trades)}건 ##########")
        for algo in TREND_ALGOS:
            ts = [t for t in res.trades if t.algo_id == algo]
            if not ts:
                continue
            line = f"  {algo:15} n={len(ts):>3}"
            for t in ts:
                b, _, _ = simulate(t, bars, 0.0)
                base_totals[algo] += b
                per_trade_base[algo].append(b)
                counts[algo] += 1
            line += f" baseline {sum(x for x in per_trade_base[algo][-len(ts) :]) * 100:>+7.2f}%"
            for aw in args.add_weights:
                s = 0.0
                na = 0
                for t in ts:
                    _, p, k = simulate(t, bars, aw)
                    s += p
                    na += k
                    totals[(algo, aw)] += p
                    per_trade[(algo, aw)].append(p)
                    adds[(algo, aw)] += k
                line += f" | +{aw:.2f}: {s * 100:>+7.2f}%(추가{na})"
            print(line)
        print()

    print("########## 3자산 합산 (가중수익 합%) ##########")
    print(
        f"{'algo':16} {'n':>4} {'baseline':>10} "
        + " ".join(f"{'+' + str(w):>18}" for w in args.add_weights)
    )
    for algo in TREND_ALGOS:
        if not counts[algo]:
            continue
        row = f"{algo:16} {counts[algo]:>4} {base_totals[algo] * 100:>+10.2f} "
        for aw in args.add_weights:
            delta = (totals[(algo, aw)] - base_totals[algo]) * 100
            row += f" {totals[(algo, aw)] * 100:>+8.2f}(Δ{delta:>+6.2f})"
        print(row)
    print()
    for aw in args.add_weights:
        tot_b = sum(base_totals[a] for a in TREND_ALGOS if counts[a])
        tot_p = sum(totals[(a, aw)] for a in TREND_ALGOS if counts[a])
        n_add = sum(adds[(a, aw)] for a in TREND_ALGOS)
        print(
            f"  add_w={aw:.2f}: baseline {tot_b * 100:+.2f}% → 피라미딩 {tot_p * 100:+.2f}% (Δ{(tot_p - tot_b) * 100:+.2f}%p, 추가체결 {n_add}건)"
        )

    # 부트스트랩: 거래단위 차분의 95% CI (0 포함이면 노이즈)
    print("\n########## 차분(피라미딩−baseline) 거래단위 부트스트랩 95%CI ##########")
    rng = np.random.default_rng(42)
    for aw in args.add_weights:
        diffs = []
        for algo in TREND_ALGOS:
            if not counts[algo]:
                continue
            diffs += [
                p - b for p, b in zip(per_trade[(algo, aw)], per_trade_base[algo], strict=True)
            ]
        if len(diffs) < 3:
            continue
        arr = np.asarray(diffs)
        draws = rng.choice(arr, size=(3000, arr.size), replace=True).sum(axis=1)
        lo, hi = np.percentile(draws, [2.5, 97.5])
        verdict = (
            "0 포함 → 노이즈"
            if lo <= 0 <= hi
            else ("전부 양수 → 유망" if lo > 0 else "전부 음수 → 해로움")
        )
        print(
            f"  add_w={aw:.2f}: 합계Δ {arr.sum() * 100:>+6.2f}%p  95%CI [{lo * 100:>+6.2f}, {hi * 100:>+6.2f}]  {verdict}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
