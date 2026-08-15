"""신규 알고 후보 3종(Wellspring/Undertow/Chorus) 백테스트 — orthogonal 신호원 탐색.

배경: 기존 6개 알고(regime_trend·fng_contrarian·vix_rsi·macd_momentum·multi_factor·
omnibus)를 튜닝하는 대신, 아무도 주 신호로 안 쓰는 정보원(ETF 순유입·펀딩비·시장폭)을
써서 "추가"할 7번째+ 알고 후보를 탐색한다(2026-08-14 세션 결정 — 교체 아닌 추가).
현재 3개 전부 macro veto로만 쓰이는 필드를 주 트리거로 승격한 것.

- Wellspring: etf_flow_zscore 서지 추종 (기관 자금흐름)
- Undertow:   funding_zscore 극단 음수 역발산 (레버리지 시장 포지셔닝)
- Chorus:     breadth_up_ratio 확산 확인 추종 (횡단면 시장 참여도)

전부 ALGORITHMS dict/live 배선에 손대지 않고 backtest.run_replay(strategy_fns=...)
오버라이드로만 검증한다 — 통과 여부와 무관하게 라이브 무영향.

방법론: 단일 사전 사양(그리드 튜닝 아님) → DSR은 n_trials=1로 계산(선택 편향 없음).
전/후반 분할 + 부트스트랩 95%CI로 강건성만 확인. 통과해도 이건 "채택"이 아니라
"실거래 배선을 검토할 가치가 있는지"의 1차 필터.

재현:
  .venv/bin/python3 scripts/analysis/new_algo_candidates_backtest.py
  .venv/bin/python3 scripts/analysis/new_algo_candidates_backtest.py --symbol ETHUSDT
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402
from arena.algorithms import _is_risk_off, _regime_state  # noqa: E402

# ── 후보 신호 함수 (설계값, 그리드 튜닝 없음 — regime_trend/macd_momentum과 동일한
#    "재현 가능한 로직 명시" 스타일. 임계값은 뒤에서 ±민감도만 가볍게 확인) ──────────

WELLSPRING_ETF_INFLOW_Z = 1.0


def wellspring(macro: dict, ind: dict) -> str | None:
    """기관 ETF 순유입 서지 추종 — etf_flow_zscore가 강한 양수일 때 롱."""
    z = macro.get("etf_flow_zscore")
    if z is None or _is_risk_off(_regime_state(macro)):
        return None
    return "long" if z >= WELLSPRING_ETF_INFLOW_Z else None


UNDERTOW_FUNDING_Z = -1.5


def undertow(macro: dict, ind: dict) -> str | None:
    """펀딩비 극단 음수 역발산 — 레버리지 숏 과밀(비관 극단) 시 롱."""
    z = macro.get("funding_zscore")
    if z is None or _is_risk_off(_regime_state(macro)):
        return None
    return "long" if z <= UNDERTOW_FUNDING_Z else None


CHORUS_BREADTH_MIN = 0.70


def chorus(macro: dict, ind: dict) -> str | None:
    """시장 폭 확산 확인 추종 — breadth_up_ratio가 넓은 참여를 보일 때 롱."""
    b = macro.get("breadth_up_ratio")
    if b is None or _is_risk_off(_regime_state(macro)):
        return None
    return "long" if b >= CHORUS_BREADTH_MIN else None


CANDIDATES: dict[str, backtest.StrategyFn] = {
    "wellspring": wellspring,
    "undertow": undertow,
    "chorus": chorus,
}

# 민감도 확인용 임계값 밴드(그리드 탐색 아님 — "이 근방에서 부호가 뒤집히는지"만 확인)
_SENSITIVITY = {
    "wellspring": ("etf_flow_zscore", [0.5, 1.0, 1.5], lambda v, t: v >= t),
    "undertow": ("funding_zscore", [-1.0, -1.5, -2.0], lambda v, t: v <= t),
    "chorus": ("breadth_up_ratio", [0.60, 0.70, 0.80], lambda v, t: v >= t),
}


def _bootstrap_ci(
    trades: list, n_resamples: int = 3000, seed: int = 42
) -> tuple[float, float, float]:
    """가중수익 부트스트랩 95%CI. (point, lo, hi) — trades는 단일 algo_id 리스트."""
    if not trades:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    weighted = np.array([t.ret_pct * t.position_weight for t in trades])
    point = weighted.sum()
    n = len(weighted)
    resampled = rng.choice(weighted, size=(n_resamples, n), replace=True).sum(axis=1)
    lo, hi = np.percentile(resampled, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def _split_half(trades: list) -> tuple[float, float]:
    ts = sorted(trades, key=lambda t: t.open_time)
    mid = len(ts) // 2
    if mid == 0:
        return 0.0, 0.0
    first = sum(t.ret_pct * t.position_weight for t in ts[:mid]) * 100
    second = sum(t.ret_pct * t.position_weight for t in ts[mid:]) * 100
    return first, second


def _summarize(algo_id: str, symbol: str, trades: list) -> None:
    algo_trades = [t for t in trades if t.algo_id == algo_id]
    n = len(algo_trades)
    print(f"\n--- {algo_id} / {symbol} (n={n}) ---")
    if n == 0:
        print("  거래 없음 (임계값 미도달 또는 macro 미커버)")
        return
    wins = [t for t in algo_trades if t.ret_pct > 0]
    losses = [t for t in algo_trades if t.ret_pct <= 0]
    win_rate = len(wins) / n * 100
    sum_w = sum(t.ret_pct * t.position_weight for t in algo_trades) * 100
    gross_win = sum(t.ret_pct for t in wins)
    gross_loss = -sum(t.ret_pct for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    avg_hold = sum(t.hold_hours for t in algo_trades) / n
    exits = defaultdict(int)
    for t in algo_trades:
        exits[t.exit_reason] += 1
    print(
        f"  win%={win_rate:.1f}  sum_w%={sum_w:+.2f}  PF={pf:.2f}  "
        f"avg_hold={avg_hold:.0f}h  exits={dict(exits)}"
    )
    point, lo, hi = _bootstrap_ci(algo_trades)
    print(
        f"  가중합 부트스트랩 95%CI: [{lo * 100:+.2f}%, {hi * 100:+.2f}%] (point={point * 100:+.2f}%)"
    )
    if n >= 6:
        first, second = _split_half(algo_trades)
        print(f"  전/후반 분할: 전반={first:+.2f}%  후반={second:+.2f}%")
    returns = np.array([t.ret_pct for t in algo_trades])
    dsr = deflated_sharpe_ratio(returns, n_trials=1)
    print(f"  DSR(n_trials=1, 무튜닝 단일사양)={dsr['dsr']:.3f}  sharpe={dsr['sharpe']:.3f}")


def _sensitivity_check(algo_id: str, symbol: str, frames: list) -> None:
    field, thresholds, cmp_fn = _SENSITIVITY[algo_id]
    print(f"  [민감도] {field} 임계값별 신호 발화 횟수 (그리드 탐색 아님, 방향확인용):")
    for t in thresholds:
        n_fire = sum(
            1
            for f in frames
            if f.macro.get(field) is not None
            and not _is_risk_off(_regime_state(f.macro))
            and cmp_fn(f.macro.get(field), t)
        )
        print(f"    threshold={t:+.2f} -> {n_fire}건 발화 (봉 기준, 진입과 다름)")


async def _run_symbol(db, symbol: str, macro_rows: list[dict], from_dt, to_dt) -> list:
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile_id = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    profile = frequency.get_frequency_profile(profile_id)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=symbol,
        interval=profile.interval,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_dt,
        to_date=to_dt,
    )
    return frames


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows[-1]["reference_date"], tz=timezone.utc).to_pydatetime()
    print(
        f"macro 백필: {len(macro_rows)}일 {macro_rows[0]['reference_date']}~"
        f"{macro_rows[-1]['reference_date']}"
    )
    print(
        f"후보: {list(CANDIDATES)}  임계값: wellspring>={WELLSPRING_ETF_INFLOW_Z} "
        f"undertow<={UNDERTOW_FUNDING_Z} chorus>={CHORUS_BREADTH_MIN}"
    )

    await positions.init()
    db = positions.db()

    for symbol in args.symbols:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")
        frames = await _run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        if not frames:
            print(f"  frames 없음 — {symbol} 히스토리 확인 필요")
            continue
        covered = sum(1 for f in frames if f.macro.get("etf_flow_zscore") is not None)
        print(
            f"  frames={len(frames)}  {frames[0].bar.close_time.date()}~"
            f"{frames[-1].bar.close_time.date()}  macro커버={covered}/{len(frames)}"
        )
        buy_hold = (frames[-1].bar.close / frames[0].bar.close - 1.0) * 100
        print(f"  buy&hold(구간 전체): {buy_hold:+.2f}%")

        result = backtest.run_replay(frames, strategy_fns=CANDIDATES)
        for algo_id in CANDIDATES:
            _summarize(algo_id, symbol, result.trades)
            _sensitivity_check(algo_id, symbol, frames)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
