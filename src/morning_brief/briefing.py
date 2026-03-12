from __future__ import annotations

from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from openai import OpenAI

from morning_brief.config import Settings
from morning_brief.prompting import build_prompt_cache_key, render_brief_prompts

logger = logging.getLogger(__name__)



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

    if fg_value is not None and fg_label:
        sentiment_text = f"공포탐욕지수는 {fg_value}({fg_label})로 확인됩니다."
    else:
        sentiment_text = "공포탐욕지수는 이번 집계에서 확인되지 않았습니다."

    body = f"""Morning Market Brief ({date_str})

1. 거시 환경
금리·달러·변동성 지표는 {macro_text} 흐름입니다. 단기적으로는 금리와 달러의 방향성이 기술주 밸류에이션에 직접적인 영향을 주는 구간입니다. VIX가 낮게 유지되면 위험자산 선호가 이어질 수 있지만, 금리 급등 시 성장주 변동성은 확대될 수 있습니다.

2. 미국 증시 흐름
주요 지수는 {index_text}로 마감했습니다. 나스닥과 반도체 섹터의 상대 강도는 AI 관련 수요 기대를 반영하고 있으며, 지수 상승이 소수 종목에 집중되는지 여부가 다음 추세의 지속성을 가를 핵심 포인트입니다.

3. AI / 빅테크 동향
빅테크·반도체 주요 종목에서 변동이 큰 종목은 {top_movers_text}입니다. 실적 가이던스, AI 인프라 투자 속도, 데이터센터 CAPEX 기대가 종목별 차별화를 만들고 있어, 단순 업종 베팅보다 기업별 펀더멘털 해석이 중요합니다.

4. 비트코인 시장
비트코인 현물은 {btc_spot.get('price', 0):.2f}달러({btc_spot.get('change_pct', 0):+.2f}%) 수준이며, 주요 ETF 합산 거래량은 약 {btc.get('etf_total_volume', 0):,}주입니다. {sentiment_text} ETF 자금 유입 강도와 가격 반응의 괴리가 커지면 단기 변동성 확대 신호로 해석할 수 있습니다.

5. 중요한 뉴스
{chr(10).join(news_lines) if news_lines else '- 오늘 반영할 주요 뉴스가 충분히 수집되지 않았습니다.'}

6. 시장 해석
현재 시장은 "금리 경로"와 "AI 투자 모멘텀"이 동시에 가격을 결정하는 이중 축 국면입니다. 금리 안정과 실적 기대가 유지되면 기술주·반도체 중심의 위험선호가 이어질 수 있지만, 정책/규제 변수나 매크로 서프라이즈가 발생할 경우 빠른 포지션 재조정이 나타날 수 있습니다. 오늘의 핵심 체크포인트는 연준 관련 발언, 미 국채금리 방향, 대형 기술주의 투자지출 신호, 비트코인 ETF 자금 흐름입니다.
"""
    return _inject_quality_notice(body, packet)



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
            raise ValueError("Empty briefing from model")
        cached_tokens = _cached_input_tokens(response)
        if cached_tokens is not None:
            logger.info(
                "OpenAI prompt cache key=%s cached_input_tokens=%s",
                prompt_cache_key,
                cached_tokens,
            )
        return _inject_quality_notice(text, packet)
    except Exception as exc:
        logger.warning("LLM briefing failed; using fallback template: %s", exc)
        return _fallback_brief(packet=packet, timezone=settings.timezone)
