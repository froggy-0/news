"""Bug Condition Exploration Tests — 수정 전 코드에서 FAIL이 기대됨.

이 테스트는 기대 동작(expected behavior)을 인코딩한다.
수정 전 코드에서 실패하면 버그 존재가 증명되고,
수정 후 코드에서 통과하면 버그가 해결된 것이다.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from morning_brief.data.market import MACRO_FALLBACK_TARGETS
from morning_brief.data.market_policy import CANONICAL_KEY_BY_SOURCE
from morning_brief.data.sources.btc_etf_official import fetch_official_btc_etf_snapshots


# ---------------------------------------------------------------------------
# 테스트 1a: MACRO_FALLBACK_TARGETS에서 DXY 티커가 유효한 DX=F인지 확인
# ---------------------------------------------------------------------------
class TestDxyTickerInMacroFallbackTargets:
    """DXY 티커가 비활성화된 DX-Y.NYB이 아니라 유효한 DX=F여야 한다.

    **Validates: Requirements 1.1, 1.2**
    """

    def test_dxy_entry_exists_in_macro_fallback_targets(self):
        """MACRO_FALLBACK_TARGETS에 dxy canonical key가 존재해야 한다."""
        dxy_entries = [
            (key, ticker, scale) for key, ticker, scale in MACRO_FALLBACK_TARGETS if key == "dxy"
        ]
        assert len(dxy_entries) == 1, (
            f"MACRO_FALLBACK_TARGETS에 dxy 항목이 정확히 1개여야 하지만 {len(dxy_entries)}개 발견"
        )

    def test_dxy_ticker_is_valid_dx_futures(self):
        """DXY 티커가 유효한 DX=F(ICE Dollar Index Futures)여야 한다.

        수정 전: DX-Y.NYB (비활성화됨, "possibly delisted") → FAIL 기대
        수정 후: DX=F (유효한 선물 티커) → PASS 기대
        """
        dxy_entries = [
            (key, ticker, scale) for key, ticker, scale in MACRO_FALLBACK_TARGETS if key == "dxy"
        ]
        assert len(dxy_entries) == 1
        _, ticker, _ = dxy_entries[0]
        assert ticker == "DX=F", (
            f"DXY 티커가 'DX=F'여야 하지만 '{ticker}'임 — "
            f"비활성화된 'DX-Y.NYB' 티커가 여전히 사용 중"
        )

    def test_dxy_ticker_is_not_delisted_dx_y_nyb(self):
        """DXY 티커가 비활성화된 DX-Y.NYB이 아니어야 한다.

        수정 전: DX-Y.NYB 사용 중 → FAIL 기대
        수정 후: DX=F 사용 → PASS 기대
        """
        dxy_entries = [
            (key, ticker, scale) for key, ticker, scale in MACRO_FALLBACK_TARGETS if key == "dxy"
        ]
        assert len(dxy_entries) == 1
        _, ticker, _ = dxy_entries[0]
        assert ticker != "DX-Y.NYB", (
            "DXY 티커가 비활성화된 'DX-Y.NYB'임 — yfinance에서 'possibly delisted' 오류 발생"
        )


# ---------------------------------------------------------------------------
# 테스트 1b: fetch_official_btc_etf_snapshots()가 _request_reference_snapshots()를
#            먼저 호출하지 않는 구조인지 확인
# ---------------------------------------------------------------------------
class TestBtcEtfDirectFetchPrimary:
    """fetch_official_btc_etf_snapshots()가 Perplexity structured query를
    호출하지 않고 direct fetch를 primary 경로로 사용해야 한다.

    **Validates: Requirements 1.3, 1.4**
    """

    def test_fetch_official_btc_etf_snapshots_does_not_call_perplexity_first(self):
        """fetch_official_btc_etf_snapshots()의 소스 코드에서
        _request_reference_snapshots() 호출이 없어야 한다.

        수정 전: _request_reference_snapshots()를 먼저 호출 → FAIL 기대
        수정 후: direct fetch를 primary로 사용 → PASS 기대
        """
        source = textwrap.dedent(inspect.getsource(fetch_official_btc_etf_snapshots))
        tree = ast.parse(source)

        perplexity_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "_request_reference_snapshots":
                    perplexity_calls.append(func.id)
                elif (
                    isinstance(func, ast.Attribute) and func.attr == "_request_reference_snapshots"
                ):
                    perplexity_calls.append(func.attr)

        assert len(perplexity_calls) == 0, (
            f"fetch_official_btc_etf_snapshots()가 _request_reference_snapshots()를 "
            f"{len(perplexity_calls)}회 호출함 — "
            f"Perplexity structured query가 primary 경로로 사용 중이며 "
            f"불필요한 API 비용과 지연 발생"
        )


# ---------------------------------------------------------------------------
# 테스트 1c: CANONICAL_KEY_BY_SOURCE에 DX=F → dxy 매핑이 존재하는지 확인
# ---------------------------------------------------------------------------
class TestCanonicalKeyMapping:
    """CANONICAL_KEY_BY_SOURCE에 새 DXY 티커 DX=F의 매핑이 있어야 한다.

    **Validates: Requirements 1.1, 1.2**
    """

    def test_dx_futures_mapped_to_dxy(self):
        """CANONICAL_KEY_BY_SOURCE에 'DX=F' → 'dxy' 매핑이 존재해야 한다.

        수정 전: DX=F 매핑 없음 → FAIL 기대
        수정 후: DX=F → dxy 매핑 추가 → PASS 기대
        """
        assert "DX=F" in CANONICAL_KEY_BY_SOURCE, (
            "CANONICAL_KEY_BY_SOURCE에 'DX=F' 키가 없음 — 새 DXY 티커의 canonical key 매핑이 누락됨"
        )
        assert CANONICAL_KEY_BY_SOURCE["DX=F"] == "dxy", (
            f"'DX=F'의 canonical key가 'dxy'여야 하지만 '{CANONICAL_KEY_BY_SOURCE.get('DX=F')}'임"
        )
