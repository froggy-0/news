"""청산(forceOrder) 4h 버킷 → 롤링 소진·비대칭 피처 (WI-9 v2, 2026-08-10 설계).

⚠️ 검증 전 인프라 — 게이트는 기본 off(parameters.LIQUIDATION_EXHAUSTION_GATE_ENABLED=False).
설계 근거·최소 관측 요건(청산 스파이크 5건+ 관측 전엔 그리드/튜닝 착수 금지)은
docs/arena/research/liquidation-feature-design-20260810.md 참조. 여기 함수는 전부
순수함수(DB 접근은 data_lake.fetch_liquidation_bars가 담당) — scheduler가 결합해 macro에 주입.

문헌 가드레일: arXiv:2607.27070("Where does the criticality live?", 2026, 바이낸스 BTCUSDT
7개 캐스케이드 분석)이 단일변수 조기경보(forward-looking 예측)의 취약함을 반증했으므로,
이 모듈은 "캐스케이드가 곧 온다" 예측이 아니라 "이미 일어난 소진을 관측"(backward-looking)
하는 것만 다룬다 — fng_contrarian/omnibus REBOUND의 진입 품질 veto 후보일 뿐, 방향성 신호나
사이징 확대에는 쓰지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

RECENT_WINDOW_HOURS = 24.0  # 소진 관측 윈도우 — 4h × 6봉, arena 결정주기와 정렬
_DEFAULT_LOOKBACK_DAYS = 30.0
_DEFAULT_MIN_PERIODS = 5  # 설계문서 §4 go/no-go 게이트(청산 스파이크 5건+)와 정합


def _parse_bar_start(value: object) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def recent_liquidation_totals(
    bars: list[dict], *, now: datetime, window_hours: float = RECENT_WINDOW_HOURS
) -> tuple[float, float]:
    """now 기준 최근 window_hours 이내 롱/숏 청산 명목합(USD).

    bars는 arena_liquidation_bars 행(dict, bar_start/long_liq_usd/short_liq_usd 키 필요) —
    심볼 필터링은 호출측 책임(단일 심볼 bars만 넘길 것).
    """
    cutoff = now - timedelta(hours=window_hours)
    long_usd = short_usd = 0.0
    for bar in bars:
        start = _parse_bar_start(bar.get("bar_start"))
        if start is None or start < cutoff or start > now:
            continue
        long_usd += float(bar.get("long_liq_usd") or 0.0)
        short_usd += float(bar.get("short_liq_usd") or 0.0)
    return long_usd, short_usd


def liquidation_asymmetry(long_usd: float, short_usd: float) -> float | None:
    """(롱청산−숏청산)/합계. +1=롱청산(투매) 지배, −1=숏청산(숏스퀴즈) 지배.

    합계가 0이면 None — "관측된 청산 없음"과 "완전 균형(0.0)"을 구분하기 위해 0.0을
    반환하지 않는다.
    """
    total = long_usd + short_usd
    if total <= 0:
        return None
    return (long_usd - short_usd) / total


def liquidation_intensity_zscore(
    bars: list[dict],
    *,
    now: datetime,
    window_hours: float = RECENT_WINDOW_HOURS,
    lookback_days: float = _DEFAULT_LOOKBACK_DAYS,
    min_periods: int = _DEFAULT_MIN_PERIODS,
) -> float | None:
    """최근 window_hours 청산총액(롱+숏)이 과거 lookback_days 대비 몇 표준편차인지.

    lookback_days를 window_hours 크기의 겹치지 않는 청크로 now에서 거꾸로 나눠 각 청크
    합계 분포를 만들고, 가장 최근(현재) 청크의 z-score를 반환. 청크 경계는 데이터 유무와
    무관하게 고정 시간격자로 생성하므로(bar 없는 구간=0 청산으로 자연스럽게 반영), 저빈도
    이벤트인 청산의 "빈 4h 봉"을 결측이 아닌 진짜 0으로 취급한다.

    과거 표본(min_periods)이 부족하면 None — 설계문서의 "n=1~2로 그리드하면 과최적화"
    경고와 동일 원리로, 섣부른 z-score 신뢰를 막는다.
    """
    if window_hours <= 0:
        return None
    window = timedelta(hours=window_hours)
    lookback_start = now - timedelta(days=lookback_days)
    chunk_totals: list[float] = []
    chunk_end = now
    while chunk_end - window >= lookback_start:
        chunk_start = chunk_end - window
        total = 0.0
        for bar in bars:
            start = _parse_bar_start(bar.get("bar_start"))
            if start is None or not (chunk_start <= start < chunk_end):
                continue
            total += float(bar.get("long_liq_usd") or 0.0) + float(bar.get("short_liq_usd") or 0.0)
        chunk_totals.append(total)
        chunk_end = chunk_start
    if len(chunk_totals) < min_periods + 1:  # +1: 최신 청크 자신은 분포에서 제외
        return None
    recent, history = chunk_totals[0], chunk_totals[1:]
    mean = sum(history) / len(history)
    variance = sum((x - mean) ** 2 for x in history) / len(history)
    std = variance**0.5
    if std <= 0:
        return None
    return (recent - mean) / std


def liquidation_snapshot(
    bars: list[dict], *, now: datetime, window_hours: float = RECENT_WINDOW_HOURS
) -> dict[str, float | None]:
    """macro 주입용 스냅샷 — 전부 None-graceful(관측 부족 시). 단일 심볼 bars 기준."""
    long_usd, short_usd = recent_liquidation_totals(bars, now=now, window_hours=window_hours)
    return {
        "liq_long_usd_24h": round(long_usd, 2),
        "liq_short_usd_24h": round(short_usd, 2),
        "liq_asymmetry_24h": liquidation_asymmetry(long_usd, short_usd),
        "liq_intensity_zscore_24h": liquidation_intensity_zscore(
            bars, now=now, window_hours=window_hours
        ),
    }
