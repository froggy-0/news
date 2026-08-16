"""Phase B 숏 후보 전체 재감사 — DSR 단일기준 대신 결정유형별 프레임워크 적용 (2026-08-16).

배경: 2026-08-15 Phase B 1순환은 6개 알고 x 3자산 x 2변형(=36셀) 전부를
`DSR(n_trials=2) >= 0.95` 하나로 기각했다. 그런데 같은 날(2026-08-16) 저녁
`evidence-criteria-framework-20260816.md`가 DSR은 "그리드 탐색 승자"에 맞는
기준이고, Phase B처럼 사전등록 단일사양(그리드 아님, n_trials<=2)엔 PSR+MinTRL이
맞는 기준이라는 걸 확립했다 — 그 재적용을 vix_rsi(ETH)/multi_factor(풀링) 두
셀에만 하고 나머지 34셀은 방치했다. 이 스크립트는 그 34셀 전부에 동일한
재분류를 적용해 "진짜 SR 음수라 기각"과 "검정력 부족이라 판정불가"를 가른다.

그리드 탐색이 아니다 — 각 셀은 Phase B 설계 문서(§8~13)가 이미 확정한 사전
사양 그대로 재실행만 한다. 코드·파라미터 변경 없음, 순수 재분석.

재현:
  .venv/bin/python3 scripts/analysis/phase_b_full_evidence_reaudit.py
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fng_contrarian_short_backtest as fng_mod  # noqa: E402
import macd_momentum_short_backtest as macd_mod  # noqa: E402
import multi_factor_short_backtest as mf_mod  # noqa: E402
import omnibus_short_backtest as omni_mod  # noqa: E402
import regime_trend_short_backtest as rt_mod  # noqa: E402
import vix_rsi_short_backtest as vix_mod  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from evidence_criteria import (  # noqa: E402
    min_track_record_length,
    minimum_detectable_sharpe,
    probabilistic_sharpe_ratio,
)
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _weighted_returns(trades: list, algo_id: str) -> np.ndarray:
    return np.asarray(
        [t.ret_pct * t.position_weight for t in trades if t.algo_id == algo_id],
        dtype=float,
    )


def _score(cell: str, algo_id: str, returns: np.ndarray, *, n_trials: int) -> dict:
    n = returns.size
    if n < 3:
        return {"cell": cell, "n": n, "verdict": "표본부족(n<3)"}

    dsr = deflated_sharpe_ratio(returns, n_trials)
    psr = probabilistic_sharpe_ratio(returns)
    trl = min_track_record_length(returns)
    mde = minimum_detectable_sharpe(n)

    if psr["sharpe"] <= 0:
        verdict = "SR음수(방향자체가 나쁨)"
    elif not trl["feasible"]:
        verdict = "SR양수·MinTRL계산불가"
    elif trl["sufficient"]:
        verdict = "검정력충분·판정가능"
    else:
        verdict = "검정력부족(판정불가)"

    return {
        "cell": cell,
        "algo_id": algo_id,
        "n": n,
        "sum_pct": float(returns.sum() * 100),
        "sharpe": psr["sharpe"],
        "dsr": dsr["dsr"],
        "psr": psr["psr"],
        "min_trl": trl.get("min_trl"),
        "shortfall_ratio": trl.get("shortfall_ratio"),
        "mde_sharpe": mde,
        "verdict": verdict,
    }


async def _macd(db, macro_rows, from_dt, to_dt) -> list[dict]:
    out = []
    # 원본 스크립트가 main() 안에서만 적용하던 몽키패치(음수 신호 사이징 클립 해제)를
    # 여기서도 적용하지 않으면 position_weight가 0으로 클립돼 전 거래가 가중수익 0으로
    # 나온다 — 실제로 이 재감사 1차 실행에서 그 버그로 macd_momentum 6셀 전부 SR=0.000이
    # 나왔던 것을 발견해 수정.
    assert hasattr(algorithms, "tsmom_nl_position_multiplier")
    algorithms.tsmom_nl_position_multiplier = macd_mod._tsmom_nl_position_multiplier_abs
    for symbol in ASSETS:
        frames = await macd_mod._run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        settings = backtest.BacktestSettings(product_type="usdm_perp")
        for label, fns in (("veto유지", macd_mod.VARIANTS), ("veto제거", macd_mod.VARIANTS_NOVETO)):
            result = backtest.run_replay(frames, strategy_fns=fns, settings=settings)
            rets = _weighted_returns(result.trades, "macd_momentum")
            out.append(_score(f"macd_momentum/{symbol}/{label}", "macd_momentum", rets, n_trials=2))
    return out


async def _regime_trend(db, macro_rows, from_dt, to_dt) -> list[dict]:
    out = []
    for symbol in ASSETS:
        frames = await rt_mod._run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        settings = backtest.BacktestSettings(product_type="usdm_perp")
        for label, fns in (
            ("strict_8of8", rt_mod.VARIANTS_STRICT),
            ("relaxed_4of8", rt_mod.VARIANTS_RELAXED),
        ):
            result = backtest.run_replay(frames, strategy_fns=fns, settings=settings)
            rets = _weighted_returns(result.trades, "regime_trend")
            out.append(_score(f"regime_trend/{symbol}/{label}", "regime_trend", rets, n_trials=2))
    return out


async def _multi_factor(db, macro_rows, from_dt, to_dt) -> list[dict]:
    out = []
    for symbol in ASSETS:
        frames = await mf_mod._run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        settings = backtest.BacktestSettings(product_type="usdm_perp")
        for label, fns in (
            ("direction_soft", mf_mod.VARIANTS_A),
            ("direction_hard_reint", mf_mod.VARIANTS_B),
        ):
            result = backtest.run_replay(frames, strategy_fns=fns, settings=settings)
            rets = _weighted_returns(result.trades, "multi_factor")
            out.append(_score(f"multi_factor/{symbol}/{label}", "multi_factor", rets, n_trials=2))
    return out


async def _vix_rsi(db, macro_rows, from_dt, to_dt) -> list[dict]:
    out = []
    for symbol in ASSETS:
        frames = await vix_mod._run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        settings = backtest.BacktestSettings(product_type="usdm_perp")
        for label, fns in (
            ("veto유지", vix_mod.VARIANTS_VETO_KEPT),
            ("veto제거", vix_mod.VARIANTS_VETO_REMOVED),
        ):
            result = backtest.run_replay(frames, strategy_fns=fns, settings=settings)
            rets = _weighted_returns(result.trades, "vix_rsi")
            out.append(_score(f"vix_rsi/{symbol}/{label}", "vix_rsi", rets, n_trials=2))
    return out


async def _fng_contrarian(db, macro_rows, from_dt, to_dt) -> list[dict]:
    out = []
    # §13 발견 결함(backtest.py의 target/scale-in이 direction 미분기) 회피용 몽키패치 재사용.
    parameters.FNG_TARGET_EXIT_ENABLED = False
    parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED = False
    for symbol in ASSETS:
        frames = await fng_mod._run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        settings = backtest.BacktestSettings(product_type="usdm_perp")
        for label, fns in (
            ("veto유지", fng_mod.VARIANTS_VETO_KEPT),
            ("veto제거", fng_mod.VARIANTS_VETO_REMOVED),
        ):
            result = backtest.run_replay(frames, strategy_fns=fns, settings=settings)
            rets = _weighted_returns(result.trades, "fng_contrarian")
            out.append(
                _score(f"fng_contrarian/{symbol}/{label}", "fng_contrarian", rets, n_trials=2)
            )
    return out


async def _omnibus(macro_rows, from_date, to_date) -> list[dict]:
    out = []
    fetch_start = from_date - timedelta(hours=4 * (omni_mod.INDICATOR_WARMUP_BARS + 5))
    settings = backtest.BacktestSettings(
        product_type="usdm_perp",
        position_semantics="usdm_perp_long_short",
        warmup_bars=omni_mod.INDICATOR_WARMUP_BARS,
    )
    for symbol in ASSETS:
        rows = await omni_mod._fetch_bar_rows(symbol, fetch_start, to_date)
        profile_id = (
            frequency.LIVE_4H_PROFILE_ID
            if symbol == parameters.BINANCE_SYMBOL
            else frequency.multi_asset_shadow_profile_id(symbol)
        )
        profile = frequency.get_frequency_profile(profile_id)
        frames = backtest.build_frames_from_bar_rows(
            rows,
            interval="4h",
            warmup_bars=omni_mod.INDICATOR_WARMUP_BARS,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
            from_date=from_date,
            to_date=to_date,
        )
        for label, fn in omni_mod.VARIANTS.items():
            result = backtest.run_replay(frames, strategy_fns={"omnibus": fn}, settings=settings)
            rets = _weighted_returns(result.trades, "omnibus")
            out.append(_score(f"omnibus/{symbol}/{label}", "omnibus", rets, n_trials=2))
    return out


async def main() -> int:
    parquet = Path("data/sentiment_join/master_20260710.parquet")
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows[-1]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt_omni = to_dt + timedelta(days=2)

    await positions.init()
    db = positions.db()

    all_results: list[dict] = []
    print("macd_momentum ...")
    all_results += await _macd(db, macro_rows, from_dt, to_dt)
    print("regime_trend ...")
    all_results += await _regime_trend(db, macro_rows, from_dt, to_dt)
    print("multi_factor ...")
    all_results += await _multi_factor(db, macro_rows, from_dt, to_dt)
    print("vix_rsi ...")
    all_results += await _vix_rsi(db, macro_rows, from_dt, to_dt)
    print("fng_contrarian ...")
    all_results += await _fng_contrarian(db, macro_rows, from_dt, to_dt)
    print("omnibus ...")
    all_results += await _omnibus(macro_rows, from_dt, to_dt_omni)

    print("\n" + "=" * 100)
    print(
        f"{'cell':42s} {'n':>4s} {'SR':>7s} {'sum%':>8s} {'DSR':>6s} {'PSR':>6s} "
        f"{'MinTRL':>8s} {'배수':>6s} {'진단':>24s}"
    )
    print("=" * 100)
    for r in all_results:
        if r.get("n", 0) < 3:
            print(f"{r['cell']:42s} {'':>4s} 표본부족")
            continue
        trl = r.get("min_trl")
        trl_s = f"{trl:.0f}" if trl and math.isfinite(trl) else "불가"
        ratio = r.get("shortfall_ratio")
        ratio_s = f"{ratio:.1f}x" if ratio and math.isfinite(ratio) else "-"
        print(
            f"{r['cell']:42s} {r['n']:>4d} {r['sharpe']:>+7.3f} {r['sum_pct']:>+7.2f}% "
            f"{r['dsr']:>6.3f} {r['psr']:>6.3f} {trl_s:>8s} {ratio_s:>6s} {r['verdict']:>24s}"
        )

    # 알고별 진단 분포 요약
    print("\n" + "=" * 100)
    print("알고별 요약 (셀 6개 중 진단 분포)")
    print("=" * 100)
    by_algo: dict[str, list[dict]] = {}
    for r in all_results:
        if r.get("n", 0) < 3:
            continue
        by_algo.setdefault(r["algo_id"], []).append(r)
    for algo_id, cells in by_algo.items():
        verdicts = [c["verdict"] for c in cells]
        n_neg = sum(1 for v in verdicts if v == "SR음수(방향자체가 나쁨)")
        n_underpowered = sum(1 for v in verdicts if v == "검정력부족(판정불가)")
        n_pass = sum(1 for v in verdicts if v == "검정력충분·판정가능")
        best = max(cells, key=lambda c: c["sharpe"])
        print(
            f"  {algo_id:16s} SR음수={n_neg} 판정불가(검정력부족)={n_underpowered} "
            f"판정가능={n_pass}  |  최선셀: {best['cell']} SR={best['sharpe']:+.3f} "
            f"n={best['n']} 배수={best.get('shortfall_ratio', float('nan')):.1f}x"
            if best.get("shortfall_ratio")
            and math.isfinite(best.get("shortfall_ratio", float("nan")))
            else f"  {algo_id:16s} SR음수={n_neg} 판정불가(검정력부족)={n_underpowered} "
            f"판정가능={n_pass}  |  최선셀: {best['cell']} SR={best['sharpe']:+.3f} n={best['n']}"
        )

    out_path = Path("docs/arena/research/phase-b-full-evidence-reaudit-20260816.json")
    out_path.write_text(
        json.dumps(
            {"as_of": "2026-08-16", "results": all_results},
            ensure_ascii=False,
            indent=2,
            default=float,
        )
        + "\n"
    )
    print(f"\n원시 결과 저장: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
