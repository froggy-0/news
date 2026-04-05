from __future__ import annotations

import logging
from typing import Any

import requests

from morning_brief.config import load_settings
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import execute_with_provider_retry, policy_for
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
_TOKEN_PATH = "/oauth2/tokenP"
_QUOTE_PATH = "/uapi/overseas-price/v1/quotations/price"
_USDKRW_PATH = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
_QUOTE_TR_ID = "HHDFS00000300"
_USDKRW_TR_ID = "FHKST03030100"
_USDKRW_ISCD = "FX@KRW"
_TIMEOUT_SECONDS = 15
_TOKEN: str | None = None

_EXCD_MAP: dict[str, str] = {
    "SPY": "AMS",
    "QQQ": "NAS",
    "SOXX": "NAS",
    "NVDA": "NAS",
    "MSFT": "NAS",
    "AAPL": "NAS",
    "AMZN": "NAS",
    "GOOGL": "NAS",
    "META": "NAS",
    "AMD": "NAS",
    "TSM": "NYS",
    "ASML": "NAS",
    "AVGO": "NAS",
    "IBIT": "NAS",
    "FBTC": "AMS",
    "ARKB": "AMS",
    "BITB": "AMS",
    "GBTC": "AMS",
}


class _KisRateLimitError(HttpFetchError):
    def __init__(self) -> None:
        super().__init__(
            "KIS 초당 거래건수를 초과했어요 (EGW00201)",
            provider="kis",
            retryable=True,
            rate_limited=True,
        )


def _credentials() -> tuple[str, str]:
    settings = load_settings()
    return settings.kis_app_key, settings.kis_app_secret


def is_available() -> bool:
    app_key, app_secret = _credentials()
    return bool(app_key and app_secret)


def _get_token(app_key: str, app_secret: str) -> str:
    try:
        response = requests.post(
            KIS_BASE_URL + _TOKEN_PATH,
            json={
                "grant_type": "client_credentials",
                "appkey": app_key,
                "appsecret": app_secret,
            },
            headers={"Content-Type": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HttpFetchError(
            "KIS access token을 발급하지 못했어요.",
            provider="kis",
            retryable=True,
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HttpFetchError("KIS token 응답을 JSON으로 읽지 못했어요.", provider="kis") from exc

    if response.status_code >= 400:
        raise HttpFetchError(
            f"KIS token 발급 실패: {payload.get('msg1') or payload.get('message') or response.status_code}",
            status_code=response.status_code,
            provider="kis",
            retryable=response.status_code in policy_for("kis").retryable_statuses,
            rate_limited=response.status_code == 429,
        )

    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise HttpFetchError("KIS token 응답에 access_token이 없어요.", provider="kis")
    return token


def _ensure_token() -> str:
    global _TOKEN
    if _TOKEN is not None:
        return _TOKEN

    app_key, app_secret = _credentials()
    if not app_key or not app_secret:
        raise HttpFetchError("KIS 인증 정보가 없어 token을 발급할 수 없어요.", provider="kis")

    _TOKEN = _get_token(app_key, app_secret)
    return _TOKEN


def _build_headers(token: str, *, tr_id: str) -> dict[str, str]:
    app_key, app_secret = _credentials()
    return {
        "Content-Type": "application/json",
        "Accept": "text/plain",
        "charset": "UTF-8",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "tr_cont": "",
    }


def _kis_get(path: str, params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.get(
            KIS_BASE_URL + path,
            params=params,
            headers=headers,
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HttpFetchError(
            f"KIS GET 요청에 실패했어요: {path}",
            provider="kis",
            retryable=True,
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HttpFetchError(f"KIS 응답을 JSON으로 읽지 못했어요: {path}", provider="kis") from exc

    if response.status_code == 500:
        if payload.get("message") == "EGW00201":
            raise _KisRateLimitError()
        raise HttpFetchError(
            f"KIS HTTP 500: {payload.get('msg1') or payload.get('message') or path}",
            status_code=500,
            provider="kis",
            retryable=True,
        )

    if response.status_code >= 400:
        raise HttpFetchError(
            f"KIS HTTP {response.status_code}: {payload.get('msg1') or payload.get('message') or path}",
            status_code=response.status_code,
            provider="kis",
            retryable=response.status_code in policy_for("kis").retryable_statuses,
            rate_limited=response.status_code == 429,
        )

    if not isinstance(payload, dict):
        raise HttpFetchError(f"KIS 응답 구조가 예상과 달라요: {path}", provider="kis")
    return payload


def _log_retry(
    exc: Exception,
    attempt: int,
    max_attempts: int,
    delay: float,
    *,
    target: str,
) -> None:
    log_structured(
        logger,
        event="provider.retry",
        message="KIS 데이터를 다시 가져오는 중이에요.",
        level=logging.WARNING,
        provider="kis",
        attempt=attempt,
        max_attempts=max_attempts,
        ticker=target,
        reason=str(exc),
        retryable=True,
        delay_seconds=delay,
    )


def _parse_float(raw: object) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_int(raw: object) -> int:
    value = _parse_float(raw)
    if value is None:
        return 0
    return int(value)


def fetch_close_change_and_volume(ticker: str) -> tuple[float, float, int]:
    normalized_ticker = ticker.strip().upper()
    excd = _EXCD_MAP.get(normalized_ticker)
    if not excd:
        raise HttpFetchError(f"KIS EXCD 매핑 없음: {ticker}", provider="kis")

    token = _ensure_token()
    headers = _build_headers(token, tr_id=_QUOTE_TR_ID)
    params = {"AUTH": "", "EXCD": excd, "SYMB": normalized_ticker}

    data = execute_with_provider_retry(
        provider="kis",
        operation=lambda: _kis_get(_QUOTE_PATH, params, headers),
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=lambda exc, attempt, max_attempts, delay: _log_retry(
            exc,
            attempt,
            max_attempts,
            delay,
            target=normalized_ticker,
        ),
    )

    rt_cd = str(data.get("rt_cd", "1"))
    output = data.get("output")
    if not isinstance(output, dict):
        raise HttpFetchError(f"KIS 응답에 output이 없어요: {normalized_ticker}", provider="kis")

    last = str(output.get("last", "")).strip()
    if rt_cd != "0" or not last or last == "0":
        raise HttpFetchError(
            f"KIS 유효 데이터 없음: {normalized_ticker} rt_cd={rt_cd} last={last!r}",
            provider="kis",
        )

    close = _parse_float(last)
    base = _parse_float(output.get("base"))
    if close is None:
        raise HttpFetchError(f"KIS 현재가를 읽지 못했어요: {normalized_ticker}", provider="kis")

    change_pct = 0.0 if not base else ((close - base) / base) * 100
    volume = _parse_int(output.get("tvol"))
    return round(close, 4), round(change_pct, 2), volume


def _rate_from_output1(output1: dict[str, Any]) -> tuple[float, float] | None:
    current = _parse_float(output1.get("ovrs_nmix_prpr"))
    if current is None:
        return None

    change_pct = _parse_float(output1.get("prdy_ctrt"))
    if change_pct is not None:
        return round(current, 4), round(change_pct, 2)

    previous = _parse_float(output1.get("ovrs_nmix_prdy_clpr"))
    if not previous:
        return round(current, 4), 0.0

    return round(current, 4), round(((current - previous) / previous) * 100, 2)


def _rate_from_output2(output2: list[Any]) -> tuple[float, float] | None:
    rows: list[dict[str, Any]] = [row for row in output2 if isinstance(row, dict)]
    valid_rows = [row for row in rows if _parse_float(row.get("ovrs_nmix_prpr")) is not None]
    if not valid_rows:
        return None

    latest = valid_rows[0]
    current = _parse_float(latest.get("ovrs_nmix_prpr"))
    if current is None:
        return None

    if len(valid_rows) >= 2:
        previous = _parse_float(valid_rows[1].get("ovrs_nmix_prpr"))
        if previous:
            return round(current, 4), round(((current - previous) / previous) * 100, 2)

    change_pct = _parse_float(latest.get("prdy_ctrt"))
    if change_pct is not None:
        return round(current, 4), round(change_pct, 2)

    return round(current, 4), 0.0


def fetch_usdkrw_point() -> tuple[float, float]:
    token = _ensure_token()
    headers = _build_headers(token, tr_id=_USDKRW_TR_ID)
    params = {
        "FID_COND_MRKT_DIV_CODE": "X",
        "FID_INPUT_ISCD": _USDKRW_ISCD,
        "FID_INPUT_DATE_1": "",
        "FID_INPUT_DATE_2": "",
        "FID_PERIOD_DIV_CODE": "D",
    }

    data = execute_with_provider_retry(
        provider="kis",
        operation=lambda: _kis_get(_USDKRW_PATH, params, headers),
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=lambda exc, attempt, max_attempts, delay: _log_retry(
            exc,
            attempt,
            max_attempts,
            delay,
            target="usdkrw",
        ),
    )

    if str(data.get("rt_cd", "1")) != "0":
        raise HttpFetchError(
            f"KIS USD/KRW 응답 실패: {data.get('msg1') or data.get('message') or data.get('rt_cd')}",
            provider="kis",
        )

    output1 = data.get("output1")
    if isinstance(output1, dict):
        rate = _rate_from_output1(output1)
        if rate is not None:
            return rate

    output2 = data.get("output2")
    if isinstance(output2, list):
        rate = _rate_from_output2(output2)
        if rate is not None:
            return rate

    raise HttpFetchError("KIS USD/KRW 응답에서 유효 값을 찾지 못했어요.", provider="kis")


__all__ = [
    "HttpFetchError",
    "fetch_close_change_and_volume",
    "fetch_usdkrw_point",
    "is_available",
]
