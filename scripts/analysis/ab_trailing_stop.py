"""트레일링 스톱 on/off A/B — 동일 OHLCV 프레임에 run_replay를 두 번 돌려 비교."""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, "src")

from arena import backtest, frequency, parameters, positions  # noqa: E402


def _summarize(label: str, result: backtest.BacktestResult) -> dict:
    trades = result.trades
    n = len(trades)
    wins = sum(1 for t in trades if t.net_ret_pct > 0)
    total_ret = sum(t.net_ret_pct for t in trades)
    avg_hold = sum(t.hold_hours for t in trades) / n if n else 0.0
    reasons = Counter(t.exit_reason for t in trades)
    # per-algo 종료 자산 (복리)
    eq: dict[str, float] = {}
    for t in trades:
        eq[t.algo_id] = eq.get(t.algo_id, 1.0) * (1.0 + t.net_ret_pct)
    print(f"\n=== {label} ===")
    print(
        f"  trades={n}  win%={100 * wins / n if n else 0:.1f}  sum_net_ret={total_ret * 100:+.2f}%"
    )
    print(f"  avg_hold={avg_hold:.1f}h  exit_reasons={dict(reasons)}")
    print(
        f"  per-algo terminal equity: {{ {', '.join(f'{k}:{v:.3f}' for k, v in sorted(eq.items()))} }}"
    )
    return {"n": n, "wins": wins, "total_ret": total_ret, "reasons": reasons, "eq": eq}


async def main() -> int:
    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    indicator_profile_id = profile.default_indicator_profile_id
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=indicator_profile_id,
        from_date=None,
        to_date=None,
    )
    if not frames:
        print("프레임 없음")
        return 1
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )
    settings = backtest.BacktestSettings()

    parameters.TRAILING_STOP_ENABLED = True
    on = backtest.run_replay(frames, settings=settings)
    s_on = _summarize("트레일링 ON (arena-spot-v4)", on)

    parameters.TRAILING_STOP_ENABLED = False
    off = backtest.run_replay(frames, settings=settings)
    s_off = _summarize("트레일링 OFF (기존 고정 손절)", off)

    # --- sanity: 스톱이 실제 트리거되는 타이트 스톱 시나리오 (메커니즘 검증) ---
    import dataclasses

    tight = dataclasses.replace(settings, stop_loss_min_pct=0.005, stop_loss_max_pct=0.015)
    parameters.TRAILING_STOP_ENABLED = True
    t_on = backtest.run_replay(frames, settings=tight)
    _summarize("[tight stop 1.5%] 트레일링 ON", t_on)
    parameters.TRAILING_STOP_ENABLED = False
    t_off = backtest.run_replay(frames, settings=tight)
    _summarize("[tight stop 1.5%] 트레일링 OFF", t_off)

    parameters.TRAILING_STOP_ENABLED = True  # 원복

    def geomean(eq: dict[str, float]) -> float:
        vals = list(eq.values())
        if not vals:
            return 1.0
        prod = 1.0
        for v in vals:
            prod *= v
        return prod ** (1.0 / len(vals))

    print("\n=== Δ (ON − OFF) ===")
    print(f"  sum_net_ret: {(s_on['total_ret'] - s_off['total_ret']) * 100:+.2f}%p")
    print(
        f"  포트폴리오 기하평균 자산: ON={geomean(s_on['eq']):.4f}  OFF={geomean(s_off['eq']):.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
