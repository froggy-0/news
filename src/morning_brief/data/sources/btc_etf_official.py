from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from perplexity import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    Perplexity,
    RateLimitError,
)

from morning_brief.data.sources.domain_utils import domain_matches, normalize_domain
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import (
    disabled_reason,
    execute_with_provider_retry,
    open_circuit,
    parse_retry_after_seconds,
    policy_for,
    record_skip,
)
from morning_brief.models import BitcoinEtfIssuerSnapshot
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

IBIT_URL = "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf"
BITB_URL = "https://bitbetf.com/"
GBTC_URL = "https://etfs.grayscale.com/gbtc"
IBIT_CREATION_BASKET_SHARES = 40_000
PERPLEXITY_PROVIDER = "perplexity"
BTC_ETF_REFERENCE_MODEL = "sonar"
BTC_ETF_REFERENCE_DOMAINS = (
    "ishares.com",
    "bitbetf.com",
    "etfs.grayscale.com",
)
BTC_ETF_REFERENCE_PROMPT = """
Return only JSON with this exact schema:
{
  "snapshots": [
    {
      "ticker": "IBIT",
      "issuer": "iShares",
      "source_url": "https://...",
      "as_of": "MM/DD/YYYY",
      "shares_outstanding": 0,
      "daily_volume": 0,
      "aum_usd": 0,
      "total_btc": 0,
      "bitcoin_per_share": 0
    }
  ]
}

Task:
- Find the latest available official spot Bitcoin ETF issuer data for IBIT, BITB, and GBTC.
- Use only official issuer domains.
- Include an item only if you can provide all numeric fields and a direct official source URL.
- Prefer the most recent daily snapshot available as of {today}.
- Do not include commentary, markdown, or citations outside the JSON.
""".strip()

DATE_RE = r"(?:[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}|\d{2}/\d{2}/\d{4})"
VALUE_RE = r"\$?[\d,]+(?:\.\d+)?(?:[MB])?"
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>\s*(?P<payload>\{.*?\})\s*</script>',
    flags=re.DOTALL | re.IGNORECASE,
)
JSON_CODE_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(?P<payload>\{.*?\})\s*```",
    flags=re.DOTALL | re.IGNORECASE,
)
RESPONSE_PREVIEW_LEN = 200


def _normalize_page_text(text: str) -> str:
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _parse_compact_number(raw: str) -> float:
    normalized = raw.strip().replace("$", "").replace(",", "")
    multiplier = 1.0
    if normalized.endswith("B"):
        multiplier = 1_000_000_000.0
        normalized = normalized[:-1]
    elif normalized.endswith("M"):
        multiplier = 1_000_000.0
        normalized = normalized[:-1]
    return float(normalized) * multiplier


def _extract_value(text: str, label: str) -> float:
    match = re.search(rf"{re.escape(label)}\*?\s+(?P<value>{VALUE_RE})", text, flags=re.IGNORECASE)
    if not match:
        raise HttpFetchError(f"공식 ETF 페이지에서 '{label}' 값을 찾지 못했어요.")
    return _parse_compact_number(match.group("value"))


def _extract_first_matching_value(text: str, labels: list[str]) -> float:
    last_error: Exception | None = None
    for label in labels:
        try:
            return _extract_value(text, label)
        except Exception as exc:
            last_error = exc
    raise HttpFetchError("공식 ETF 페이지에서 값을 찾지 못했어요.") from last_error


def _extract_dated_value(text: str, label: str) -> tuple[str, float]:
    match = re.search(
        rf"{re.escape(label)}\s+as of\s+(?P<date>{DATE_RE})\s+(?P<value>{VALUE_RE})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise HttpFetchError(f"공식 ETF 페이지에서 날짜가 포함된 '{label}' 값을 찾지 못했어요.")
    return match.group("date"), _parse_compact_number(match.group("value"))


def _extract_page_date(text: str) -> str:
    match = re.search(rf"(?:Data|data)\s+as\s+of\s+(?P<date>{DATE_RE})", text)
    if not match:
        raise HttpFetchError("공식 ETF 페이지에서 기준일을 찾지 못했어요.")
    return match.group("date")


def _extract_next_data_payload(text: str) -> dict:
    match = NEXT_DATA_RE.search(text)
    if not match:
        raise HttpFetchError("Bitwise 페이지에서 __NEXT_DATA__를 찾지 못했어요.")

    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError as exc:
        raise HttpFetchError("Bitwise 페이지의 __NEXT_DATA__ JSON을 읽지 못했어요.") from exc

    if not isinstance(payload, dict):
        raise HttpFetchError("Bitwise 페이지의 __NEXT_DATA__ 구조가 예상과 달라요.")
    return payload


def _find_first_key(payload: object, key: str) -> object | None:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = _find_first_key(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_first_key(item, key)
            if found is not None:
                return found
    return None


def _extract_bitb_structured_values(text: str) -> tuple[str, float, float, int, int]:
    payload = _extract_next_data_payload(text)
    as_of_raw = _find_first_key(payload, "timestamp")
    total_btc_raw = _find_first_key(payload, "totalReserve")
    aum_usd_raw = _find_first_key(payload, "netAssets")
    shares_outstanding_raw = _find_first_key(payload, "sharesOutstanding")
    daily_volume_raw = _find_first_key(payload, "volume")

    if not all(
        value is not None
        for value in [total_btc_raw, aum_usd_raw, shares_outstanding_raw, daily_volume_raw]
    ):
        raise HttpFetchError("Bitwise 페이지의 구조화 데이터가 충분하지 않아요.")

    as_of = _extract_page_date(_normalize_page_text(text))
    if isinstance(as_of_raw, str) and as_of_raw.strip():
        try:
            as_of = datetime.fromisoformat(as_of_raw.replace("Z", "+00:00")).strftime("%m/%d/%Y")
        except ValueError:
            as_of = as_of_raw[:10].replace("-", "/")

    return (
        as_of,
        float(_parse_numeric(total_btc_raw)),
        float(_parse_numeric(aum_usd_raw)),
        int(_parse_numeric(shares_outstanding_raw, integer=True)),
        int(_parse_numeric(daily_volume_raw, integer=True)),
    )


def parse_ibit_snapshot(text: str) -> BitcoinEtfIssuerSnapshot:
    normalized = _normalize_page_text(text)
    as_of, aum_usd = _extract_dated_value(normalized, "Net Assets of Fund")
    _, shares_outstanding = _extract_dated_value(normalized, "Shares Outstanding")
    _, daily_volume = _extract_dated_value(normalized, "Daily Volume")
    _, basket_bitcoin_amount = _extract_dated_value(normalized, "Basket Bitcoin Amount")
    bitcoin_per_share = basket_bitcoin_amount / IBIT_CREATION_BASKET_SHARES
    total_btc = bitcoin_per_share * shares_outstanding
    return BitcoinEtfIssuerSnapshot(
        ticker="IBIT",
        issuer="iShares",
        source_url=IBIT_URL,
        as_of=as_of,
        shares_outstanding=int(round(shares_outstanding)),
        daily_volume=int(round(daily_volume)),
        aum_usd=round(aum_usd, 2),
        total_btc=round(total_btc, 8),
        bitcoin_per_share=round(bitcoin_per_share, 10),
    )


def parse_bitb_snapshot(text: str) -> BitcoinEtfIssuerSnapshot:
    normalized = _normalize_page_text(text)
    try:
        as_of, total_btc, aum_usd, shares_outstanding, daily_volume = (
            _extract_bitb_structured_values(text)
        )
        bitcoin_per_share = total_btc / shares_outstanding
    except HttpFetchError:
        as_of = _extract_page_date(normalized)
        aum_usd = _extract_first_matching_value(normalized, ["Net Assets (AUM)", "Net Assets"])
        shares_outstanding = int(round(_extract_value(normalized, "Shares Outstanding")))
        daily_volume = int(
            round(
                _extract_first_matching_value(normalized, ["Daily Volume (Shares)", "Daily Volume"])
            )
        )
        total_btc = _extract_value(normalized, "Bitcoin in Trust")
        bitcoin_per_share = _extract_value(normalized, "Bitcoin per Share")
    return BitcoinEtfIssuerSnapshot(
        ticker="BITB",
        issuer="Bitwise",
        source_url=BITB_URL,
        as_of=as_of,
        shares_outstanding=int(round(shares_outstanding)),
        daily_volume=int(round(daily_volume)),
        aum_usd=round(aum_usd, 2),
        total_btc=round(total_btc, 8),
        bitcoin_per_share=round(bitcoin_per_share, 10),
    )


def parse_gbtc_snapshot(text: str) -> BitcoinEtfIssuerSnapshot:
    normalized = _normalize_page_text(text)
    as_of = _extract_page_date(normalized)
    aum_usd = _extract_value(normalized, "ASSETS UNDER MANAGEMENT")
    shares_outstanding = _extract_value(normalized, "SHARES OUTSTANDING")
    daily_volume = _extract_value(normalized, "DAILY VOLUME (SHARES)")
    total_btc = _extract_value(normalized, "TOTAL BITCOIN IN TRUST")
    bitcoin_per_share = _extract_value(normalized, "BITCOIN PER SHARE")
    return BitcoinEtfIssuerSnapshot(
        ticker="GBTC",
        issuer="Grayscale",
        source_url=GBTC_URL,
        as_of=as_of,
        shares_outstanding=int(round(shares_outstanding)),
        daily_volume=int(round(daily_volume)),
        aum_usd=round(aum_usd, 2),
        total_btc=round(total_btc, 8),
        bitcoin_per_share=round(bitcoin_per_share, 10),
    )


def _build_client(api_key: str) -> Perplexity:
    return Perplexity(api_key=api_key, timeout=25, max_retries=1)


def _format_status_error(exc: APIStatusError) -> str:
    status_code = getattr(exc, "status_code", "unknown")
    response = getattr(exc, "response", None)
    detail = ""
    if response is not None:
        try:
            detail = str(response.text).strip()
        except Exception:
            detail = ""
    if detail:
        detail = " ".join(detail.split())[:240]
        return f"status={status_code}, detail={detail}"
    return f"status={status_code}"


def _retry_after_seconds_from_exception(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        return parse_retry_after_seconds(headers.get("Retry-After") or headers.get("retry-after"))
    return None


def _to_http_fetch_error(exc: Exception) -> HttpFetchError:
    if isinstance(exc, RateLimitError):
        message = f"Perplexity ETF 참조 요청 한도에 걸렸어요: {_format_status_error(exc)}"
        open_circuit(PERPLEXITY_PROVIDER, message)
        return HttpFetchError(
            message,
            provider=PERPLEXITY_PROVIDER,
            retryable=False,
            rate_limited=True,
            retry_after_seconds=_retry_after_seconds_from_exception(exc),
        )

    if isinstance(exc, APITimeoutError):
        return HttpFetchError(
            "Perplexity ETF 참조 응답 시간이 너무 오래 걸렸어요.",
            provider=PERPLEXITY_PROVIDER,
            retryable=True,
        )

    if isinstance(exc, APIConnectionError):
        return HttpFetchError(
            "Perplexity ETF 참조 연결을 열지 못했어요.",
            provider=PERPLEXITY_PROVIDER,
            retryable=True,
        )

    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", None)
        retry_after_seconds = _retry_after_seconds_from_exception(exc)
        if status_code == 429:
            message = f"Perplexity ETF 참조 요청 한도에 걸렸어요: {_format_status_error(exc)}"
            open_circuit(PERPLEXITY_PROVIDER, message)
            return HttpFetchError(
                message,
                provider=PERPLEXITY_PROVIDER,
                retryable=False,
                rate_limited=True,
                retry_after_seconds=retry_after_seconds,
            )
        return HttpFetchError(
            f"Perplexity ETF 참조 요청이 거절됐어요: {_format_status_error(exc)}",
            provider=PERPLEXITY_PROVIDER,
            retryable=status_code in policy_for(PERPLEXITY_PROVIDER).retryable_statuses,
            retry_after_seconds=retry_after_seconds,
        )

    return HttpFetchError(
        f"Perplexity ETF 참조 데이터를 가져오지 못했어요: {exc}",
        provider=PERPLEXITY_PROVIDER,
        retryable=False,
    )


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    choice_text = _extract_choice_message_text(payload.get("choices"))
    if choice_text:
        return choice_text

    raise HttpFetchError("Perplexity ETF 참조 응답에서 JSON 본문을 찾지 못했어요.")


def _extract_choice_message_text(choices: object) -> str:
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts = [
        text
        for item in content
        if isinstance(item, dict)
        for text in [str(item.get("text", "")).strip()]
        if text
    ]
    return "\n".join(parts)


def _decode_reference_snapshot_json(text: str) -> dict[str, Any]:
    stripped = text.strip().lstrip("\ufeff")
    if not stripped:
        raise HttpFetchError("Perplexity ETF 참조 응답에서 JSON 본문을 찾지 못했어요.")

    seen: set[str] = set()
    pending_candidates = _json_candidate_strings(stripped)
    while pending_candidates:
        candidate = pending_candidates.pop(0)
        normalized_candidate = candidate.strip()
        if not normalized_candidate or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        try:
            decoded = json.loads(normalized_candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, str):
            _append_nested_json_candidates(decoded, pending_candidates, seen)
            continue
        found = _find_snapshot_payload(decoded)
        if found is not None:
            return found

    raise HttpFetchError(
        f"Perplexity ETF 참조 JSON을 읽지 못했어요. preview={_response_preview(stripped)}"
    )


def _json_candidate_strings(text: str) -> list[str]:
    candidates: list[str] = []
    code_block_match = JSON_CODE_BLOCK_RE.search(text)
    if code_block_match:
        candidates.append(code_block_match.group("payload").strip())

    candidates.append(text)

    snapshot_member_candidate = _snapshot_member_candidate(text)
    if snapshot_member_candidate:
        candidates.append(snapshot_member_candidate)

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())

    return candidates


def _snapshot_member_candidate(text: str) -> str | None:
    snapshot_member_index = text.find('"snapshots"')
    if snapshot_member_index == -1:
        return None
    member_payload = text[snapshot_member_index:].strip().strip(",")
    return f"{{{member_payload}}}"


def _append_nested_json_candidates(
    decoded: str,
    pending_candidates: list[str],
    seen: set[str],
) -> None:
    nested = decoded.strip()
    if not nested or nested in seen:
        return
    pending_candidates.append(nested)
    snapshot_member_candidate = _snapshot_member_candidate(nested)
    if snapshot_member_candidate:
        pending_candidates.append(snapshot_member_candidate)


def _is_snapshot_payload(decoded: object) -> bool:
    return isinstance(decoded, dict) and (
        "snapshots" in decoded
        or {"ticker", "source_url", "shares_outstanding", "total_btc"} <= decoded.keys()
    )


def _find_snapshot_payload(decoded: object) -> dict[str, Any] | None:
    if _is_snapshot_payload(decoded):
        assert isinstance(decoded, dict)
        return decoded
    if isinstance(decoded, dict):
        for value in decoded.values():
            found = _find_snapshot_payload(value)
            if found is not None:
                return found
    if isinstance(decoded, list):
        for value in decoded:
            found = _find_snapshot_payload(value)
            if found is not None:
                return found
    return None


def _response_preview(text: str) -> str:
    preview = " ".join(str(text or "").split())
    if len(preview) <= RESPONSE_PREVIEW_LEN:
        return preview
    return f"{preview[:RESPONSE_PREVIEW_LEN]}..."


def _parse_numeric(value: object, *, integer: bool = False) -> int | float:
    if isinstance(value, (int, float)):
        return int(value) if integer else float(value)

    normalized = str(value or "").strip().replace(",", "").replace("$", "")
    if not normalized:
        raise ValueError("값이 비어 있어요.")
    numeric = float(normalized)
    return int(round(numeric)) if integer else numeric


def _is_allowed_official_url(url: str) -> bool:
    domain = normalize_domain(url)
    return any(domain_matches(domain, candidate) for candidate in BTC_ETF_REFERENCE_DOMAINS)


def _snapshot_from_item(item: dict[str, Any]) -> BitcoinEtfIssuerSnapshot:
    ticker = str(item.get("ticker", "")).strip().upper()
    source_url = str(item.get("source_url", "")).strip()
    as_of = str(item.get("as_of", "")).strip()
    issuer = str(item.get("issuer", "")).strip() or ticker
    if not ticker or not source_url or not as_of or not _is_allowed_official_url(source_url):
        raise ValueError("필수 ETF 참조 필드가 없거나 공식 도메인이 아니에요.")

    shares_outstanding = int(_parse_numeric(item.get("shares_outstanding"), integer=True))
    daily_volume = int(_parse_numeric(item.get("daily_volume"), integer=True))
    aum_usd = float(_parse_numeric(item.get("aum_usd")))
    total_btc = float(_parse_numeric(item.get("total_btc")))
    bitcoin_per_share_raw = item.get("bitcoin_per_share")
    if bitcoin_per_share_raw in (None, ""):
        bitcoin_per_share = total_btc / shares_outstanding
    else:
        bitcoin_per_share = float(_parse_numeric(bitcoin_per_share_raw))

    if shares_outstanding <= 0 or daily_volume < 0 or aum_usd <= 0 or total_btc <= 0:
        raise ValueError("ETF 참조 수치가 유효 범위를 벗어나요.")

    return BitcoinEtfIssuerSnapshot(
        ticker=ticker,
        issuer=issuer,
        source_url=source_url,
        as_of=as_of,
        shares_outstanding=shares_outstanding,
        daily_volume=daily_volume,
        aum_usd=round(aum_usd, 2),
        total_btc=round(total_btc, 8),
        bitcoin_per_share=round(bitcoin_per_share, 10),
    )


def _parse_reference_snapshot_response(payload: dict[str, Any]) -> list[BitcoinEtfIssuerSnapshot]:
    text = _extract_response_text(payload)
    decoded = _decode_reference_snapshot_json(text)
    if not isinstance(decoded, dict):
        raise HttpFetchError("Perplexity ETF 참조 JSON 구조가 예상과 달라요.")

    if (
        "snapshots" not in decoded
        and {
            "ticker",
            "source_url",
            "shares_outstanding",
            "total_btc",
        }
        <= decoded.keys()
    ):
        decoded = {"snapshots": [decoded]}

    raw_snapshots = decoded.get("snapshots", [])
    if not isinstance(raw_snapshots, list):
        raise HttpFetchError("Perplexity ETF 참조 JSON에 snapshots 배열이 없어요.")

    snapshots: list[BitcoinEtfIssuerSnapshot] = []
    for raw_item in raw_snapshots:
        if not isinstance(raw_item, dict):
            continue
        try:
            snapshots.append(_snapshot_from_item(raw_item))
        except ValueError as exc:
            logger.warning("Perplexity ETF 참조 항목을 건너뛸게요: %s", exc)

    snapshots.sort(key=lambda item: item.ticker)
    return snapshots


def _request_reference_snapshots(
    api_key: str,
    *,
    observer: PipelineObserver | None = None,
) -> list[BitcoinEtfIssuerSnapshot]:
    if not api_key:
        logger.info("Perplexity API 키가 없어 BTC ETF 참조 스냅샷은 건너뛸게요.")
        return []

    unavailable_reason = disabled_reason(PERPLEXITY_PROVIDER)
    if unavailable_reason:
        record_skip(PERPLEXITY_PROVIDER)
        raise HttpFetchError(
            f"Perplexity는 이번 실행에서 더 이상 쓰지 않을게요: {unavailable_reason}"
        )

    client = _build_client(api_key)
    if observer is not None:
        observer.record_provider_usage(PERPLEXITY_PROVIDER, requests=1)

    def request_once() -> list[BitcoinEtfIssuerSnapshot]:
        try:
            response = client.chat.completions.create(
                model=BTC_ETF_REFERENCE_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You normalize financial reference data into strict JSON.",
                    },
                    {
                        "role": "user",
                        "content": BTC_ETF_REFERENCE_PROMPT.format(today=date.today().isoformat()),
                    },
                ],
                search_domain_filter=list(BTC_ETF_REFERENCE_DOMAINS),
                search_recency_filter="month",
                search_mode="web",
                country="US",
                temperature=0.0,
                max_tokens=900,
                response_format={"type": "json_object"},
            )
        except (RateLimitError, APITimeoutError, APIConnectionError, APIStatusError) as exc:
            raise _to_http_fetch_error(exc) from exc

        try:
            payload = response.model_dump()
        except AttributeError:
            if isinstance(response, dict):
                payload = response
            else:
                raise HttpFetchError("Perplexity ETF 참조 응답 구조가 예상과 달라요.")

        if not isinstance(payload, dict):
            raise HttpFetchError("Perplexity ETF 참조 응답 구조가 예상과 달라요.")

        return _parse_reference_snapshot_response(payload)

    snapshots = execute_with_provider_retry(
        provider=PERPLEXITY_PROVIDER,
        operation=request_once,
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=lambda exc, attempt, max_attempts, delay: logger.warning(
            "Perplexity ETF 참조 데이터를 다시 시도하는 중이에요 (%s/%s). %s | sleep=%.2fs",
            attempt,
            max_attempts,
            exc,
            delay,
        ),
        retry_after_seconds_for_error=lambda exc: exc.retry_after_seconds
        if isinstance(exc, HttpFetchError)
        else None,
    )
    if observer is not None:
        observer.record_provider_usage(
            PERPLEXITY_PROVIDER,
            response_sources=len(snapshots),
        )
    return snapshots


def fetch_official_btc_etf_snapshots(
    *,
    api_key: str = "",
    observer: PipelineObserver | None = None,
) -> list[BitcoinEtfIssuerSnapshot]:
    return _request_reference_snapshots(api_key, observer=observer)


def load_official_btc_etf_cache(cache_file: Path) -> dict[str, BitcoinEtfIssuerSnapshot]:
    if not cache_file.exists():
        return {}

    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    snapshots: dict[str, BitcoinEtfIssuerSnapshot] = {}
    for ticker, item in payload.items():
        if not isinstance(item, dict):
            continue
        try:
            snapshots[str(ticker)] = BitcoinEtfIssuerSnapshot(**item)
        except TypeError:
            continue
    return snapshots


def save_official_btc_etf_cache(
    cache_file: Path, snapshots: list[BitcoinEtfIssuerSnapshot]
) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {snapshot.ticker: asdict(snapshot) for snapshot in snapshots}
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = [
    "BitcoinEtfIssuerSnapshot",
    "GBTC_URL",
    "IBIT_URL",
    "BITB_URL",
    "fetch_official_btc_etf_snapshots",
    "load_official_btc_etf_cache",
    "parse_bitb_snapshot",
    "parse_gbtc_snapshot",
    "parse_ibit_snapshot",
    "save_official_btc_etf_cache",
]
