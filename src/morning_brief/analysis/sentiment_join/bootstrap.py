"""Block bootstrap utilities for overlapping-sample alpha validation.

T+k forward returns share k-1 days of underlying data with adjacent observations,
violating the i.i.d. assumption. Block bootstrap (Politis & Romano 1992 — circular
block; Politis & White 2004 — block-length tuning) preserves local autocorrelation
inside each resampled block, so CI / p-values reflect the true sampling variance.

Default block length is `2 * horizon_days` (rule of thumb for k-day overlap).

Public API:
- BootstrapConfig    : dataclass — bootstrap parameters
- BootstrapResult    : point estimate + CI bounds + one-sided p-value
- bootstrap_metric   : single-series bootstrap → BootstrapResult
- bootstrap_paired   : paired (signal vs baseline) bootstrap with shared resample
                       indices → two BootstrapResults + comparison p-value
- benjamini_hochberg : BH-FDR q-values across a family of p-values
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np

ANNUALIZATION_FACTOR = 365  # mirror statistical_tests.ANNUALIZATION_FACTOR
DEFAULT_BLOCK_LENGTH = 14  # 2 × horizon for T+7
DEFAULT_N_BOOTSTRAP = 1000


@dataclass(frozen=True)
class BootstrapConfig:
    """Block bootstrap 파라미터.

    method "circular" : circular block bootstrap (Politis & Romano 1992) — 결정론적 길이.
    method "iid"      : i.i.d. resampling (기존 variance.bootstrap_ci 와 동치).
    """

    n_bootstrap: int = DEFAULT_N_BOOTSTRAP
    block_length: int = DEFAULT_BLOCK_LENGTH
    method: Literal["circular", "iid"] = "circular"
    seed: int = 0
    ci_alpha: float = 0.05  # 95% CI


@dataclass(frozen=True)
class BootstrapResult:
    """단일 메트릭의 bootstrap 결과.

    pvalue_one_sided : paired bootstrap 에서만 채워진다 (signal ≤ baseline 비율).
                       단일 시리즈 bootstrap 에서는 NaN.
    """

    point: float
    ci_lower: float
    ci_upper: float
    pvalue_one_sided: float
    n_bootstrap: int
    method: str
    block_length: int


def _circular_block_indices(n: int, block_length: int, rng: np.random.Generator) -> np.ndarray:
    """길이 n 의 circular block 인덱스 시퀀스를 반환한다.

    blocks_needed = ceil(n / block_length) 개의 시작점을 [0, n) 에서 뽑고,
    각 블록 [start, start+L) 를 mod n 으로 wrap 해 이어붙인 뒤 앞 n 개로 자른다.
    """
    if block_length < 1:
        raise ValueError(f"block_length must be ≥ 1, got {block_length}")
    if n <= 0:
        return np.empty(0, dtype=np.int64)
    block_length = min(block_length, n)
    blocks_needed = math.ceil(n / block_length)
    starts = rng.integers(low=0, high=n, size=blocks_needed)
    offsets: np.ndarray = np.arange(block_length, dtype=np.int64)
    raw = (starts[:, None] + offsets[None, :]) % n
    return raw.reshape(-1)[:n].astype(np.int64)


def _batch_circular_block_indices(
    n: int, block_length: int, n_bootstrap: int, rng: np.random.Generator
) -> np.ndarray:
    """circular block bootstrap 인덱스 행렬을 rng 호출 1회로 배치 생성.

    shape = (n_bootstrap, n). 개별 호출 대신 이 함수를 쓰면 rng 오버헤드가
    n_bootstrap 배 → 1 배로 줄어든다.
    """
    if block_length < 1:
        raise ValueError(f"block_length must be ≥ 1, got {block_length}")
    if n <= 0:
        return np.empty((n_bootstrap, 0), dtype=np.int64)
    block_length = min(block_length, n)
    blocks_needed = math.ceil(n / block_length)
    starts = rng.integers(low=0, high=n, size=(n_bootstrap, blocks_needed))
    offsets: np.ndarray = np.arange(block_length, dtype=np.int64)
    raw = (starts[:, :, None] + offsets[None, None, :]) % n  # (B, blocks, L)
    return raw.reshape(n_bootstrap, -1)[:, :n].astype(np.int64)  # (B, n)


def _resample_indices(n: int, cfg: BootstrapConfig, rng: np.random.Generator) -> np.ndarray:
    if cfg.method == "iid":
        return rng.integers(low=0, high=n, size=n).astype(np.int64)
    if cfg.method == "circular":
        return _circular_block_indices(n, cfg.block_length, rng)
    raise ValueError(f"unsupported bootstrap method: {cfg.method!r}")


def _batch_resample_indices(
    n: int, n_bootstrap: int, cfg: BootstrapConfig, rng: np.random.Generator
) -> np.ndarray:
    """(n_bootstrap, n) 인덱스 행렬을 rng 호출 1회로 생성한다."""
    if cfg.method == "iid":
        return rng.integers(low=0, high=n, size=(n_bootstrap, n)).astype(np.int64)
    if cfg.method == "circular":
        return _batch_circular_block_indices(n, cfg.block_length, n_bootstrap, rng)
    raise ValueError(f"unsupported bootstrap method: {cfg.method!r}")


def _ci_bounds(boot_values: np.ndarray, alpha: float) -> tuple[float, float]:
    finite = boot_values[np.isfinite(boot_values)]
    if finite.size == 0:
        return float("nan"), float("nan")
    lo = float(np.percentile(finite, 100.0 * (alpha / 2)))
    hi = float(np.percentile(finite, 100.0 * (1.0 - alpha / 2)))
    return lo, hi


def bootstrap_metric(
    values: np.ndarray,
    metric_fn: Callable[[np.ndarray], float],
    cfg: BootstrapConfig | None = None,
) -> BootstrapResult:
    """단일 시리즈에 대해 bootstrap 으로 메트릭의 CI 산출.

    NaN 값을 포함한 입력은 호출자가 사전 처리해야 한다 (메트릭 함수 책임).
    """
    cfg = cfg or BootstrapConfig()
    arr = np.asarray(values)
    n = arr.shape[0]
    if n == 0:
        return BootstrapResult(
            point=float("nan"),
            ci_lower=float("nan"),
            ci_upper=float("nan"),
            pvalue_one_sided=float("nan"),
            n_bootstrap=cfg.n_bootstrap,
            method=cfg.method,
            block_length=cfg.block_length,
        )
    rng = np.random.default_rng(cfg.seed)
    point = float(metric_fn(arr))
    all_idx = _batch_resample_indices(n, cfg.n_bootstrap, cfg, rng)
    boot: np.ndarray = np.empty(cfg.n_bootstrap, dtype=np.float64)
    for i in range(cfg.n_bootstrap):
        boot[i] = float(metric_fn(arr[all_idx[i]]))
    lo, hi = _ci_bounds(boot, cfg.ci_alpha)
    return BootstrapResult(
        point=point,
        ci_lower=lo,
        ci_upper=hi,
        pvalue_one_sided=float("nan"),
        n_bootstrap=cfg.n_bootstrap,
        method=cfg.method,
        block_length=cfg.block_length,
    )


def bootstrap_paired(
    signal_values: np.ndarray,
    baseline_values: np.ndarray,
    metric_fn: Callable[[np.ndarray], float],
    cfg: BootstrapConfig | None = None,
) -> tuple[BootstrapResult, BootstrapResult]:
    """signal/baseline 시리즈에 동일 인덱스 시퀀스로 bootstrap 적용.

    리샘플링 노이즈를 paired 로 제거 → CI 와 one-sided p-value (signal ≤ baseline 비율) 이
    "signal 이 baseline 보다 진짜 좋다" 가설과 직접 매핑된다.

    두 시리즈의 길이가 다르면 ValueError. NaN 처리는 호출자 책임.
    """
    cfg = cfg or BootstrapConfig()
    sig = np.asarray(signal_values)
    base = np.asarray(baseline_values)
    if sig.shape[0] != base.shape[0]:
        raise ValueError(f"signal/baseline length mismatch: {sig.shape[0]} vs {base.shape[0]}")
    n = sig.shape[0]
    if n == 0:
        empty = BootstrapResult(
            point=float("nan"),
            ci_lower=float("nan"),
            ci_upper=float("nan"),
            pvalue_one_sided=float("nan"),
            n_bootstrap=cfg.n_bootstrap,
            method=cfg.method,
            block_length=cfg.block_length,
        )
        return empty, empty
    rng = np.random.default_rng(cfg.seed)
    sig_point = float(metric_fn(sig))
    base_point = float(metric_fn(base))
    all_idx = _batch_resample_indices(n, cfg.n_bootstrap, cfg, rng)
    boot_sig: np.ndarray = np.empty(cfg.n_bootstrap, dtype=np.float64)
    boot_base: np.ndarray = np.empty(cfg.n_bootstrap, dtype=np.float64)
    leq_count = 0
    for i in range(cfg.n_bootstrap):
        idx = all_idx[i]
        s_val = float(metric_fn(sig[idx]))
        b_val = float(metric_fn(base[idx]))
        boot_sig[i] = s_val
        boot_base[i] = b_val
        if s_val <= b_val:
            leq_count += 1
    # one-sided p-value with +1/+1 add-1 smoothing (Davison & Hinkley 1997)
    pvalue = (1 + leq_count) / (cfg.n_bootstrap + 1)
    sig_lo, sig_hi = _ci_bounds(boot_sig, cfg.ci_alpha)
    base_lo, base_hi = _ci_bounds(boot_base, cfg.ci_alpha)
    sig_result = BootstrapResult(
        point=sig_point,
        ci_lower=sig_lo,
        ci_upper=sig_hi,
        pvalue_one_sided=pvalue,
        n_bootstrap=cfg.n_bootstrap,
        method=cfg.method,
        block_length=cfg.block_length,
    )
    base_result = BootstrapResult(
        point=base_point,
        ci_lower=base_lo,
        ci_upper=base_hi,
        pvalue_one_sided=float("nan"),
        n_bootstrap=cfg.n_bootstrap,
        method=cfg.method,
        block_length=cfg.block_length,
    )
    return sig_result, base_result


def auto_block_length(values: np.ndarray, fallback: int = DEFAULT_BLOCK_LENGTH) -> int:
    """시계열의 ACF 구조를 기반으로 적정 block length를 자동 계산한다.

    Politis & White (2004) 규칙을 단순화한 휴리스틱:
      b* ≈ 첫 번째로 Bartlett 95% 신뢰구간 내로 들어오는 lag
    statsmodels 없이 동작하도록 직접 구현한다.

    Parameters
    ----------
    values : np.ndarray
        hits 시계열 (0/1 배열).
    fallback : int
        ACF 계산 불가 시 사용할 기본값.

    Returns
    -------
    int
        권장 block length. 최소 1, 최대 len(values) // 3 으로 클램핑.
    """
    n = len(values)
    if n < 10:
        return fallback
    max_lag = min(35, n // 2)
    mean = float(np.mean(values))
    var = float(np.var(values, ddof=0))
    if var < 1e-15:
        return fallback
    centered = values - mean
    threshold = 1.96 / math.sqrt(n)
    for lag in range(1, max_lag + 1):
        acf_lag = float(np.sum(centered[lag:] * centered[:-lag])) / (n * var)
        if abs(acf_lag) < threshold:
            return max(1, min(lag, n // 3))
    return max(1, min(max_lag, n // 3))


def benjamini_hochberg(pvalues: np.ndarray, alpha: float = 0.10) -> np.ndarray:
    """BH-FDR q-value 산출.

    q[i] = min over k≥rank(i) of (p[k] * m / (k+1)).
    NaN p-value 는 NaN q 로 그대로 반환.
    """
    p = np.asarray(pvalues, dtype=np.float64)
    m = int(np.sum(np.isfinite(p)))
    q = np.full_like(p, fill_value=np.nan, dtype=np.float64)
    if m == 0:
        return q
    finite_mask = np.isfinite(p)
    finite_p = p[finite_mask]
    order = np.argsort(finite_p, kind="mergesort")
    ranked = finite_p[order]
    raw_q = ranked * m / (np.arange(1, m + 1))
    # monotone non-increasing from the right
    monotone = np.minimum.accumulate(raw_q[::-1])[::-1]
    # cap at 1.0
    monotone = np.minimum(monotone, 1.0)
    finite_q = np.empty_like(monotone)
    finite_q[order] = monotone
    q[finite_mask] = finite_q
    # bookkeeping: alpha is informational; downstream compares q ≤ threshold itself
    _ = alpha
    return q


__all__ = [
    "ANNUALIZATION_FACTOR",
    "BootstrapConfig",
    "BootstrapResult",
    "DEFAULT_BLOCK_LENGTH",
    "DEFAULT_N_BOOTSTRAP",
    "auto_block_length",
    "benjamini_hochberg",
    "bootstrap_metric",
    "bootstrap_paired",
    "_batch_resample_indices",
]
