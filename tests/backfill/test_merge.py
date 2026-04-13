"""병합기 단위 테스트."""

from __future__ import annotations

from backfill.merge import merge_articles
from backfill.sources.coindesk import RawArticle


def _cd(id_: str, title: str, date: str = "2024-01-01") -> RawArticle:
    return RawArticle(
        source="coindesk", article_id=id_, date=date, title=title, body="b", published_ts=0
    )


def _al(id_: str, title: str, date: str = "2024-01-01") -> RawArticle:
    return RawArticle(
        source="alpaca", article_id=id_, date=date, title=title, body="b", published_ts=0
    )


# ──────────────────────────────────────────────
# 합산 기사 수 정확성
# ──────────────────────────────────────────────


def test_merge_counts_correctly() -> None:
    """CoinDesk 3개 + Alpaca 2개 = 5개 (중복 없음)."""
    cd = [_cd("1", "A"), _cd("2", "B"), _cd("3", "C")]
    al = [_al("4", "D"), _al("5", "E")]

    result = merge_articles(cd, al)

    assert len(result["2024-01-01"]) == 5


# ──────────────────────────────────────────────
# CoinDesk 우선 보존
# ──────────────────────────────────────────────


def test_coindesk_priority_on_duplicate_title() -> None:
    """동일 title → CoinDesk 기사만 보존."""
    cd = [_cd("cd1", "Bitcoin surges")]
    al = [_al("al1", "Bitcoin surges")]  # 동일 title

    result = merge_articles(cd, al)

    articles = result["2024-01-01"]
    assert len(articles) == 1
    assert articles[0].source == "coindesk"
    assert articles[0].article_id == "cd1"


# ──────────────────────────────────────────────
# 대소문자 무관 중복 처리
# ──────────────────────────────────────────────


def test_case_insensitive_dedup() -> None:
    """'Bitcoin SURGES' vs 'bitcoin surges' → 중복으로 처리."""
    cd = [_cd("1", "Bitcoin SURGES")]
    al = [_al("2", "bitcoin surges")]

    result = merge_articles(cd, al)

    assert len(result["2024-01-01"]) == 1
    assert result["2024-01-01"][0].source == "coindesk"


# ──────────────────────────────────────────────
# 서로 다른 title은 모두 포함
# ──────────────────────────────────────────────


def test_different_titles_both_included() -> None:
    cd = [_cd("1", "BTC rises")]
    al = [_al("2", "ETH drops")]

    result = merge_articles(cd, al)

    assert len(result["2024-01-01"]) == 2


# ──────────────────────────────────────────────
# Alpaca 없을 때
# ──────────────────────────────────────────────


def test_alpaca_empty_returns_coindesk_only() -> None:
    cd = [_cd("1", "A"), _cd("2", "B")]

    result = merge_articles(cd, [])

    assert len(result["2024-01-01"]) == 2
    assert all(a.source == "coindesk" for a in result["2024-01-01"])


# ──────────────────────────────────────────────
# 날짜별 분리
# ──────────────────────────────────────────────


def test_articles_grouped_by_date() -> None:
    cd = [
        _cd("1", "A", date="2024-01-01"),
        _cd("2", "B", date="2024-01-02"),
    ]

    result = merge_articles(cd, [])

    assert len(result["2024-01-01"]) == 1
    assert len(result["2024-01-02"]) == 1
