from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import execute_with_provider_retry, policy_for
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_PATH = "/oauth2/tokenP"
CHARTPRICE_PATH = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
CHARTPRICE_TR_ID = "FHKST03030100"
USDKRW_ISCD = "FX@KRW"
TIMEOUT_SECONDS = 15


def _empty_close_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="object"),
            "close": pd.Series(dtype="float64"),
        }
    )


def _parse_float(value: object) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _kis_token(app_key: str, app_secret: str) -> str:
    def _request() -> requests.Response:
        return requests.post(
            KIS_BASE_URL + TOKEN_PATH,
            json={
                "grant_type": "client_credentials",
                "appkey": app_key,
                "appsecret": app_secret,
            },
            timeout=TIMEOUT_SECONDS,
        )

    response = execute_with_provider_retry(
        provider="kis",
        operation=_request,
        should_retry=lambda exc: True,
        max_attempts=3,
        base_backoff_seconds=1.0,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HttpFetchError("KIS token 응답을 JSON으로 읽지 못했어요.", provider="kis") from exc
    if response.status_code >= 400:
        raise HttpFetchError(
            f"KIS token 발급 실패: {response.status_code}",
            status_code=response.status_code,
            provider="kis",
            retryable=response.status_code in policy_for("kis").retryable_statuses,
        )
    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise HttpFetchError("KIS token 응답에 access_token이 없어요.", provider="kis")
    return token


def _kis_headers(token: str, app_key: str, app_secret: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "text/plain",
        "charset": "UTF-8",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": CHARTPRICE_TR_ID,
        "custtype": "P",
    }


def _kis_chartprice(app_key: str, app_secret: str, start_date: str, end_date: str) -> pd.DataFrame:
    token = _kis_token(app_key, app_secret)
    params = {
        "FID_COND_MRKT_DIV_CODE": "X",
        "FID_INPUT_ISCD": USDKRW_ISCD,
        "FID_INPUT_DATE_1": start_date.replace("-", ""),
        "FID_INPUT_DATE_2": end_date.replace("-", ""),
        "FID_PERIOD_DIV_CODE": "D",
    }

    def _request() -> requests.Response:
        return requests.get(
            KIS_BASE_URL + CHARTPRICE_PATH,
            params=params,
            headers=_kis_headers(token, app_key, app_secret),
            timeout=TIMEOUT_SECONDS,
        )

    response = execute_with_provider_retry(
        provider="kis",
        operation=_request,
        should_retry=lambda exc: True,
        max_attempts=3,
        base_backoff_seconds=1.0,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HttpFetchError("KIS 환율 응답을 JSON으로 읽지 못했어요.", provider="kis") from exc
    if response.status_code >= 400 or str(payload.get("rt_cd", "1")) != "0":
        raise HttpFetchError(
            f"KIS 환율 응답 실패: {payload.get('msg1', response.status_code)}",
            status_code=response.status_code,
            provider="kis",
            retryable=response.status_code in policy_for("kis").retryable_statuses,
        )

    rows = payload.get("output2")
    if not isinstance(rows, list) or not rows:
        raise HttpFetchError("KIS 환율 응답에 output2가 없어요.", provider="kis")

    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_raw = str(row.get("stck_bsop_date", "")).strip()
        if len(date_raw) != 8:
            continue
        price = _parse_float(row.get("ovrs_nmix_prpr"))
        if price is None or price <= 0:
            continue
        parsed_rows.append(
            {
                "date": f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}",
                "close": float(price),
            }
        )
    if not parsed_rows:
        raise HttpFetchError("KIS 환율 응답에서 유효한 값을 찾지 못했어요.", provider="kis")

    frame = pd.DataFrame(parsed_rows)
    return (
        frame.groupby("date", as_index=False)["close"]
        .last()
        .sort_values("date")
        .reset_index(drop=True)
    )


def _download_with_yfinance(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    end_exclusive = (datetime.fromisoformat(end_date) + timedelta(days=1)).date().isoformat()

    def _download() -> pd.DataFrame:
        history = yf.download(
            ticker,
            start=start_date,
            end=end_exclusive,
            auto_adjust=False,
            progress=False,
        )
        if history.empty:
            raise RuntimeError(f"{ticker} 이력 데이터가 비어 있어요.")
        return history

    history = execute_with_provider_retry(
        provider="yfinance",
        operation=_download,
        should_retry=lambda exc: True,
        max_attempts=3,
        base_backoff_seconds=1.0,
    )

    index = pd.to_datetime(history.index, utc=True)
    close_col = history["Close"]
    if isinstance(close_col, pd.DataFrame):
        close_col = close_col.iloc[:, 0]
    frame = pd.DataFrame(
        {
            "date": index.strftime("%Y-%m-%d"),
            "close": close_col.astype(float).tolist(),
        }
    )
    return (
        frame.groupby("date", as_index=False)["close"]
        .last()
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_usdkrw_close(
    start_date: str,
    end_date: str,
    kis_app_key: str,
    kis_app_secret: str,
) -> pd.DataFrame:
    if kis_app_key.strip() and kis_app_secret.strip():
        try:
            frame = _kis_chartprice(kis_app_key, kis_app_secret, start_date, end_date)
            frame.attrs["fallback_used"] = False
            return frame
        except Exception as exc:
            log_structured(
                logger,
                event="fallback.used",
                message="KIS 환율 수집에 실패해 yfinance로 전환합니다.",
                level=logging.WARNING,
                source="usdkrw",
                reason=str(exc),
            )
    else:
        log_structured(
            logger,
            event="fallback.used",
            message="KIS 인증 정보가 없어 yfinance로 전환합니다.",
            level=logging.WARNING,
            source="usdkrw",
            reason="missing_credentials",
        )

    try:
        frame = _download_with_yfinance("KRW=X", start_date, end_date)
        frame.attrs["fallback_used"] = True
        return frame
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="USD/KRW 환율 수집이 모두 실패했습니다.",
            level=logging.WARNING,
            source="usdkrw",
            reason=str(exc),
        )
        frame = _empty_close_frame()
        frame.attrs["fallback_used"] = True
        return frame


__all__ = ["fetch_usdkrw_close"]
