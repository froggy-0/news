from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderRolePolicy:
    provider: str
    primary_role: str
    allowed_capabilities: tuple[str, ...]
    forbidden_capabilities: tuple[str, ...]


PERPLEXITY_PROVIDER = "perplexity"
GROK_PROVIDER = "grok"
OPENAI_PROVIDER = "openai"
GEMINI_PROVIDER = "gemini"

CAPABILITY_NEWS_COLLECTION = "news_collection"
CAPABILITY_X_SIGNAL = "x_signal"
CAPABILITY_BTC_ETF_REFERENCE = "btc_etf_reference"
CAPABILITY_BRIEF_GENERATION = "brief_generation"
CAPABILITY_BRIEF_REVIEW = "brief_review"
CAPABILITY_WEB_BACKFILL = "web_backfill"


CAPABILITY_NEWS_FALLBACK = "news_fallback"


PROVIDER_ROLE_POLICIES = {
    PERPLEXITY_PROVIDER: ProviderRolePolicy(
        provider=PERPLEXITY_PROVIDER,
        primary_role="뉴스 수집 + BTC ETF structured response",
        allowed_capabilities=(CAPABILITY_NEWS_COLLECTION, CAPABILITY_BTC_ETF_REFERENCE),
        forbidden_capabilities=(
            CAPABILITY_X_SIGNAL,
            CAPABILITY_BRIEF_GENERATION,
            CAPABILITY_BRIEF_REVIEW,
            CAPABILITY_WEB_BACKFILL,
        ),
    ),
    GROK_PROVIDER: ProviderRolePolicy(
        provider=GROK_PROVIDER,
        primary_role="공식 X 실시간 시그널",
        allowed_capabilities=(CAPABILITY_X_SIGNAL,),
        forbidden_capabilities=(
            CAPABILITY_NEWS_COLLECTION,
            CAPABILITY_BTC_ETF_REFERENCE,
            CAPABILITY_BRIEF_GENERATION,
            CAPABILITY_BRIEF_REVIEW,
            CAPABILITY_WEB_BACKFILL,
        ),
    ),
    OPENAI_PROVIDER: ProviderRolePolicy(
        provider=OPENAI_PROVIDER,
        primary_role="브리핑 생성 + 검수",
        allowed_capabilities=(
            CAPABILITY_BRIEF_GENERATION,
            CAPABILITY_BRIEF_REVIEW,
            CAPABILITY_WEB_BACKFILL,
        ),
        forbidden_capabilities=(
            CAPABILITY_NEWS_COLLECTION,
            CAPABILITY_X_SIGNAL,
            CAPABILITY_BTC_ETF_REFERENCE,
        ),
    ),
    GEMINI_PROVIDER: ProviderRolePolicy(
        provider=GEMINI_PROVIDER,
        primary_role="뉴스 fallback 전담",
        allowed_capabilities=(CAPABILITY_NEWS_FALLBACK,),
        forbidden_capabilities=(
            CAPABILITY_X_SIGNAL,
            CAPABILITY_BTC_ETF_REFERENCE,
            CAPABILITY_BRIEF_GENERATION,
            CAPABILITY_BRIEF_REVIEW,
            CAPABILITY_WEB_BACKFILL,
        ),
    ),
}


def capability_allowed(provider: str, capability: str) -> bool:
    policy = PROVIDER_ROLE_POLICIES[provider]
    return capability in policy.allowed_capabilities


def provider_role_snapshot() -> dict[str, dict[str, object]]:
    return {provider: asdict(policy) for provider, policy in PROVIDER_ROLE_POLICIES.items()}
