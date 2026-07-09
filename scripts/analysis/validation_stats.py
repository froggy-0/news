"""WI-8: 백테스트 과적합 보정 통계 — Deflated Sharpe Ratio(DSR) + Probability of
Backtest Overfitting(PBO, CSCV).

파라미터 그리드 탐색(WI-2·5·6·7 등)이 반복될수록 selection bias가 누적된다. plateau
중앙값 채택은 좋은 휴리스틱이지만 정량 보정이 아니다. 이 모듈은 후속 튜닝의 채택 게이트
통계를 제공한다.

- DSR (Bailey·López de Prado 2014): 시도 횟수 N·수익률 skew/kurtosis를 보정한 Sharpe
  유의확률. 여러 config를 시도했을 때 관측 Sharpe가 우연이 아닐 확률.
- PBO (Bailey et al. 2015, CSCV): 데이터를 S개 블록으로 나눠 조합적 in-sample/out-of-sample
  분할 → in-sample 최적 config가 OOS에서 중앙값 이하 순위로 떨어지는 빈도. 높을수록 과적합.

사용:
  from validation_stats import deflated_sharpe_ratio, probability_of_backtest_overfitting
  # 또는 CLI:  .venv/bin/python3 scripts/analysis/validation_stats.py --json grid.json
  # grid.json = {"config_a": [ret1, ret2, ...], "config_b": [...], ...}  (config별 트레이드 수익)

의존성: numpy, scipy (이미 .venv 보유).
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from math import comb
from pathlib import Path

import numpy as np
from scipy.stats import norm


def _sharpe(returns: np.ndarray) -> float:
    if returns.size < 2:
        return 0.0
    sd = returns.std(ddof=1)
    if sd == 0:
        return 0.0
    return returns.mean() / sd


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int,
    *,
    sharpe_benchmark: float = 0.0,
) -> dict[str, float]:
    """관측 Sharpe가 다중검정 하에서 우연이 아닐 확률(DSR).

    returns: 선택된(최적) config의 트레이드/기간 수익률 배열.
    n_trials: 시도한 config 총수(그리드 크기) — selection bias 보정 강도.
    반환: {sharpe, dsr, expected_max_sharpe_noise}.
    """
    returns = np.asarray(returns, dtype=float)
    T = returns.size
    if T < 2:
        return {"sharpe": 0.0, "dsr": 0.0, "expected_max_sharpe_noise": 0.0}
    sr = _sharpe(returns)
    # 고차 모멘트(skew, kurtosis) — 비정규성 보정.
    mean = returns.mean()
    sd = returns.std(ddof=1)
    if sd == 0:
        return {"sharpe": 0.0, "dsr": 0.0, "expected_max_sharpe_noise": 0.0}
    skew = float(((returns - mean) ** 3).mean() / sd**3)
    kurt = float(((returns - mean) ** 4).mean() / sd**4)  # non-excess

    # 순수 잡음에서 N회 시도 시 기대되는 최대 Sharpe (López de Prado 근사).
    n = max(n_trials, 1)
    euler_mascheroni = 0.5772156649
    e = np.e
    if n > 1:
        z1 = norm.ppf(1.0 - 1.0 / n)
        z2 = norm.ppf(1.0 - 1.0 / (n * e))
        expected_max = z1 * (1.0 - euler_mascheroni) + z2 * euler_mascheroni
    else:
        expected_max = 0.0
    # SR 추정치의 표준편차 (비정규성 반영).
    sr_std = np.sqrt((1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2) / (T - 1.0))
    if sr_std <= 0:
        dsr = 0.0
    else:
        dsr = float(norm.cdf((sr - (sharpe_benchmark + expected_max * sr_std)) / sr_std))
    return {
        "sharpe": float(sr),
        "dsr": dsr,
        "expected_max_sharpe_noise": float(expected_max * sr_std),
        "skew": skew,
        "kurtosis": kurt,
    }


def probability_of_backtest_overfitting(
    config_returns: dict[str, list[float]],
    *,
    n_splits: int = 16,
) -> dict[str, float]:
    """CSCV 기반 PBO — in-sample 최적 config의 OOS 상대순위 열화 빈도.

    config_returns: {config명: 시계열 수익률}. 모든 config는 동일 길이여야 함(같은 bar들).
    n_splits(S): 짝수. 시계열을 S개 블록으로 나눠 C(S, S/2) 조합의 IS/OOS 분할을 만든다.
    반환: {pbo, n_combinations, n_configs}. pbo가 낮을수록 견고(≤0.2 권장).
    """
    names = list(config_returns.keys())
    if len(names) < 2:
        return {"pbo": 0.0, "n_combinations": 0, "n_configs": len(names)}
    mat = np.array([config_returns[n] for n in names], dtype=float)  # (n_configs, T)
    T = mat.shape[1]
    S = n_splits if n_splits % 2 == 0 else n_splits - 1
    S = max(2, min(S, T))
    # 인접 블록 인덱스 분할.
    block_bounds = np.array_split(np.arange(T), S)
    blocks = [b for b in block_bounds if b.size > 0]
    S = len(blocks)
    if S < 2:
        return {"pbo": 0.0, "n_combinations": 0, "n_configs": len(names)}
    half = S // 2
    logits: list[float] = []
    for is_idx in combinations(range(S), half):
        is_set = set(is_idx)
        is_bars = np.concatenate([blocks[i] for i in is_idx])
        oos_bars = np.concatenate([blocks[i] for i in range(S) if i not in is_set])
        is_sr = np.array([_sharpe(mat[c, is_bars]) for c in range(len(names))])
        oos_sr = np.array([_sharpe(mat[c, oos_bars]) for c in range(len(names))])
        best_is = int(np.argmax(is_sr))
        # OOS에서 best_is config의 순위(0=최악 … 1=최고)를 상대 순위로.
        oos_rank = float((oos_sr < oos_sr[best_is]).sum()) / max(len(names) - 1, 1)
        w = min(max(oos_rank, 1e-6), 1 - 1e-6)
        logits.append(np.log(w / (1.0 - w)))
    logits_arr = np.array(logits)
    pbo = float((logits_arr <= 0).mean()) if logits_arr.size else 0.0
    return {
        "pbo": pbo,
        "n_combinations": int(comb(S, half)),
        "n_configs": len(names),
        "n_splits_effective": S,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="{config명: [수익률,...]} JSON 파일")
    ap.add_argument("--splits", type=int, default=16)
    args = ap.parse_args()
    data = json.loads(Path(args.json).read_text())
    n_trials = len(data)
    # 최적 config = 총수익 기준.
    best = max(data, key=lambda k: sum(data[k]))
    dsr = deflated_sharpe_ratio(np.asarray(data[best], dtype=float), n_trials)
    pbo = probability_of_backtest_overfitting(data, n_splits=args.splits)
    print(f"configs={n_trials}  best={best}")
    print(
        f"DSR(best): sharpe={dsr['sharpe']:.3f}  dsr={dsr['dsr']:.3f}  "
        f"(≥0.95 권장)  skew={dsr.get('skew', 0):.2f}  kurt={dsr.get('kurtosis', 0):.2f}"
    )
    print(
        f"PBO: {pbo['pbo']:.3f}  (≤0.2 권장)  "
        f"combos={pbo['n_combinations']}  splits={pbo.get('n_splits_effective')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
