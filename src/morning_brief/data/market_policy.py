from __future__ import annotations

from typing import Iterable

CANONICAL_LABELS = {
    "us10y": "미국 10년물 국채금리",
    "us2y": "미국 2년물 국채금리",
    "dxy": "달러 인덱스",
    "vix": "VIX",
    "hy_spread": "하이일드 스프레드",
    "usdkrw": "원/달러 환율",
    "nq_futures": "나스닥 선물",
    "dow30": "다우30",
    "kospi": "코스피",
    "kosdaq": "코스닥",
    "spy": "S&P500",
    "qqq": "NASDAQ",
    "soxx": "반도체 섹터 (SOXX)",
    "btc": "BTC-USD",
}

CANONICAL_KEY_BY_SOURCE = {
    "DGS10": "us10y",
    "^TNX": "us10y",
    "DGS2": "us2y",
    # ICE DXY만 canonical dxy로 취급하고, FRED broad dollar index(DTWEXBGS)는 의도적으로 제외한다.
    # DTWEXAFEGS(연준 AFE 무역가중 달러 지수)는 공식 FRED 시리즈로 dxy canonical에 포함한다.
    "DTWEXAFEGS": "dxy",
    "DX=F": "dxy",  # yfinance fallback — FRED 실패 시 사용
    "DX-Y.NYB": "dxy",  # 하위 호환성 유지 (캐시에 이전 티커가 남아있을 수 있음, 상장폐지)
    "BAMLH0A0HYM2": "hy_spread",
    "VIXCLS": "vix",
    "^VIX": "vix",
    "KRW=X": "usdkrw",
    "NQ=F": "nq_futures",
    ".DJI": "dow30",
    "^DJI": "dow30",
    "0001": "kospi",
    "^KS11": "kospi",
    "1001": "kosdaq",
    "^KQ11": "kosdaq",
    "SPY": "spy",
    "spy.us": "spy",
    "QQQ": "qqq",
    "qqq.us": "qqq",
    "SOXX": "soxx",
    "soxx.us": "soxx",
    "BTC-USD": "btc",
}

MARKET_VALIDATION_BOUNDS = {
    # DTWEXAFEGS는 DXY(ICE)보다 스케일이 다름. 실제 시계열 기준 범위 조정.
    "dxy": (95.0, 130.0),
    "vix": (10.0, 80.0),
    "us10y": (0.5, 8.0),
    "btc": (10_000.0, 200_000.0),
    "dow30": (10_000.0, 80_000.0),
    "kospi": (1_000.0, 6_500.0),
    "kosdaq": (300.0, 2_000.0),
    "spy": (300.0, 700.0),
    "hy_spread": (1.5, 20.0),  # 단위: %. 정상: 2~5%, 위기: 8%+, 상한 20은 이상값 방어
}

# 감성 분석 파이프라인 검증에서 제외되는 뉴스레터 표시 전용 항목 검증 범위
DISPLAY_ONLY_VALIDATION = {
    "usdkrw": (900.0, 2000.0),
    "nq_futures": (8000.0, 40000.0),
}

RATE_CANONICAL_KEYS = frozenset({"us10y", "us2y"})


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


def is_rate_canonical_key(canonical_key: str) -> bool:
    return canonical_key.strip().lower() in RATE_CANONICAL_KEYS


def normalize_change_bps(change_bps: float) -> float:
    return float(int(round(change_bps)))
