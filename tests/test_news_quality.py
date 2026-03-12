from __future__ import annotations

from datetime import datetime, timedelta, timezone

from morning_brief.data import news
from morning_brief.models import NewsItem



def test_normalize_url_strips_tracking_params():
    raw = "https://example.com/path?a=1&utm_source=x&gclid=123#frag"
    normalized = news._normalize_url(raw)
    assert normalized == "https://example.com/path?a=1"



def test_item_score_prefers_preferred_domain():
    now = datetime.now(timezone.utc)
    preferred = NewsItem(
        title="Fed signals rate path",
        url="https://www.reuters.com/world/us/fed-signals-rate-path/",
        source="Reuters",
        published_at=now,
    )
    non_preferred = NewsItem(
        title="Fed signals rate path",
        url="https://randomblog.example.com/fed-signals-rate-path",
        source="Blog",
        published_at=now,
    )
    assert news._item_score(preferred) > news._item_score(non_preferred)



def test_dedup_and_rank_keeps_highest_scored_duplicate():
    now = datetime.now(timezone.utc)
    low = NewsItem(
        title="Bitcoin ETF flow rises",
        url="https://www.reuters.com/markets/a?utm_source=x",
        source="Reuters",
        published_at=now - timedelta(hours=12),
    )
    high = NewsItem(
        title="Bitcoin ETF flow rises",
        url="https://www.reuters.com/markets/a?utm_campaign=y",
        source="Reuters",
        published_at=now,
    )

    ranked = news._dedup_and_rank([low, high], max_items=5)
    assert len(ranked) == 1
    assert ranked[0].published_at == high.published_at


def test_is_preferred_domain_rejects_substring_spoof():
    assert not news._is_preferred_domain("https://totallynotreuters.com/market")
    assert not news._is_preferred_domain("https://news.reuters.com.evil.tld/path")


def test_domain_score_rejects_substring_spoof():
    assert news._domain_score("https://totallynotreuters.com/market") == 0.0
    assert news._domain_score("https://news.reuters.com.evil.tld/path") == 0.0
