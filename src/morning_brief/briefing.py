from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from morning_brief.brief_formatting import improve_readability_spacing
from morning_brief.brief_review import validate_and_rewrite_briefing
from morning_brief.config import Settings
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.observability import PipelineObserver
from morning_brief.openai_utils import cached_input_tokens, usage_snapshot
from morning_brief.prompting import build_prompt_cache_key, render_brief_prompts

logger = logging.getLogger(__name__)


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
    references = packet.get("web_search_references", [])
    if not isinstance(references, list) or not references:
        return text

    lines = ["참고 출처"]
    seen: set[str] = set()
    for item in references[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or "출처"
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        lines.append(f"- {title} — {url}")

    if len(lines) == 1:
        return text

    return f"{text.rstrip()}\n\n" + "\n".join(lines)


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
    if ticker in {"DX-Y.NYB", "^IRX", "^TNX", "^VIX"}:
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


def _fallback_news_lines(news: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in news[:5]:
        why_it_matters = (
            str(item.get("why_it_matters", "")).strip() or "시장 해석에 바로 연결되는 기사입니다."
        )
        lines.append(f"- {item['title']} | {why_it_matters} | {_news_reference(item)}")
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


def _fear_greed_line(btc: dict) -> str:
    fg_value = btc.get("fear_greed_value")
    fg_label = btc.get("fear_greed_label")
    if fg_value is not None and fg_label:
        return f"공포탐욕지수는 {fg_value}({fg_label})로 확인됐습니다."
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


def _fallback_stock_lines(
    tech: list[dict],
    btc: dict,
    btc_spot: dict,
    btc_spot_price: float | None,
    btc_spot_change: float | None,
) -> list[str]:
    stock_lines = [
        f"{point['label']} | {(_point_change_pct(point) or 0.0):+.2f}% | {point['label']} 흐름을 확인했습니다{_point_suffix(point)} | [출처: Stooq]"
        for point in tech
        if _point_change_pct(point) is not None
    ][:4]
    if btc_spot_price is not None and btc_spot_change is not None:
        stock_lines.append(
            f"BTC-USD | {btc_spot_change:+.2f}% | 비트코인 현물은 {btc_spot_price:.2f}달러였습니다{_point_suffix(btc_spot)} | [출처: CoinGecko]"
        )
    official_flow_btc = btc.get("official_etf_daily_flow_btc")
    official_supported = btc.get("official_etf_supported_tickers", [])
    official_total_btc = btc.get("official_etf_total_btc")
    if official_flow_btc is not None:
        stock_lines.append(
            f"BTC ETF | {official_flow_btc:+,.2f} BTC | 직전 스냅샷 대비 {'순유입' if official_flow_btc >= 0 else '순유출'}입니다 | [출처: Perplexity structured response]"
        )
    if official_supported and official_total_btc:
        stock_lines.append(
            f"BTC ETF 보유량 | {official_total_btc:,.2f} BTC | 공식 발행사 기준으로 집계한 {', '.join(official_supported)} 합산 보유량입니다 | [출처: Perplexity structured response]"
        )
    etf_total_volume = btc.get("etf_total_volume")
    if etf_total_volume is not None:
        stock_lines.append(
            f"BTC ETF 거래량 | {etf_total_volume:,}주 | 주요 ETF 합산 거래량입니다 | [출처: Stooq/yfinance]"
        )
    return stock_lines


def _fallback_brief(packet: dict, timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    date_str = now.strftime("%Y-%m-%d")

    macro = packet.get("macro", [])
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
    btc_spot_line, btc_spot_price, btc_spot_change = _fallback_btc_spot_line(btc_spot)
    macro_lines = _fallback_macro_lines(macro, sentiment_text)
    stock_lines = _fallback_stock_lines(tech, btc, btc_spot, btc_spot_price, btc_spot_change)

    body = f"""Morning Market Brief ({date_str})

1. LAYER 1 | 오늘 한줄 판단
핵심 판단
- 금리, 기술주, 비트코인 흐름은 한 방향으로만 정렬되기보다 서로 다른 반응이 함께 관찰됐습니다.

주요 지표
{
        _bullet_lines(
            [
                f"{macro_text} [출처: FRED/yfinance]",
                f"{index_text} [출처: Stooq]",
                f"{btc_spot_line} [출처: CoinGecko]",
            ]
        )
    }

배경과 해석
금리와 달러, 주가, 비트코인 흐름은 같은 방향으로만 움직이지 않았고 시장에서는 이를 함께 비교하는 분위기가 이어졌습니다.

지표 사이에 괴리가 있으면 단일 원인보다 수급과 기대 차이를 같이 보는 편이 더 안전해 보입니다.

주목할 변수
{
        _bullet_lines(
            [
                "전일 종가 대비 금리와 기술주 반응이 다시 같은 방향으로 모이는지",
                "직전 스냅샷 대비 BTC ETF 자금 흐름이 이어지는지",
            ]
        )
    }

2. LAYER 2 | 주요 뉴스
핵심 이슈
{
        chr(10).join(news_lines)
        if news_lines
        else "- 오늘 반영할 주요 뉴스가 충분하지 않았습니다. | 시장 영향 해석을 보수적으로 유지합니다. | 출처 없음"
    }

배경과 해석
오늘 뉴스는 금리 경로, AI 투자 기대, 비트코인 ETF 수급처럼 시장이 민감하게 보는 주제에 집중됐습니다.

뉴스와 가격 흐름이 다르게 움직인 구간은 기사 자체보다 시장 반응 속도를 함께 보는 편이 적절합니다.

주목할 변수
{
        _bullet_lines(
            [
                "같은 주제를 다른 신뢰 출처도 같이 다루는지",
                "공식 채널 확인이 붙은 이슈가 장중에도 이어지는지",
            ]
        )
    }

3. LAYER 3 | 종목 브리핑
주요 지표
{
        _bullet_lines(
            stock_lines
            or ["주요 종목 등락률은 이번 집계에서 충분히 확인되지 않았습니다. | 출처 없음"]
        )
    }

거시 지표
{_bullet_lines(macro_lines)}

배경과 해석
종목별로는 같은 AI 테마 안에서도 차이가 보였고, 비트코인과 ETF 흐름도 가격과 완전히 같은 방향으로만 움직이지는 않았습니다.

그래서 오늘은 숫자 자체보다 서로 다른 자산이 얼마나 비슷하거나 다르게 반응하는지 비교해서 보는 편이 적절합니다.

주목할 변수
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
            logger.info(
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
        return _finalize_briefing(text, packet)
    except BriefGenerationError:
        raise
    except Exception as exc:
        raise BriefGenerationError(f"OpenAI 브리핑 생성에 실패했어요: {exc}") from exc
