from __future__ import annotations

import re

SECTION_HEADING_RE = re.compile(r"^(\d+)\.\s+(.+)$")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'“”‘’(]*[A-Za-z가-힣])")

NOTICE_PREFIX = "[데이터 품질 알림]"
REFERENCE_MARKER = "\n참고 출처\n"

CONCLUSION_LABELS = {"핵심 판단", "한줄 결론", "오늘의 한줄 결론"}
METRIC_LABELS = {"주요 지표", "주요 수치", "핵심 수치", "수치 체크", "핵심 내용", "핵심 이슈"}
INSIGHT_LABELS = {"배경과 해석", "쉽게 보면", "해석", "이렇게 읽으면 좋아요", "이렇게 읽으면 돼요", "왜 중요한지"}
WATCH_LABELS = {"주목할 변수", "오늘 볼 점", "오늘 체크할 포인트", "지금 주의해서 볼 점", "체크 포인트"}
ALL_SUBSECTION_LABELS = CONCLUSION_LABELS | METRIC_LABELS | INSIGHT_LABELS | WATCH_LABELS


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
    current_kind = "conclusion"
    groups = {
        "conclusion": {"label": "핵심 판단", "lines": []},
        "metrics": {"label": "주요 지표", "lines": []},
        "insight": {"label": "배경과 해석", "lines": []},
        "watch": {"label": "주목할 변수", "lines": []},
    }
    explicit_labels_found = False

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            groups[current_kind]["lines"].append("")
            continue

        if line in CONCLUSION_LABELS:
            current_kind = "conclusion"
            explicit_labels_found = True
            continue

        if line in METRIC_LABELS:
            current_kind = "metrics"
            explicit_labels_found = True
            continue

        if line in INSIGHT_LABELS:
            current_kind = "insight"
            explicit_labels_found = True
            continue

        if line in WATCH_LABELS:
            current_kind = "watch"
            explicit_labels_found = True
            continue

        groups[current_kind]["lines"].append(line)

    if not explicit_labels_found:
        paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
        if paragraphs:
            groups["conclusion"]["lines"] = [paragraphs[0]]
            for paragraph in paragraphs[1:]:
                lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
                if lines and all(line.startswith("- ") for line in lines):
                    groups["metrics"]["lines"].extend(lines)
                else:
                    groups["insight"]["lines"].append(paragraph)

    return {
        key: (value["label"], "\n".join(value["lines"]).strip())
        for key, value in groups.items()
    }
