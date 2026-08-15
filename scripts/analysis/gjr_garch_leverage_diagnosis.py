"""GJR-GARCH(1,1) 비대칭 계수 진단 (Phase B 2순환 §3-1, 전략 아님).

배경: docs/arena/research/short-entry-asymmetry-literature-review-20260815.md §3-1.
크립토 문헌은 "역방향 레버리지 효과"(양의 충격이 변동성을 더 키움, γ<0)를
보고하는데, 이 프로젝트의 실제 BTC/ETH/SOL 표본에서도 나타나는지 확인한다.
이건 전략이 아니라 Phase B 2순환(macd_momentum 모멘텀 vol 사이징) 착수 여부를
가르는 사전 진단 — 그리드 없이 단일 모델 사양(GJR-GARCH(1,1), Student-t)으로
1회만 적합한다.

데이터: arena_ohlcv_bars 4H 봉 전체 커버리지(2023-05~현재)를 일봉으로 리샘플
(리샘플 근거: leverage-effect 문헌의 표준 관행이 일간 수익률, 4H는 마이크로구조
노이즈로 비대칭 추정이 불안정해질 수 있음 — arch_model 부분에 4H 결과도
참고용으로 함께 출력해 방향이 일치하는지만 교차확인).

파라미터화(arch 패키지 GJR-GARCH, o=1):
  σ²_t = ω + α·ε²_{t-1} + γ·ε²_{t-1}·I(ε_{t-1}<0) + β·σ²_{t-1}
  γ>0 (유의) → 정방향 레버리지 효과(하락이 변동성을 더 키움, 주식시장형)
  γ<0 (유의) → 역방향 레버리지 효과(상승이 변동성을 더 키움, 문헌이 예측한 크립토형)

재현: .venv/bin/python3 scripts/analysis/gjr_garch_leverage_diagnosis.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import positions  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


async def _fetch_close_series(db, symbol: str) -> pd.Series:
    """arena_ohlcv_bars 4H 전체(2023-05-01~현재)를 페이지네이션으로 가져와 close_time 인덱스 Series."""
    rows: list[dict] = []
    page_size = 1000
    start = 0
    while True:
        res = await (
            db.table("arena_ohlcv_bars")
            .select("close_time,close")
            .eq("symbol", symbol)
            .eq("interval", "4h")
            .order("open_time")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    idx = pd.to_datetime([r["close_time"] for r in rows], utc=True)
    vals = [float(r["close"]) for r in rows]
    s = pd.Series(vals, index=idx, name=symbol)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _log_returns_pct(close: pd.Series, rule: str | None) -> pd.Series:
    series = close.resample(rule).last().dropna() if rule else close
    log_ret = np.log(series / series.shift(1)).dropna()
    # arch 패키지 관행: 수익률을 %로 스케일(수치 안정성, 계수 해석에는 무관)
    return log_ret * 100.0


def _fit_gjr_garch(returns: pd.Series) -> dict:
    am = arch_model(returns, mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t")
    res = am.fit(disp="off")
    gamma = float(res.params["gamma[1]"])
    gamma_p = float(res.pvalues["gamma[1]"])
    alpha = float(res.params["alpha[1]"])
    beta = float(res.params["beta[1]"])
    return {
        "n": int(returns.shape[0]),
        "alpha": alpha,
        "gamma": gamma,
        "gamma_pvalue": gamma_p,
        "gamma_significant_5pct": gamma_p < 0.05,
        "beta": beta,
        "persistence": alpha + beta + gamma / 2.0,
        "loglik": float(res.loglikelihood),
        "converged": bool(res.convergence_flag == 0),
    }


def _direction_label(gamma: float, significant: bool) -> str:
    if not significant:
        return "유의하지 않음(중립)"
    return "정방향(주식시장형, 하락이 변동성↑)" if gamma > 0 else "역방향(크립토형, 상승이 변동성↑)"


async def main() -> int:
    await positions.init()
    db = positions.db()

    print(f"{'=' * 78}\nGJR-GARCH(1,1) 비대칭 계수 진단 — 그리드 없음, 단일 사양 1회\n{'=' * 78}")

    daily_results: dict[str, dict] = {}
    h4_results: dict[str, dict] = {}

    for symbol in SYMBOLS:
        print(f"\n--- {symbol} ---")
        close = await _fetch_close_series(db, symbol)
        print(f"  4H 봉: {len(close)}개  {close.index[0].date()} ~ {close.index[-1].date()}")

        daily_ret = _log_returns_pct(close, "1D")
        h4_ret = _log_returns_pct(close, None)

        print(f"  일간 로그수익률 n={len(daily_ret)}")
        d = _fit_gjr_garch(daily_ret)
        daily_results[symbol] = d
        print(
            f"    daily: alpha={d['alpha']:+.4f} gamma={d['gamma']:+.4f} "
            f"(p={d['gamma_pvalue']:.4f}, {'유의' if d['gamma_significant_5pct'] else '비유의'}) "
            f"beta={d['beta']:.4f} persistence={d['persistence']:.4f} converged={d['converged']}"
        )
        print(f"    → {_direction_label(d['gamma'], d['gamma_significant_5pct'])}")

        print(f"  4H 로그수익률 n={len(h4_ret)} (교차확인용, 참고)")
        h = _fit_gjr_garch(h4_ret)
        h4_results[symbol] = h
        print(
            f"    4h: alpha={h['alpha']:+.4f} gamma={h['gamma']:+.4f} "
            f"(p={h['gamma_pvalue']:.4f}, {'유의' if h['gamma_significant_5pct'] else '비유의'}) "
            f"beta={h['beta']:.4f} persistence={h['persistence']:.4f} converged={h['converged']}"
        )
        print(f"    → {_direction_label(h['gamma'], h['gamma_significant_5pct'])}")

    print(f"\n{'=' * 78}\n요약\n{'=' * 78}")
    header = (
        f"{'symbol':10s} {'freq':6s} {'n':>6s} {'gamma':>9s} {'p':>8s} {'sig':>5s} {'방향':30s}"
    )
    print(header)
    for symbol in SYMBOLS:
        for label, results in (("daily", daily_results), ("4h", h4_results)):
            r = results[symbol]
            sig = "Y" if r["gamma_significant_5pct"] else "N"
            direction = _direction_label(r["gamma"], r["gamma_significant_5pct"])
            print(
                f"{symbol:10s} {label:6s} {r['n']:>6d} {r['gamma']:>+9.4f} "
                f"{r['gamma_pvalue']:>8.4f} {sig:>5s} {direction:30s}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
