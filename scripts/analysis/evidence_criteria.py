"""결정 유형별 증거 기준(evidence criteria) — DSR 단일 게이트의 대체 도구모음.

배경: 이 프로젝트는 지금까지 모든 채택 판정에 `DSR ≥ 0.95` 하나만 써 왔다. 그런데 DSR
(Bailey·López de Prado 2014)은 **긴 시계열에서 대규모 그리드 탐색의 최적 config를 고를 때
선택편향을 보정**하려고 만든 도구다. 아레나의 실제 결정 대부분은 그 상황이 아니다:

- Phase B 숏 검증은 **사전등록 단일사양**(n_trials=1)이라 선택편향이 애초에 없다 —
  이때 DSR은 수학적으로 PSR(Probabilistic Sharpe Ratio)과 같아지고, 남는 병목은
  선택편향이 아니라 **표본 길이 T**다. 그런데 T가 부족한 것과 엣지가 없는 것을
  DSR 값 하나로는 구분할 수 없다 → `min_track_record_length()`가 이 구분을 준다.
- 3자산 풀링(§18)은 거래의 97%가 시간 중복이라 "n=33 독립표본"이 거짓이다 →
  `design_effect()` / `effective_sample_size()`로 유효표본을 깎아야 정직하다.
- `meridian`처럼 라이브 표본으로 검증하는 경우, 백테스트용 고정표본 검정을 쓰면
  "언제 볼 것인가"에 따라 1종오류가 부풀어 오른다 → `evalue_process()`(anytime-valid,
  Wald SPRT/e-value 계열)가 맞는 도구. 아무 때나 봐도 되고 중단해도 α가 유지된다.
- 여러 후보를 동시에 스크리닝할 때 각각에 DSR(FWER형 보정)을 걸면 이중 보수화가 된다 →
  `benjamini_hochberg_yekutieli()`가 발견 단계에 맞는 FDR 통제(Harvey·Liu 2015가
  BHY/FDR과 Bonferroni-Holm/FWER의 용도 차이를 명시).
- 이미 라이브 중인 알고를 "유지할지 내릴지"는 양수 증명이 아니라 **명백한 음수인지**를
  물어야 한다 → `inferiority_test()`(방향을 뒤집은 비열등성 검정).

전부 numpy/scipy만 사용(추가 의존성 없음). 각 함수는 순수함수라 단독 테스트 가능하다.

참고 문헌:
- Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier", J. of Risk 15(2)
  — PSR·MinTRL.
- Bailey & López de Prado (2014), "The Deflated Sharpe Ratio" — DSR(기존 validation_stats).
- Harvey & Liu (2015), "Backtesting", J. of Portfolio Management — haircut, FDR vs FWER.
- Hansen (2005), "A Test for Superior Predictive Ability" — 상관 후보군 비교.
- Ramdas et al., e-values / always-valid inference — 라이브 순차검정.

재현:
  .venv/bin/python3 scripts/analysis/evidence_criteria.py --self-test
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
from scipy.stats import norm

# ---------------------------------------------------------------------------
# 기초: Sharpe와 그 고차모멘트 보정 분산
# ---------------------------------------------------------------------------


def _moments(returns: np.ndarray) -> tuple[float, float, float, int]:
    """(sharpe, skew, kurtosis_non_excess, T). 표본이 부족하면 sharpe=0."""
    r = np.asarray(returns, dtype=float)
    T = r.size
    if T < 2:
        return 0.0, 0.0, 3.0, T
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0, 0.0, 3.0, T
    sr = float(r.mean() / sd)
    mean = r.mean()
    skew = float(((r - mean) ** 3).mean() / sd**3)
    kurt = float(((r - mean) ** 4).mean() / sd**4)  # non-excess
    return sr, skew, kurt, T


def _sr_variance_factor(sr: float, skew: float, kurt: float) -> float:
    """SR 추정치 분산의 분자 — (1 - γ₃·SR + (γ₄-1)/4·SR²).

    정규분포면 skew=0, kurt=3이라 1 + SR²/2로 환원된다. 음수가 되면(극단 왜도)
    수치적으로 무의미하므로 하한을 둔다.
    """
    factor = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2
    return max(factor, 1e-9)


# ---------------------------------------------------------------------------
# 결정유형 B: 사전등록 단일가설 — PSR + MinTRL
# ---------------------------------------------------------------------------


def probabilistic_sharpe_ratio(returns: np.ndarray, *, benchmark_sr: float = 0.0) -> dict:
    """PSR — 관측 SR이 benchmark_sr를 실제로 초과할 확률(비정규성 보정).

    DSR에서 선택편향 항(expected_max)을 뺀 것과 동일하다. 즉 n_trials=1인 DSR = PSR.
    사전등록 단일사양 검증에는 이쪽이 의미가 명확하다(보정할 선택편향이 없으므로).
    """
    sr, skew, kurt, T = _moments(returns)
    if T < 2:
        return {"psr": 0.0, "sharpe": 0.0, "T": T}
    factor = _sr_variance_factor(sr, skew, kurt)
    z = (sr - benchmark_sr) * np.sqrt(T - 1.0) / np.sqrt(factor)
    return {
        "psr": float(norm.cdf(z)),
        "sharpe": sr,
        "skew": skew,
        "kurtosis": kurt,
        "T": T,
    }


def min_track_record_length(
    returns: np.ndarray,
    *,
    benchmark_sr: float = 0.0,
    confidence: float = 0.95,
) -> dict:
    """MinTRL — 관측된 SR·왜도·첨도를 그대로 유지한다고 가정할 때, `confidence`
    수준으로 SR > benchmark_sr를 주장하려면 필요한 최소 관측 수.

    이 값이 이 모듈의 핵심이다. DSR/PSR이 낮게 나왔을 때 그게
      (a) "엣지가 없다"인지
      (b) "표본이 부족해 판정 자체가 불가능하다"인지
    를 구분해 준다. observed_T < MinTRL이면 그 검정은 애초에 검정력이 없었던 것이고,
    "기각"이 아니라 "판정 불가(inconclusive)"로 기록해야 정직하다.

    반환의 `shortfall_ratio` = MinTRL / T — 표본이 몇 배 더 필요한지.
    SR ≤ benchmark면 MinTRL은 정의되지 않는다(아무리 모아도 못 넘음) → inf.
    """
    sr, skew, kurt, T = _moments(returns)
    if T < 2:
        return {"min_trl": float("inf"), "T": T, "sharpe": 0.0, "feasible": False}
    if sr <= benchmark_sr:
        return {
            "min_trl": float("inf"),
            "T": T,
            "sharpe": sr,
            "feasible": False,
            "reason": "관측 SR이 기준선 이하 — 표본을 늘려도 이 방향으론 못 넘음",
        }
    factor = _sr_variance_factor(sr, skew, kurt)
    z_alpha = norm.ppf(confidence)
    min_trl = 1.0 + factor * (z_alpha / (sr - benchmark_sr)) ** 2
    return {
        "min_trl": float(min_trl),
        "T": T,
        "sharpe": sr,
        "skew": skew,
        "kurtosis": kurt,
        "feasible": True,
        "shortfall_ratio": float(min_trl / T) if T > 0 else float("inf"),
        "sufficient": bool(T >= min_trl),
    }


def minimum_detectable_sharpe(T: int, *, confidence: float = 0.95) -> float:
    """표본 T개로 `confidence` 수준에서 검출 가능한 최소 SR(정규 근사, MDE).

    MinTRL의 역함수격. "n=33으로는 SR 0.29 미만은 어차피 못 잡는다"처럼
    사전에 검정력을 확인할 때 쓴다.
    """
    if T < 2:
        return float("inf")
    z = norm.ppf(confidence)
    # sr ≈ z·sqrt((1+sr²/2)/(T-1)) 를 sr에 대해 푼 근사(정규 가정).
    a = 1.0 - (z**2) / (2.0 * (T - 1))
    if a <= 0:
        return float("inf")
    return float(z / np.sqrt((T - 1) * a))


# ---------------------------------------------------------------------------
# 결정유형 E: 상관된 다자산/중복 표본 — 유효표본 보정
# ---------------------------------------------------------------------------


def design_effect(cluster_sizes: list[int], intra_cluster_corr: float) -> float:
    """DEFF = 1 + (m̄ - 1)·ρ  (Kish). m̄는 평균 클러스터 크기.

    아레나 적용: 하나의 매크로 신호가 BTC/ETH/SOL에 동시 발화하면 그 3건이 한 클러스터다.
    ρ는 클러스터 내 수익률 상관.
    """
    if not cluster_sizes:
        return 1.0
    m_bar = float(np.mean(cluster_sizes))
    rho = float(np.clip(intra_cluster_corr, 0.0, 1.0))
    return max(1.0, 1.0 + (m_bar - 1.0) * rho)


def effective_sample_size(
    returns: np.ndarray,
    cluster_labels: list,
) -> dict:
    """클러스터 상관을 반영한 유효표본 n_eff = n / DEFF.

    cluster_labels: 각 관측이 속한 클러스터 ID(같은 시간대 동시발화 = 같은 ID).
    ρ는 클러스터 내 상관을 일원배치 분산분석(ANOVA) 방식으로 추정한다:
      ρ = (MSB - MSW) / (MSB + (m̄-1)·MSW)
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2 or len(cluster_labels) != n:
        return {"n": n, "n_eff": float(n), "deff": 1.0, "icc": 0.0}
    labels = np.asarray(cluster_labels)
    uniq = np.unique(labels)
    k = uniq.size
    if k < 2 or k == n:
        # 클러스터가 하나거나 전부 단독이면 보정 불가/불필요.
        return {"n": n, "n_eff": float(n), "deff": 1.0, "icc": 0.0, "n_clusters": k}
    grand = r.mean()
    sizes = []
    ssb = 0.0
    ssw = 0.0
    for c in uniq:
        grp = r[labels == c]
        sizes.append(grp.size)
        ssb += grp.size * (grp.mean() - grand) ** 2
        ssw += ((grp - grp.mean()) ** 2).sum()
    msb = ssb / (k - 1)
    msw = ssw / (n - k) if n > k else 0.0
    m_bar = float(np.mean(sizes))
    denom = msb + (m_bar - 1.0) * msw
    icc = float((msb - msw) / denom) if denom > 0 else 0.0
    icc = float(np.clip(icc, 0.0, 1.0))
    deff = design_effect(sizes, icc)
    return {
        "n": n,
        "n_clusters": k,
        "mean_cluster_size": m_bar,
        "icc": icc,
        "deff": float(deff),
        "n_eff": float(n / deff),
    }


def psr_with_effective_n(
    returns: np.ndarray, cluster_labels: list, *, benchmark_sr: float = 0.0
) -> dict:
    """유효표본으로 재계산한 PSR — 상관 표본을 독립인 척하지 않는 버전."""
    ess = effective_sample_size(returns, cluster_labels)
    sr, skew, kurt, T = _moments(returns)
    n_eff = max(ess["n_eff"], 2.0)
    factor = _sr_variance_factor(sr, skew, kurt)
    z = (sr - benchmark_sr) * np.sqrt(n_eff - 1.0) / np.sqrt(factor)
    return {
        "psr_naive": probabilistic_sharpe_ratio(returns, benchmark_sr=benchmark_sr)["psr"],
        "psr_effective": float(norm.cdf(z)),
        "sharpe": sr,
        **ess,
    }


# ---------------------------------------------------------------------------
# 결정유형 C: 라이브 표본 축적 — anytime-valid 순차검정(e-value)
# ---------------------------------------------------------------------------


def evalue_process(
    returns: np.ndarray,
    *,
    alpha: float = 0.05,
    n_lambda: int = 40,
    clip: float = 3.0,
) -> dict:
    """H0: E[r] ≤ 0 에 대한 e-value(혼합 betting) 과정.

    anytime-valid: 매 거래마다 확인해도, 언제 멈춰도 1종오류가 alpha로 유지된다.
    고정표본 검정(DSR/PSR)과 달리 "표본이 다 쌓일 때까지 기다렸다가 한 번에 판정"할
    필요가 없어, `meridian`처럼 라이브로 검증하는 알고에 정확히 맞는 도구다.

    구현: 베팅비율 λ에 대한 **혼합**(mixture) e-value —
        e_n = (1/K)·Σ_k ∏_i (1 + λ_k·x_i),   x_i = clip(r_i/scale)
    각 λ_k에 대해 ∏(1+λx_i)는 H0에서 기댓값 ≤ 1인 비음수 마팅게일이고, e-value들의
    고정가중 혼합도 e-value이므로 전체가 유효하다. plug-in(과거추정 λ) 방식보다
    초기 표본에서 훨씬 안정적이고 검정력이 높다(mSPRT 계열의 표준 관행).

    λ_k는 0 초과 구간만 사용한다 — 단측 대립가설(엣지가 양수)을 검정하므로.
    λ·clip < 1이어야 로그가 정의되므로 λ 상한은 1/clip 미만으로 잡는다.

    기각 임계: e_n ≥ 1/alpha (Ville 부등식).
    `max_evalue`는 경로 전체 최댓값 — anytime-valid라 한 번이라도 넘으면 기각 가능.
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2:
        return {"evalue": 1.0, "max_evalue": 1.0, "reject": False, "n": n}
    scale = r.std(ddof=1)
    if scale <= 0:
        return {"evalue": 1.0, "max_evalue": 1.0, "reject": False, "n": n}
    x = np.clip(r / scale, -clip, clip)
    lam_max = 0.95 / clip
    lambdas = np.linspace(lam_max / n_lambda, lam_max, n_lambda)
    # (K, n) 로그 성장 → 누적합으로 경로 전체를 한 번에.
    log_terms = np.log1p(np.outer(lambdas, x))
    cum = np.cumsum(log_terms, axis=1)
    # 혼합: logsumexp로 수치안정.
    m = cum.max(axis=0)
    mixture_path = m + np.log(np.exp(cum - m).mean(axis=0))
    e_path = np.exp(mixture_path)
    threshold = 1.0 / alpha
    return {
        "evalue": float(e_path[-1]),
        "max_evalue": float(e_path.max()),
        "threshold": threshold,
        "reject": bool(e_path.max() >= threshold),
        "n": n,
        "log_evalue": float(mixture_path[-1]),
        "path": e_path.tolist(),
    }


def evalue_trades_needed(observed_returns: np.ndarray, *, alpha: float = 0.05) -> dict:
    """현재 관측된 분포가 그대로 이어진다고 가정할 때 e-value가 1/alpha에 도달하는
    데 필요한 대략적 거래 수 — 라이브 검증의 '언제쯤 결론 나나' 추정.

    로그 e-value의 관측 평균 증가율(drift)로 선형 외삽한다. drift ≤ 0이면 도달 불가.
    """
    proc = evalue_process(observed_returns, alpha=alpha)
    n = proc["n"]
    if n < 3:
        return {"reachable": False, "reason": "표본 부족"}
    log_e = proc.get("log_evalue", np.log(max(proc["evalue"], 1e-12)))
    drift = log_e / n
    target = np.log(1.0 / alpha)
    if drift <= 0:
        return {
            "reachable": False,
            "reason": (
                "현재까지 누적 증거가 감소 방향 — e-value 로그가 음수라 "
                "이 표본분포가 이어지면 기각선에 도달하지 않음"
            ),
            "current_evalue": proc["evalue"],
        }
    return {
        "reachable": True,
        "current_evalue": proc["evalue"],
        "log_drift_per_trade": float(drift),
        "trades_needed_total": float(target / drift),
        "trades_remaining": float(max(0.0, (target - log_e) / drift)),
    }


# ---------------------------------------------------------------------------
# 결정유형 D: 다후보 스크리닝 — FDR(BHY) 통제
# ---------------------------------------------------------------------------


def benjamini_hochberg_yekutieli(pvalues: list[float], *, q: float = 0.10) -> dict:
    """BHY(Benjamini-Hochberg-Yekutieli) — 임의 의존성 하에서도 유효한 FDR 통제.

    Harvey & Liu(2015)가 백테스트 다중검정에 권고한 것 중 하나. FWER(Bonferroni/Holm,
    그리고 사실상 DSR의 expected-max 보정)은 "단 한 건의 오탐도 불허"라 발견 단계에는
    지나치게 보수적이다. 후보 스크리닝에는 FDR이 맞다.

    반환: 각 가설의 기각 여부 + 임계 p값.
    """
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    if m == 0:
        return {"rejected": [], "threshold": 0.0, "n_rejected": 0}
    order = np.argsort(p)
    sorted_p = p[order]
    # Yekutieli 보정계수 c(m) = Σ 1/i
    c_m = float(np.sum(1.0 / np.arange(1, m + 1)))
    ranks = np.arange(1, m + 1)
    crit = ranks / (m * c_m) * q
    passed = sorted_p <= crit
    if not passed.any():
        return {
            "rejected": [False] * m,
            "threshold": 0.0,
            "n_rejected": 0,
            "c_m": c_m,
            "q": q,
        }
    k = int(np.max(np.where(passed)[0]))
    thresh = float(sorted_p[k])
    rejected = (p <= thresh).tolist()
    return {
        "rejected": rejected,
        "threshold": thresh,
        "n_rejected": int(np.sum(rejected)),
        "c_m": c_m,
        "q": q,
    }


def sharpe_pvalue(returns: np.ndarray, *, benchmark_sr: float = 0.0) -> float:
    """단측 p값 = 1 - PSR. BHY 입력용."""
    return float(1.0 - probabilistic_sharpe_ratio(returns, benchmark_sr=benchmark_sr)["psr"])


# ---------------------------------------------------------------------------
# 결정유형 F: 유지/철회 판정 — 방향을 뒤집은 열등성 검정
# ---------------------------------------------------------------------------


def inferiority_test(
    returns: np.ndarray,
    *,
    inferiority_margin_sr: float = -0.10,
    confidence: float = 0.95,
    min_observations: int = 20,
) -> dict:
    """ "이 알고를 내려야 하는가" 검정 — 귀무가설을 뒤집는다.

    채택 판정(H0: 엣지 없음, 증명책임=전략)과 철회 판정(H0: 전략 유지, 증명책임=철회)은
    **다른 검정**이어야 한다. 이미 라이브 중인 알고를 계속 둘지는 "양수임을 증명"이
    아니라 "명백히 margin보다 나쁜가"를 물어야 한다 — 안 그러면 검정력 없는 표본에서
    무조건 철회가 되어 vision.md의 "표본 확보" 원칙과 정면 충돌한다.

    반환 `should_retire`=True는 SR이 margin보다 나쁘다는 걸 confidence 수준에서
    확신할 수 있을 때만이다.

    `min_observations`: 이 미만에서는 철회 판정을 내지 않는다. SR 분산의 왜도·첨도
    보정항이 소표본에서 극도로 불안정해(n<20이면 표본첨도 자체가 신뢰구간이 매우 넓다)
    분모를 우연히 축소시키면 "확신"이 인위적으로 생긴다 — 실제로 라이브 n=6 표본에서
    이 현상이 관측돼 가드를 넣었다.
    """
    sr, skew, kurt, T = _moments(returns)
    if T < 2:
        return {"should_retire": False, "reason": "표본 부족", "T": T}
    factor = _sr_variance_factor(sr, skew, kurt)
    se = np.sqrt(factor / (T - 1))
    # H0: SR >= margin  vs  H1: SR < margin
    z = (sr - inferiority_margin_sr) / se
    p_worse = float(norm.cdf(z))  # margin보다 나쁠 확률의 여집합
    confident = (1.0 - p_worse) >= confidence
    underpowered = T < min_observations
    return {
        "sharpe": sr,
        "T": T,
        "margin": inferiority_margin_sr,
        "prob_worse_than_margin": float(1.0 - p_worse),
        "should_retire": bool(confident and not underpowered),
        "verdict_deferred": bool(confident and underpowered),
        "se": float(se),
        "min_observations": min_observations,
    }


# ---------------------------------------------------------------------------
# 결정유형 B': 문헌 사전확률을 반영한 베이지안 — 숏의 비대칭 증거요구 형식화
# ---------------------------------------------------------------------------


def bayesian_edge_probability(
    returns: np.ndarray,
    *,
    prior_mean_sr: float = 0.0,
    prior_strength: float = 10.0,
) -> dict:
    """P(SR > 0 | 데이터, 사전확률) — 정규-정규 켤레 근사.

    `prior_strength`는 사전확률의 '가상 표본수'다. 문헌이 강한 부정적 근거를 주는
    경우(추세미러 숏 = 모멘텀 크래시, Daniel & Moskowitz 2016)를 prior_mean_sr<0으로
    형식화하면, 숏에 더 많은 증거를 요구한다는 프로젝트의 기존 정성적 판단이
    수치로 표현된다 — 임의의 문턱값을 알고마다 다르게 두는 것보다 일관적이다.

    prior_strength=0이면 무정보 사전확률(빈도주의 결과에 수렴).
    """
    sr, skew, kurt, T = _moments(returns)
    if T < 2:
        return {"prob_positive": 0.5, "T": T}
    factor = _sr_variance_factor(sr, skew, kurt)
    data_var = factor / max(T - 1, 1)
    if prior_strength <= 0:
        post_mean, post_var = sr, data_var
    else:
        prior_var = factor / prior_strength
        w = (1.0 / data_var) / (1.0 / data_var + 1.0 / prior_var)
        post_mean = w * sr + (1.0 - w) * prior_mean_sr
        post_var = 1.0 / (1.0 / data_var + 1.0 / prior_var)
    post_sd = np.sqrt(post_var)
    return {
        "prob_positive": float(1.0 - norm.cdf(0.0, loc=post_mean, scale=post_sd)),
        "posterior_mean_sr": float(post_mean),
        "posterior_sd": float(post_sd),
        "observed_sharpe": sr,
        "prior_mean_sr": prior_mean_sr,
        "prior_strength": prior_strength,
        "T": T,
    }


def bootstrap_ci(returns: np.ndarray, *, n_resamples: int = 3000, seed: int = 42) -> tuple:
    """평균 수익률의 부트스트랩 95% CI(기존 스크립트들과 동일 관행)."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(n_resamples, r.size), replace=True).mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(r.mean()), float(lo), float(hi)


# ---------------------------------------------------------------------------
# 자가검증
# ---------------------------------------------------------------------------


def _self_test() -> int:
    rng = np.random.default_rng(7)
    print("=" * 72)
    print("evidence_criteria 자가검증")
    print("=" * 72)

    # 1) 진짜 엣지가 있는 큰 표본 → PSR 높고 MinTRL < T
    strong = rng.normal(0.004, 0.01, 500)
    psr = probabilistic_sharpe_ratio(strong)
    trl = min_track_record_length(strong)
    print(f"\n[강한 엣지·큰 표본] SR={psr['sharpe']:.3f} PSR={psr['psr']:.4f}")
    print(f"  MinTRL={trl['min_trl']:.1f} vs T={trl['T']}  충분={trl['sufficient']}")
    assert psr["psr"] > 0.99 and trl["sufficient"]

    # 2) 같은 엣지인데 표본만 작음 → PSR 낮지만 MinTRL이 '판정불가'를 알려줌
    small = strong[:25]
    psr_s = probabilistic_sharpe_ratio(small)
    trl_s = min_track_record_length(small)
    print(f"\n[같은 엣지·작은 표본 n=25] SR={psr_s['sharpe']:.3f} PSR={psr_s['psr']:.4f}")
    print(f"  MinTRL={trl_s['min_trl']:.1f} vs T={trl_s['T']}  충분={trl_s['sufficient']}")
    print(f"  → 표본이 {trl_s['shortfall_ratio']:.1f}배 필요 = '기각'이 아니라 '판정불가'")

    # 3) MDE
    for n in (20, 33, 50, 100, 250):
        print(f"  n={n:4d} → 검출가능 최소 SR(거래당) = {minimum_detectable_sharpe(n):.3f}")

    # 4) 클러스터 상관 → 유효표본 감소
    base = rng.normal(0.002, 0.02, 11)
    corr_returns = np.concatenate([base, base * 0.98 + rng.normal(0, 0.001, 11), base * 1.02])
    labels = list(range(11)) * 3
    ess = effective_sample_size(corr_returns, labels)
    print(f"\n[3자산 동시발화 모사] n={ess['n']} → n_eff={ess['n_eff']:.1f}")
    print(f"  ICC={ess['icc']:.3f}  DEFF={ess['deff']:.2f}")
    assert ess["n_eff"] < ess["n"]

    # 5) e-value: 엣지 있으면 증가, 없으면 안 증가
    ev_edge = evalue_process(rng.normal(0.004, 0.01, 200))
    ev_null = evalue_process(rng.normal(0.0, 0.01, 200))
    print(f"\n[e-value] 엣지있음 max_e={ev_edge['max_evalue']:.2f} reject={ev_edge['reject']}")
    print(f"[e-value] 엣지없음 max_e={ev_null['max_evalue']:.2f} reject={ev_null['reject']}")
    assert ev_edge["max_evalue"] > ev_null["max_evalue"]

    # 6) BHY
    bhy = benjamini_hochberg_yekutieli([0.001, 0.02, 0.30, 0.55, 0.80], q=0.10)
    print(f"\n[BHY q=0.10] 기각수={bhy['n_rejected']}  임계p={bhy['threshold']:.4f}")

    # 7) 열등성 검정 — 소표본에서는 철회하지 않아야 함
    inf_small = inferiority_test(rng.normal(-0.001, 0.02, 15))
    inf_bad = inferiority_test(rng.normal(-0.010, 0.01, 300))
    print(f"\n[열등성] 소표본 약음수 → 철회={inf_small['should_retire']} (False여야 정상)")
    print(f"[열등성] 대표본 명확음수 → 철회={inf_bad['should_retire']} (True여야 정상)")
    assert not inf_small["should_retire"]

    # 8) 베이지안 사전확률 효과
    obs = rng.normal(0.003, 0.02, 40)
    flat = bayesian_edge_probability(obs, prior_mean_sr=0.0, prior_strength=0)
    skeptic = bayesian_edge_probability(obs, prior_mean_sr=-0.10, prior_strength=40)
    print(f"\n[베이지안] 무정보 P(SR>0)={flat['prob_positive']:.3f}")
    print(f"[베이지안] 회의적사전(숏) P(SR>0)={skeptic['prob_positive']:.3f}")
    assert skeptic["prob_positive"] < flat["prob_positive"]

    print("\n모든 자가검증 통과.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
