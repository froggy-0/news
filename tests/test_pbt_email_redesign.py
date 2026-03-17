"""Property-Based Tests (P1~P7) for email briefing redesign.

P1: 섹션 파싱 라운드트립
P2: 배지 방향 일관성
P3: 뉴스 아이템 파싱 완전성
P4: 섹터 매핑 유효성
P5: 공포탐욕 레이블 일관성
P6: 데이터 품질 상태 일관성
P7: 스냅샷 배지 개수
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
# Section content: printable text without section heading patterns
import re as _re

import hypothesis.strategies as st
from hypothesis import given, settings

from morning_brief.brief_formatting import (
    SECTION_KEY_MAP,
    SectionMap,
    extract_sections,
    parse_news_items,
    parse_sector_mapping,
    serialize_sections,
)
from morning_brief.emailer import (
    FEAR_GREED_LABELS,
    _build_btc_data,
    _build_email_context_v2,
    _build_snapshot_badges,
)

_HEADING_PAT = _re.compile(r"^\d+(?:-\d+)?\.\s+")

_section_content = (
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\r\x00",
        ),
        min_size=0,
        max_size=80,
    )
    .map(lambda s: s.replace("\n", " ").strip())
    .filter(lambda s: not _HEADING_PAT.match(s))
)

_SECTION_KEYS = [v for v in SECTION_KEY_MAP.values()]


def _section_map_strategy() -> st.SearchStrategy[SectionMap]:
    """Generate valid SectionMap dicts with random content."""
    return st.fixed_dictionaries(
        {"title": st.just("Morning Market Brief")},
        optional={k: _section_content for k in _SECTION_KEYS},
    )


_CIRCLED = ["①", "②", "③", "④", "⑤"]
_SOURCES = ["Reuters", "Bloomberg", "WSJ", "FT", "CNBC", "CoinDesk"]


def _news_block_strategy(count: int = 3) -> st.SearchStrategy[str]:
    """Generate valid Section 4-2 text with 1~count news items."""

    def _build_block(items: list[tuple[str, str, str]]) -> str:
        lines = []
        for i, (headline, body, source) in enumerate(items):
            num = _CIRCLED[i]
            lines.append(f"{num} {headline} — {source}")
            lines.append(body)
            lines.append(f"→ 원문 보기 https://example.com/{i}")
            lines.append(f"핵심 한줄: {headline} 요약")
            lines.append("")
        return "\n".join(lines)

    item_st = st.tuples(
        st.text(
            min_size=3,
            max_size=40,
            alphabet=st.characters(
                whitelist_categories=("L", "N", "Z"),
                blacklist_characters="\r\x00\n",
            ),
        ).filter(lambda s: s.strip()),
        st.text(
            min_size=5,
            max_size=80,
            alphabet=st.characters(
                whitelist_categories=("L", "N", "Z"),
                blacklist_characters="\r\x00\n",
            ),
        ),
        st.sampled_from(_SOURCES),
    )
    return st.lists(item_st, min_size=1, max_size=count).map(_build_block)


def _sector_text_strategy() -> st.SearchStrategy[str]:
    """Generate valid Section 4-3 text with all 3 categories."""

    def _build(items: tuple[list[str], list[str], list[str]]) -> str:
        pos, neg, neu = items
        lines = ["▲ 수혜 방향"]
        for t in pos:
            lines.append(f"- {t} AI 수요 확대")
        lines.append("")
        lines.append("▼ 압력 방향")
        for t in neg:
            lines.append(f"- {t} 유가 하락 압력")
        lines.append("")
        lines.append("— 중립 / 관망")
        for t in neu:
            lines.append(f"- {t} 금리 동결 시 중립")
        return "\n".join(lines)

    ticker_st = st.text(
        min_size=2,
        max_size=5,
        alphabet=st.characters(whitelist_categories=("Lu",)),
    ).filter(lambda s: s.strip())
    return st.tuples(
        st.lists(ticker_st, min_size=1, max_size=3),
        st.lists(ticker_st, min_size=1, max_size=3),
        st.lists(ticker_st, min_size=1, max_size=3),
    ).map(_build)


# ---------------------------------------------------------------------------
# P1: 섹션 파싱 라운드트립
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=2000)
@given(data=_section_map_strategy())
def test_p1_section_roundtrip(data: dict) -> None:
    """extract_sections(serialize_sections(m)) == m for all valid SectionMap."""
    section_map = SectionMap(**data)
    serialized = serialize_sections(section_map)
    recovered = extract_sections(serialized)

    # title should match
    assert recovered.get("title", "") == section_map.get("title", "")

    # All non-empty sections should roundtrip
    for key in _SECTION_KEYS:
        original = section_map.get(key, "")  # type: ignore[literal-required]
        if original:
            assert recovered.get(key, "") == original, (  # type: ignore[literal-required]
                f"Section {key} mismatch: {original!r} != {recovered.get(key, '')!r}"
            )


# ---------------------------------------------------------------------------
# P2: 배지 방향 일관성
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=2000)
@given(change=st.floats(min_value=-50, max_value=50, allow_nan=False, allow_infinity=False))
def test_p2_badge_direction_consistency(change: float) -> None:
    """Badge direction matches sign of change value."""
    packet = {
        "us_indices": [{"ticker": "SPY", "change_pct": change}],
        "bitcoin": {"spot": {"change_pct": 0}},
        "macro": {"VIX": {"value": 15}},
    }
    badges = _build_snapshot_badges(packet)
    spy_badge = badges[0]

    if change > 0:
        assert spy_badge["direction"] == "up"
    elif change < 0:
        assert spy_badge["direction"] == "down"
    else:
        assert spy_badge["direction"] == "flat"


# ---------------------------------------------------------------------------
# P3: 뉴스 아이템 파싱 완전성
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=2000)
@given(text=_news_block_strategy(5))
def test_p3_news_parsing_completeness(text: str) -> None:
    """Parsed news items have non-empty headline and valid number."""
    items = parse_news_items(text)
    assert len(items) >= 1, "Should parse at least 1 news item"
    for item in items:
        assert item["headline"].strip(), "Headline must not be empty"
        assert item["number"] in _CIRCLED, f"Number must be ①~⑤, got {item['number']}"


# ---------------------------------------------------------------------------
# P4: 섹터 매핑 유효성
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=2000)
@given(text=_sector_text_strategy())
def test_p4_sector_mapping_validity(text: str) -> None:
    """If parse_sector_mapping returns non-None, all 3 categories have items with reasons."""
    result = parse_sector_mapping(text)
    if result is not None:
        assert len(result["positive"]) >= 1, "positive must have items"
        assert len(result["negative"]) >= 1, "negative must have items"
        assert len(result["neutral"]) >= 1, "neutral must have items"
        for cat in ("positive", "negative", "neutral"):
            for item in result[cat]:  # type: ignore[literal-required]
                assert item["reason"].strip(), f"reason must not be empty in {cat}"


# ---------------------------------------------------------------------------
# P5: 공포탐욕 레이블 일관성
# ---------------------------------------------------------------------------


@settings(max_examples=101, deadline=2000)
@given(value=st.integers(min_value=0, max_value=100))
def test_p5_fear_greed_label_consistency(value: int) -> None:
    """Fear/greed label matches value range, warning at >= 75."""
    packet = {
        "bitcoin": {
            "spot": {"price": 67000, "change_pct": 0},
            "fear_greed_value": value,
            "etf_points": [],
            "official_etf_daily_flow_btc": 0,
        },
    }
    btc_data = _build_btc_data(packet, "")

    # Check label
    expected_label = "Greed"  # default
    for (lo, hi), label in FEAR_GREED_LABELS.items():
        if lo <= value <= hi:
            expected_label = label
            break
    assert btc_data["fear_greed_label"] == expected_label

    # Check warning
    if value >= 75:
        assert btc_data.get("fear_greed_warning") == "과열 경계"
    else:
        assert btc_data.get("fear_greed_warning", "") == ""


# ---------------------------------------------------------------------------
# P6: 데이터 품질 상태 일관성
# ---------------------------------------------------------------------------


@settings(max_examples=30, deadline=5000)
@given(status=st.sampled_from(["ok", "degraded", "critical"]))
def test_p6_data_quality_consistency(status: str) -> None:
    """ok → empty footer_notes, critical → subject has [데이터 참고]."""
    packet = {
        "data_quality": {"status": status},
        "data_footer_notes": ["테스트 노트"] if status != "ok" else [],
        "us_indices": [{"ticker": "SPY", "change_pct": 0.5}],
        "bitcoin": {"spot": {"price": 67000, "change_pct": 1.0}},
        "macro": {"VIX": {"value": 15}},
    }
    body = "Morning Market Brief\n0. 오늘의 핵심\n테스트 요약"

    ctx = _build_email_context_v2("", body, packet)

    if status == "ok":
        assert ctx["footer_notes"] == []
    if status == "critical":
        assert "[데이터 참고]" in str(ctx["subject"])


# ---------------------------------------------------------------------------
# P7: 스냅샷 배지 개수
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=2000)
@given(
    spy_pct=st.floats(min_value=-20, max_value=20, allow_nan=False, allow_infinity=False),
    qqq_pct=st.floats(min_value=-20, max_value=20, allow_nan=False, allow_infinity=False),
    btc_pct=st.floats(min_value=-30, max_value=30, allow_nan=False, allow_infinity=False),
    vix_val=st.floats(min_value=8, max_value=80, allow_nan=False, allow_infinity=False),
)
def test_p7_snapshot_badge_count(
    spy_pct: float, qqq_pct: float, btc_pct: float, vix_val: float
) -> None:
    """Snapshot badges: <= 4, each has required keys, valid direction."""
    packet = {
        "us_indices": [
            {"ticker": "SPY", "change_pct": spy_pct},
            {"ticker": "QQQ", "change_pct": qqq_pct},
        ],
        "bitcoin": {"spot": {"change_pct": btc_pct}},
        "macro": {"VIX": {"value": vix_val}},
    }
    badges = _build_snapshot_badges(packet)

    assert len(badges) <= 4
    for badge in badges:
        assert "label" in badge
        assert "value" in badge
        assert "direction" in badge
        assert badge["direction"] in ("up", "down", "flat")
