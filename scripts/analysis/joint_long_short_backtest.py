"""동적 롱/숏 결합 백테스트 — Phase B "지적 2" 해소 (2026-08-16).

배경: Phase B(및 phase_b_full_evidence_reaudit.py)는 알고 함수를 통째로
숏전용으로 교체해 "숏만 썼다면 어땠을까"를 격리 테스트했다 — 이건 실제 라이브
배선(`short_signals.resolve()`가 매 사이클 롱함수·숏함수를 둘 다 평가해 동적으로
합성)과 다르다는 지적(사용자, 2026-08-16)에 답한다.

**단순화 근거(검증됨, 그리드 아님)**: `short_signals.resolve()`의 충돌 처리
(`current_direction` 필요)는 같은 봉에서 롱신호와 숏신호가 동시에 True일 때만
쓰인다. 이번에 라이브 배선한 3개 알고는 전부 롱·숏 핵심조건이 **구조적으로
상호배타**라 이 세션에서 코드로 확인했다:
  - macd_momentum: TSMOM_NL 신호 s에 대해 롱은 s>MIN_SIGNAL(0.0), 숏은
    s<-MIN_SIGNAL(0.0) — 동시 참 불가능.
  - fng_contrarian: 롱은 FNG<30, 숏은 FNG>70 — 동시 참 불가능.
  - vix_rsi: 롱은 vix_now<임계, 숏은 vix_now>=같은 임계(상보) — 동시 참 불가능.
따라서 `resolved = long_signal or short_signal`로 충분하고(resolve()의 비충돌
분기와 동일), current_direction 없이도 백테스트 하니스(run_replay의
strategy_fns가 macro/indicators만 받고 포지션 상태를 안 줌)로 정확히 재현
가능하다.

3가지 변형을 비교한다: long_only(기존 롱함수만, perp 비용), short_only(Phase B
격리 숏 후보, 참고용 재현), combined(위 결합 wrapper — **실제 라이브과 동일한
동적 선택**). combined이 이 세션의 핵심 관심사다.

재현:
  .venv/bin/python3 scripts/analysis/joint_long_short_backtest.py
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fng_contrarian_short_backtest as fng_mod  # noqa: E402
import macd_momentum_short_backtest as macd_mod  # noqa: E402
import vix_rsi_short_backtest as vix_mod  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from evidence_criteria import (  # noqa: E402
    min_track_record_length,
    probabilistic_sharpe_ratio,
)
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import algorithms, backtest, positions  # noqa: E402


def _combined(long_fn, short_fn):
    """long_signal or short_signal — 두 조건이 구조적으로 상호배타라
    short_signals.resolve()의 비충돌 분기와 동치(위 docstring 검증 근거)."""

    def fn(macro: dict, ind: dict) -> str | None:
        long_sig = long_fn(macro, ind)
        if long_sig is not None:
            return long_sig
        return short_fn(macro, ind)

    return fn


# (algo_id, symbol, long_fn, short_fn, short_run_symbol_loader) — v41로 라이브
# 승격한 4개 조합 + 이미 확정승격된 vix_rsi/ETH(대조군).
COMBOS = [
    (
        "macd_momentum",
        "BTCUSDT",
        algorithms.macd_momentum,
        algorithms.macd_momentum_short,
        macd_mod,
    ),
    (
        "macd_momentum",
        "ETHUSDT",
        algorithms.macd_momentum,
        algorithms.macd_momentum_short,
        macd_mod,
    ),
    (
        "macd_momentum",
        "SOLUSDT",
        algorithms.macd_momentum,
        algorithms.macd_momentum_short,
        macd_mod,
    ),
    (
        "fng_contrarian",
        "SOLUSDT",
        algorithms.fng_contrarian,
        algorithms.fng_contrarian_short,
        fng_mod,
    ),
    ("vix_rsi", "SOLUSDT", algorithms.vix_rsi, algorithms.vix_rsi_short, vix_mod),
    ("vix_rsi", "ETHUSDT", algorithms.vix_rsi, algorithms.vix_rsi_short, vix_mod),
]


def _weighted_returns(trades: list, algo_id: str) -> np.ndarray:
    return np.asarray(
        [t.ret_pct * t.position_weight for t in trades if t.algo_id == algo_id],
        dtype=float,
    )


def _score(returns: np.ndarray) -> dict:
    n = returns.size
    if n < 3:
        return {"n": n, "sum_pct": float(returns.sum() * 100) if n else 0.0}
    psr = probabilistic_sharpe_ratio(returns)
    trl = min_track_record_length(returns)
    dsr = deflated_sharpe_ratio(returns, n_trials=1)
    return {
        "n": n,
        "sum_pct": float(returns.sum() * 100),
        "sharpe": psr["sharpe"],
        "psr": psr["psr"],
        "dsr": dsr["dsr"],
        "min_trl": trl.get("min_trl"),
        "shortfall_ratio": trl.get("shortfall_ratio"),
        "sufficient": trl.get("sufficient", False),
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

    settings = backtest.BacktestSettings(product_type="usdm_perp")
    results: list[dict] = []

    for algo_id, symbol, long_fn, short_fn, loader_mod in COMBOS:
        frames = await loader_mod._run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        variants = {
            "long_only": {algo_id: long_fn},
            "short_only": {algo_id: short_fn},
            "combined": {algo_id: _combined(long_fn, short_fn)},
        }
        row = {"algo_id": algo_id, "symbol": symbol}
        for label, fns in variants.items():
            result = backtest.run_replay(frames, strategy_fns=fns, settings=settings)
            rets = _weighted_returns(result.trades, algo_id)
            row[label] = _score(rets)
        results.append(row)
        print(f"\n=== {algo_id}/{symbol} ===")
        for label in ("long_only", "short_only", "combined"):
            s = row[label]
            trl = s.get("min_trl")
            trl_s = f"{trl:.0f}" if trl and math.isfinite(trl) else "-"
            ratio = s.get("shortfall_ratio")
            ratio_s = f"{ratio:.1f}x" if ratio and math.isfinite(ratio) else "-"
            print(
                f"  {label:10s} n={s.get('n', 0):4d} sum%={s.get('sum_pct', 0.0):+7.2f} "
                f"sharpe={s.get('sharpe', float('nan')):+.3f} psr={s.get('psr', float('nan')):.3f} "
                f"DSR={s.get('dsr', float('nan')):.3f} minTRL={trl_s} 배수={ratio_s} "
                f"충분={s.get('sufficient', False)}"
            )

    out = Path("docs/arena/research/joint-long-short-backtest-20260816.json")
    out.write_text(
        json.dumps(
            {"as_of": "2026-08-16", "results": results}, ensure_ascii=False, indent=2, default=float
        )
        + "\n"
    )
    print(f"\n원시 결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
