"""BTC 거래소 순유출 데이터 소스 (스캐폴딩).

거래소 순유출(Exchange Net Outflow)은 온체인 신호 중 BTC 가격 선행성이
학술/실무에서 가장 일관되게 보고되는 지표입니다 (HR delta ~5-10%).
ETF 레이어만 보는 etf_net_inflow_usd와 달리, 모든 거래소 전체의 온체인 이동을 봅니다.

## 데이터 소스 옵션 (우선순위 순)

1. **CryptoQuant** (권장)
   - endpoint: https://api.cryptoquant.com/v1/btc/exchange-flows/netflow
   - env: CRYPTOQUANT_API_KEY
   - 무료 플랜: 최근 180일, 일별 해상도
   - 컬럼: date, netflow_total (음수 = 유출 우세)

2. **Glassnode**
   - endpoint: https://api.glassnode.com/v1/metrics/transactions/transfers_volume_to_exchanges_sum
   - env: GLASSNODE_API_KEY
   - 무료: 최근 1년, 주별만 / 유료: 일별

3. **CoinMetrics** (부분 무료)
   - endpoint: https://community-api.coinmetrics.io/v4/timeseries/asset-metrics
   - metrics: FlowInExNtv, FlowOutExNtv
   - 무료: community tier, 일별

## 파이프라인 연결 지점

join.py merge_sources()에서 vix와 동일한 패턴으로 left-join:

    from morning_brief.analysis.sentiment_join.sources.exchange_outflow import (
        fetch_exchange_outflow,
    )
    outflow_df = fetch_exchange_outflow(start_date, end_date)
    outflow_cols = ["btc_exchange_net_outflow_usd"]
    if not outflow_df.empty:
        merged = merged.merge(outflow_df[["date"] + outflow_cols], on="date", how="left")
    else:
        merged["btc_exchange_net_outflow_usd"] = float("nan")

feature_store.py / statistical_tests.py에 추가할 컬럼:
    "btc_exchange_net_outflow_usd_lag1"  — Granger 검정 대상

## 구현 체크리스트 (다음 세션)

- [ ] API 키 결정 (CryptoQuant vs Glassnode vs CoinMetrics)
- [ ] fetch_exchange_outflow() 실제 구현
- [ ] join.py merge_sources() 연결
- [ ] _add_futures_lag_columns() 또는 별도 함수에 lag1 생성
- [ ] statistical_tests.py _PREDICTORS_RAW에 추가
- [ ] baselines.py exchange_outflow_long() 신호 함수 추가
- [ ] check_acf_block_length.py predictor 목록에 추가
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

# 지원 제공자 (환경변수로 선택)
_PROVIDER_ENV = "EXCHANGE_OUTFLOW_PROVIDER"  # "cryptoquant" | "glassnode" | "coinmetrics"
_DEFAULT_PROVIDER = "cryptoquant"


def _empty_outflow_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="object"),
            "btc_exchange_net_outflow_usd": pd.Series(dtype="float64"),
        }
    )


def fetch_exchange_outflow(start_date: str, end_date: str) -> pd.DataFrame:
    """BTC 거래소 순유출 일별 시계열을 반환합니다.

    양수 = 유입 우세(매도 압력), 음수 = 유출 우세(보유 전환 신호).
    API 키 미설정 또는 실패 시 빈 프레임을 반환합니다 (파이프라인은 left-join).

    Parameters
    ----------
    start_date : str
        조회 시작일 (YYYY-MM-DD).
    end_date : str
        조회 종료일 (YYYY-MM-DD).

    Returns
    -------
    pd.DataFrame
        columns: date (str), btc_exchange_net_outflow_usd (float)
    """
    provider = os.getenv(_PROVIDER_ENV, _DEFAULT_PROVIDER).lower().strip()

    if provider == "cryptoquant":
        return _fetch_cryptoquant(start_date, end_date)
    if provider == "glassnode":
        return _fetch_glassnode(start_date, end_date)
    if provider == "coinmetrics":
        return _fetch_coinmetrics(start_date, end_date)

    log_structured(
        logger,
        event="source.skipped",
        message=f"알 수 없는 EXCHANGE_OUTFLOW_PROVIDER: {provider!r}. 건너뜁니다.",
        source="exchange_outflow",
    )
    frame = _empty_outflow_frame()
    frame.attrs["source"] = "none"
    return frame


# ─── 제공자별 구현 (TODO) ───────────────────────────────────────────────────


def _fetch_cryptoquant(start_date: str, end_date: str) -> pd.DataFrame:
    """CryptoQuant API에서 BTC exchange netflow를 가져옵니다.

    환경변수: CRYPTOQUANT_API_KEY
    endpoint: https://api.cryptoquant.com/v1/btc/exchange-flows/netflow
    """
    api_key = os.getenv("CRYPTOQUANT_API_KEY", "").strip()
    if not api_key:
        log_structured(
            logger,
            event="source.skipped",
            message="CRYPTOQUANT_API_KEY가 없어 exchange outflow 수집을 건너뜁니다.",
            source="exchange_outflow",
        )
        frame = _empty_outflow_frame()
        frame.attrs["source"] = "cryptoquant_skipped"
        return frame

    # TODO: 실제 API 호출 구현
    # from morning_brief.data.sources.http_client import get_json_with_retry
    # payload = get_json_with_retry(
    #     "https://api.cryptoquant.com/v1/btc/exchange-flows/netflow",
    #     params={"window": "day", "from": start_date, "to": end_date, "limit": 730},
    #     headers={"Authorization": f"Bearer {api_key}"},
    #     provider="cryptoquant",
    # )
    # records = [
    #     {"date": item["date"][:10], "btc_exchange_net_outflow_usd": item["netflow_total"]}
    #     for item in payload.get("result", {}).get("data", [])
    # ]
    raise NotImplementedError("CryptoQuant fetch_exchange_outflow 미구현 — 위 TODO 참고")


def _fetch_glassnode(start_date: str, end_date: str) -> pd.DataFrame:
    """Glassnode API에서 BTC exchange netflow를 가져옵니다.

    환경변수: GLASSNODE_API_KEY
    """
    api_key = os.getenv("GLASSNODE_API_KEY", "").strip()
    if not api_key:
        log_structured(
            logger,
            event="source.skipped",
            message="GLASSNODE_API_KEY가 없어 exchange outflow 수집을 건너뜁니다.",
            source="exchange_outflow",
        )
        frame = _empty_outflow_frame()
        frame.attrs["source"] = "glassnode_skipped"
        return frame

    raise NotImplementedError("Glassnode fetch_exchange_outflow 미구현")


def _fetch_coinmetrics(start_date: str, end_date: str) -> pd.DataFrame:
    """CoinMetrics Community API에서 BTC exchange netflow를 가져옵니다.

    API 키 불필요 (community tier), 단 rate limit 있음.
    """
    # TODO: 실제 API 호출 구현
    # from morning_brief.data.sources.http_client import get_json_with_retry
    # payload = get_json_with_retry(
    #     "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
    #     params={
    #         "assets": "btc",
    #         "metrics": "FlowInExNtv,FlowOutExNtv",
    #         "start_time": start_date,
    #         "end_time": end_date,
    #         "frequency": "1d",
    #     },
    #     provider="coinmetrics",
    # )
    raise NotImplementedError("CoinMetrics fetch_exchange_outflow 미구현")


__all__ = ["fetch_exchange_outflow"]
