from __future__ import annotations

from datetime import datetime
import logging
import re
from zoneinfo import ZoneInfo

from openai import OpenAI

from morning_brief.config import Settings
from morning_brief.prompting import build_prompt_cache_key, render_brief_prompts

logger = logging.getLogger(__name__)
SECTION_HEADING_RE = re.compile(r"^\d+\.\s+.+$")
SUBSECTION_LABELS = {"수치 체크", "해석", "핵심 내용", "오늘 볼 포인트"}
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'“”‘’(]*[A-Za-z가-힣])")



def _fmt_point(point: dict) -> str:
    sign = "+" if point["change_pct"] >= 0 else ""
    return f"{point['label']} {point['price']:.2f} ({sign}{point['change_pct']:.2f}%)"


def _format_points(points: list[dict], empty_text: str) -> str:
    if not points:
        return empty_text
    return " / ".join(_fmt_point(p) for p in points)


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


def _improve_readability_spacing(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if (
            not stripped
            or stripped.startswith("[데이터 품질 알림]")
            or SECTION_HEADING_RE.match(stripped)
            or stripped in SUBSECTION_LABELS
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


def _bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item.strip())


def _cached_input_tokens(response: object) -> int | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    details = getattr(usage, "input_tokens_details", None)
    if details is None:
        return None

    cached_tokens = getattr(details, "cached_tokens", None)
    if cached_tokens is None:
        return None

    try:
        return int(cached_tokens)
    except (TypeError, ValueError):
        return None



def _fallback_brief(packet: dict, timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    date_str = now.strftime("%Y-%m-%d")

    macro = packet.get("macro", [])
    indices = packet.get("us_indices", [])
    tech = packet.get("tech_stocks", [])
    btc = packet.get("bitcoin", {})
    news = packet.get("news", [])[:5]

    top_gainers = sorted(tech, key=lambda x: x["change_pct"], reverse=True)[:3]
    top_losers = sorted(tech, key=lambda x: x["change_pct"])[:3]
    mover_parts: list[str] = []
    seen_labels: set[str] = set()
    for point in top_gainers + top_losers:
        label = point.get("label", "")
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        mover_parts.append(f"{label}({point['change_pct']:+.2f}%)")
        if len(mover_parts) >= 4:
            break
    top_movers_text = ", ".join(mover_parts) if mover_parts else "데이터 수집 종목 기준 뚜렷한 변동 종목이 제한적입니다"

    news_lines = []
    for item in news[:5]:
        news_lines.append(f"- {item['title']} ({item['source']})")

    macro_text = _format_points(macro, "핵심 매크로 지표 데이터가 일부 누락되었습니다.")
    index_text = _format_points(indices, "주요 지수 데이터가 일부 누락되었습니다.")

    btc_spot = btc.get("spot", {})
    fg_value = btc.get("fear_greed_value")
    fg_label = btc.get("fear_greed_label")
    official_supported = btc.get("official_etf_supported_tickers", [])
    official_compared = btc.get("official_etf_compared_tickers", [])
    official_total_btc = btc.get("official_etf_total_btc")
    official_flow_btc = btc.get("official_etf_daily_flow_btc")
    official_flow_usd = btc.get("official_etf_daily_flow_usd")

    if fg_value is not None and fg_label:
        sentiment_text = f"공포탐욕지수는 {fg_value}({fg_label})로 확인됐어요."
    else:
        sentiment_text = "공포탐욕지수는 이번 집계에서 확인되지 않았어요."

    official_etf_lines: list[str] = []
    if official_supported and official_total_btc:
        supported_text = ", ".join(official_supported)
        official_etf_lines.append(
            f"공식 발행사 기준으로 집계한 {supported_text} 합산 보유량은 {official_total_btc:,.2f} BTC였어요."
        )
    if official_compared and official_flow_btc is not None:
        direction = "순유입" if official_flow_btc >= 0 else "순유출"
        flow_usd_text = ""
        if official_flow_usd is not None:
            flow_usd_text = f", 달러 기준 약 {abs(official_flow_usd):,.0f}달러"
        official_etf_lines.append(
            f"직전 스냅샷과 비교한 공식 ETF 흐름은 {abs(official_flow_btc):,.2f} BTC {direction}{flow_usd_text}로 계산됐어요."
        )

    body = f"""Morning Market Brief ({date_str})

1. 거시 환경
수치 체크
{_bullet_lines([f"금리·달러·변동성 지표는 {macro_text} 흐름으로 확인됐어요."])}

해석
금리와 달러의 방향은 기술주 밸류에이션에 직접적인 영향을 주고 있어요.

VIX가 낮게 유지되면 위험자산 선호가 이어질 수 있지만, 금리가 다시 오르면 성장주 변동성은 커질 수 있어요.

2. 미국 증시 흐름
수치 체크
{_bullet_lines([f"주요 지수는 {index_text} 흐름으로 마감했어요."])}

해석
나스닥과 반도체 섹터의 상대 강도는 AI 수요 기대가 아직 살아 있다는 신호로 읽혀요.

다만 지수 상승이 소수 종목에만 몰리면 추세의 힘은 생각보다 약할 수 있어서, 시장 폭이 넓어지는지 함께 볼 필요가 있어요.

3. AI / 빅테크 동향
수치 체크
{_bullet_lines([f"빅테크·반도체 주요 종목 가운데 변동이 큰 종목은 {top_movers_text}였어요."])}

해석
실적 가이던스와 AI 인프라 투자 속도, 데이터센터 CAPEX 기대가 종목별 차이를 만들고 있어요.

같은 AI 테마 안에서도 기업별 해석이 더 중요해지는 구간으로 보여요.

4. 비트코인 시장
수치 체크
{_bullet_lines([
    f"비트코인 현물은 {btc_spot.get('price', 0):.2f}달러({btc_spot.get('change_pct', 0):+.2f}%) 수준이었어요.",
    f"주요 ETF 합산 거래량은 약 {btc.get('etf_total_volume', 0):,}주였어요.",
    *official_etf_lines,
    sentiment_text,
])}

해석
ETF 자금 유입 강도와 가격 반응이 엇갈리면 단기 변동성이 커질 수 있어요.

가격 자체보다 자금 흐름이 얼마나 꾸준한지가 더 중요한 구간으로 보여요.

5. 중요한 뉴스
핵심 내용
{chr(10).join(news_lines) if news_lines else '- 오늘 반영할 주요 뉴스가 충분히 수집되지 않았어요.'}

해석
오늘 뉴스 흐름은 금리 경로와 AI 투자 기대, 그리고 ETF 수급 해석에 영향을 줄 수 있는 재료들 위주로 읽히고 있어요.

6. 시장 해석
오늘 볼 포인트
{_bullet_lines([
    "연준 관련 발언과 미 국채금리 방향",
    "대형 기술주의 투자지출 신호",
    "비트코인 ETF 자금 흐름",
])}

해석
지금 시장은 금리 경로와 AI 투자 모멘텀이 함께 가격을 움직이는 구간으로 보여요.

금리가 안정되고 실적 기대가 유지되면 기술주와 반도체 중심의 위험 선호가 이어질 수 있어요.

반대로 정책 변수나 매크로 서프라이즈가 나오면 포지션이 빠르게 재조정될 수 있어서, 오늘은 방향성보다 반응 속도를 같이 보는 편이 좋아요.
"""
    return _append_reference_block(
        _improve_readability_spacing(_inject_quality_notice(body, packet)),
        packet,
    )



def generate_briefing(packet: dict, settings: Settings) -> str:
    if not settings.openai_api_key:
        return _fallback_brief(packet=packet, timezone=settings.timezone)

    client = OpenAI(api_key=settings.openai_api_key)

    try:
        instructions, user_prompt = render_brief_prompts(packet=packet, settings=settings)
        prompt_cache_key = build_prompt_cache_key(settings=settings, instructions=instructions)
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
            raise ValueError("모델이 비어 있는 브리핑을 반환했어요.")
        cached_tokens = _cached_input_tokens(response)
        if cached_tokens is not None:
            logger.info(
                "OpenAI 프롬프트 캐시를 사용했어요. key=%s | cached_input_tokens=%s",
                prompt_cache_key,
                cached_tokens,
            )
        return _append_reference_block(
            _improve_readability_spacing(_inject_quality_notice(text, packet)),
            packet,
        )
    except Exception as exc:
        logger.warning("LLM 브리핑 생성에 문제가 있어 기본 템플릿으로 이어갈게요: %s", exc)
        return _fallback_brief(packet=packet, timezone=settings.timezone)
