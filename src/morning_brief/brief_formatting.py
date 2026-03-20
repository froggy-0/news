from __future__ import annotations

import re
from typing import TypedDict

# ---------------------------------------------------------------------------
# V2 데이터 모델 (Section 0~6 구조)
# ---------------------------------------------------------------------------


class SectionMap(TypedDict, total=False):
    """LLM 출력을 섹션별로 파싱한 결과."""

    title: str
    section_0: str  # 오늘의 핵심 (30초 요약)
    section_1: str  # 거시 지표 Dashboard
    section_2: str  # 미국 증시
    section_3: str  # BTC & 크립토
    section_4_1: str  # 이슈 브리핑
    section_4_2: str  # 핵심 뉴스 5선
    section_4_3: str  # 섹터/자산 영향 매핑
    section_5_1: str  # 주간 맥락 연결
    section_5_2: str  # Sonar 교차 분석
    section_5_3: str  # X 시장 반응
    section_6: str  # 이벤트 캘린더


class NewsItemV2(TypedDict):
    """Section 4-2 뉴스 아이템 파싱 결과."""

    number: str  # ①~⑤
    headline: str
    body: str  # 5~8문장 서술 단락
    source_name: str | None
    source_url: str | None
    tldr: str  # 핵심 한줄 요약
    source_tier: int | None  # 1=Tier1


class SectorMappingItem(TypedDict):
    """Section 4-3 개별 매핑 항목."""

    ticker: str
    name: str
    reason: str


class SectorMapping(TypedDict):
    """Section 4-3 전체 매핑."""

    positive: list[SectorMappingItem]
    negative: list[SectorMappingItem]
    neutral: list[SectorMappingItem]
    commentary: str


class EventItem(TypedDict):
    """Section 6 이벤트 캘린더 항목."""

    date: str
    time: str
    name: str
    expected: str
    impact: int  # 1~5
    is_today: bool


class MacroIndicator(TypedDict):
    """Section 1 거시 지표 항목."""

    label: str
    value: str
    change: str
    direction: str  # up / down / flat
    is_previous: bool
    is_anomaly: bool
    status_text: str | None


class StockItem(TypedDict):
    """Section 2 종목 항목."""

    ticker: str
    name: str
    price: str
    change_pct: str
    direction: str  # up / down / flat
    volume: str | None


class BTCData(TypedDict, total=False):
    """Section 3 BTC 데이터."""

    spot_price: str
    spot_change: str
    spot_direction: str
    fear_greed_value: int
    fear_greed_label: str
    etf_items: list[dict]
    official_snapshots: list[dict]
    official_total_btc: str
    official_total_aum: str
    status_text: str


# ---------------------------------------------------------------------------
# V1 레거시 상수 및 패턴
# ---------------------------------------------------------------------------

SECTION_HEADING_RE = re.compile(r"^(\d+(?:-\d+)?)\.\s+(.+)$")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'“”‘’(]*[A-Za-z가-힣])")

NOTICE_PREFIX = "[데이터 품질 알림]"
FOOTER_NOTE_MARKER = "\n데이터 처리 메모\n"
REFERENCE_MARKER = "\n참고 출처\n"

CONCLUSION_LABELS = {"핵심 판단", "한줄 결론", "오늘의 한줄 결론"}
METRIC_LABELS = {"주요 지표", "주요 수치", "핵심 수치", "수치 체크", "핵심 내용", "핵심 이슈"}
INSIGHT_LABELS = {
    "배경과 해석",
    "쉽게 보면",
    "해석",
    "이렇게 읽으면 좋아요",
    "이렇게 읽으면 돼요",
    "왜 중요한지",
}
WATCH_LABELS = {
    "주목할 변수",
    "오늘 볼 점",
    "오늘 체크할 포인트",
    "지금 주의해서 볼 점",
    "체크 포인트",
}
MACRO_LABELS = {"거시 지표", "거시 환경"}
ALL_SUBSECTION_LABELS = (
    CONCLUSION_LABELS | METRIC_LABELS | INSIGHT_LABELS | WATCH_LABELS | MACRO_LABELS
)
SECTION_KIND_BY_LABEL = {
    **{label: "conclusion" for label in CONCLUSION_LABELS},
    **{label: "metrics" for label in METRIC_LABELS},
    **{label: "insight" for label in INSIGHT_LABELS},
    **{label: "watch" for label in WATCH_LABELS},
    **{label: "macro" for label in MACRO_LABELS},
}


class _SectionGroupState(TypedDict):
    label: str
    lines: list[str]


def split_reference_block(body: str) -> tuple[str, list[str]]:
    if REFERENCE_MARKER not in body:
        return body, []

    main_body, raw_references = body.split(REFERENCE_MARKER, 1)
    references = [
        line.strip()[2:].strip()
        for line in raw_references.splitlines()
        if line.strip().startswith("- ")
    ]
    return main_body.strip(), references


def split_footer_note_block(body: str) -> tuple[str, list[str]]:
    if FOOTER_NOTE_MARKER not in body:
        return body, []

    main_body, raw_notes = body.split(FOOTER_NOTE_MARKER, 1)
    notes = [
        line.strip()[2:].strip() for line in raw_notes.splitlines() if line.strip().startswith("- ")
    ]
    return main_body.strip(), notes


def improve_readability_spacing(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if (
            not stripped
            or stripped.startswith(NOTICE_PREFIX)
            or SECTION_HEADING_RE.match(stripped)
            or stripped in ALL_SUBSECTION_LABELS
            or stripped.startswith("- ")
        ):
            lines.append(stripped)
            continue

        expanded = SENTENCE_BREAK_RE.sub("\n\n", stripped)
        lines.extend(part.strip() for part in expanded.splitlines())

    compacted: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        compacted.append(line)
        previous_blank = is_blank
    return "\n".join(compacted).strip()


def extract_brief_structure(body: str) -> tuple[str, str, list[tuple[str, str]]]:
    lines = [line.rstrip() for line in body.replace("\r\n", "\n").split("\n")]
    title = lines[0].strip() if lines else "Morning Market Brief"

    notice = ""
    start_index = 1
    if len(lines) > 1 and lines[1].strip().startswith(NOTICE_PREFIX):
        notice = lines[1].strip()
        start_index = 2

    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    def flush_section() -> None:
        nonlocal current_heading, current_lines
        if not current_heading:
            return
        sections.append((current_heading, "\n".join(current_lines).strip()))
        current_heading = ""
        current_lines = []

    for raw_line in lines[start_index:]:
        line = raw_line.strip()
        if not line and not current_heading:
            continue

        match = SECTION_HEADING_RE.match(line)
        if match:
            flush_section()
            current_heading = match.group(2).strip()
            continue

        if current_heading:
            current_lines.append(raw_line.strip())

    flush_section()
    return title, notice, sections


def split_section_groups(content: str) -> dict[str, tuple[str, str]]:
    normalized = improve_readability_spacing(content)
    groups: dict[str, _SectionGroupState] = {
        "conclusion": {"label": "핵심 판단", "lines": []},
        "metrics": {"label": "주요 지표", "lines": []},
        "insight": {"label": "배경과 해석", "lines": []},
        "watch": {"label": "주목할 변수", "lines": []},
        "macro": {"label": "거시 지표", "lines": []},
    }
    explicit_labels_found = _collect_section_groups(
        normalized,
        groups,
    )
    if not explicit_labels_found:
        _backfill_section_groups_without_labels(normalized, groups)

    return {
        key: (value["label"], "\n".join(value["lines"]).strip()) for key, value in groups.items()
    }


def _collect_section_groups(
    normalized: str,
    groups: dict[str, _SectionGroupState],
) -> bool:
    current_kind = "conclusion"
    explicit_labels_found = False
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            groups[current_kind]["lines"].append("")
            continue

        next_kind = SECTION_KIND_BY_LABEL.get(line)
        if next_kind is not None:
            current_kind = next_kind
            explicit_labels_found = True
            continue

        groups[current_kind]["lines"].append(line)
    return explicit_labels_found


def _backfill_section_groups_without_labels(
    normalized: str,
    groups: dict[str, _SectionGroupState],
) -> None:
    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    if not paragraphs:
        return

    groups["conclusion"]["lines"] = [paragraphs[0]]
    for paragraph in paragraphs[1:]:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if lines and all(line.startswith("- ") for line in lines):
            groups["metrics"]["lines"].extend(lines)
        else:
            groups["insight"]["lines"].append(paragraph)


# ---------------------------------------------------------------------------
# V2 섹션 파싱 (Section 0~6 구조)
# ---------------------------------------------------------------------------

SECTION_HEADING_V2_RE = SECTION_HEADING_RE

SECTION_KEY_MAP: dict[str, str] = {
    "0": "section_0",
    "1": "section_1",
    "2": "section_2",
    "3": "section_3",
    "4-1": "section_4_1",
    "4-2": "section_4_2",
    "4-3": "section_4_3",
    "5-1": "section_5_1",
    "5-2": "section_5_2",
    "5-3": "section_5_3",
    "6": "section_6",
}

SECTION_TITLES: dict[str, str] = {
    "section_0": "0. 오늘의 핵심",
    "section_1": "1. 거시 지표 Dashboard",
    "section_2": "2. 미국 증시",
    "section_3": "3. BTC & 크립토",
    "section_4_1": "4-1. 이슈 브리핑",
    "section_4_2": "4-2. 핵심 뉴스 5선",
    "section_4_3": "4-3. 섹터/자산 영향 매핑",
    "section_5_1": "5-1. 주간 맥락 연결",
    "section_5_2": "5-2. Sonar 교차 분석",
    "section_5_3": "5-3. X 시장 반응",
    "section_6": "6. 이벤트 캘린더",
}


def _is_legacy_layer_format(body: str) -> bool:
    return False


def extract_sections(body: str) -> SectionMap:
    """새 섹션 구조(0~6)의 LLM 출력을 파싱하여 SectionMap 반환.

    누락된 섹션은 빈 문자열로 처리.
    기존 LAYER 구조 감지 시 레거시 파싱으로 폴백.
    """
    if False:
        pass

    lines = body.replace("\r\n", "\n").split("\n")
    title = lines[0].strip() if lines else "Morning Market Brief"

    section_map = SectionMap(title=title)
    current_key: str | None = None
    current_lines: list[str] = []

    for line in lines[1:]:
        match = SECTION_HEADING_V2_RE.match(line.strip())
        if match:
            if current_key:
                section_map[current_key] = "\n".join(current_lines).strip()  # type: ignore[literal-required]
            num = match.group(1)
            current_key = SECTION_KEY_MAP.get(num)
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key:
        section_map[current_key] = "\n".join(current_lines).strip()  # type: ignore[literal-required]

    return section_map


def serialize_sections(section_map: SectionMap) -> str:
    """SectionMap을 LLM 출력 형식 텍스트로 직렬화."""
    parts = [section_map.get("title", "Morning Market Brief")]
    for key, heading in SECTION_TITLES.items():
        content = section_map.get(key, "")
        if content:
            parts.append(f"\n{heading}\n{content}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# V2 뉴스 아이템 파싱 (Section 4-2)
# ---------------------------------------------------------------------------

_CIRCLED_DIGITS = "①②③④⑤"
_NEWS_SPLIT_RE = re.compile(r"(?=^[①②③④⑤])", re.MULTILINE)
NEWS_ITEM_RE = re.compile(r"^([①②③④⑤])\s+(.+?)(?:\s*[—–-]\s*(.+))?$")
LINK_RE = re.compile(r"→\s*원문\s*(?:보기|링크)?\s*(https?://\S+)")
TLDR_RE = re.compile(r"(?:핵심\s*한줄|TL;?DR)[:\s]*(.+)", re.IGNORECASE)

_TIER1_SOURCES: set[str] = {
    "Reuters",
    "Bloomberg",
    "WSJ",
    "FT",
    "CNBC",
    "CoinDesk",
    "The Wall Street Journal",
    "Financial Times",
}


def parse_news_items(section_4_2: str) -> list[NewsItemV2]:
    """Section 4-2 텍스트를 NewsItemV2 리스트로 파싱. 최대 5개."""
    if not section_4_2.strip():
        return []

    items: list[NewsItemV2] = []
    blocks = _NEWS_SPLIT_RE.split(section_4_2)

    for block in blocks:
        block = block.strip()
        if not block or block[0] not in _CIRCLED_DIGITS:
            continue

        block_lines = block.splitlines()
        first_match = NEWS_ITEM_RE.match(block_lines[0].strip())
        if not first_match:
            continue

        number = first_match.group(1)
        headline = first_match.group(2).strip()
        source_name = first_match.group(3).strip() if first_match.group(3) else None

        body_lines: list[str] = []
        url: str | None = None
        tldr = ""

        for line in block_lines[1:]:
            link_match = LINK_RE.search(line)
            if link_match:
                url = link_match.group(1)
                continue
            tldr_match = TLDR_RE.match(line.strip())
            if tldr_match:
                tldr = tldr_match.group(1).strip()
                continue
            body_lines.append(line)

        body_raw = "\n".join(body_lines).strip()
        # 중복 단락 제거: LLM이 같은 단락을 반복 생성하는 경우 대응
        seen_paras: list[str] = []
        for para in re.split(r"\n{2,}", body_raw):
            para = para.strip()
            if para and para not in seen_paras:
                seen_paras.append(para)
        body_deduped = "\n\n".join(seen_paras)

        items.append(
            NewsItemV2(
                number=number,
                headline=headline,
                body=body_deduped,
                source_name=source_name,
                source_url=url,
                tldr=tldr,
                source_tier=1 if source_name and source_name in _TIER1_SOURCES else None,
            )
        )

    return items[:5]


# ---------------------------------------------------------------------------
# V2 섹터 매핑 파싱 (Section 4-3)
# ---------------------------------------------------------------------------

SECTOR_DIRECTION_RE = re.compile(r"^(수혜|압력|중립)\s*(?:방향)?\s*\(?\s*([+\-]?)\s*\)?")


def parse_sector_mapping(section_4_3: str) -> SectorMapping | None:
    """Section 4-3 텍스트를 SectorMapping으로 파싱.

    3분류 중 하나라도 비어있으면 None 반환.
    """
    if not section_4_3.strip():
        return None

    mapping: SectorMapping = {
        "positive": [],
        "negative": [],
        "neutral": [],
        "commentary": "",
    }
    _DIRECTION_MAP = {"수혜": "positive", "압력": "negative", "중립": "neutral"}
    current_direction: str | None = None
    commentary_lines: list[str] = []
    in_commentary = False

    for line in section_4_3.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_direction and mapping[current_direction]:  # type: ignore[literal-required]
                in_commentary = True
            continue

        dir_match = SECTOR_DIRECTION_RE.match(stripped)
        if dir_match:
            label = dir_match.group(1)
            current_direction = _DIRECTION_MAP[label]
            in_commentary = False
            continue

        if in_commentary:
            commentary_lines.append(stripped)
            continue

        if current_direction:
            # 항목 파싱: "TICKER reason" 또는 "  TICKER reason"
            parts = stripped.lstrip("- ").strip().split(None, 1)
            if len(parts) >= 2:
                mapping[current_direction].append(  # type: ignore[literal-required]
                    SectorMappingItem(ticker=parts[0], name=parts[0], reason=parts[1])
                )
            elif len(parts) == 1:
                mapping[current_direction].append(  # type: ignore[literal-required]
                    SectorMappingItem(ticker=parts[0], name=parts[0], reason="")
                )

    mapping["commentary"] = "\n".join(commentary_lines).strip()

    if not mapping["positive"] or not mapping["negative"] or not mapping["neutral"]:
        return None

    return mapping


# ---------------------------------------------------------------------------
# V2 이벤트 캘린더 파싱 (Section 6)
# ---------------------------------------------------------------------------

EVENT_LINE_RE = re.compile(r"(\d{1,2}:\d{2})?\s*(.+?)\s+(?:예상\s+)?([^\s■□]+)?\s*((?:[■□]){1,5})")


def parse_event_calendar(section_6: str) -> list[EventItem]:
    """Section 6 텍스트를 EventItem 리스트로 파싱."""
    if not section_6.strip():
        return []

    items: list[EventItem] = []
    current_date = ""
    is_today_block = False

    for line in section_6.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if "오늘" in stripped and ("발표" in stripped or "예정" in stripped):
            is_today_block = True
            date_match = re.search(r"\d{1,2}/\d{1,2}", stripped)
            if date_match:
                current_date = date_match.group(0)
            continue

        if "이번 주" in stripped or "이번주" in stripped:
            is_today_block = False
            continue

        date_line_match = re.match(r"(\d{1,2}/\d{1,2})\s*(.*)", stripped)
        if date_line_match and not EVENT_LINE_RE.match(stripped):
            current_date = date_line_match.group(1)
            is_today_block = False
            continue

        match = EVENT_LINE_RE.match(stripped)
        if match:
            impact_str = match.group(4)
            items.append(
                EventItem(
                    date=current_date,
                    time=match.group(1) or "",
                    name=match.group(2).strip(),
                    expected=match.group(3) or "",
                    impact=impact_str.count("■"),
                    is_today=is_today_block,
                )
            )

    return items
