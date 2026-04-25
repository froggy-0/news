"""Provider identifier constants — single source of truth.

두 개의 네임스페이스를 명확히 분리한다:

- Data provenance: NewsItem.provider 필드에 실제로 기록되는 값
- Runtime circuit breaker: provider_runtime.py ProviderPolicy.name 과 일치하는 값

순환 임포트를 방지하기 위해 stdlib/typing 외 내부 모듈을 임포트하지 않는다.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Data provenance constants
# NewsItem.provider 필드에 기록되는 값과 정확히 일치해야 한다.
# ---------------------------------------------------------------------------

PERPLEXITY_SEARCH = "perplexity_search"
PERPLEXITY_SONAR = "perplexity_sonar"
GROK_OFFICIAL_X = "grok_official_x"
GROK_X_KEYWORD = "grok_x_keyword"
GROK_WEB_SEARCH = "grok_web_search"
COINDESK_API = "coindesk_api"
THENEWSAPI = "thenewsapi"

# ---------------------------------------------------------------------------
# Runtime circuit breaker constants
# provider_runtime.py ProviderPolicy.name 과 일치해야 한다.
# GROK_X_KEYWORD ("grok_x_keyword") 와 구분된다:
#   - GROK_X_KEYWORD: NewsItem.provider 값 (data provenance)
#   - RUNTIME_GROK_KEYWORD: circuit breaker policy 이름 (runtime identity)
# ---------------------------------------------------------------------------

RUNTIME_GROK_KEYWORD = "grok_keyword"
RUNTIME_GROK_WEB_SEARCH = "grok_web_search"

# ---------------------------------------------------------------------------
# Provider group sets
# ---------------------------------------------------------------------------

PERPLEXITY_PROVIDERS: frozenset[str] = frozenset({PERPLEXITY_SEARCH, PERPLEXITY_SONAR})
GROK_PROVIDERS: frozenset[str] = frozenset({GROK_OFFICIAL_X, GROK_X_KEYWORD, GROK_WEB_SEARCH})
COINDESK_PROVIDERS: frozenset[str] = frozenset({COINDESK_API})
