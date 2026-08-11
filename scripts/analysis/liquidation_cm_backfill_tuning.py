"""LIQUIDATION_EXHAUSTION_GATE_ENABLED A/B — cm 청산 아카이브 백필 (D3, 2026-08-11 후속).

배경: docs/arena/research/binance-data-catalog-audit-20260811.md D3 + liquidation-feature-
design-20260810.md. 2026-08-10에 배선한 `_liquidation_exhaustion_sufficient()` 게이트
(fng_contrarian 핵심조건 뒤, omnibus DOWN_TREND/OVERSOLD_REBOUND 레그)는 그때까지 백테스트
데이터가 전혀 없어(청산 히스토리 자체가 UM에 없음) 검증 불가능한 인프라였다. COIN-M(cm)
아카이브(BTC/ETH/SOL, 2023-06-25~2024-10-14)로 처음 검증한다.

⚠️ 이 검증은 "게이트를 켤 근거"가 아니라 "게이트를 끌 근거를 찾는 반증 목적"으로 설계됐다
(D3 §4 한계 3 그대로 계승):
  1. cm(코인마진) ≠ 우리가 라이브로 쓰는 um(USDT마진) — 규모·참여자 다름. 비율 기반
     (liq_asymmetry_24h)이라 절대 임계보다는 덜 취약하지만 완전히 같은 시장은 아니다.
  2. 2024-10-14 이후 데이터가 없어 하락장 창 검증이 불가능 — 이 프로젝트 관행인 상승장/
     하락장 전후반 분할 검증을 상승장 창 내부에서만 할 수 있다(약한 검증).
  3. 그리드 채택 기준: 상승장 창에서조차 baseline보다 뚜렷이 나빠지면 명확한 기각(게이트를
     계속 off로 둘 근거 강화). 반대로 개선되더라도 위 두 한계 때문에 "채택"이 아니라 "추가
     검증 대상으로 격상"까지만 — 하락장 데이터 없이 라이브 활성화는 하지 않는다.

방법: p2_edge_cost_audit.py의 상승장 매크로(FNG+funding) 재구성 + BTC/ETH/SOL 프레임 빌더를
재사용. 각 프레임의 macro에 liq_asymmetry_24h/liq_intensity_zscore_24h를 cm 아카이브 4h
피처로 오버레이(dataclasses.replace, baseline 프레임은 무변형). LIQUIDATION_EXHAUSTION_
MAX_ASYMMETRY 그리드로 fng_contrarian 전체·omnibus DOWN_TREND 레그를 비교.

재현:
  .venv/bin/python3 scripts/analysis/liquidation_cm_backfill_tuning.py
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from liquidation_cm_archive import (  # noqa: E402
    CM_TO_ARENA_SYMBOL,
    build_symbol_bars,
    compute_4h_features,
)
from p2_edge_cost_audit import (  # noqa: E402
    _parse_date,
    _profile_for,
    _settings_for,
    build_bull_macro_rows,
)
from validation_stats import deflated_sharpe_ratio, effective_trial_count  # noqa: E402

from arena import algorithms, backtest, parameters, positions  # noqa: E402

ARENA_TO_CM_SYMBOL = {v: k for k, v in CM_TO_ARENA_SYMBOL.items()}
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
ASYMMETRY_GRID = [0.3, 0.5, 0.7]  # 잠정 placeholder(0.5) 좌우로 실측 분포 감안한 그리드


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


def _bucket_key(close_time) -> "pd.Timestamp":
    """arena_ohlcv_bars.close_time은 4h 경계 -1초로 저장 — 아카이브 bar_close(정각 경계)와
    맞추려면 +1초(lsr_oi_backfill_tuning.py와 동일 규약)."""
    return pd.Timestamp(close_time) + pd.Timedelta(seconds=1)


def overlay_liquidation(frames: list, symbol: str, cache_start, cache_end) -> tuple[list, dict]:
    cm_symbol = ARENA_TO_CM_SYMBOL[symbol]
    bars = build_symbol_bars(cm_symbol, cache_start, cache_end)
    feats = compute_4h_features(bars)
    keys = [_bucket_key(f.bar.close_time) for f in frames]
    asym = feats["liq_asymmetry_24h"].reindex(keys)
    intensity = feats["liq_intensity_zscore_24h"].reindex(keys)

    out = []
    covered = 0
    for f, ts in zip(frames, keys, strict=True):
        overrides = {}
        if ts in asym.index and pd.notna(asym.loc[ts]):
            overrides["liq_asymmetry_24h"] = float(asym.loc[ts])
            covered += 1
        if ts in intensity.index and pd.notna(intensity.loc[ts]):
            overrides["liq_intensity_zscore_24h"] = float(intensity.loc[ts])
        if overrides:
            out.append(dataclasses.replace(f, macro={**f.macro, **overrides}))
        else:
            out.append(f)
    coverage = {"n": len(frames), "covered": covered, "bars_downloaded": len(bars)}
    return out, coverage


def _trade_stats(trades: list) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "sum_w_ret": 0.0, "win": 0.0, "rets": []}
    sum_w = sum(t.ret_pct * t.position_weight for t in trades) * 100
    win = sum(1 for t in trades if t.ret_pct > 0) / n * 100
    return {"n": n, "sum_w_ret": sum_w, "win": win, "rets": [t.ret_pct for t in trades]}


def _fng_trades(trades: list) -> list:
    return [t for t in trades if t.algo_id == "fng_contrarian"]


def _omnibus_down_trend_trades(trades: list) -> list:
    out = []
    for t in trades:
        if t.algo_id != "omnibus":
            continue
        leg = algorithms.omnibus_regime_for(t.macro_snapshot, t.indicator_snapshot)
        if leg == "DOWN_TREND":
            out.append(t)
    return out


def _line(label: str, base: dict, var: dict) -> str:
    d = var["sum_w_ret"] - base["sum_w_ret"]
    flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
    return (
        f"  {flag} {label:24} n {base['n']:>3}→{var['n']:<3} "
        f"win {base['win']:>4.0f}→{var['win']:<4.0f} "
        f"sum_w_ret {base['sum_w_ret']:>+6.2f}→{var['sum_w_ret']:<+6.2f}  Δ{d:+.2f}"
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bull-from", default="2023-08-04")
    ap.add_argument("--bull-to", default="2024-07-31")
    args = ap.parse_args()

    bull_start, bull_end = _parse_date(args.bull_from), _parse_date(args.bull_to)
    print("상승장 FNG+funding macro 재구성 중...")
    bull_macro, coverage = build_bull_macro_rows(start=bull_start, end=bull_end)
    print(f"macro rows: {len(bull_macro)}  coverage={coverage}")

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    cache_start = bull_start.date() - timedelta(days=45)  # 청산 z-score 워밍업 여유
    cache_end = bull_end.date() + timedelta(days=1)

    results: dict = {"method": {"window": "bull_2023_08_2024_07", "asymmetry_grid": ASYMMETRY_GRID}}
    base_fng_all: list = []
    var_fng_all: dict[float, list] = {t: [] for t in ASYMMETRY_GRID}
    base_omni_all: list = []
    var_omni_all: dict[float, list] = {t: [] for t in ASYMMETRY_GRID}

    for symbol in ASSETS:
        profile = _profile_for(symbol)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=profile.interval,
            limit=5000,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            from_date=bull_start,
            to_date=bull_end,
            macro_rows=bull_macro,
        )
        if not frames:
            print(f"{symbol}: 프레임 없음, 스킵")
            continue

        variant_frames, liq_coverage = overlay_liquidation(frames, symbol, cache_start, cache_end)
        print(
            f"{symbol}: frames={len(frames)} liq_coverage="
            f"{liq_coverage['covered']}/{liq_coverage['n']} "
            f"(bars={liq_coverage['bars_downloaded']})"
        )

        settings = _settings_for(symbol)
        base_trades = backtest.run_replay(frames, settings=settings).trades
        base_fng = _fng_trades(base_trades)
        base_omni = _omnibus_down_trend_trades(base_trades)
        base_fng_all.extend(base_fng)
        base_omni_all.extend(base_omni)

        results[symbol] = {"liq_coverage": liq_coverage, "grid": {}}
        for thresh in ASYMMETRY_GRID:
            with _params(
                LIQUIDATION_EXHAUSTION_GATE_ENABLED=True,
                LIQUIDATION_EXHAUSTION_MAX_ASYMMETRY=thresh,
            ):
                var_trades = backtest.run_replay(variant_frames, settings=settings).trades
            var_fng = _fng_trades(var_trades)
            var_omni = _omnibus_down_trend_trades(var_trades)
            var_fng_all[thresh].extend(var_fng)
            var_omni_all[thresh].extend(var_omni)

            b_fng, v_fng = _trade_stats(base_fng), _trade_stats(var_fng)
            b_omni, v_omni = _trade_stats(base_omni), _trade_stats(var_omni)
            print(f"  thresh={thresh}")
            print(_line("fng_contrarian", b_fng, v_fng))
            print(_line("omnibus(DOWN_TREND)", b_omni, v_omni))
            results[symbol]["grid"][str(thresh)] = {
                "fng_contrarian": {
                    "baseline": {k: v for k, v in b_fng.items() if k != "rets"},
                    "variant": {k: v for k, v in v_fng.items() if k != "rets"},
                },
                "omnibus_down_trend": {
                    "baseline": {k: v for k, v in b_omni.items() if k != "rets"},
                    "variant": {k: v for k, v in v_omni.items() if k != "rets"},
                },
            }

    print("\n=== 포트폴리오 합산 (BTC+ETH+SOL) ===")
    results["portfolio"] = {}
    for algo_label, base_all, var_all in (
        ("fng_contrarian", base_fng_all, var_fng_all),
        ("omnibus_down_trend", base_omni_all, var_omni_all),
    ):
        b = _trade_stats(base_all)
        print(
            f"\n{algo_label} baseline: n={b['n']} win={b['win']:.0f}% sum_w_ret={b['sum_w_ret']:+.2f}"
        )
        results["portfolio"][algo_label] = {
            "baseline": {k: v for k, v in b.items() if k != "rets"},
            "grid": {},
        }
        for thresh in ASYMMETRY_GRID:
            v = _trade_stats(var_all[thresh])
            print(_line(f"thresh={thresh}", b, v))
            entry = {"variant": {k: vv for k, vv in v.items() if vv != "rets"}}
            usable = {"baseline": b["rets"], "variant": v["rets"]}
            usable = {k: r for k, r in usable.items() if len(r) >= 5}
            if len(usable) == 2:
                best = "variant" if v["sum_w_ret"] > b["sum_w_ret"] else "baseline"
                n_trials = effective_trial_count(
                    len(ASYMMETRY_GRID), algo_id=f"{algo_label}_liq_gate"
                )
                dsr = deflated_sharpe_ratio(np.asarray(usable[best]), n_trials)
                entry["dsr"] = round(dsr["dsr"], 3)
                entry["best"] = best
                print(f"      best={best} dsr={dsr['dsr']:.3f} n_trials={n_trials}")
            results["portfolio"][algo_label]["grid"][str(thresh)] = entry

    out = (
        Path(__file__).resolve().parents[2]
        / "docs/arena/research/d3-liquidation-cm-backfill-results.json"
    )
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
