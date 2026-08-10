"""Nonlinear TSMOM(macd_momentum 대체 후보) 그리드 A/B (2026-08-08).

배경: macd_momentum이 3년 백테스트(2023-08~2026-08, n=251)에서 -31.79%·DSR 0.012로
완전 기각(macd_hard_gate_tuning.py). 대체 후보로 Moskowitz·Sabbatucci·Tamoni·Uhl
(2025-12-10, "Nonlinear Time Series Momentum")의 연속 비선형 사이징 TSMOM을 설계·
루브릭검증(docs/arena/research/nonlinear-tsmom-design-20260808.md) 후 구현
(algorithms.py의 TSMOM_NL_ENABLED 분기, algo_id "macd_momentum" 슬롯 재사용).

이 스크립트는 wi_tuning.py/macd_hard_gate_tuning.py와 동일 하니스(플래그 오버라이드 +
동일 frames 재실행)로 lookback × vol_mode × min_signal 그리드를 검증한다.

재현:
  .venv/bin/python3 scripts/analysis/tsmom_nl_tuning.py \
      --parquet data/sentiment_join/master_20260710.parquet --limit 6000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio, effective_trial_count  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402


@contextmanager
def _params(**overrides):
    saved = {k: getattr(parameters, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(parameters, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(parameters, k, v)


def _algo_stats(trades: list, algo_id: str) -> dict:
    ts = [t for t in trades if t.algo_id == algo_id]
    n = len(ts)
    if n == 0:
        return {"n": 0, "sum_w_ret": 0.0, "win": 0.0, "rets": []}
    sum_w = sum(t.ret_pct * t.position_weight for t in ts) * 100
    win = sum(1 for t in ts if t.ret_pct > 0) / n * 100
    return {"n": n, "sum_w_ret": sum_w, "win": win, "rets": [t.ret_pct for t in ts]}


def _run(frames, overrides: dict) -> list:
    with _params(**overrides):
        return backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades


def _split_half(trades: list, algo_id: str) -> tuple[dict, dict]:
    ts = sorted((t for t in trades if t.algo_id == algo_id), key=lambda t: t.open_time)
    mid = len(ts) // 2
    return _algo_stats(ts[:mid], algo_id), _algo_stats(ts[mid:], algo_id)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--limit", type=int, default=6000)
    args = ap.parse_args()
    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    await positions.init()
    db = positions.db()
    warmup = max(parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD, 400)
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=args.limit,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )

    all_algos = [
        "regime_trend",
        "fng_contrarian",
        "vix_rsi",
        "macd_momentum",
        "multi_factor",
        "omnibus",
    ]
    base = _run(frames, {"TSMOM_NL_ENABLED": False})
    b = {a: _algo_stats(base, a) for a in all_algos}
    print("\n=== BASELINE (TSMOM_NL_ENABLED=False, 기존 MACD 로직) ===")
    for a, s in b.items():
        print(f"  {a:16} n {s['n']:>3}  win {s['win']:>4.0f}  sum_w_ret {s['sum_w_ret']:>+6.2f}")

    target = "macd_momentum"
    configs: dict[str, dict] = {}
    for lookback in parameters.TSMOM_NL_LOOKBACK_CANDIDATES:
        for vol_mode in ("rv6", "ewma"):
            for min_signal in (0.0, 0.2, 0.5):
                name = f"L{lookback}_{vol_mode}_min{min_signal}"
                configs[name] = {
                    "TSMOM_NL_ENABLED": True,
                    "TSMOM_NL_LOOKBACK_BARS": lookback,
                    "TSMOM_NL_VOL_MODE": vol_mode,
                    "TSMOM_NL_MIN_SIGNAL": min_signal,
                }

    print(f"\n=== Nonlinear TSMOM 그리드 (target={target}, {len(configs)}개 변형) ===")
    results = {}
    for vname, ov in configs.items():
        trades = _run(frames, ov)
        st = _algo_stats(trades, target)
        results[vname] = st
        d = st["sum_w_ret"] - b[target]["sum_w_ret"]
        flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
        print(
            f"  {flag} {vname:24} n {st['n']:>3}  win {st['win']:>4.0f}  "
            f"sum_w_ret {st['sum_w_ret']:>+6.2f}  Δvs_legacy_macd{d:+.2f}"
        )
        regress = []
        for a in all_algos:
            if a == target:
                continue
            sv = _algo_stats(trades, a)
            if abs(sv["sum_w_ret"] - b[a]["sum_w_ret"]) > 0.01:
                regress.append(f"{a}:{b[a]['sum_w_ret']:+.2f}→{sv['sum_w_ret']:+.2f}")
        if regress:
            print(f"      ⚠️ 타 알고 변화: {regress}")

    usable = {k: v["rets"] for k, v in results.items() if v["n"] >= 5}
    decisions: dict = {"legacy_macd_baseline": round(b[target]["sum_w_ret"], 3)}
    best = None
    if usable:
        best = max(usable, key=lambda k: results[k]["sum_w_ret"])
        n_trials = effective_trial_count(len(usable), algo_id=target)
        dsr = deflated_sharpe_ratio(np.asarray(usable[best]), n_trials)
        print(
            f"\n  best={best}  n={results[best]['n']}  sum_w_ret={results[best]['sum_w_ret']:+.2f} "
            f"DSR sharpe={dsr['sharpe']:.3f} dsr={dsr['dsr']:.3f} n_trials={n_trials} "
            f"(usable variants n≥5: {len(usable)}/{len(configs)})"
        )
        decisions["best"] = best
        decisions["dsr"] = round(dsr["dsr"], 3)
        decisions["n_trials"] = n_trials

        first_half, second_half = _split_half(_run(frames, configs[best]), target)
        print(
            f"  전/후반 분할: 전반 n={first_half['n']} sum_w={first_half['sum_w_ret']:+.2f}  "
            f"후반 n={second_half['n']} sum_w={second_half['sum_w_ret']:+.2f}"
        )
        decisions["split_first_half"] = {
            "n": first_half["n"],
            "sum_w_ret": round(first_half["sum_w_ret"], 3),
        }
        decisions["split_second_half"] = {
            "n": second_half["n"],
            "sum_w_ret": round(second_half["sum_w_ret"], 3),
        }
    else:
        print("\n  ⚠️ n≥5인 변형 없음 — DSR 계산 불가, 표본 부족으로 전부 기각 대상.")

    decisions["results"] = {
        k: {"n": v["n"], "win": round(v["win"], 1), "sum_w_ret": round(v["sum_w_ret"], 3)}
        for k, v in results.items()
    }
    out = Path(__file__).resolve().parents[2] / "docs/arena/research/tsmom-nl-tuning-20260808.json"
    out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    print(f"\n결정 요약 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
