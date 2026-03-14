from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from morning_brief.brief_formatting import (
    extract_brief_structure,
    split_footer_note_block,
    split_reference_block,
    split_section_groups,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"
OBSERVABILITY_DIRNAME = "observability"
BRIEF_GLOB = "brief_*.md"
URL_RE = re.compile(r"https?://\S+")
KOREAN_RE = re.compile(r"[가-힣]")
JUDGEMENT_TOKENS = ("매수 관심", "관망", "리스크 주의")
FEAR_GREED_LABELS = ("극단적 공포", "공포", "중립", "탐욕", "극단적 탐욕")
STOCK_CAUSE_RE = re.compile(
    r"^(?P<name>.+?)(?:는|은)\s.+(?:으로|로|속에)\s+\d[\d,.]*%\s+(?:상승|하락|보합)했습니다\.",
)


@dataclass(frozen=True)
class BriefQualityCheck:
    category: str
    label: str
    status: str
    detail: str = ""


def _find_latest_brief_file(output_dir: Path) -> Path | None:
    candidates = sorted(output_dir.glob(BRIEF_GLOB))
    if not candidates:
        return None
    return candidates[-1]


def _metric_lines(section_content: str) -> list[str]:
    metrics_text = split_section_groups(section_content)["metrics"][1]
    return [
        line.strip()[2:].strip()
        for line in metrics_text.splitlines()
        if line.strip().startswith("- ")
    ]


def _layer_three_lines(section_content: str) -> tuple[list[str], list[str]]:
    stock_lines: list[str] = []
    macro_lines: list[str] = []
    in_macro = False
    for raw_line in split_section_groups(section_content)["metrics"][1].splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == "거시 지표":
            in_macro = True
            continue
        if not stripped.startswith("- "):
            continue
        line = stripped[2:].strip()
        if in_macro:
            macro_lines.append(line)
        else:
            stock_lines.append(line)
    return stock_lines, macro_lines


def _parse_news_title(line: str) -> str:
    return line.split("|", 1)[0].strip()


def _extract_subject(line: str) -> str:
    match = re.match(r"^\s*(.+?)(?:는|은)\s", line)
    if match:
        return match.group(1).strip()
    return line.strip()


def _extract_macro_label(line: str) -> str:
    for token in ("는 ", "은 "):
        if token in line:
            return line.split(token, 1)[0].strip()
    return line.strip()


def _build_checks(brief_path: Path) -> list[BriefQualityCheck]:
    raw_text = brief_path.read_text(encoding="utf-8")
    body_without_references, references = split_reference_block(raw_text)
    body_without_footer, _ = split_footer_note_block(body_without_references)
    _title, _notice, sections = extract_brief_structure(body_without_footer)
    section_map = {heading: content for heading, content in sections}

    layer_one = section_map.get("LAYER 1 | 오늘 한줄 판단", "")
    layer_two = section_map.get("LAYER 2 | 주요 뉴스", "")
    layer_three = section_map.get("LAYER 3 | 종목 브리핑", "")
    layer_two_items = _metric_lines(layer_two) if layer_two else []
    stock_lines, macro_lines = _layer_three_lines(layer_three) if layer_three else ([], [])
    titles = [_parse_news_title(line) for line in layer_two_items]
    stock_subjects = [_extract_subject(line) for line in stock_lines]
    macro_subjects = [_extract_macro_label(line) for line in macro_lines]
    checks: list[BriefQualityCheck] = []

    def add(
        category: str, label: str, passed: bool, detail: str = "", *, warn: bool = False
    ) -> None:
        status = "WARN" if warn else ("PASS" if passed else "FAIL")
        checks.append(
            BriefQualityCheck(category=category, label=label, status=status, detail=detail)
        )

    add(
        "구조 검증",
        "LAYER 1 존재",
        bool(layer_one),
        "LAYER 1 섹션을 찾지 못했습니다." if not layer_one else "",
    )
    add(
        "구조 검증",
        "LAYER 2 뉴스 2개 이상",
        len(layer_two_items) >= 2,
        f"뉴스 bullet 수가 {len(layer_two_items)}개입니다." if len(layer_two_items) < 2 else "",
    )
    add(
        "구조 검증",
        "LAYER 3 종목 브리핑 2개 이상",
        bool(layer_three) and len(stock_lines) >= 2,
        "LAYER 3 섹션 또는 종목 bullet 수가 부족합니다."
        if not (layer_three and len(stock_lines) >= 2)
        else "",
    )
    add(
        "구조 검증",
        "거시 지표 섹션 존재",
        "거시 지표" in layer_three and bool(macro_lines),
        "거시 지표 소제목 또는 bullet이 없습니다."
        if not ("거시 지표" in layer_three and macro_lines)
        else "",
    )
    add(
        "구조 검증",
        "출처 섹션 존재",
        bool(references),
        "하단 참고 출처 섹션이 없습니다." if not references else "",
    )

    has_judgement = any(token in layer_one for token in JUDGEMENT_TOKENS)
    add(
        "콘텐츠 품질",
        "LAYER 1 판단 결론 포함",
        has_judgement,
        "매수/관망/리스크 주의 판단 문구가 없습니다." if not has_judgement else "",
    )
    has_kospi_line = "오늘 미국 증시 흐름이 코스피에 미치는 영향:" in layer_one
    add(
        "콘텐츠 품질",
        "LAYER 1 코스피 영향 한줄",
        has_kospi_line,
        "코스피 영향 문장이 없습니다." if not has_kospi_line else "",
    )
    korean_titles = bool(titles) and all(KOREAN_RE.search(title) for title in titles)
    add(
        "콘텐츠 품질",
        "LAYER 2 뉴스 제목 한국어",
        korean_titles,
        "영문 제목이 그대로 노출됐거나 뉴스 항목이 없습니다." if not korean_titles else "",
    )
    has_none = "None" in layer_two or "none" in layer_two or "null" in layer_two
    add(
        "콘텐츠 품질",
        "LAYER 2 None 노출 없음",
        not has_none,
        "LAYER 2에 None/null 문자열이 노출됩니다." if has_none else "",
    )
    cause_ok = bool(stock_lines) and all(STOCK_CAUSE_RE.search(line) for line in stock_lines)
    add(
        "콘텐츠 품질",
        "Layer 문자열 미노출",
        "Layer" not in raw_text,
        "Layer 문자열이 그대로 노출됩니다." if "Layer" in raw_text else "",
    )
    add(
        "콘텐츠 품질",
        "LAYER 3 종목 브리핑 원인 포함",
        cause_ok,
        "종목 브리핑이 원인+등락률 자연어 형식을 따르지 않습니다." if not cause_ok else "",
    )
    duplicate_stocks = sorted({name for name in stock_subjects if stock_subjects.count(name) > 1})
    add(
        "콘텐츠 품질",
        "종목 브리핑 중복 없음",
        not duplicate_stocks,
        f"중복 종목: {', '.join(duplicate_stocks)}" if duplicate_stocks else "",
    )
    duplicate_macros = sorted({name for name in macro_subjects if macro_subjects.count(name) > 1})
    add(
        "콘텐츠 품질",
        "거시 지표 중복 없음",
        not duplicate_macros,
        f"중복 거시 지표: {', '.join(duplicate_macros)}" if duplicate_macros else "",
    )

    add(
        "신규 지표",
        "원/달러 환율",
        "원/달러 환율" in raw_text,
        "원/달러 환율이 미포함입니다." if "원/달러 환율" not in raw_text else "",
    )
    has_nq_direction = bool(re.search(r"나스닥 선물.*(상승|하락|보합)", raw_text))
    add(
        "신규 지표",
        "나스닥 선물 방향",
        has_nq_direction,
        "나스닥 선물 방향 문구가 없습니다." if not has_nq_direction else "",
    )
    has_fear_greed = any(label in raw_text for label in FEAR_GREED_LABELS)
    add(
        "신규 지표",
        "공포탐욕지수 수준 판단",
        has_fear_greed,
        "공포탐욕지수 수준 문구가 없습니다." if not has_fear_greed else "",
    )

    reference_count = raw_text.count("참고 출처")
    add(
        "출처 검증",
        "출처 섹션 하단 단일 위치",
        reference_count == 1
        and raw_text.rfind("참고 출처") > raw_text.find("3. LAYER 3 | 종목 브리핑"),
        f"참고 출처 섹션 개수={reference_count}" if reference_count != 1 else "",
    )
    body_has_url = bool(URL_RE.search(body_without_footer))
    add(
        "출처 검증",
        "본문 내 URL 노출 없음",
        not body_has_url,
        "본문에 URL이 직접 노출됩니다." if body_has_url else "",
    )
    has_google_news = any("news.google.com" in reference for reference in references)
    add(
        "출처 검증",
        "news.google.com URL 여부",
        not has_google_news,
        "news.google.com 리다이렉트 URL이 포함돼 있습니다." if has_google_news else "",
        warn=has_google_news,
    )
    return checks


def _summarize_checks(checks: list[BriefQualityCheck]) -> dict[str, int]:
    return {
        "total": len(checks),
        "pass": sum(1 for check in checks if check.status == "PASS"),
        "fail": sum(1 for check in checks if check.status == "FAIL"),
        "warn": sum(1 for check in checks if check.status == "WARN"),
    }


def _format_report(brief_path: Path, checks: list[BriefQualityCheck]) -> str:
    summary = _summarize_checks(checks)
    lines = [f"브리핑 품질 검증: {brief_path}", ""]
    categories = ["구조 검증", "콘텐츠 품질", "신규 지표", "출처 검증"]
    for category in categories:
        category_checks = [check for check in checks if check.category == category]
        if not category_checks:
            continue
        passed = sum(1 for check in category_checks if check.status == "PASS")
        failed = sum(1 for check in category_checks if check.status == "FAIL")
        warned = sum(1 for check in category_checks if check.status == "WARN")
        label = (
            category.replace(" 검증", "")
            .replace("콘텐츠 품질", "품질")
            .replace("신규 지표", "지표")
        )
        line = f"{label:<4} PASS: {passed}/{len(category_checks)}"
        if failed:
            line = f"{label:<4} FAIL: {failed}/{len(category_checks)}"
        elif warned:
            line = f"{label:<4} WARN: {warned}/{len(category_checks)}"
        lines.append(line)

    lines.append("")
    lines.append("상세 결과")
    current_category = ""
    for check in checks:
        if check.category != current_category:
            current_category = check.category
            lines.append(f"[{current_category}]")
        line = f"- {check.label}: {check.status}"
        if check.detail:
            line = f"{line} ← {check.detail}"
        lines.append(line)
    lines.append(
        f"총 {summary['total']}개 항목 중 {summary['pass']}개 PASS, {summary['fail']}개 FAIL, {summary['warn']}개 WARN"
    )
    return "\n".join(lines)


def _write_report_log(brief_path: Path, checks: list[BriefQualityCheck]) -> Path:
    observability_dir = brief_path.parent / OBSERVABILITY_DIRNAME
    observability_dir.mkdir(parents=True, exist_ok=True)
    log_path = observability_dir / f"brief-quality-{brief_path.stem}.json"
    payload = {
        "brief_path": str(brief_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": _summarize_checks(checks),
        "checks": [asdict(check) for check in checks],
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def validate_brief_quality(brief_path: Path) -> tuple[list[BriefQualityCheck], str, Path]:
    checks = _build_checks(brief_path)
    report = _format_report(brief_path, checks)
    log_path = _write_report_log(brief_path, checks)
    return checks, report, log_path


def _passing_brief_text() -> str:
    return """Morning Market Brief (2026-03-14)

1. LAYER 1 | 오늘 한줄 판단
핵심 판단
오늘은 관망 국면입니다.
미국 10년물 금리가 높아 추가 확인이 필요합니다.

주요 지표
- 원/달러 환율은 1,330.50원으로 전일 대비 +0.12%였습니다. [출처: yfinance]
- 나스닥 선물은 전일 대비 +0.48%로 상승 방향입니다. [출처: yfinance]
- 공포탐욕지수는 60으로 탐욕 구간입니다. [출처: alternative.me]

배경과 해석
금리와 지수 흐름이 엇갈렸습니다.

오늘 미국 증시 흐름이 코스피에 미치는 영향: 나스닥 선물이 견조해 코스피 대형 기술주 심리를 받쳐줄 수 있습니다.

주목할 변수
- 금리와 성장주 반응이 다시 같은 방향으로 모이는지 보겠습니다.

2. LAYER 2 | 주요 뉴스
핵심 이슈
- 엔비디아가 새 AI 클러스터를 공개했습니다 | AI 투자 기대를 자극했습니다.
- 애플이 신규 서비스 전략을 제시했습니다 | 빅테크 수요를 확인했습니다.
- 비트코인 ETF 자금 유입이 이어졌습니다 | 수급 심리를 지지했습니다.

배경과 해석
오늘 뉴스는 AI 투자와 ETF 수급에 집중됐습니다.

주목할 변수
- 같은 주제를 다른 신뢰 출처도 다루는지 보겠습니다.

3. LAYER 3 | 종목 브리핑
주요 지표
- AVGO는 전반적 시장 하락 영향으로 4.11% 하락했습니다. [출처: Stooq]
- META는 광고 업종 약세 흐름으로 3.83% 하락했습니다. [출처: Stooq]
- NVDA는 AI 투자 관련 뉴스 흐름 속에 1.20% 상승했습니다. [출처: Stooq]
- 비트코인은 비트코인 ETF 수급 뉴스 흐름으로 0.16% 하락했습니다. [출처: CoinGecko]

거시 지표
- 달러 인덱스는 100.49였습니다. [출처: yfinance]
- 미국 10년물 금리는 4.10%였습니다. [출처: FRED]
- VIX는 17.50이었습니다. [출처: FRED]

배경과 해석
종목별로는 AI 관련주와 플랫폼주의 반응이 갈렸습니다.

주목할 변수
- 기술주와 반도체의 상대 강도를 보겠습니다.

참고 출처
- 엔비디아가 새 AI 클러스터를 공개했습니다 — https://www.reuters.com/world/us/example
- 애플이 신규 서비스 전략을 제시했습니다 — https://www.cnbc.com/2026/03/14/example.html
- 비트코인 ETF 자금 유입이 이어졌습니다 — https://www.wsj.com/articles/example
"""


def _failing_brief_text() -> str:
    return """Morning Market Brief (2026-03-14)

1. LAYER 1 | 오늘 한줄 판단
핵심 판단
미국 시장은 여러 자산이 혼재했습니다.

2. LAYER 2 | 주요 뉴스
핵심 이슈
- Nvidia unveils new AI cluster | None
- Apple launches service | 수요를 봅니다.
- Bitcoin ETF inflows resume | 기사입니다.

3. LAYER 3 | 종목 브리핑
주요 지표
- AVGO는 4.11% 하락했습니다. [출처: Stooq]
- AVGO는 4.11% 하락했습니다. [출처: Stooq]

거시 지표
- 달러 인덱스는 100.49였습니다. [출처: yfinance]
- 달러 인덱스는 100.49였습니다. [출처: yfinance]

참고 출처
- Nvidia unveils new AI cluster — https://news.google.com/rss/articles/CBMiQWh0dHBzOi8vZXhhbXBsZS5jb20?oc=5
"""


def test_validate_brief_quality_uses_latest_brief_file_and_saves_log(
    tmp_path: Path, capsys
) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True)
    older = output_dir / "brief_20260314_0900.md"
    latest = output_dir / "brief_20260314_1302.md"
    older.write_text(_failing_brief_text(), encoding="utf-8")
    latest.write_text(_passing_brief_text(), encoding="utf-8")

    brief_path = _find_latest_brief_file(output_dir)

    assert brief_path == latest
    checks, report, log_path = validate_brief_quality(brief_path)
    print(report)
    captured = capsys.readouterr()

    summary = _summarize_checks(checks)
    assert "브리핑 품질 검증:" in captured.out
    assert "구조" in captured.out
    assert "품질" in captured.out
    assert "지표" in captured.out
    assert "출처" in captured.out
    assert summary["fail"] == 0
    assert summary["warn"] == 0
    assert log_path.exists()
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["brief_path"] == str(latest)
    assert payload["summary"]["pass"] == summary["pass"]


def test_validate_brief_quality_detects_failures_and_warning(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True)
    brief_path = output_dir / "brief_20260314_1317.md"
    brief_path.write_text(_failing_brief_text(), encoding="utf-8")

    checks, report, log_path = validate_brief_quality(brief_path)
    print(report)
    captured = capsys.readouterr()

    summary = _summarize_checks(checks)
    assert summary["fail"] >= 1
    assert summary["warn"] == 1
    assert "- LAYER 1 판단 결론 포함: FAIL" in captured.out
    assert "- LAYER 2 뉴스 제목 한국어: FAIL" in captured.out
    assert "- news.google.com URL 여부: WARN" in captured.out
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["summary"]["warn"] == 1
    assert any(check["status"] == "FAIL" for check in payload["checks"])


def test_validate_latest_repo_brief_if_present() -> None:
    latest = _find_latest_brief_file(OUTPUT_DIR)
    if latest is None:
        pytest.skip("outputs/brief_*.md 파일이 아직 없어 실제 출력물 검증은 건너뜁니다.")

    checks, report, _log_path = validate_brief_quality(latest)
    print(report)
    summary = _summarize_checks(checks)
    assert summary["fail"] == 0
