"""보존 속성 테스트 — 수정 전 코드에서 PASS가 기대됨.

observation-first 방법론: 수정 전 코드의 동작을 관찰하고,
해당 동작이 수정 후에도 보존되어야 함을 property-based test로 검증한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from hypothesis import given, settings
from hypothesis import strategies as st

from morning_brief.data.market import (
    BTC_ETF_TICKERS,
    MACRO_FALLBACK_TARGETS,
    TECH_STOCK_TICKERS,
    US_INDEX_TARGETS,
    build_market_packet,
    fetch_macro_points,
    fetch_us_index_points,
)
from morning_brief.data.market_policy import (
    CANONICAL_KEY_BY_SOURCE,
    MARKET_VALIDATION_BOUNDS,
    validation_bounds_for,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# DXY 외 거시 지표의 canonical key 집합
_NON_DXY_MACRO_KEYS = [key for key, _, _ in MACRO_FALLBACK_TARGETS if key != "dxy"]
st_non_dxy_macro_key = st.sampled_from(_NON_DXY_MACRO_KEYS) if _NON_DXY_MACRO_KEYS else st.nothing()

# US_INDEX_TARGETS의 canonical key 집합
_US_INDEX_KEYS = [key for key, _ in US_INDEX_TARGETS]
st_us_index_key = st.sampled_from(_US_INDEX_KEYS)

# KIS 패턴을 사용하는 모든 티커 (US indices + tech stocks + BTC ETF)
_KIS_PATTERN_TICKERS = (
    [ticker for _, ticker in US_INDEX_TARGETS] + list(TECH_STOCK_TICKERS) + list(BTC_ETF_TICKERS)
)
st_kis_ticker = st.sampled_from(_KIS_PATTERN_TICKERS)


# ===========================================================================
# Property 2a: DXY 외 거시 지표가 FRED → yfinance fallback 경로를 유지
# **Validates: Requirements 3.1, 3.7**
# ===========================================================================
class TestMacroFallbackPreservation:
    """DXY 외 거시 지표가 동일한 FRED → yfinance fallback 경로를 유지하는지 검증.

    관찰:
    - MACRO_FALLBACK_TARGETS에 us10y(^TNX), vix(^VIX)가 포함됨 (us3m 제거됨)
    - dxy는 FRED DTWEXAFEGS가 주소스; DX=F는 FRED 실패 시 yfinance fallback
    - fetch_macro_points()는 FRED 우선 → MACRO_FALLBACK_TARGETS yfinance fallback 구조

    **Validates: Requirements 3.1, 3.7**
    """

    def test_non_dxy_macro_targets_present(self):
        """us10y, vix가 MACRO_FALLBACK_TARGETS에 포함되어야 한다 (us3m 제거됨)."""
        keys = {key for key, _, _ in MACRO_FALLBACK_TARGETS}
        assert "us10y" in keys, "us10y가 MACRO_FALLBACK_TARGETS에 없음"
        assert "vix" in keys, "vix가 MACRO_FALLBACK_TARGETS에 없음"
        assert "us3m" not in keys, "us3m이 MACRO_FALLBACK_TARGETS에 있으면 안 됨 (제거됨)"

    def test_us10y_ticker_is_tnx(self):
        """us10y 티커가 ^TNX여야 한다."""
        entries = [(k, t) for k, t, _ in MACRO_FALLBACK_TARGETS if k == "us10y"]
        assert len(entries) == 1
        assert entries[0][1] == "^TNX"

    def test_vix_ticker_is_vix(self):
        """vix 티커가 ^VIX여야 한다."""
        entries = [(k, t) for k, t, _ in MACRO_FALLBACK_TARGETS if k == "vix"]
        assert len(entries) == 1
        assert entries[0][1] == "^VIX"

    @given(key=st_non_dxy_macro_key)
    @settings(max_examples=10)
    def test_non_dxy_macro_targets_have_valid_structure(self, key: str):
        """DXY 외 모든 거시 지표가 (canonical_key, ticker, scale) 3-tuple 구조를 유지한다.

        **Validates: Requirements 3.1**
        """
        entries = [entry for entry in MACRO_FALLBACK_TARGETS if entry[0] == key]
        assert len(entries) == 1, f"{key}가 MACRO_FALLBACK_TARGETS에 정확히 1개여야 함"
        canonical_key, ticker, scale = entries[0]
        assert isinstance(canonical_key, str) and canonical_key
        assert isinstance(ticker, str) and ticker
        assert isinstance(scale, (int, float)) and scale > 0

    def test_fetch_macro_points_uses_yfinance_fallback_pattern(self):
        """fetch_macro_points()의 내부 _fallback_macro_points()가
        MACRO_FALLBACK_TARGETS를 순회하며 _safe_yfinance_point()를 호출하는 구조를 유지한다.

        **Validates: Requirements 3.1, 3.7**
        """
        source = textwrap.dedent(inspect.getsource(fetch_macro_points))
        # _fallback_macro_points 내부 함수가 존재해야 함
        assert "_fallback_macro_points" in source
        # MACRO_FALLBACK_TARGETS를 참조해야 함
        assert "MACRO_FALLBACK_TARGETS" in source
        # _safe_yfinance_point를 호출해야 함
        assert "_safe_yfinance_point" in source


# ===========================================================================
# Property 2b: 미국 지수·빅테크·BTC ETF 가격이 KIS → yfinance fallback 유지
# **Validates: Requirements 3.2, 3.3**
# ===========================================================================
class TestKisFallbackPreservation:
    """미국 지수·빅테크·BTC ETF 가격이 동일한 KIS → yfinance fallback 패턴을 유지하는지 검증.

    관찰:
    - US_INDEX_TARGETS에 SPY, QQQ, SOXX가 KIS 우선 패턴으로 수집됨
    - BTC_ETF_TICKERS가 _safe_kis_point_and_volume() 경로를 사용함

    **Validates: Requirements 3.2, 3.3**
    """

    def test_us_index_targets_contain_spy_qqq_soxx(self):
        """US_INDEX_TARGETS에 SPY, QQQ, SOXX가 포함되어야 한다."""
        tickers = {ticker for _, ticker in US_INDEX_TARGETS}
        assert "SPY" in tickers
        assert "QQQ" in tickers
        assert "SOXX" in tickers

    @given(key=st_us_index_key)
    @settings(max_examples=10)
    def test_us_index_targets_have_valid_structure(self, key: str):
        """미국 지수 타겟이 (canonical_key, ticker) 2-tuple 구조를 유지한다.

        **Validates: Requirements 3.2**
        """
        entries = [entry for entry in US_INDEX_TARGETS if entry[0] == key]
        assert len(entries) == 1
        canonical_key, ticker = entries[0]
        assert isinstance(canonical_key, str) and canonical_key
        assert isinstance(ticker, str) and ticker

    def test_fetch_us_index_points_uses_safe_kis_point(self):
        """fetch_us_index_points()가 _safe_kis_point()를 사용하는 구조를 유지한다.

        **Validates: Requirements 3.2**
        """
        source = textwrap.dedent(inspect.getsource(fetch_us_index_points))
        assert "_safe_kis_point" in source
        assert "US_INDEX_TARGETS" in source

    def test_btc_etf_tickers_present(self):
        """BTC_ETF_TICKERS에 IBIT, FBTC, ARKB, BITB, GBTC가 포함되어야 한다.

        **Validates: Requirements 3.3**
        """
        assert "IBIT" in BTC_ETF_TICKERS
        assert "FBTC" in BTC_ETF_TICKERS
        assert "ARKB" in BTC_ETF_TICKERS
        assert "BITB" in BTC_ETF_TICKERS
        assert "GBTC" in BTC_ETF_TICKERS

    def test_btc_etf_uses_safe_kis_point_and_volume(self):
        """fetch_newsletter_display_data()에서 BTC ETF 가격·거래량이
        _safe_kis_point_and_volume() 경로를 사용하는 구조를 유지한다.
        (ETF 가격은 감성 파이프라인에서 제외 → 뉴스레터 렌더링 전용)

        **Validates: Requirements 3.3**
        """
        from morning_brief.data.market import fetch_newsletter_display_data

        source = textwrap.dedent(inspect.getsource(fetch_newsletter_display_data))
        assert "_safe_kis_point_and_volume" in source
        assert "BTC_ETF_TICKERS" in source


# ===========================================================================
# Property 2c: 캐시 구조 및 packet 구조가 변경되지 않았는지 검증
# **Validates: Requirements 3.4, 3.6, 3.8**
# ===========================================================================
class TestCacheAndPacketStructurePreservation:
    """캐시 구조 및 packet 구조가 변경되지 않았는지 검증.

    관찰:
    - build_market_packet() 반환 packet 구조가 macro, korea_watch, validated_indices,
      us_indices, tech_stocks, bitcoin 키를 포함함
    - DXY validation bounds가 (95.0, 115.0)임

    **Validates: Requirements 3.4, 3.6, 3.8**
    """

    def test_build_market_packet_returns_expected_keys(self):
        """build_market_packet()의 소스 코드에서 packet dict에
        macro, korea_watch, validated_indices, us_indices, tech_stocks, bitcoin 키가 포함되어야 한다.

        **Validates: Requirements 3.6**
        """
        source = textwrap.dedent(inspect.getsource(build_market_packet))
        tree = ast.parse(source)

        # packet dict에 할당되는 키를 추출
        expected_keys = {
            "macro",
            "korea_watch",
            "validated_indices",
            "us_indices",
            "tech_stocks",
            "bitcoin",
        }
        found_keys: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in expected_keys:
                    found_keys.add(node.value)

        missing = expected_keys - found_keys
        assert not missing, f"build_market_packet() packet에 {missing} 키가 누락됨"

    def test_dxy_validation_bounds(self):
        """DXY validation bounds가 (95.0, 130.0)이어야 한다.
        (DTWEXAFEGS는 ICE DXY보다 스케일이 다름 — 범위 조정됨)

        **Validates: Requirements 3.7**
        """
        bounds = validation_bounds_for("dxy")
        assert bounds is not None, "dxy validation bounds가 없음"
        assert bounds == (95.0, 130.0), f"dxy bounds가 {bounds}이지만 (95.0, 130.0)이어야 함"

    def test_market_validation_bounds_preserved(self):
        """기존 MARKET_VALIDATION_BOUNDS의 모든 키가 보존되어야 한다.

        **Validates: Requirements 3.7, 3.8**
        """
        expected_keys = {"dxy", "vix", "us10y", "btc", "spy", "dow30", "kospi", "kosdaq"}
        assert expected_keys <= set(MARKET_VALIDATION_BOUNDS.keys()), (
            f"MARKET_VALIDATION_BOUNDS에서 {expected_keys - set(MARKET_VALIDATION_BOUNDS.keys())} 누락"
        )

    def test_btc_etf_cache_structure_preserved(self):
        """BTC ETF 캐시 로드/저장 함수가 존재하고 올바른 시그니처를 유지한다.

        **Validates: Requirements 3.4**
        """
        from morning_brief.data.sources.btc_etf_official import (
            load_official_btc_etf_cache,
            save_official_btc_etf_cache,
            save_official_btc_etf_cache_state,
        )

        # 함수가 존재하고 호출 가능한지 확인
        assert callable(load_official_btc_etf_cache)
        assert callable(save_official_btc_etf_cache)
        assert callable(save_official_btc_etf_cache_state)

        # load_official_btc_etf_cache의 파라미터에 cache_file이 있어야 함
        sig = inspect.signature(load_official_btc_etf_cache)
        assert "cache_file" in sig.parameters

    def test_btc_etf_cache_max_age_hours_preserved(self):
        """BTC_ETF_CACHE_MAX_AGE_HOURS가 48시간으로 유지되어야 한다.

        **Validates: Requirements 3.4**
        """
        from morning_brief.data.market import BTC_ETF_CACHE_MAX_AGE_HOURS

        assert BTC_ETF_CACHE_MAX_AGE_HOURS == 48

    @given(
        bounds_key=st.sampled_from(list(MARKET_VALIDATION_BOUNDS.keys())),
    )
    @settings(max_examples=10)
    def test_validation_bounds_are_valid_tuples(self, bounds_key: str):
        """모든 validation bounds가 (lower, upper) 형태의 유효한 튜플이어야 한다.

        **Validates: Requirements 3.7**
        """
        bounds = validation_bounds_for(bounds_key)
        assert bounds is not None
        lower, upper = bounds
        assert isinstance(lower, (int, float))
        assert isinstance(upper, (int, float))
        assert lower < upper, f"{bounds_key} bounds: lower({lower}) >= upper({upper})"


# ===========================================================================
# Property 2d: Perplexity Sonar의 토픽 요약·뉴스 수집·맥락 분석이
#              btc_etf_official.py 외부에 있음
# **Validates: Requirements 3.5**
# ===========================================================================
class TestPerplexitySonarPreservation:
    """Perplexity Sonar의 토픽 요약·뉴스 수집·맥락 분석 코드가
    btc_etf_official.py 외부에 있음을 확인.

    관찰:
    - perplexity_sonar.py에 fetch_sonar_summaries, fetch_sonar_context,
      collect_sonar_news_items 함수가 존재
    - btc_etf_official.py에는 이 함수들이 없음

    **Validates: Requirements 3.5**
    """

    def test_sonar_summary_functions_exist_in_perplexity_sonar(self):
        """perplexity_sonar.py에 토픽 요약 관련 함수가 존재해야 한다."""
        from morning_brief.data.sources.perplexity_sonar import (
            collect_sonar_news_items,
            fetch_sonar_context,
            fetch_sonar_summaries,
        )

        assert callable(fetch_sonar_summaries)
        assert callable(fetch_sonar_context)
        assert callable(collect_sonar_news_items)

    def test_sonar_functions_not_in_btc_etf_official(self):
        """btc_etf_official.py에 Sonar 토픽 요약 함수가 없어야 한다."""
        import morning_brief.data.sources.btc_etf_official as btc_mod

        assert not hasattr(btc_mod, "fetch_sonar_summaries")
        assert not hasattr(btc_mod, "fetch_sonar_context")
        assert not hasattr(btc_mod, "collect_sonar_news_items")

    def test_sonar_topic_names_preserved(self):
        """Sonar 토픽 이름이 보존되어야 한다."""
        from morning_brief.data.sources.perplexity_sonar import TOPIC_NAMES

        assert "macro" in TOPIC_NAMES
        assert "us_equity" in TOPIC_NAMES
        assert "bitcoin" in TOPIC_NAMES

    def test_perplexity_sonar_imported_in_news_module(self):
        """news.py에서 perplexity_sonar 모듈이 import되어야 한다."""
        source = inspect.getsource(
            __import__("morning_brief.data.news", fromlist=["collect_news_packet"])
        )
        assert "perplexity_sonar" in source


# ===========================================================================
# Property 2e: CANONICAL_KEY_BY_SOURCE 기존 매핑 보존
# **Validates: Requirements 3.1, 3.7**
# ===========================================================================
class TestCanonicalKeyMappingPreservation:
    """CANONICAL_KEY_BY_SOURCE의 기존 매핑이 보존되어야 한다.

    **Validates: Requirements 3.1, 3.7**
    """

    _EXPECTED_MAPPINGS = {
        "DGS10": "us10y",
        "^TNX": "us10y",
        "DGS2": "us2y",
        "DTWEXAFEGS": "dxy",  # FRED 공식 달러 지수 (신규)
        "DX=F": "dxy",  # yfinance fallback
        "DX-Y.NYB": "dxy",  # 하위 호환성 (상장폐지)
        "BAMLH0A0HYM2": "hy_spread",  # FRED 하이일드 스프레드 (신규)
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

    @given(
        source_key=st.sampled_from(list(_EXPECTED_MAPPINGS.keys())),
    )
    @settings(max_examples=20)
    def test_existing_canonical_mappings_preserved(self, source_key: str):
        """기존 CANONICAL_KEY_BY_SOURCE 매핑이 모두 보존되어야 한다.

        **Validates: Requirements 3.1**
        """
        expected_canonical = self._EXPECTED_MAPPINGS[source_key]
        assert source_key in CANONICAL_KEY_BY_SOURCE, (
            f"CANONICAL_KEY_BY_SOURCE에 '{source_key}' 키가 없음"
        )
        assert CANONICAL_KEY_BY_SOURCE[source_key] == expected_canonical, (
            f"'{source_key}'의 canonical key가 '{expected_canonical}'이어야 하지만 "
            f"'{CANONICAL_KEY_BY_SOURCE[source_key]}'임"
        )
