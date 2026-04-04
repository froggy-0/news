"""providers.py 상수 정확성 및 순환 임포트 검증."""

from __future__ import annotations

import importlib

from morning_brief.data import providers
from morning_brief.data.sources.provider_runtime import PROVIDER_POLICIES


def test_grok_x_keyword_matches_actual_value() -> None:
    """providers.GROK_X_KEYWORD가 grok_x_keyword.py:298에서 실제 설정하는 값과 일치해야 한다."""
    assert providers.GROK_X_KEYWORD == "grok_x_keyword"


def test_runtime_grok_keyword_matches_policy_name() -> None:
    """providers.RUNTIME_GROK_KEYWORD가 provider_runtime.py ProviderPolicy.name과 일치해야 한다."""
    assert providers.RUNTIME_GROK_KEYWORD == "grok_keyword"
    assert PROVIDER_POLICIES["grok_keyword"].name == providers.RUNTIME_GROK_KEYWORD


def test_grok_official_x_matches_actual_value() -> None:
    """providers.GROK_OFFICIAL_X가 grok_official_signals.py:477에서 실제 설정하는 값과 일치해야 한다."""
    assert providers.GROK_OFFICIAL_X == "grok_official_x"


def test_perplexity_search_value() -> None:
    assert providers.PERPLEXITY_SEARCH == "perplexity_search"


def test_perplexity_sonar_value() -> None:
    assert providers.PERPLEXITY_SONAR == "perplexity_sonar"


def test_grok_web_search_value() -> None:
    assert providers.GROK_WEB_SEARCH == "grok_web_search"


def test_perplexity_providers_set() -> None:
    assert providers.PERPLEXITY_PROVIDERS == frozenset({"perplexity_search", "perplexity_sonar"})


def test_grok_providers_set() -> None:
    assert providers.GROK_PROVIDERS == frozenset(
        {"grok_official_x", "grok_x_keyword", "grok_web_search"}
    )


def test_no_circular_import() -> None:
    """providers 모듈이 내부 모듈 임포트 없이 단독 로드 가능해야 한다."""
    # 모듈이 이미 로드됐더라도 reload로 재실행하여 순환 임포트 없음을 확인
    spec = importlib.util.find_spec("morning_brief.data.providers")
    assert spec is not None
    mod = importlib.import_module("morning_brief.data.providers")
    assert hasattr(mod, "GROK_OFFICIAL_X")


def test_runtime_keyword_not_in_data_provenance_sets() -> None:
    """RUNTIME_GROK_KEYWORD는 data provenance 집합에 포함되면 안 된다."""
    assert providers.RUNTIME_GROK_KEYWORD not in providers.PERPLEXITY_PROVIDERS
    assert providers.RUNTIME_GROK_KEYWORD not in providers.GROK_PROVIDERS
