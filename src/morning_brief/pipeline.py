from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from morning_brief.briefing import generate_briefing
from morning_brief.config import Settings
from morning_brief.data.market import build_market_packet
from morning_brief.data.news import build_news_packet
from morning_brief.emailer import GmailSender



def run_pipeline(settings: Settings) -> str:
    market_packet = build_market_packet()
    news_packet = build_news_packet(
        max_items=settings.max_news_items,
        newsapi_key=settings.newsapi_key,
    )

    packet = {
        **market_packet,
        "news": news_packet,
    }

    briefing = generate_briefing(packet=packet, settings=settings)

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo(settings.timezone))
    file_name = now.strftime("brief_%Y%m%d.md")
    (settings.output_dir / file_name).write_text(briefing, encoding="utf-8")

    subject = f"Morning Market Brief | {now.strftime('%Y-%m-%d')}"
    GmailSender(settings).send(subject=subject, body=briefing)

    return briefing
