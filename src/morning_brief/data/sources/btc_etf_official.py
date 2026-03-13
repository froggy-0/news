from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import html
import json
import logging
from pathlib import Path
import re

from morning_brief.data.sources.http_client import HttpFetchError, get_text_with_retry
from morning_brief.models import BitcoinEtfIssuerSnapshot

logger = logging.getLogger(__name__)

IBIT_URL = "https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf"
BITB_URL = "https://bitbetf.com/"
GBTC_URL = "https://etfs.grayscale.com/gbtc"
IBIT_CREATION_BASKET_SHARES = 40_000

DATE_RE = r"(?:[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}|\d{2}/\d{2}/\d{4})"
VALUE_RE = r"\$?[\d,]+(?:\.\d+)?(?:[MB])?"
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>\s*(?P<payload>\{.*?\})\s*</script>',
    flags=re.DOTALL | re.IGNORECASE,
)


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

    if not all(value is not None for value in [total_btc_raw, aum_usd_raw, shares_outstanding_raw, daily_volume_raw]):
        raise HttpFetchError("Bitwise 페이지의 구조화 데이터가 충분하지 않아요.")

    as_of = _extract_page_date(_normalize_page_text(text))
    if isinstance(as_of_raw, str) and as_of_raw.strip():
        try:
            as_of = datetime.fromisoformat(as_of_raw.replace("Z", "+00:00")).strftime("%m/%d/%Y")
        except ValueError:
            as_of = as_of_raw[:10].replace("-", "/")

    return (
        as_of,
        float(total_btc_raw),
        float(aum_usd_raw),
        int(float(shares_outstanding_raw)),
        int(float(daily_volume_raw)),
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
        as_of, total_btc, aum_usd, shares_outstanding, daily_volume = _extract_bitb_structured_values(text)
        bitcoin_per_share = total_btc / shares_outstanding
    except HttpFetchError:
        as_of = _extract_page_date(normalized)
        aum_usd = _extract_first_matching_value(normalized, ["Net Assets (AUM)", "Net Assets"])
        shares_outstanding = _extract_value(normalized, "Shares Outstanding")
        daily_volume = _extract_first_matching_value(normalized, ["Daily Volume (Shares)", "Daily Volume"])
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


def fetch_official_btc_etf_snapshots() -> list[BitcoinEtfIssuerSnapshot]:
    issuers = [
        ("IBIT", IBIT_URL, parse_ibit_snapshot),
        ("BITB", BITB_URL, parse_bitb_snapshot),
        ("GBTC", GBTC_URL, parse_gbtc_snapshot),
    ]
    snapshots: list[BitcoinEtfIssuerSnapshot] = []
    for ticker, url, parser in issuers:
        try:
            page_text = get_text_with_retry(
                url,
                provider="btc_etf_official",
                timeout=20,
            )
            snapshots.append(parser(page_text))
        except Exception as exc:
            logger.warning("공식 BTC ETF 발행사 페이지를 건너뛸게요. ticker=%s | %s", ticker, exc)
    snapshots.sort(key=lambda item: item.ticker)
    return snapshots


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


def save_official_btc_etf_cache(cache_file: Path, snapshots: list[BitcoinEtfIssuerSnapshot]) -> None:
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
