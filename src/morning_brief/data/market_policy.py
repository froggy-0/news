from __future__ import annotations

from typing import Iterable

CANONICAL_LABELS = {
    "us10y": "미국 10년물 국채금리",
    "us2y": "미국 2년물 국채금리",
    "us3m": "미국 13주물 단기금리",
    "dxy": "달러 인덱스",
    "vix": "VIX",
    "spy": "S&P500",
    "qqq": "NASDAQ",
    "soxx": "반도체 섹터 (SOXX)",
    "btc": "BTC-USD",
}

CANONICAL_KEY_BY_SOURCE = {
    "DGS10": "us10y",
    "^TNX": "us10y",
    "DGS2": "us2y",
    "^IRX": "us3m",
    "DTWEXBGS": "dxy",
    "DX-Y.NYB": "dxy",
    "VIXCLS": "vix",
    "^VIX": "vix",
    "SPY": "spy",
    "spy.us": "spy",
    "QQQ": "qqq",
    "qqq.us": "qqq",
    "SOXX": "soxx",
    "soxx.us": "soxx",
    "BTC-USD": "btc",
}

MARKET_VALIDATION_BOUNDS = {
    "dxy": (95.0, 115.0),
    "vix": (10.0, 80.0),
    "us10y": (0.5, 8.0),
    "btc": (10_000.0, 200_000.0),
    "spy": (300.0, 700.0),
}


def _normalize_identifier(value: str) -> str:
    return value.strip()


def canonical_key_for(*identifiers: str) -> str:
    for identifier in identifiers:
        normalized = _normalize_identifier(identifier)
        if not normalized:
            continue
        if normalized in CANONICAL_KEY_BY_SOURCE:
            return CANONICAL_KEY_BY_SOURCE[normalized]

    for identifier in identifiers:
        normalized = _normalize_identifier(identifier)
        if normalized:
            return normalized.lower().replace("^", "").replace(".", "_").replace("-", "_")

    raise ValueError("적어도 하나의 식별자가 필요해요.")


def canonical_label_for(canonical_key: str, *, fallback: str = "") -> str:
    normalized = canonical_key.strip().lower()
    return CANONICAL_LABELS.get(normalized, fallback or canonical_key)


def canonical_keys_for_identifiers(identifiers: Iterable[str]) -> list[str]:
    return [canonical_key_for(identifier) for identifier in identifiers if identifier.strip()]


def validation_bounds_for(canonical_key: str) -> tuple[float, float] | None:
    return MARKET_VALIDATION_BOUNDS.get(canonical_key.strip().lower())
