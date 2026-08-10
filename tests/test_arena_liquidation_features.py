from datetime import datetime, timedelta, timezone

from arena import liquidation_features as lf


def _bar(hours_ago: float, *, long_usd: float, short_usd: float, now: datetime) -> dict:
    return {
        "bar_start": (now - timedelta(hours=hours_ago)).isoformat(),
        "long_liq_usd": long_usd,
        "short_liq_usd": short_usd,
    }


def test_recent_liquidation_totals_sums_within_window_only() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    bars = [
        _bar(2, long_usd=1000.0, short_usd=200.0, now=now),  # 안쪽(24h)
        _bar(20, long_usd=500.0, short_usd=100.0, now=now),  # 안쪽(24h)
        _bar(30, long_usd=99999.0, short_usd=99999.0, now=now),  # 바깥(24h 초과) — 제외
    ]
    long_usd, short_usd = lf.recent_liquidation_totals(bars, now=now)
    assert long_usd == 1500.0
    assert short_usd == 300.0


def test_recent_liquidation_totals_empty_bars_is_zero() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    assert lf.recent_liquidation_totals([], now=now) == (0.0, 0.0)


def test_liquidation_asymmetry_direction_and_none_when_no_observation() -> None:
    # 롱청산(투매) 지배 → 양수.
    assert lf.liquidation_asymmetry(900.0, 100.0) == 0.8
    # 숏청산(숏스퀴즈) 지배 → 음수.
    assert lf.liquidation_asymmetry(100.0, 900.0) == -0.8
    # 균형 → 0.0(관측은 있음, None 아님).
    assert lf.liquidation_asymmetry(500.0, 500.0) == 0.0
    # 관측 자체가 없음(합계 0) → None ("소진 완료"와 구분).
    assert lf.liquidation_asymmetry(0.0, 0.0) is None


def test_liquidation_intensity_zscore_none_when_history_insufficient() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    # 과거 청크가 min_periods(기본 5) 미만 → 관측 부족으로 None.
    bars = [_bar(2, long_usd=1000.0, short_usd=0.0, now=now)]
    assert lf.liquidation_intensity_zscore(bars, now=now, lookback_days=3) is None


def test_liquidation_intensity_zscore_detects_spike_above_uniform_history() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    bars = []
    # 과거 30일, 24h 청크마다 살짝 변동 있는 청산액(분산 0 방지) + 최근 24h 스파이크.
    for i in range(1, 30):
        wobble = 50.0 if i % 2 == 0 else -50.0
        bars.append(_bar(24 * i, long_usd=1000.0 + wobble, short_usd=800.0, now=now))
    bars.append(_bar(2, long_usd=50_000.0, short_usd=2_000.0, now=now))
    z = lf.liquidation_intensity_zscore(bars, now=now)
    assert z is not None
    assert z > 5.0  # 이례적 스파이크 — 뚜렷하게 큰 z


def test_liquidation_intensity_zscore_none_when_history_variance_zero() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    # 과거 청크(+최근 청크)가 전부 완전히 동일 → 분산 0 → z 정의 불가 → None(잘못된 신뢰 방지).
    # -12h 오프셋으로 각 청크 경계(24h 배수)에 정확히 걸치지 않게 배치(경계 모호성 회피).
    bars = [_bar(24 * i - 12, long_usd=1000.0, short_usd=800.0, now=now) for i in range(1, 10)] + [
        _bar(2, long_usd=1000.0, short_usd=800.0, now=now)
    ]
    assert lf.liquidation_intensity_zscore(bars, now=now, lookback_days=9.5, min_periods=5) is None


def test_liquidation_snapshot_keys_and_graceful_empty() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    snap = lf.liquidation_snapshot([], now=now)
    assert snap == {
        "liq_long_usd_24h": 0.0,
        "liq_short_usd_24h": 0.0,
        "liq_asymmetry_24h": None,
        "liq_intensity_zscore_24h": None,
    }
