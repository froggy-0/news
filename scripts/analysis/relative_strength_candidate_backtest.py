"""7번째+ 알고 후보 — Vanguard: 자산간 상대강도(cross-asset relative strength) 롱온리.

배경 (2026-08-15 세션): "정직한 표본 확보를 위해 무기한 대기"만으로는 방향이 아니라는
지적에 따라 스프린트 구조(가설 → 당일 백테스트 → 결론)로 전환한 첫 산출물. 기존 6개
알고는 전부 자기 자산의 가격만 보고 판단하는데, BTC/ETH/SOL 3자산이 실거래 확보
(2026-08-06)됐으니 "셋 중 지금 가장 강한 자산이 어느 것인가"라는 횡단면(cross-sectional)
정보가 처음으로 신호원이 될 수 있다. new-algo-candidates(2026-08-14)가 다음 축으로
지목했던 항목.

설계 (단일 사전 사양, 그리드 튜닝 아님 — wellspring/undertow/chorus와 동일 방법론):
  rel_strength_i(t) = trailing_return_i(t, L) − mean(trailing_return_j(t, L) for j != i)
  진입: rel_strength_i >= REL_STRENGTH_THRESHOLD  AND  trailing_return_i(t, L) > 0
        (상대적으로 셋 중 제일 강해도 절대 모멘텀이 마이너스면 진입 안 함 — "셋 중 제일
        덜 나쁜 놈"에 올라타는 것 방지)  AND  not risk-off(로컬 4h 레짐, 자산별 독립계산).
  청산: 조건 거짓 → 표준 flat_signal(run_replay 엔진 공용 로직, 기존 6알고와 동일).
  L=30봉(4h×30=5일), threshold=0.03(=peer 평균보다 3%p 우위) — 사전설계값. 민감도는
  L∈{15,30,60}, threshold∈{0.0,0.03,0.06}만 확인(그리드 탐색/선택 아님).

macro 미주입(macro_rows=[]) — 순수 가격기반 신호라 macro backfill(2026-07까지만 존재)에
안 묶이고 arena_ohlcv_bars 전체 커버리지(2023-05-01~현재, 3자산 연속 6600+봉)를 그대로
쓴다. risk-off는 run_replay가 로컬 지표로 자동 주입하는 arena_regime_state로 처리
(algorithms.py 기존 6알고와 동일 경로, macro 불필요).

기존 6개 ALGORITHMS dict/live 배선 무변경 — backtest.run_replay(strategy_fns=...)
오버라이드로만 검증. 통과해도 "채택"이 아니라 "실거래 배선을 검토할 가치가 있는지"의
1차 필터(new_algo_candidates_backtest.py와 동일 기준).

재현: .venv/bin/python3 scripts/analysis/relative_strength_candidate_backtest.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import backtest, parameters, positions  # noqa: E402
from arena.algorithms import _is_risk_off, _regime_state  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# ── 설계값 (사전 사양) ────────────────────────────────────────────────────
REL_STRENGTH_LOOKBACK_BARS = 30
REL_STRENGTH_THRESHOLD = 0.03

_SENSITIVITY_LOOKBACKS = [15, 30, 60]
_SENSITIVITY_THRESHOLDS = [0.0, 0.03, 0.06]


def vanguard(macro: dict, ind: dict) -> str | None:
    """자산간 상대강도 — 셋 중 가장 강하고(peer 대비) 절대 모멘텀도 양수일 때만 롱."""
    if _is_risk_off(_regime_state(macro)):
        return None
    rel = ind.get("peer_rel_strength")
    own = ind.get("own_trailing_return")
    if rel is None or own is None:
        return None
    return "long" if (rel >= REL_STRENGTH_THRESHOLD and own > 0) else None


async def _fetch_close_series(db, symbol: str) -> pd.Series:
    """arena_ohlcv_bars 전체(2023-05-01~현재)를 페이지네이션으로 가져와 close_time 인덱스 Series."""
    rows: list[dict] = []
    page_size = 1000
    start = 0
    while True:
        res = await (
            db.table("arena_ohlcv_bars")
            .select("close_time,close")
            .eq("symbol", symbol)
            .eq("interval", "4h")
            .order("open_time")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    idx = pd.to_datetime([r["close_time"] for r in rows], utc=True)
    vals = [float(r["close"]) for r in rows]
    s = pd.Series(vals, index=idx, name=symbol)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _compute_rel_strength(closes: pd.DataFrame, lookback: int) -> dict[str, pd.DataFrame]:
    """symbol별 {close_time -> (rel_strength, own_trailing_return)} 계산."""
    rets = closes.pct_change(lookback)
    out: dict[str, pd.DataFrame] = {}
    for sym in closes.columns:
        peers = [c for c in closes.columns if c != sym]
        peer_mean = rets[peers].mean(axis=1)
        rel = rets[sym] - peer_mean
        out[sym] = pd.DataFrame({"own_ret": rets[sym], "rel": rel})
    return out


def _bootstrap_ci(
    trades: list, n_resamples: int = 3000, seed: int = 42
) -> tuple[float, float, float]:
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


def _summarize(symbol: str, trades: list, buy_hold: float) -> None:
    algo_trades = [t for t in trades if t.algo_id == "vanguard"]
    n = len(algo_trades)
    print(f"\n--- vanguard / {symbol} (n={n}) — buy&hold(구간 전체)={buy_hold:+.2f}% ---")
    if n == 0:
        print("  거래 없음 (임계값 미도달)")
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


def _sensitivity_fire_counts(rel_maps: dict[int, dict[str, pd.DataFrame]], symbol: str) -> None:
    print("  [민감도] L×threshold 별 신호 발화 횟수 (그리드 탐색 아님, 방향확인용):")
    for L in _SENSITIVITY_LOOKBACKS:
        df = rel_maps[L][symbol]
        for t in _SENSITIVITY_THRESHOLDS:
            n_fire = int(((df["rel"] >= t) & (df["own_ret"] > 0)).sum())
            print(
                f"    L={L:>3} threshold={t:+.2f} -> {n_fire}건 발화(봉 기준, risk-off/진입판정 이전)"
            )


async def main() -> int:
    await positions.init()
    db = positions.db()

    print(f"자산: {SYMBOLS}  L={REL_STRENGTH_LOOKBACK_BARS}봉  threshold={REL_STRENGTH_THRESHOLD}")
    print("close 시계열 로딩 (arena_ohlcv_bars, 2023-05-01~현재, 페이지네이션)...")
    series = {}
    for sym in SYMBOLS:
        s = await _fetch_close_series(db, sym)
        series[sym] = s
        print(f"  {sym}: {len(s)}봉  {s.index[0]}~{s.index[-1]}")

    closes = pd.concat(series, axis=1, join="inner").sort_index()
    print(f"정렬 후 공통 타임스탬프: {len(closes)}봉  {closes.index[0]}~{closes.index[-1]}")

    rel_primary = _compute_rel_strength(closes, REL_STRENGTH_LOOKBACK_BARS)
    rel_sensitivity = {L: _compute_rel_strength(closes, L) for L in _SENSITIVITY_LOOKBACKS}

    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    from_dt = closes.index[0].to_pydatetime()
    to_dt = closes.index[-1].to_pydatetime()

    total_sum_w = 0.0
    for symbol in SYMBOLS:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval="4h",
            warmup_bars=warmup,
            macro_rows=[],
            from_date=from_dt,
            to_date=to_dt,
        )
        if not frames:
            print("  frames 없음")
            continue
        rel_df = rel_primary[symbol]
        injected = []
        for f in frames:
            row = rel_df.loc[rel_df.index == pd.Timestamp(f.bar.close_time)]
            if row.empty or pd.isna(row["rel"].iloc[0]) or pd.isna(row["own_ret"].iloc[0]):
                continue
            new_ind = dict(f.indicators)
            new_ind["peer_rel_strength"] = float(row["rel"].iloc[0])
            new_ind["own_trailing_return"] = float(row["own_ret"].iloc[0])
            injected.append(backtest.ReplayFrame(bar=f.bar, indicators=new_ind, macro=f.macro))
        print(
            f"  frames={len(frames)}  신호커버={len(injected)}  {injected[0].bar.close_time.date()}~{injected[-1].bar.close_time.date()}"
            if injected
            else "  신호 커버 프레임 없음"
        )
        if not injected:
            continue
        buy_hold = (injected[-1].bar.close / injected[0].bar.close - 1.0) * 100
        result = backtest.run_replay(injected, strategy_fns={"vanguard": vanguard})
        _summarize(symbol, result.trades, buy_hold)
        algo_trades = [t for t in result.trades if t.algo_id == "vanguard"]
        total_sum_w += sum(t.ret_pct * t.position_weight for t in algo_trades) * 100
        _sensitivity_fire_counts(rel_sensitivity, symbol)

    print(
        f"\n{'=' * 70}\n3자산 가중합% 합계 (참고용, 자산별 독립자본이라 단순가산): {total_sum_w:+.2f}%\n{'=' * 70}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
