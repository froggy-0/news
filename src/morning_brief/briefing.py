from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from morning_brief.brief_formatting import (
    extract_brief_structure,
    improve_readability_spacing,
    split_section_groups,
)
from morning_brief.brief_review import validate_and_rewrite_briefing
from morning_brief.config import Settings
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.observability import PipelineObserver
from morning_brief.openai_utils import cached_input_tokens, usage_snapshot
from morning_brief.prompting import build_prompt_cache_key, render_brief_prompts

logger = logging.getLogger(__name__)

REQUIRED_LAYER_HEADINGS = (
    "LAYER 1 | 오늘 한줄 판단",
    "LAYER 2 | 주요 뉴스",
    "LAYER 3 | 종목 브리핑",
)
MIN_LAYER_TWO_BULLETS = 2
MIN_LAYER_THREE_BULLETS = 2


def _point_price(point: dict) -> float | None:
    resolved = point.get("resolved_value")
    if resolved is not None:
        return float(resolved)

    raw_price = point.get("price")
    if raw_price is None:
        return None

    return float(raw_price)


def _point_change_pct(point: dict) -> float | None:
    raw_change = point.get("change_pct")
    if raw_change is None:
        return None
    return float(raw_change)


def _point_suffix(point: dict) -> str:
    if (
        bool(point.get("is_previous_value"))
        or str(point.get("validation_status", "")) == "previous_value"
    ):
        return " (전일 값)"
    return ""


def _fmt_point(point: dict) -> str:
    price = _point_price(point)
    change_pct = _point_change_pct(point)
    if price is None or change_pct is None:
        return ""
    sign = "+" if change_pct >= 0 else ""
    return f"{point['label']} {price:.2f} ({sign}{change_pct:.2f}%){_point_suffix(point)}"


def _format_points(points: list[dict], empty_text: str) -> str:
    formatted = [text for point in points if (text := _fmt_point(point))]
    if not formatted:
        return empty_text
    return " / ".join(formatted)


def _point_by_key(points: list[dict], canonical_key: str) -> dict:
    for point in points:
        if str(point.get("canonical_key", "")).strip() == canonical_key:
            return point
    return {}


def _quality_notice(packet: dict) -> str:
    quality = packet.get("data_quality", {})
    if not isinstance(quality, dict):
        return ""

    status = str(quality.get("status", "ok")).lower()
    warnings = quality.get("warnings", [])
    if status == "ok" or not isinstance(warnings, list) or not warnings:
        return ""

    top_warnings = [str(w).strip() for w in warnings if str(w).strip()][:2]
    if not top_warnings:
        return ""

    return f"[데이터 품질 알림] {' / '.join(top_warnings)}."


def _inject_quality_notice(text: str, packet: dict) -> str:
    notice = _quality_notice(packet)
    if not notice:
        return text

    if notice in text:
        return text

    lines = text.splitlines()
    if not lines:
        return notice

    if lines[0].startswith("Morning Market Brief"):
        return "\n".join([lines[0], notice, *lines[1:]]).strip()

    return f"{notice}\n\n{text}".strip()


def _append_reference_block(text: str, packet: dict) -> str:
    news_items = packet.get("news", [])
    web_references = packet.get("web_search_references", [])
    if not isinstance(news_items, list):
        news_items = []
    if not isinstance(web_references, list):
        web_references = []
    if not news_items and not web_references:
        return text

    lines = ["참고 출처"]
    seen: set[str] = set()
    _append_news_reference_lines(lines, seen, news_items)
    _append_web_reference_lines(lines, seen, web_references)

    if len(lines) == 1:
        return text

    return f"{text.rstrip()}\n\n" + "\n".join(lines)


def _append_news_reference_lines(
    lines: list[str],
    seen: set[str],
    news_items: list[dict],
) -> None:
    for item in news_items[:5]:
        if not isinstance(item, dict):
            continue
        url = _news_reference(item)
        if not url or url == "출처 없음" or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title", "")).strip() or "출처"
        lines.append(f"- {title} — {url}")


def _append_web_reference_lines(
    lines: list[str],
    seen: set[str],
    web_references: list[dict],
) -> None:
    for item in web_references[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or "출처"
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        lines.append(f"- {title} — {url}")


def _append_footer_note_block(text: str, packet: dict) -> str:
    notes = packet.get("data_footer_notes", [])
    if not isinstance(notes, list) or not notes:
        return text

    lines = ["데이터 처리 메모"]
    for note in notes:
        note_text = str(note).strip()
        if note_text:
            lines.append(f"- {note_text}")

    if len(lines) == 1:
        return text

    return f"{text.rstrip()}\n\n" + "\n".join(lines)


_improve_readability_spacing = improve_readability_spacing


def _count_metric_bullets(text: str, *, stop_at_label: str | None = None) -> int:
    count = 0
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stop_at_label is not None and stripped == stop_at_label:
            break
        if stripped.startswith("- "):
            count += 1
    return count


def _count_section_bullets(text: str, *, stop_at_label: str | None = None) -> int:
    count = 0
    for raw_line in improve_readability_spacing(text).splitlines():
        stripped = raw_line.strip()
        if stop_at_label is not None and stripped == stop_at_label:
            break
        if stripped.startswith("- "):
            count += 1
    return count


def _brief_structure_issues(text: str) -> list[str]:
    _, _, sections = extract_brief_structure(text)
    section_map = {heading: content for heading, content in sections}
    issues: list[str] = []

    for heading in REQUIRED_LAYER_HEADINGS:
        if heading not in section_map:
            issues.append(f"{heading} 섹션이 없어요.")

    layer_two = section_map.get("LAYER 2 | 주요 뉴스")
    if layer_two:
        layer_two_groups = split_section_groups(layer_two)
        layer_two_bullets = _count_metric_bullets(layer_two_groups["metrics"][1])
        if layer_two_bullets == 0:
            layer_two_bullets = _count_section_bullets(layer_two)
        if layer_two_bullets < MIN_LAYER_TWO_BULLETS:
            issues.append(
                f"LAYER 2 bullet 수가 부족해요. count={layer_two_bullets}, expected>={MIN_LAYER_TWO_BULLETS}"
            )

    layer_three = section_map.get("LAYER 3 | 종목 브리핑")
    if layer_three:
        layer_three_groups = split_section_groups(layer_three)
        layer_three_bullets = _count_metric_bullets(
            layer_three_groups["metrics"][1],
            stop_at_label="거시 지표",
        )
        if layer_three_bullets == 0:
            layer_three_bullets = _count_section_bullets(layer_three, stop_at_label="거시 지표")
        if layer_three_bullets < MIN_LAYER_THREE_BULLETS:
            issues.append(
                f"LAYER 3 종목 bullet 수가 부족해요. count={layer_three_bullets}, expected>={MIN_LAYER_THREE_BULLETS}"
            )

    return issues


def _fallback_if_incomplete(
    *,
    text: str,
    packet: dict,
    settings: Settings,
    observer: PipelineObserver | None = None,
) -> str:
    issues = _brief_structure_issues(text)
    if not issues:
        return _finalize_briefing(text, packet)

    logger.warning(
        "브리핑 구조가 완전하지 않아 안전한 기본 브리핑으로 대체할게요: %s",
        "; ".join(issues[:3]),
    )
    if observer is not None:
        observer.log_event(
            "brief_fallback_used",
            reason="incomplete_structure",
            issues=issues,
        )
    return _fallback_brief(packet=packet, timezone=settings.timezone)


def _finalize_briefing(text: str, packet: dict) -> str:
    return _append_reference_block(
        _append_footer_note_block(
            _inject_quality_notice(_improve_readability_spacing(text), packet),
            packet,
        ),
        packet,
    )


def _bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item.strip())


def _market_source_label(point: dict) -> str:
    ticker = str(point.get("ticker", "")).strip()
    if ticker in {"DGS10", "DGS2", "VIXCLS"}:
        return "FRED"
    if ticker in {"DX-Y.NYB", "^IRX", "^TNX", "^VIX", "KRW=X", "NQ=F"}:
        return "yfinance"
    if ticker == "BTC-USD":
        return "CoinGecko"
    return "Stooq"


def _news_reference(item: dict) -> str:
    citations = item.get("citations", [])
    if isinstance(citations, list):
        for citation in citations:
            text = str(citation).strip()
            if text:
                return text
    return str(item.get("url", "")).strip() or "출처 없음"


def _fallback_news_takeaway(item: dict) -> str:
    topic = str(item.get("topic", "")).strip().lower()
    if topic == "bitcoin":
        return "국내 투자자에게는 비트코인과 관련주 반응을 함께 보는 편이 적절합니다."
    if topic in {"ai_bigtech", "us_equity"}:
        return "국내 투자자에게는 반도체와 대형 기술주 흐름을 같이 보는 편이 적절합니다."
    if topic == "macro":
        return "국내 투자자에게는 환율과 외국인 수급 변화까지 같이 확인할 필요가 있습니다."
    return "국내 투자자에게는 같은 주제를 국내 관련주가 어떻게 반영하는지 확인할 필요가 있습니다."


def _fallback_news_lines(news: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in news[:5]:
        title = str(item.get("title", "")).strip() or "주요 뉴스"
        why_it_matters = (
            str(item.get("why_it_matters", "")).strip() or "시장 해석에 바로 연결되는 기사입니다."
        )
        lines.append(
            f"- {title} | {why_it_matters} | {_fallback_news_takeaway(item)} | {_news_reference(item)}"
        )
    return lines


def _fallback_btc_spot_line(btc_spot: dict) -> tuple[str, float | None, float | None]:
    btc_spot_price = _point_price(btc_spot)
    btc_spot_change = _point_change_pct(btc_spot)
    if btc_spot_price is None or btc_spot_change is None:
        return "비트코인 현물은 이번 집계에서 확인되지 않았습니다.", btc_spot_price, btc_spot_change
    return (
        f"비트코인 현물은 {btc_spot_price:.2f}달러({btc_spot_change:+.2f}%)"
        f"{_point_suffix(btc_spot)} 수준이었습니다.",
        btc_spot_price,
        btc_spot_change,
    )


def _change_direction(change_pct: float | None, *, flat_threshold: float = 0.05) -> str:
    if change_pct is None:
        return "보합"
    if change_pct > flat_threshold:
        return "상승"
    if change_pct < -flat_threshold:
        return "하락"
    return "보합"


def _abs_change_text(change_pct: float | None) -> str:
    return f"{abs(change_pct or 0.0):.2f}%"


def _fear_greed_line(btc: dict) -> str:
    fg_value = btc.get("fear_greed_value")
    fg_label = btc.get("fear_greed_label")
    if fg_value is not None and fg_label:
        return f"공포탐욕지수는 {fg_value}으로 {fg_label} 구간입니다."
    return "공포탐욕지수는 이번 집계에서 확인되지 않았습니다."


def _fallback_macro_lines(macro: list[dict], sentiment_text: str) -> list[str]:
    lines = [
        f"{_fmt_point(point)} [출처: {_market_source_label(point)}]"
        for point in macro
        if _fmt_point(point)
    ]
    if sentiment_text:
        lines.append(f"{sentiment_text} [출처: alternative.me]")
    return lines[:4]


def _korea_watch_lines(korea_watch: list[dict], btc: dict) -> list[str]:
    lines: list[str] = []

    usdkrw = _point_by_key(korea_watch, "usdkrw")
    usdkrw_price = _point_price(usdkrw)
    usdkrw_change = _point_change_pct(usdkrw)
    if usdkrw_price is not None and usdkrw_change is not None:
        lines.append(
            f"원/달러 환율은 {usdkrw_price:,.2f}원으로 전일 대비 {usdkrw_change:+.2f}%였습니다{_point_suffix(usdkrw)}. [출처: yfinance]"
        )

    nq_futures = _point_by_key(korea_watch, "nq_futures")
    nq_change = _point_change_pct(nq_futures)
    if nq_change is not None:
        lines.append(
            f"나스닥 선물은 전일 대비 {nq_change:+.2f}%로 {_change_direction(nq_change)} 방향입니다{_point_suffix(nq_futures)}. [출처: yfinance]"
        )

    sentiment_text = _fear_greed_line(btc)
    if sentiment_text:
        lines.append(f"{sentiment_text} [출처: alternative.me]")

    return lines[:4]


def _judgement_and_reason(
    *,
    macro: list[dict],
    indices: list[dict],
    korea_watch: list[dict],
) -> tuple[str, str]:
    vix = _point_price(_point_by_key(macro, "vix"))
    us10y_point = _point_by_key(macro, "us10y")
    us10y = _point_price(us10y_point)
    us10y_change = _point_change_pct(us10y_point)
    spy_change = _point_change_pct(_point_by_key(indices, "spy"))
    nq_change = _point_change_pct(_point_by_key(korea_watch, "nq_futures"))
    usdkrw_change = _point_change_pct(_point_by_key(korea_watch, "usdkrw"))

    if (
        (vix is not None and vix >= 24.0)
        or (nq_change is not None and nq_change <= -0.7)
        or (spy_change is not None and spy_change <= -1.0)
        or (usdkrw_change is not None and usdkrw_change >= 0.5)
    ):
        if vix is not None and vix >= 24.0:
            return (
                "리스크 주의",
                f"VIX가 {vix:.2f}로 높은 편이라 변동성 경계가 우선입니다.",
            )
        if nq_change is not None and nq_change <= -0.7:
            return (
                "리스크 주의",
                f"나스닥 선물이 전일 대비 {nq_change:+.2f}%로 약해 개장 전 위험 선호가 약합니다.",
            )
        if usdkrw_change is not None and usdkrw_change >= 0.5:
            return (
                "리스크 주의",
                f"원/달러 환율이 전일 대비 {usdkrw_change:+.2f}% 올라 외국인 수급 부담을 함께 봐야 합니다.",
            )
        return (
            "리스크 주의",
            f"S&P500이 전일 대비 {spy_change:+.2f}% 밀려 위험자산 심리가 약해졌습니다.",
        )

    if (
        (vix is not None and vix <= 18.0)
        and (nq_change is not None and nq_change >= 0.4)
        and (spy_change is not None and spy_change >= 0.5)
    ):
        return (
            "매수 관심",
            f"VIX가 {vix:.2f}로 안정적이고 나스닥 선물과 S&P500 흐름이 함께 강합니다.",
        )

    if us10y is not None and us10y_change is not None:
        return (
            "관망",
            f"미국 10년물 금리가 {us10y:.2f}%로 높고 전일 대비 {us10y_change:+.2f}% 움직여 금리 부담을 더 확인할 필요가 있습니다.",
        )
    if nq_change is not None:
        return (
            "관망",
            f"나스닥 선물이 전일 대비 {nq_change:+.2f}%로 한쪽 방향이 뚜렷하지 않아 추가 확인이 필요합니다.",
        )
    return ("관망", "금리와 지수 흐름이 한 방향으로 정리되지 않아 추가 확인이 필요합니다.")


def _kospi_impact_line(*, korea_watch: list[dict], indices: list[dict]) -> str:
    usdkrw_change = _point_change_pct(_point_by_key(korea_watch, "usdkrw"))
    nq_change = _point_change_pct(_point_by_key(korea_watch, "nq_futures"))
    spy_change = _point_change_pct(_point_by_key(indices, "spy"))

    if (nq_change is not None and nq_change > 0.2) and (
        usdkrw_change is None or usdkrw_change <= 0.2
    ):
        detail = "나스닥 선물이 강하고 원/달러 환율이 비교적 안정돼, 대형 기술주 심리를 받쳐줄"
    elif (nq_change is not None and nq_change < -0.2) or (
        usdkrw_change is not None and usdkrw_change > 0.3
    ):
        detail = "나스닥 선물이 약하거나 원/달러 환율이 올라, 외국인 수급과 성장주 심리에 부담을 줄"
    elif spy_change is not None and spy_change > 0.3:
        detail = "미국 지수 전반이 견조해, 코스피도 낙폭을 제한하는 데 도움을 줄"
    else:
        detail = "미국 증시 신호가 엇갈려, 코스피는 업종별 차별화 장세로 이어질"
    return f"오늘 미국 증시 흐름이 코스피에 미치는 영향: {detail} 수 있습니다."


def _fallback_stock_cause(label: str, change_pct: float | None, news: list[dict]) -> str:
    normalized = label.strip().upper()
    topics = {
        str(item.get("topic", "")).strip()
        for item in news
        if isinstance(item, dict) and str(item.get("topic", "")).strip()
    }
    if normalized in {"BTC", "BTC-USD", "비트코인"} and "bitcoin" in topics:
        return "비트코인 ETF 수급 뉴스 흐름으로"
    if normalized in {
        "NVDA",
        "MSFT",
        "AAPL",
        "AMZN",
        "GOOGL",
        "META",
        "AMD",
        "TSM",
        "ASML",
        "AVGO",
    }:
        if "ai_bigtech" in topics:
            return "AI 투자 관련 뉴스 흐름 속에"
        if "us_equity" in topics:
            return "기술주 전반 흐름 속에"
    if "macro" in topics:
        return "금리와 달러 흐름 영향으로"
    if change_pct is not None and change_pct > 0:
        return "전반적 시장 상승 흐름 속에"
    return "전반적 시장 하락 영향으로"


def _fallback_stock_lines(
    tech: list[dict],
    btc: dict,
    btc_spot: dict,
    btc_spot_price: float | None,
    btc_spot_change: float | None,
    news: list[dict],
) -> list[str]:
    stock_lines = []
    for point in tech:
        change_pct = _point_change_pct(point)
        if change_pct is None:
            continue
        cause = _fallback_stock_cause(point["label"], change_pct, news)
        stock_lines.append(
            f"{point['label']}는 {cause} {_abs_change_text(change_pct)} {_change_direction(change_pct)}했습니다{_point_suffix(point)}. [출처: Stooq]"
        )
        if len(stock_lines) >= 4:
            break

    if btc_spot_price is not None and btc_spot_change is not None:
        cause = _fallback_stock_cause("BTC-USD", btc_spot_change, news)
        stock_lines.append(
            f"비트코인은 {cause} {_abs_change_text(btc_spot_change)} {_change_direction(btc_spot_change)}했고, 현재 {btc_spot_price:,.2f}달러입니다{_point_suffix(btc_spot)}. [출처: CoinGecko]"
        )
    official_flow_btc = btc.get("official_etf_daily_flow_btc")
    official_supported = btc.get("official_etf_supported_tickers", [])
    official_total_btc = btc.get("official_etf_total_btc")
    if official_flow_btc is not None:
        stock_lines.append(
            f"BTC ETF는 직전 스냅샷 대비 {'순유입' if official_flow_btc >= 0 else '순유출'} {abs(official_flow_btc):,.2f} BTC가 확인됐습니다. [출처: Perplexity structured response]"
        )
    if official_supported and official_total_btc:
        stock_lines.append(
            f"BTC ETF 보유량은 공식 발행사 기준 {', '.join(official_supported)} 합산 보유량 {official_total_btc:,.2f} BTC입니다. [출처: Perplexity structured response]"
        )
    etf_total_volume = btc.get("etf_total_volume")
    if etf_total_volume is not None:
        stock_lines.append(
            f"BTC ETF 거래량은 주요 ETF 합산 {etf_total_volume:,}주입니다. [출처: Stooq/yfinance]"
        )
    return stock_lines


def _fallback_brief(packet: dict, timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    date_str = now.strftime("%Y-%m-%d")

    macro = packet.get("macro", [])
    korea_watch = packet.get("korea_watch", [])
    indices = packet.get("us_indices", [])
    tech = [
        point for point in packet.get("tech_stocks", []) if _point_change_pct(point) is not None
    ]
    btc = packet.get("bitcoin", {})
    news = packet.get("news", [])[:5]
    news_lines = _fallback_news_lines(news)

    macro_text = _format_points(macro, "핵심 매크로 지표 데이터가 일부 누락되었습니다.")
    index_text = _format_points(indices, "주요 지수 데이터가 일부 누락되었습니다.")

    btc_spot = btc.get("spot", {})
    if not isinstance(btc_spot, dict):
        btc_spot = {}
    sentiment_text = _fear_greed_line(btc)
    investor_lines = _korea_watch_lines(korea_watch, btc)
    btc_spot_line, btc_spot_price, btc_spot_change = _fallback_btc_spot_line(btc_spot)
    macro_lines = _fallback_macro_lines(macro, sentiment_text)
    stock_lines = _fallback_stock_lines(tech, btc, btc_spot, btc_spot_price, btc_spot_change, news)
    judgement, judgement_reason = _judgement_and_reason(
        macro=macro,
        indices=indices,
        korea_watch=korea_watch,
    )
    kospi_impact = _kospi_impact_line(korea_watch=korea_watch, indices=indices)

    body = f"""Morning Market Brief ({date_str})

1. LAYER 1 | 오늘 한줄 판단
한줄 결론
오늘은 {judgement} 국면입니다.

{judgement_reason}

핵심 수치
{
        _bullet_lines(
            investor_lines
            or [
                f"{macro_text} [출처: FRED/yfinance]",
                f"{index_text} [출처: Stooq]",
                f"{btc_spot_line} [출처: CoinGecko]",
            ]
        )
    }

쉽게 보면
금리와 달러, 지수 흐름이 한 방향으로 정렬되지 않아 미국 장 마감 신호를 함께 비교할 필요가 있습니다.

{kospi_impact}

오늘 체크할 포인트
{
        _bullet_lines(
            [
                "전일 종가 대비 금리와 기술주 반응이 다시 같은 방향으로 모이는지",
                "직전 스냅샷 대비 BTC ETF 자금 흐름이 이어지는지",
            ]
        )
    }

2. LAYER 2 | 주요 뉴스
한줄 결론
오늘 뉴스는 금리 경로, AI 투자 기대, 비트코인 ETF 수급처럼 시장이 민감하게 보는 주제에 집중됐습니다.

핵심 이슈
{
        chr(10).join(news_lines)
        if news_lines
        else "- 오늘 반영할 주요 뉴스가 충분하지 않았습니다. | 시장 영향 해석을 보수적으로 유지합니다. | 국내 투자자에게는 관련 섹터 반응을 더 확인할 필요가 있습니다. | 출처 없음"
    }

왜 중요한지
오늘 뉴스는 금리 경로, AI 투자 기대, 비트코인 ETF 수급처럼 시장이 민감하게 보는 주제에 집중됐습니다.

뉴스와 가격 흐름이 다르게 움직인 구간은 기사 자체보다 시장 반응 속도를 함께 보는 편이 적절합니다.

오늘 체크할 포인트
{
        _bullet_lines(
            [
                "같은 주제를 다른 신뢰 출처도 같이 다루는지",
                "공식 채널 확인이 붙은 이슈가 장중에도 이어지는지",
            ]
        )
    }

3. LAYER 3 | 종목 브리핑
한줄 결론
오늘 종목 흐름은 AI와 반도체 기대가 유지된 구간과, 금리 부담이 먼저 반영된 구간이 함께 나타났습니다.

주요 지표
{_bullet_lines(stock_lines or ["주요 종목 등락률은 이번 집계에서 충분히 확인되지 않았습니다."])}

거시 지표
{_bullet_lines(macro_lines)}

쉽게 보면
종목별로는 같은 AI 테마 안에서도 차이가 보였고, 비트코인과 ETF 흐름도 가격과 완전히 같은 방향으로만 움직이지는 않았습니다.

그래서 오늘은 숫자 자체보다 서로 다른 자산이 얼마나 비슷하거나 다르게 반응하는지 비교해서 보는 편이 적절합니다.

오늘 체크할 포인트
{
        _bullet_lines(
            [
                "대형 기술주와 반도체의 등락률 차이가 더 커지는지",
                "VIX, 달러 인덱스, 미국 10년물 금리와 위험자산 반응이 다시 엇갈리는지",
            ]
        )
    }
"""
    return _finalize_briefing(body, packet)


def generate_briefing(
    packet: dict,
    settings: Settings,
    *,
    observer: PipelineObserver | None = None,
) -> str:
    if not settings.openai_api_key:
        raise BriefGenerationError("OpenAI API 키가 없어 브리핑 생성을 진행할 수 없어요.")

    client = OpenAI(api_key=settings.openai_api_key)

    try:
        instructions, user_prompt = render_brief_prompts(packet=packet, settings=settings)
        prompt_cache_key = build_prompt_cache_key(settings=settings, instructions=instructions)
        started_at = time.perf_counter()
        response = client.responses.create(
            model=settings.openai_model,
            instructions=instructions,
            input=user_prompt,
            reasoning={"effort": settings.openai_reasoning_effort},
            max_output_tokens=settings.openai_max_output_tokens,
            prompt_cache_key=prompt_cache_key,
        )
        text = (response.output_text or "").strip()
        if not text:
            raise BriefGenerationError("모델이 비어 있는 브리핑을 반환했어요.")
        text = _improve_readability_spacing(text)
        cached_tokens = cached_input_tokens(response)
        if cached_tokens is not None:
            logger.debug(
                "OpenAI 프롬프트 캐시를 사용했어요. key=%s | cached_input_tokens=%s",
                prompt_cache_key,
                cached_tokens,
            )
        if observer is not None:
            observer.record_provider_usage("openai", requests=1, **usage_snapshot(response))
            observer.record_phase_duration(
                "brief",
                int(round((time.perf_counter() - started_at) * 1000)),
            )
        text = validate_and_rewrite_briefing(
            draft_text=text,
            packet=packet,
            settings=settings,
            client=client,
            observer=observer,
        )
        return _fallback_if_incomplete(
            text=text,
            packet=packet,
            settings=settings,
            observer=observer,
        )
    except BriefGenerationError:
        raise
    except Exception as exc:
        raise BriefGenerationError(f"OpenAI 브리핑 생성에 실패했어요: {exc}") from exc
