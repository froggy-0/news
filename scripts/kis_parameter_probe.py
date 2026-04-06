from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_PATH = "/oauth2/tokenP"
OVERSEAS_CHART_PATH = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
DOMESTIC_INDEX_PATH = "/uapi/domestic-stock/v1/quotations/inquire-index-price"
TIMEOUT_SECONDS = 15
MIN_INTERVAL_SECONDS = 0.7

FX_TARGETS = {
    "usdkrw": ["FX@KRW"],
    "jpykrw": ["FX@JPY"],
    "eurkrw": ["FX@EUR"],
    "cnykrw": ["FX@CNY"],
}

OVERSEAS_INDEX_TARGETS = {
    "dow30": [".DJI"],
    "sp500": [".SPX", ".INX"],
    "nasdaq100": [".NDX"],
    "nasdaq_composite": [".IXIC"],
    "dax": [".GDAXI", ".DAX"],
    "nikkei225": [".N225", ".NKY"],
}

BOND_NOTES = [
    "국채 3Y/10Y: 요구사항 범위에 있으나 concrete KIS code/path를 아직 공식 샘플에서 확정하지 못함",
]

COMMODITY_NOTES = [
    "원자재 WTI/Gold/Silver: 요구사항 범위에 있으나 concrete KIS code(SRS_CD 등)를 아직 공식 샘플에서 확정하지 못함",
]

_LAST_REQUEST_AT = 0.0


@dataclass
class ProbeResult:
    target: str
    candidate: str
    status: str
    value: float | None
    source: str
    message: str
    output2_len: int | None = None


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _extract_message(payload: dict[str, Any], fallback: object = "") -> str:
    for key in ("msg1", "message", "error_description", "msg_cd", "error_code"):
        value = str(payload.get(key, "")).strip()
        if value:
            return value
    return str(fallback)


def _request_slot() -> None:
    global _LAST_REQUEST_AT
    now = time.monotonic()
    remaining = MIN_INTERVAL_SECONDS - (now - _LAST_REQUEST_AT)
    if remaining > 0:
        time.sleep(remaining)
    _LAST_REQUEST_AT = time.monotonic()


def _parse_float(raw: object) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _token() -> str:
    app_key = _require_env("KIS_APP_KEY")
    app_secret = _require_env("KIS_APP_SECRET")
    response = requests.post(
        KIS_BASE_URL + TOKEN_PATH,
        data=json.dumps(
            {
                "grant_type": "client_credentials",
                "appkey": app_key,
                "appsecret": app_secret,
            }
        ),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/plain",
            "charset": "UTF-8",
        },
        timeout=TIMEOUT_SECONDS,
    )
    payload = response.json()
    print(f"[token] status={response.status_code} message={_extract_message(payload)}")
    if response.status_code >= 400:
        raise SystemExit("token failed")
    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise SystemExit("token missing access_token")
    return token


def _headers(token: str, tr_id: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "text/plain",
        "charset": "UTF-8",
        "Authorization": f"Bearer {token}",
        "appkey": _require_env("KIS_APP_KEY"),
        "appsecret": _require_env("KIS_APP_SECRET"),
        "tr_id": tr_id,
        "custtype": "P",
        "tr_cont": "",
    }


def _get(path: str, params: dict[str, str], headers: dict[str, str], label: str) -> dict[str, Any]:
    for attempt in range(1, 4):
        _request_slot()
        response = requests.get(
            KIS_BASE_URL + path,
            params=params,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
        payload = response.json()
        summary = {
            "status": response.status_code,
            "rt_cd": payload.get("rt_cd"),
            "message": _extract_message(payload),
        }
        print(f"[{label}] attempt={attempt} {summary}")
        text = json.dumps(payload, ensure_ascii=False)[:500]
        print(f"[{label}] body={text}")

        if response.status_code == 500 and "EGW00201" in text and attempt < 3:
            print(f"[{label}] rate-limited, backing off before retry")
            time.sleep(2.0)
            continue
        return payload
    return {}


def _latest_chart_value(payload: dict[str, Any]) -> tuple[float | None, str]:
    output1 = payload.get("output1")
    if isinstance(output1, dict):
        value = _parse_float(output1.get("ovrs_nmix_prpr"))
        if value is not None:
            return value, "output1"

    output2 = payload.get("output2")
    if isinstance(output2, list):
        for row in output2:
            if not isinstance(row, dict):
                continue
            value = _parse_float(row.get("ovrs_nmix_prpr"))
            if value is not None:
                return value, "output2"
    return None, "missing"


def _classify_chart_payload(target: str, candidate: str, payload: dict[str, Any]) -> ProbeResult:
    output2 = payload.get("output2")
    output2_len = len(output2) if isinstance(output2, list) else None
    message = _extract_message(payload)
    if str(payload.get("rt_cd")) != "0":
        return ProbeResult(
            target=target,
            candidate=candidate,
            status="api_error",
            value=None,
            source="missing",
            message=message,
            output2_len=output2_len,
        )

    value, source = _latest_chart_value(payload)
    if value is None:
        return ProbeResult(
            target=target,
            candidate=candidate,
            status="missing",
            value=None,
            source=source,
            message=message,
            output2_len=output2_len,
        )

    if value <= 0:
        return ProbeResult(
            target=target,
            candidate=candidate,
            status="zero_payload",
            value=value,
            source=source,
            message=message,
            output2_len=output2_len,
        )

    return ProbeResult(
        target=target,
        candidate=candidate,
        status="usable",
        value=value,
        source=source,
        message=message,
        output2_len=output2_len,
    )


def _probe_chart_candidates(
    *,
    token: str,
    target: str,
    market_div: str,
    candidates: list[str],
) -> list[ProbeResult]:
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=14)
    results: list[ProbeResult] = []
    for candidate in candidates:
        payload = _get(
            OVERSEAS_CHART_PATH,
            {
                "FID_COND_MRKT_DIV_CODE": market_div,
                "FID_INPUT_ISCD": candidate,
                "FID_INPUT_DATE_1": "" if market_div == "X" else start_date.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": "" if market_div == "X" else end_date.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
            },
            _headers(token, "FHKST03030100"),
            f"{target}:{candidate}",
        )
        result = _classify_chart_payload(target, candidate, payload)
        print(
            f"[{target}] candidate={candidate} status={result.status} "
            f"value={result.value} source={result.source} output2_len={result.output2_len}"
        )
        results.append(result)
    return results


def _probe_domestic_index(token: str, label: str, code: str) -> ProbeResult:
    payload = _get(
        DOMESTIC_INDEX_PATH,
        {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": code,
        },
        _headers(token, "FHPUP02100000"),
        label,
    )
    output = payload.get("output")
    price = None
    if isinstance(output, dict):
        for field in ("bstp_nmix_prpr", "stck_prpr", "ovrs_nmix_prpr"):
            price = _parse_float(output.get(field))
            if price is not None:
                break
    status = "usable" if price and price > 0 else "missing"
    print(f"[{label}] code={code} status={status} value={price}")
    return ProbeResult(
        target=label,
        candidate=code,
        status=status,
        value=price,
        source="output",
        message=_extract_message(payload),
    )


def _print_summary(title: str, results: list[ProbeResult]) -> None:
    print(f"\n=== {title} ===")
    for result in results:
        print(
            f"- {result.target} / {result.candidate}: {result.status} "
            f"value={result.value} source={result.source} msg={result.message}"
        )


def main() -> None:
    token = _token()
    fx_results: list[ProbeResult] = []
    for target, candidates in FX_TARGETS.items():
        fx_results.extend(
            _probe_chart_candidates(
                token=token, target=target, market_div="X", candidates=candidates
            )
        )

    index_results: list[ProbeResult] = []
    for target, candidates in OVERSEAS_INDEX_TARGETS.items():
        index_results.extend(
            _probe_chart_candidates(
                token=token, target=target, market_div="N", candidates=candidates
            )
        )

    domestic_results = [
        _probe_domestic_index(token, "kospi", "0001"),
        _probe_domestic_index(token, "kosdaq", "1001"),
    ]

    _print_summary("FX Summary", fx_results)
    _print_summary("Overseas Index Summary", index_results)
    _print_summary("Domestic Index Summary", domestic_results)

    print("\n=== Manual Follow-up ===")
    for note in BOND_NOTES:
        print(f"- {note}")
    for note in COMMODITY_NOTES:
        print(f"- {note}")


if __name__ == "__main__":
    main()
