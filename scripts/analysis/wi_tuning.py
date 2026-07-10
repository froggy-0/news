"""WI-1/2/4/5/6/7 플래그 A/B·그리드 백테스트 검증 하니스.

동일 프레임(macro 백필)에서 parameters 플래그만 뒤집어 run_replay를 반복 실행 →
대상 알고의 sum_w_ret·승률·거래수 변화를 baseline과 비교한다. 알고별 독립 자본
구조라 한 알고의 플래그 변경은 타 알고에 영향 없음(확인용으로 전 알고 델타도 출력).

플래그는 algorithms/_open_position이 호출 시점에 parameters.X를 읽으므로, 같은 frames에
대해 설정만 바꿔 재실행하면 된다. rel_volume/rsi_prev/bb_mid는 프레임 빌드 시 항상
계산되므로 플래그와 무관하게 재사용 가능.

재현:
  .venv/bin/python3 scripts/analysis/wi_tuning.py \
      --parquet data/sentiment_join/sentiment_join_master_20260502.parquet
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
from validation_stats import (  # noqa: E402
    deflated_sharpe_ratio,
)

from arena import backtest, frequency, parameters, positions  # noqa: E402


@contextmanager
def _params(**overrides):
    """parameters 모듈 속성을 임시 오버라이드(복원 보장)."""
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


def _line(label: str, base: dict, var: dict) -> str:
    d = var["sum_w_ret"] - base["sum_w_ret"]
    flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
    return (
        f"  {flag} {label:32} n {base['n']:>3}→{var['n']:<3} "
        f"win {base['win']:>4.0f}→{var['win']:<4.0f} "
        f"sum_w_ret {base['sum_w_ret']:>+6.2f}→{var['sum_w_ret']:<+6.2f}  Δ{d:+.2f}"
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--parquet", default="data/sentiment_join/sentiment_join_master_20260502.parquet"
    )
    args = ap.parse_args()
    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )

    base = _run(frames, {})
    b = {
        a: _algo_stats(base, a)
        for a in [
            "regime_trend",
            "fng_contrarian",
            "vix_rsi",
            "macd_momentum",
            "multi_factor",
            "omnibus",
        ]
    }
    print("\n=== BASELINE (전 플래그 off) ===")
    for a, s in b.items():
        print(f"  {a:16} n {s['n']:>3}  win {s['win']:>4.0f}  sum_w_ret {s['sum_w_ret']:>+6.2f}")

    decisions: dict[str, dict] = {}

    def grid(name, target, configs: dict[str, dict]):
        """configs: {변형명: overrides}. 대상 알고 기준 비교 + DSR/PBO."""
        print(f"\n=== {name} (target={target}) ===")
        results = {}
        for vname, ov in configs.items():
            trades = _run(frames, ov)
            st = _algo_stats(trades, target)
            results[vname] = st
            print(_line(vname, b[target], st))
            # 타 알고 회귀 확인
            regress = []
            for a in b:
                if a == target:
                    continue
                sv = _algo_stats(trades, a)
                if abs(sv["sum_w_ret"] - b[a]["sum_w_ret"]) > 0.01:
                    regress.append(f"{a}:{b[a]['sum_w_ret']:+.2f}→{sv['sum_w_ret']:+.2f}")
            if regress:
                print(f"      ⚠️ 타 알고 변화: {regress}")
        # DSR/PBO — 변형이 2개 이상이고 각 n≥5일 때
        usable = {k: v["rets"] for k, v in results.items() if v["n"] >= 5}
        best = max(results, key=lambda k: results[k]["sum_w_ret"])
        decisions[name] = {
            "target": target,
            "best": best,
            "results": {
                k: {"n": v["n"], "win": round(v["win"], 1), "sum_w_ret": round(v["sum_w_ret"], 3)}
                for k, v in results.items()
            },
        }
        if len(usable) >= 2 and best in usable:
            dsr = deflated_sharpe_ratio(np.asarray(usable[best]), len(usable))
            # PBO는 동일 길이 시계열 필요 → 트레이드 수 달라 스킵, DSR만.
            print(f"      best={best}  DSR sharpe={dsr['sharpe']:.3f} dsr={dsr['dsr']:.3f}")
            decisions[name]["dsr"] = round(dsr["dsr"], 3)
        return results

    # WI-1 multi_factor
    grid(
        "WI-1 multi_factor 레짐필수",
        "multi_factor",
        {
            "A_baseline(5중4)": {},
            "B_레짐필수+4중3(강세만)": {
                "MULTI_FACTOR_REGIME_REQUIRED": True,
                "MULTI_FACTOR_ALLOW_SIDEWAYS": False,
            },
            "C_레짐필수+4중3(횡보허용)": {
                "MULTI_FACTOR_REGIME_REQUIRED": True,
                "MULTI_FACTOR_ALLOW_SIDEWAYS": True,
            },
        },
    )

    # WI-2 fng exit hysteresis grid
    grid(
        "WI-2 fng 청산 히스테리시스",
        "fng_contrarian",
        {
            "A_baseline": {},
            "B_neutral40": {"FNG_EXIT_HYSTERESIS_ENABLED": True, "FNG_EXIT_NEUTRAL_MIN": 40.0},
            "C_neutral45": {"FNG_EXIT_HYSTERESIS_ENABLED": True, "FNG_EXIT_NEUTRAL_MIN": 45.0},
            "D_neutral50": {"FNG_EXIT_HYSTERESIS_ENABLED": True, "FNG_EXIT_NEUTRAL_MIN": 50.0},
            "E_neutral55": {"FNG_EXIT_HYSTERESIS_ENABLED": True, "FNG_EXIT_NEUTRAL_MIN": 55.0},
        },
    )

    # P-A fng 이익포착(profit target) — MFE 진단 기반
    grid(
        "P-A fng 이익포착",
        "fng_contrarian",
        {
            "A_baseline": {},
            "B_atr1.0": {
                "FNG_TARGET_EXIT_ENABLED": True,
                "FNG_TARGET_MODE": "atr",
                "FNG_TARGET_ATR_MULT": 1.0,
            },
            "C_atr1.5": {
                "FNG_TARGET_EXIT_ENABLED": True,
                "FNG_TARGET_MODE": "atr",
                "FNG_TARGET_ATR_MULT": 1.5,
            },
            "D_atr2.0": {
                "FNG_TARGET_EXIT_ENABLED": True,
                "FNG_TARGET_MODE": "atr",
                "FNG_TARGET_ATR_MULT": 2.0,
            },
            "E_bb_mid": {"FNG_TARGET_EXIT_ENABLED": True, "FNG_TARGET_MODE": "bb_mid"},
        },
    )

    # WI-4 regime_trend volume confirm
    grid(
        "WI-4 regime_trend 볼륨확인",
        "regime_trend",
        {
            "A_baseline": {},
            "B_vol1.2": {"VOLUME_CONFIRM_ENABLED": True, "VOLUME_CONFIRM_MIN_REL": 1.2},
            "C_vol1.5": {"VOLUME_CONFIRM_ENABLED": True, "VOLUME_CONFIRM_MIN_REL": 1.5},
        },
    )

    # WI-5 vix_rsi
    grid(
        "WI-5 vix_rsi 구조",
        "vix_rsi",
        {
            "A_baseline": {},
            "B_ma200게이트": {"VIX_RSI_MA200_GATE_ENABLED": True},
            "C_크로스35": {"VIX_RSI_TRIGGER_MODE": "cross", "VIX_RSI_CROSS_OVERSOLD": 35.0},
            "D_크로스30": {"VIX_RSI_TRIGGER_MODE": "cross", "VIX_RSI_CROSS_OVERSOLD": 30.0},
            "E_ma200+크로스35": {
                "VIX_RSI_MA200_GATE_ENABLED": True,
                "VIX_RSI_TRIGGER_MODE": "cross",
                "VIX_RSI_CROSS_OVERSOLD": 35.0,
            },
        },
    )

    # WI-6 macd zero_cross
    grid(
        "WI-6 macd 0선크로스",
        "macd_momentum",
        {
            "A_baseline": {},
            "B_zero_cross": {
                "MACD_MOMENTUM_TRIGGER_MODE": "zero_cross",
                "MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED": True,
            },
            "C_zero_cross_noBB": {
                "MACD_MOMENTUM_TRIGGER_MODE": "zero_cross",
                "MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED": True,
                "MACD_MOMENTUM_ZERO_CROSS_DROP_BB_GATE": True,
            },
        },
    )

    # WI-7 omnibus target exit
    grid(
        "WI-7 omnibus 목표가익절",
        "omnibus",
        {
            "A_baseline": {},
            "B_atr1.0": {
                "OMNIBUS_TARGET_EXIT_ENABLED": True,
                "OMNIBUS_REBOUND_TARGET_ATR_MULT": 1.0,
            },
            "C_atr1.5": {
                "OMNIBUS_TARGET_EXIT_ENABLED": True,
                "OMNIBUS_REBOUND_TARGET_ATR_MULT": 1.5,
            },
            "D_atr2.0": {
                "OMNIBUS_TARGET_EXIT_ENABLED": True,
                "OMNIBUS_REBOUND_TARGET_ATR_MULT": 2.0,
            },
        },
    )

    out = Path(__file__).resolve().parents[2] / "docs/arena/research/wi-tuning-results.json"
    out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    print(f"\n결정 요약 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
