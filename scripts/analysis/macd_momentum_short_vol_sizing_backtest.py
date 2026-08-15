"""macd_momentum 숏 후보 — 모멘텀 고유 변동성 사이징 검증 (Phase B 2순환 §3-2).

배경: docs/arena/research/short-entry-asymmetry-literature-review-20260815.md §3-2.
§8(`macd_momentum_short_backtest.py`)에서 risk-off veto 유지/제거 2변형만 비교했고
(18개 판정기준 전부 미달, DSR 최댓값 0.586), veto제거가 3자산 전부 일관되게
veto유지보다 우세했다. 이 스크립트는 그 veto 축은 고정(veto제거만 사용)하고,
Barroso & Santa-Clara(2015, "Momentum Has Its Moments")가 제시하는 **모멘텀 신호
고유 변동성 기반 사이징**이라는 새 축만 추가로 검증한다(§4 방법론, D017 "같은
사양 재시도 금지"에 해당하지 않는 새 가설).

설계(단일 사전 사양, 그리드 아님):
  - σ_momentum,t = TSMOM_NL 신호 s_t(가격 자체가 아니라 이미 vol-정규화된 모멘텀
    신호, `algorithms._tsmom_nl_signal`)의 최근 MOM_VOL_LOOKBACK_BARS(=30, 문헌이
    제시한 20~60봉 범위의 중앙값)봉 롤링 표준편차.
  - target_t = σ_momentum의 확장(expanding) 평균을 1봉 시차(shift(1))로 사용 —
    미래 데이터를 안 쓰는 인과적(causal) 기준치(look-ahead 방지, 이 프로젝트
    관행대로 warmup 부족 구간은 scale=1.0 무보정).
  - scale_t = clamp(target_t / σ_momentum,t, MOM_VOL_SCALE_MIN=0.2, MOM_VOL_SCALE_MAX=1.0)
    — 모멘텀 신호가 평소보다 불안정(고변동)할 때만 사이즈를 줄이고, 평소보다
    안정적이어도 원래 사이징(f(s)) 이상으로 증폭하지 않는다(상한 1.0 — 이 축의
    목적은 문헌이 지목한 "모멘텀 크래시" 리스크 완화이지 수익 극대화가 아님).
  - 최종 사이징 = abs(f(s)) × scale_t (§8의 abs(f(s)) 절댓값 사이징에 곱셈 배수로
    추가 — f(s) 자체는 변경하지 않음).

비교(3자산 × 2변형 = 6셀, veto 축은 §8 결과대로 veto제거로 고정):
  - baseline: §8의 veto제거 변형 그대로(사이징 미적용, 회귀 재현용).
  - vol_scaled: 위 scale_t를 추가 적용.

ALGORITHMS dict·PERP_LIVE_ENABLED_ALGOS·algorithms.py 어느 것도 건드리지 않음 —
backtest.run_replay(strategy_fns=...) 오버라이드 + product_type="usdm_perp"로만
검증(§4 방법론). §8과 동일하게 algorithms.tsmom_nl_position_multiplier를 런타임
몽키패치(프로세스 로컬, 소스 파일 무변경)하되, scale_t는 프레임별로 다르므로
frame.indicators dict에 "mom_vol_scale" 키를 사전 주입해 몽키패치 함수가 읽도록
한다(ReplayFrame은 frozen dataclass이지만 indicators 필드 자체는 평범한 dict라
in-place 주입 가능 — attribute 재할당이 아니므로 frozen 제약과 무관, 이 스크립트가
로드한 frames는 이 프로세스에서만 쓰이는 사본이라 부작용 없음).

재현:
  .venv/bin/python3 scripts/analysis/macd_momentum_short_vol_sizing_backtest.py
"""

from __future__ import annotations

import argparse
import asyncio
import math
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

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402
from arena.algorithms import _tsmom_nl_signal  # noqa: E402

# ── 모멘텀 고유 변동성 사이징 설계값 (단일 사전 사양, 그리드 아님) ──────────────
MOM_VOL_LOOKBACK_BARS = 30
MOM_VOL_SCALE_MIN = 0.2
MOM_VOL_SCALE_MAX = 1.0


def _compute_mom_vol_scale(frames: list) -> list[float]:
    """frame 순서(시간순)대로 causal한 모멘텀신호 변동성 스케일 계산."""
    s_values = [_tsmom_nl_signal(fr.indicators) for fr in frames]
    s_series = pd.Series([v if v is not None else np.nan for v in s_values])
    rolling_std = s_series.rolling(MOM_VOL_LOOKBACK_BARS, min_periods=MOM_VOL_LOOKBACK_BARS).std()
    # target: 현재 봉 이전까지의 rolling_std 확장평균(1봉 시차 — 미래데이터 미사용)
    target = rolling_std.expanding(min_periods=MOM_VOL_LOOKBACK_BARS).mean().shift(1)
    scale = (target / rolling_std).clip(lower=MOM_VOL_SCALE_MIN, upper=MOM_VOL_SCALE_MAX)
    return scale.fillna(1.0).tolist()


def _inject_mom_vol_scale(frames: list) -> None:
    scale = _compute_mom_vol_scale(frames)
    for fr, sc in zip(frames, scale, strict=True):
        fr.indicators["mom_vol_scale"] = float(sc)


# ── 사이징 몽키패치 (§8과 동일한 abs(f(s)) 절댓값, vol_scaled만 scale_t 추가곱) ──


def _sizing_baseline(macro: dict, ind: dict) -> float:
    if not parameters.TSMOM_NL_ENABLED:
        return 1.0
    s = _tsmom_nl_signal(ind)
    if s is None:
        return 0.0
    f = s / (s * s + 1.0)
    return max(0.0, min(parameters.TSMOM_NL_WEIGHT_CAP, abs(f)))


def _sizing_vol_scaled(macro: dict, ind: dict) -> float:
    base = _sizing_baseline(macro, ind)
    scale = ind.get("mom_vol_scale", 1.0)
    return base * scale


# ── 숏 후보 신호 함수 (§8 veto제거 변형 고정 — §8 결과: 3자산 전부 veto제거 우세) ──


def macd_momentum_short_noveto(macro: dict, ind: dict) -> str | None:
    s = _tsmom_nl_signal(ind)
    if s is None:
        return None
    return "short" if s < -parameters.TSMOM_NL_MIN_SIGNAL else None


STRATEGY_FNS: dict[str, backtest.StrategyFn] = {
    "macd_momentum": macd_momentum_short_noveto,
}


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


def _summarize(label: str, symbol: str, trades: list) -> dict:
    algo_trades = [t for t in trades if t.algo_id == "macd_momentum"]
    n = len(algo_trades)
    print(f"\n--- {label} / {symbol} (n={n}) ---")
    if n == 0:
        print("  거래 없음")
        return {"label": label, "symbol": symbol, "n": 0}
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
        f"  가중합 부트스트랩95%CI: [{lo * 100:+.2f}%, {hi * 100:+.2f}%] (point={point * 100:+.2f}%)"
    )
    first = second = 0.0
    if n >= 6:
        first, second = _split_half(algo_trades)
        print(f"  전/후반 분할: 전반={first:+.2f}%  후반={second:+.2f}%")
    returns = np.array([t.ret_pct for t in algo_trades])
    dsr = deflated_sharpe_ratio(returns, n_trials=1)
    print(f"  DSR(n_trials=1)={dsr['dsr']:.3f}  sharpe={dsr['sharpe']:.3f}")
    return {
        "label": label,
        "symbol": symbol,
        "n": n,
        "win_rate": win_rate,
        "sum_w_pct": sum_w,
        "pf": pf,
        "ci_lo_pct": lo * 100,
        "ci_hi_pct": hi * 100,
        "split_first_pct": first,
        "split_second_pct": second,
        "dsr": dsr["dsr"],
    }


async def _run_symbol(db, symbol: str, macro_rows: list[dict], from_dt, to_dt) -> list:
    warmup = (
        parameters.MACD_SLOW_PERIOD
        + parameters.MACD_SIGNAL_PERIOD
        + parameters.TSMOM_NL_LOOKBACK_BARS
        + MOM_VOL_LOOKBACK_BARS  # 모멘텀신호 자체의 롤링 std warmup까지 포함
    )
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
        f"TSMOM_NL_ENABLED={parameters.TSMOM_NL_ENABLED} "
        f"lookback={parameters.TSMOM_NL_LOOKBACK_BARS} vol_mode={parameters.TSMOM_NL_VOL_MODE} "
        f"min_signal={parameters.TSMOM_NL_MIN_SIGNAL} weight_cap={parameters.TSMOM_NL_WEIGHT_CAP}"
    )
    print(
        f"MOM_VOL_LOOKBACK_BARS={MOM_VOL_LOOKBACK_BARS} "
        f"scale_range=[{MOM_VOL_SCALE_MIN},{MOM_VOL_SCALE_MAX}] (veto축 고정: §8 veto제거)"
    )

    assert hasattr(algorithms, "tsmom_nl_position_multiplier")

    settings_perp = backtest.BacktestSettings(product_type="usdm_perp")

    await positions.init()
    db = positions.db()

    results: list[dict] = []
    for symbol in args.symbols:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")
        frames = await _run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        if not frames:
            print(f"  frames 없음 — {symbol} 히스토리 확인 필요")
            continue
        print(
            f"  frames={len(frames)}  {frames[0].bar.close_time.date()}~"
            f"{frames[-1].bar.close_time.date()}"
        )
        buy_hold = (frames[-1].bar.close / frames[0].bar.close - 1.0) * 100
        print(f"  buy&hold(구간 전체): {buy_hold:+.2f}%")

        _inject_mom_vol_scale(frames)
        n_scaled = sum(1 for fr in frames if fr.indicators.get("mom_vol_scale", 1.0) < 1.0)
        print(f"  scale<1.0 적용 봉수: {n_scaled}/{len(frames)}")

        for label, sizing_fn in (
            ("baseline(사이징미적용)", _sizing_baseline),
            ("vol_scaled(사이징적용)", _sizing_vol_scaled),
        ):
            algorithms.tsmom_nl_position_multiplier = sizing_fn
            result = backtest.run_replay(frames, strategy_fns=STRATEGY_FNS, settings=settings_perp)
            results.append(
                _summarize(f"macd_momentum_short[noveto/{label}]", symbol, result.trades)
            )

    print(f"\n{'=' * 70}\n요약표\n{'=' * 70}")
    header = f"{'label':38s} {'symbol':10s} {'n':>4s} {'win%':>6s} {'sum_w%':>8s} {'PF':>6s} {'CI_lo%':>8s} {'CI_hi%':>8s} {'전반%':>7s} {'후반%':>7s} {'DSR':>6s}"
    print(header)
    for r in results:
        if r.get("n", 0) == 0:
            print(f"{r['label']:38s} {r['symbol']:10s} {0:>4d}  거래없음")
            continue
        print(
            f"{r['label']:38s} {r['symbol']:10s} {r['n']:>4d} {r['win_rate']:>6.1f} "
            f"{r['sum_w_pct']:>+8.2f} {(r['pf'] if math.isfinite(r['pf']) else 99.99):>6.2f} "
            f"{r['ci_lo_pct']:>+8.2f} {r['ci_hi_pct']:>+8.2f} "
            f"{r['split_first_pct']:>+7.2f} {r['split_second_pct']:>+7.2f} {r['dsr']:>6.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
