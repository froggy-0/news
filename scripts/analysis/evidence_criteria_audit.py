"""결정유형별 증거기준을 아레나 실제 결과에 적용한 감사 (2026-08-16).

`evidence_criteria.py`의 도구들을 지금까지 "DSR≥0.95 미달로 기각"된 실제 사례에
적용해, 각 기각이 (a) 엣지 부재인지 (b) 검정력 부재인지 분해한다.

대상:
  1. 롱 베이스라인 6알고(BTC, macro 백필 창) — P4 감사가 fng/vix_rsi도 미달이라 판정한 그 표본.
  2. `vix_rsi` 숏 ETH veto유지 — Phase B §12의 근접미달(DSR 0.934).
  3. `multi_factor` 숏 3자산 풀링 — §18의 97% 시간중복 사례(유효표본 보정 대상).

재현:
  .venv/bin/python3 scripts/analysis/evidence_criteria_audit.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from evidence_criteria import (  # noqa: E402
    bayesian_edge_probability,
    benjamini_hochberg_yekutieli,
    bootstrap_ci,
    evalue_process,
    evalue_trades_needed,
    inferiority_test,
    min_track_record_length,
    minimum_detectable_sharpe,
    probabilistic_sharpe_ratio,
    psr_with_effective_n,
    sharpe_pvalue,
)
from multi_factor_short_backtest import VARIANTS_A, _run_symbol  # noqa: E402
from validation_stats import deflated_sharpe_ratio, effective_trial_count  # noqa: E402
from vix_rsi_short_backtest import VARIANTS_VETO_KEPT  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGOS = [
    "regime_trend",
    "fng_contrarian",
    "vix_rsi",
    "macd_momentum",
    "multi_factor",
    "omnibus",
]


def _weighted_returns(trades: list, algo_id: str) -> np.ndarray:
    return np.asarray(
        [t.ret_pct * t.position_weight for t in trades if t.algo_id == algo_id],
        dtype=float,
    )


def _report(name: str, returns: np.ndarray, *, n_trials: int = 1) -> dict:
    """한 표본에 대해 모든 기준을 나란히 계산."""
    n = returns.size
    if n < 3:
        print(f"\n### {name}: 표본 부족(n={n})")
        return {"name": name, "n": n}

    dsr = deflated_sharpe_ratio(returns, n_trials)
    psr = probabilistic_sharpe_ratio(returns)
    trl = min_track_record_length(returns)
    mde = minimum_detectable_sharpe(n)
    point, lo, hi = bootstrap_ci(returns)
    ev = evalue_process(returns)
    inf = inferiority_test(returns)
    bayes_flat = bayesian_edge_probability(returns, prior_mean_sr=0.0, prior_strength=0)

    print(f"\n### {name}  (n={n})")
    print(f"  거래당 SR={psr['sharpe']:+.4f}   가중수익합={returns.sum() * 100:+.2f}%")
    print(
        f"  [기존] DSR(n_trials={n_trials})={dsr['dsr']:.3f}   판정={'통과' if dsr['dsr'] >= 0.95 else '미달'}"
    )
    print(f"  [B] PSR(사전등록 단일가설)={psr['psr']:.3f}")
    if trl["feasible"]:
        print(
            f"  [B] MinTRL={trl['min_trl']:.0f}건 vs 보유 {n}건 "
            f"→ {trl['shortfall_ratio']:.1f}배 필요  충분={trl['sufficient']}"
        )
        verdict = "판정가능" if trl["sufficient"] else "검정력부재(판정불가)"
    else:
        print(f"  [B] MinTRL=불가능 — {trl.get('reason', '')}")
        verdict = "방향자체가 음수"
    print(f"  [B] 이 n에서 검출가능 최소SR={mde:.3f} (관측 {psr['sharpe']:+.3f})")
    print(f"  [진단] → {verdict}")
    print(f"  [C] e-value={ev['evalue']:.3f} (기각선 20) reject={ev['reject']}")
    print(f"  [F] 철회검정(margin SR=-0.10): should_retire={inf['should_retire']}")
    print(f"  [B'] 베이지안 P(SR>0|무정보사전)={bayes_flat['prob_positive']:.3f}")
    print(f"  부트스트랩 평균 95%CI: [{lo * 100:+.3f}%, {hi * 100:+.3f}%]")

    return {
        "name": name,
        "n": n,
        "sharpe": psr["sharpe"],
        "sum_pct": float(returns.sum() * 100),
        "dsr": dsr["dsr"],
        "psr": psr["psr"],
        "min_trl": trl["min_trl"],
        "trl_feasible": trl["feasible"],
        "shortfall_ratio": trl.get("shortfall_ratio"),
        "power_sufficient": trl.get("sufficient", False),
        "mde_sharpe": mde,
        "evalue": ev["evalue"],
        "should_retire": inf["should_retire"],
        "prob_positive": bayes_flat["prob_positive"],
        "pvalue": sharpe_pvalue(returns),
        "verdict": verdict,
    }


async def main() -> int:
    parquet = Path("data/sentiment_join/master_20260710.parquet")
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows[-1]["reference_date"], tz=timezone.utc).to_pydatetime()
    await positions.init()
    db = positions.db()

    results: list[dict] = []

    # ------------------------------------------------------------------
    print("=" * 74)
    print("1. 롱 베이스라인 6알고 (BTC) — P4 감사가 '전부 미달'로 판정한 그 표본")
    print("=" * 74)
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=profile.interval,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_dt,
        to_date=to_dt,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
    )
    long_result = backtest.run_replay(frames)
    long_reports = []
    for algo_id in ALGOS:
        rets = _weighted_returns(long_result.trades, algo_id)
        if rets.size < 3:
            continue
        n_trials = effective_trial_count(1, algo_id=algo_id)
        rep = _report(f"[롱] {algo_id} (BTC)", rets, n_trials=n_trials)
        rep["algo_id"] = algo_id
        long_reports.append(rep)
        results.append(rep)

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("2. vix_rsi 숏 ETH veto유지 — Phase B §12 근접미달(DSR 0.934)")
    print("=" * 74)
    eth_frames = await _run_symbol(db, "ETHUSDT", macro_rows, from_dt, to_dt)
    settings_perp = backtest.BacktestSettings(product_type="usdm_perp")
    short_res = backtest.run_replay(
        eth_frames, strategy_fns=VARIANTS_VETO_KEPT, settings=settings_perp
    )
    short_rets = _weighted_returns(short_res.trades, "vix_rsi")
    results.append(_report("[숏] vix_rsi ETH veto유지", short_rets, n_trials=2))

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("3. multi_factor 숏 3자산 풀링 — §18의 97% 시간중복(유효표본 보정)")
    print("=" * 74)
    pooled_rets: list[float] = []
    pooled_open: list = []
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        f = await _run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        r = backtest.run_replay(f, strategy_fns=VARIANTS_A, settings=settings_perp)
        for t in r.trades:
            if t.algo_id == "multi_factor":
                pooled_rets.append(t.ret_pct * t.position_weight)
                pooled_open.append(t.open_time)
    pooled = np.asarray(pooled_rets, dtype=float)
    rep_pooled = _report("[숏] multi_factor 3자산 풀링(순진)", pooled, n_trials=2)
    results.append(rep_pooled)

    # 시간 근접(같은 주 = 같은 매크로 국면)으로 클러스터 라벨링.
    if pooled.size:
        times = pd.to_datetime(pd.Series(pooled_open), utc=True)
        cluster = times.dt.floor("7D").astype("int64").tolist()
        ess = psr_with_effective_n(pooled, cluster)
        print("\n  --- 유효표본 보정(결정유형 E) ---")
        print(f"  클러스터 수={ess['n_clusters']}  평균크기={ess['mean_cluster_size']:.2f}")
        print(f"  ICC={ess['icc']:.3f}  DEFF={ess['deff']:.2f}")
        print(f"  n={ess['n']} → n_eff={ess['n_eff']:.1f}")
        print(f"  PSR: 순진={ess['psr_naive']:.3f} → 유효표본보정={ess['psr_effective']:.3f}")
        trl_eff = min_track_record_length(pooled)
        if trl_eff["feasible"]:
            print(
                f"  유효표본 기준 필요 거래수 ≈ {trl_eff['min_trl'] * ess['deff']:.0f}건 "
                f"(DEFF {ess['deff']:.2f}배 가중)"
            )
        rep_pooled["n_eff"] = ess["n_eff"]
        rep_pooled["deff"] = ess["deff"]
        rep_pooled["icc"] = ess["icc"]
        rep_pooled["psr_effective"] = ess["psr_effective"]

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("4. 결정유형 D: 후보군 전체에 FDR(BHY) 적용 — 개별 DSR 대신")
    print("=" * 74)
    usable = [r for r in results if r.get("n", 0) >= 3]
    pvals = [r["pvalue"] for r in usable]
    for q in (0.10, 0.20):
        bhy = benjamini_hochberg_yekutieli(pvals, q=q)
        names = [usable[i]["name"] for i, ok in enumerate(bhy["rejected"]) if ok]
        print(f"  q={q:.2f} → 발견 {bhy['n_rejected']}건 {names if names else ''}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("5. 결정유형 C: 라이브 순차검정으로 결론까지 필요한 거래수")
    print("=" * 74)
    for r in usable:
        rets = None
        if r["name"].startswith("[숏] vix_rsi"):
            rets = short_rets
        elif r["name"].startswith("[숏] multi_factor"):
            rets = pooled
        if rets is None:
            continue
        need = evalue_trades_needed(rets)
        if need.get("reachable"):
            print(
                f"  {r['name']}: 현재 e={need['current_evalue']:.2f}, "
                f"총 {need['trades_needed_total']:.0f}건 필요 "
                f"(남은 {need['trades_remaining']:.0f}건)"
            )
        else:
            print(f"  {r['name']}: 도달불가 — {need.get('reason')}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("요약표 — 기각 사유 분해")
    print("=" * 74)
    print(
        f"{'대상':38s} {'n':>4s} {'SR':>7s} {'DSR':>6s} {'PSR':>6s} "
        f"{'MinTRL':>8s} {'배수':>6s} {'진단':>16s}"
    )
    for r in usable:
        trl = r.get("min_trl", float("inf"))
        trl_s = f"{trl:.0f}" if np.isfinite(trl) else "불가"
        ratio = r.get("shortfall_ratio")
        ratio_s = f"{ratio:.1f}x" if ratio and np.isfinite(ratio) else "-"
        print(
            f"{r['name']:38s} {r['n']:>4d} {r['sharpe']:>+7.3f} {r['dsr']:>6.3f} "
            f"{r['psr']:>6.3f} {trl_s:>8s} {ratio_s:>6s} {r['verdict']:>16s}"
        )

    out = Path("docs/arena/research/evidence-criteria-audit-20260816.json")
    out.write_text(
        json.dumps(
            {"as_of": "2026-08-16", "results": [{k: v for k, v in r.items()} for r in usable]},
            ensure_ascii=False,
            indent=2,
            default=float,
        )
        + "\n"
    )
    print(f"\n원시 결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
