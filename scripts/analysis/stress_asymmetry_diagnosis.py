"""STRESS 레짐의 상방/하방 비대칭 진단 (2026-08-20).

regime.classify_regime()의 stress 판정이 `abs(return_24h) > 3.0 * atr_pct`로
**부호 무관**이라, 급등도 급락과 동일하게 STRESS→_RISK_OFF_REGIMES로 분류되어
롱 전용 알고 전부가 `veto:not_risk_off`로 차단된다.

이 스크립트는 판단이 아니라 사실을 뽑는다:
  1. STRESS 발화 중 상방/하방 비율
  2. 상방 STRESS 이후 forward return (차단이 실제로 무엇을 놓쳤나)
  3. 하방 STRESS 이후 forward return (차단이 실제로 무엇을 피했나)
  4. STRESS 상태 지속 봉 수 (차단 창의 길이)

읽기 전용. 파라미터·코드 변경 없음.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

from arena import backtest, frequency, parameters, regime  # noqa: E402

FORWARD_HORIZONS = (1, 3, 6)  # 봉 단위 = 4h, 12h, 24h
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _fetch_bars(client, symbol: str) -> list[dict]:
    rows: list[dict] = []
    page = 0
    while True:
        res = (
            client.table("arena_ohlcv_bars")
            .select("open_time,close_time,open,high,low,close,volume")
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
    # run별 중복 기록 dedup (스킬 문서 명시)
    seen: dict[str, dict] = {}
    for row in rows:
        seen[str(row["open_time"])] = row
    return [seen[k] for k in sorted(seen)]


def _pct(values: list[float]) -> str:
    if not values:
        return "n/a"
    mean = statistics.mean(values) * 100
    med = statistics.median(values) * 100
    win = sum(1 for v in values if v > 0) / len(values) * 100
    return f"평균{mean:+.2f}% 중앙{med:+.2f}% 승률{win:.0f}%"


def analyse(symbol: str, frames: list) -> dict:
    states: list[str] = []
    for frame in frames:
        decision = regime.classify_regime(frame.indicators, macro={})
        states.append(decision.regime_state)

    closes = [f.bar.close for f in frames]
    up_idx: list[int] = []
    down_idx: list[int] = []
    for i, state in enumerate(states):
        if state != regime.REGIME_STRESS:
            continue
        (up_idx if frames[i].indicators.get("return_24h", 0.0) > 0 else down_idx).append(i)

    # STRESS 연속 지속 길이
    runs: list[int] = []
    run = 0
    for state in states:
        if state == regime.REGIME_STRESS:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)

    all_idx = list(range(len(closes)))

    def forward(idxs: list[int], horizon: int) -> list[float]:
        out = []
        for i in idxs:
            j = i + horizon
            if j < len(closes):
                out.append(closes[j] / closes[i] - 1.0)
        return out

    return {
        "symbol": symbol,
        "n_bars": len(frames),
        "n_stress": len(up_idx) + len(down_idx),
        "n_up": len(up_idx),
        "n_down": len(down_idx),
        "runs": runs,
        "fwd_up": {h: forward(up_idx, h) for h in FORWARD_HORIZONS},
        "fwd_down": {h: forward(down_idx, h) for h in FORWARD_HORIZONS},
        "fwd_base": {h: forward(all_idx, h) for h in FORWARD_HORIZONS},
        "start": frames[0].bar.close_time if frames else None,
        "end": frames[-1].bar.close_time if frames else None,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=list(SYMBOLS))
    args = parser.parse_args()

    load_dotenv(dotenv_path=".env")
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    warmup_bars = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    print(f"stress 임계: |return_24h| > {parameters.REGIME_STRESS_RETURN_ATR_MULTIPLE} x atr_pct")
    print(f"            range_24h_atr > {parameters.REGIME_STRESS_RANGE_ATR_MULTIPLE}")
    print("STRESS in _RISK_OFF_REGIMES → 롱 전 알고 veto:not_risk_off\n")

    results = []
    for symbol in args.symbols:
        rows = _fetch_bars(client, symbol)
        if not rows:
            print(f"{symbol}: 데이터 없음")
            continue
        frames = backtest.build_frames_from_bar_rows(
            rows,
            interval="4h",
            warmup_bars=warmup_bars,
            indicator_profile_id=frequency.DEFAULT_INDICATOR_PROFILE_ID,
            macro_rows=[],
        )
        results.append(analyse(symbol, frames))

    for r in results:
        print(
            f"===== {r['symbol']} ({r['start']:%Y-%m-%d} ~ {r['end']:%Y-%m-%d}, {r['n_bars']}봉) ====="
        )
        share = r["n_stress"] / r["n_bars"] * 100 if r["n_bars"] else 0
        print(
            f"  STRESS 발화 {r['n_stress']}봉 ({share:.1f}%) — 상방 {r['n_up']} / 하방 {r['n_down']}"
        )
        if r["runs"]:
            print(
                f"  연속 지속: 평균 {statistics.mean(r['runs']):.1f}봉 "
                f"중앙 {statistics.median(r['runs']):.0f}봉 최대 {max(r['runs'])}봉 "
                f"(1봉=4h)"
            )
        for h in FORWARD_HORIZONS:
            print(
                f"  +{h * 4:>2}h 이후 | 상방: {_pct(r['fwd_up'][h]):42s} | 하방: {_pct(r['fwd_down'][h]):42s} | 기저: {_pct(r['fwd_base'][h])}"
            )
        print()

    # 3자산 통합
    print("===== 3자산 통합 =====")
    for h in FORWARD_HORIZONS:
        up = [v for r in results for v in r["fwd_up"][h]]
        down = [v for r in results for v in r["fwd_down"][h]]
        base = [v for r in results for v in r["fwd_base"][h]]
        print(f"  +{h * 4:>2}h | 상방(n={len(up):>4}): {_pct(up):42s}")
        print(f"        | 하방(n={len(down):>4}): {_pct(down):42s}")
        print(f"        | 기저(n={len(base):>4}): {_pct(base):42s}")


if __name__ == "__main__":
    asyncio.run(main())
