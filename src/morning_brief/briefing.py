from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from morning_brief.config import Settings


SYSTEM_PROMPT = """당신은 미국 기술주/비트코인 전문 아침 브리핑 에디터다.
아래 원칙을 반드시 지켜 한국어 브리핑을 작성하라.

[형식]
Morning Market Brief
1. 거시 환경
2. 미국 증시 흐름
3. AI / 빅테크 동향
4. 비트코인 시장
5. 중요한 뉴스
6. 시장 해석

[작성 규칙]
- 읽기 시간 3~5분 분량으로 작성한다.
- 단순 숫자 나열이 아니라 원인-영향-시나리오 중심으로 해석한다.
- 뉴스는 3~5개만 선택하여 시장 영향 관점으로 정리한다.
- 투자 추천/매수·매도 권유는 절대 하지 않는다.
- 과장된 표현 없이 기관 리포트 톤으로 간결하게 쓴다.
- 미국 주식/금리/달러/VIX, 빅테크/반도체, 비트코인 ETF 흐름을 균형 있게 반영한다.
"""



def _fmt_point(point: dict) -> str:
    sign = "+" if point["change_pct"] >= 0 else ""
    return f"{point['label']} {point['price']:.2f} ({sign}{point['change_pct']:.2f}%)"



def _fallback_brief(packet: dict, timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    date_str = now.strftime("%Y-%m-%d")

    macro = packet.get("macro", [])
    indices = packet.get("us_indices", [])
    tech = packet.get("tech_stocks", [])
    btc = packet.get("bitcoin", {})
    news = packet.get("news", [])[:5]

    top_gainers = sorted(tech, key=lambda x: x["change_pct"], reverse=True)[:2]
    top_losers = sorted(tech, key=lambda x: x["change_pct"])[:2]

    news_lines = []
    for item in news[:5]:
        news_lines.append(f"- {item['title']} ({item['source']})")

    macro_text = " / ".join(_fmt_point(p) for p in macro)
    index_text = " / ".join(_fmt_point(p) for p in indices)

    btc_spot = btc.get("spot", {})
    fg_value = btc.get("fear_greed_value")
    fg_label = btc.get("fear_greed_label")

    if fg_value is not None and fg_label:
        sentiment_text = f"공포탐욕지수는 {fg_value}({fg_label})로 확인됩니다."
    else:
        sentiment_text = "공포탐욕지수는 이번 집계에서 확인되지 않았습니다."

    return f"""Morning Market Brief ({date_str})

1. 거시 환경
금리·달러·변동성 지표는 {macro_text} 흐름입니다. 단기적으로는 금리와 달러의 방향성이 기술주 밸류에이션에 직접적인 영향을 주는 구간입니다. VIX가 낮게 유지되면 위험자산 선호가 이어질 수 있지만, 금리 급등 시 성장주 변동성은 확대될 수 있습니다.

2. 미국 증시 흐름
주요 지수는 {index_text}로 마감했습니다. 나스닥과 반도체 섹터의 상대 강도는 AI 관련 수요 기대를 반영하고 있으며, 지수 상승이 소수 종목에 집중되는지 여부가 다음 추세의 지속성을 가를 핵심 포인트입니다.

3. AI / 빅테크 동향
빅테크·반도체 주요 종목에서 변동이 큰 종목은 {', '.join([f"{x['label']}({x['change_pct']:+.2f}%)" for x in top_gainers + top_losers])}입니다. 실적 가이던스, AI 인프라 투자 속도, 데이터센터 CAPEX 기대가 종목별 차별화를 만들고 있어, 단순 업종 베팅보다 기업별 펀더멘털 해석이 중요합니다.

4. 비트코인 시장
비트코인 현물은 {btc_spot.get('price', 0):.2f}달러({btc_spot.get('change_pct', 0):+.2f}%) 수준이며, 주요 ETF 합산 거래량은 약 {btc.get('etf_total_volume', 0):,}주입니다. {sentiment_text} ETF 자금 유입 강도와 가격 반응의 괴리가 커지면 단기 변동성 확대 신호로 해석할 수 있습니다.

5. 중요한 뉴스
{chr(10).join(news_lines) if news_lines else '- 오늘 반영할 주요 뉴스가 충분히 수집되지 않았습니다.'}

6. 시장 해석
현재 시장은 "금리 경로"와 "AI 투자 모멘텀"이 동시에 가격을 결정하는 이중 축 국면입니다. 금리 안정과 실적 기대가 유지되면 기술주·반도체 중심의 위험선호가 이어질 수 있지만, 정책/규제 변수나 매크로 서프라이즈가 발생할 경우 빠른 포지션 재조정이 나타날 수 있습니다. 오늘의 핵심 체크포인트는 연준 관련 발언, 미 국채금리 방향, 대형 기술주의 투자지출 신호, 비트코인 ETF 자금 흐름입니다.
"""



def generate_briefing(packet: dict, settings: Settings) -> str:
    if not settings.openai_api_key:
        return _fallback_brief(packet=packet, timezone=settings.timezone)

    client = OpenAI(api_key=settings.openai_api_key)
    user_prompt = (
        "아래 JSON 시장 데이터를 분석해 아침 브리핑을 작성하세요.\n"
        "JSON:\n"
        f"{json.dumps(packet, ensure_ascii=False)}"
    )

    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        text = (response.output_text or "").strip()
        if not text:
            raise ValueError("Empty briefing from model")
        return text
    except Exception:
        return _fallback_brief(packet=packet, timezone=settings.timezone)
