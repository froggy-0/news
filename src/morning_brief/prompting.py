from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from morning_brief.config import Settings

INSTRUCTIONS_TEMPLATE = "brief_instructions.j2"
INPUT_TEMPLATE = "brief_input.j2"
VALIDATOR_INSTRUCTIONS_TEMPLATE = "brief_validator_instructions.j2"
VALIDATOR_INPUT_TEMPLATE = "brief_validator_input.j2"
REWRITE_INSTRUCTIONS_TEMPLATE = "brief_rewrite_instructions.j2"
REWRITE_INPUT_TEMPLATE = "brief_rewrite_input.j2"
WEB_SEARCH_INSTRUCTIONS_TEMPLATE = "web_search_instructions.j2"
WEB_SEARCH_INPUT_TEMPLATE = "web_search_input.j2"
DEFAULT_CACHE_KEY = "morning-market-brief"
MAX_CACHE_KEY_LEN = 64
MAX_NAMESPACE_SEGMENT_LEN = 20
MAX_TEMPLATE_SEGMENT_LEN = 10
MAX_MODEL_SEGMENT_LEN = 18

_INVALID_CACHE_KEY_CHARS = re.compile(r"[^a-zA-Z0-9:._-]+")


class PromptTemplateError(RuntimeError):
    """Raised when prompt templates cannot be loaded or rendered."""


@lru_cache(maxsize=4)
def _load_environment(template_dir: str) -> Environment:
    directory = Path(template_dir)
    if not directory.exists():
        raise PromptTemplateError(f"Prompt template directory not found: {directory}")

    return Environment(
        loader=FileSystemLoader(str(directory)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )


def _render_template(template_dir: Path, template_name: str, **context: object) -> str:
    environment = _load_environment(str(template_dir.resolve()))
    try:
        template = environment.get_template(template_name)
    except TemplateNotFound as exc:
        raise PromptTemplateError(
            f"Prompt template not found: {template_name} (dir={template_dir})"
        ) from exc
    return template.render(**context).strip()


def _build_news_focus(packet: dict) -> dict:
    news = packet.get("news", [])
    if not isinstance(news, list):
        return {
            "top_items": [],
            "topics": {},
            "official_signals": [],
            "topic_summaries": packet.get("topic_summaries", []),
            "x_market_signals": packet.get("x_market_signals", []),
        }

    top_items = []
    topics: dict[str, list[dict]] = {}
    official_signals: list[dict] = []
    for raw_item in news[:5]:
        if not isinstance(raw_item, dict):
            continue
        item = {
            "title": str(raw_item.get("title", "")).strip(),
            "source": str(raw_item.get("source", "")).strip(),
            "topic": str(raw_item.get("topic", "")).strip() or "general",
            "summary": str(raw_item.get("summary", "")).strip(),
            "why_it_matters": str(raw_item.get("why_it_matters", "")).strip(),
            "provider": str(raw_item.get("provider", "")).strip(),
            "official_source": bool(raw_item.get("official_source")),
            "source_tier": str(raw_item.get("source_tier", "")).strip(),
            "preferred_source": bool(raw_item.get("preferred_source")),
            "citations": [
                str(value).strip() for value in raw_item.get("citations", []) if str(value).strip()
            ]
            if isinstance(raw_item.get("citations", []), list)
            else [],
        }
        if not item["title"]:
            continue
        top_items.append(item)
        topics.setdefault(item["topic"], []).append(item)
        if item["official_source"] or item["provider"] == "grok_official_x":
            official_signals.append(item)

    return {
        "top_items": top_items,
        "topics": topics,
        "official_signals": official_signals,
        "topic_summaries": packet.get("topic_summaries", []),
        "x_market_signals": packet.get("x_market_signals", []),
    }


def render_brief_prompts(packet: dict, settings: Settings) -> tuple[str, str]:
    packet_json = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    news_focus_json = json.dumps(
        _build_news_focus(packet),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    instructions = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=INSTRUCTIONS_TEMPLATE,
        prompt_template_version=settings.prompt_template_version,
    )
    user_prompt = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=INPUT_TEMPLATE,
        packet_json=packet_json,
        news_focus_json=news_focus_json,
    )
    return instructions, user_prompt


def render_web_search_prompts(
    *,
    search_context_json: str,
    settings: Settings,
) -> tuple[str, str]:
    instructions = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=WEB_SEARCH_INSTRUCTIONS_TEMPLATE,
        prompt_template_version=settings.prompt_template_version,
    )
    user_prompt = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=WEB_SEARCH_INPUT_TEMPLATE,
        search_context_json=search_context_json,
    )
    return instructions, user_prompt


def render_brief_validator_prompts(
    *,
    packet_json: str,
    draft_text: str,
    settings: Settings,
) -> tuple[str, str]:
    instructions = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=VALIDATOR_INSTRUCTIONS_TEMPLATE,
        prompt_template_version=settings.prompt_template_version,
    )
    user_prompt = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=VALIDATOR_INPUT_TEMPLATE,
        packet_json=packet_json,
        draft_text=draft_text,
    )
    return instructions, user_prompt


def render_brief_rewrite_prompts(
    *,
    packet_json: str,
    draft_text: str,
    review_json: str,
    settings: Settings,
) -> tuple[str, str]:
    instructions = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=REWRITE_INSTRUCTIONS_TEMPLATE,
        prompt_template_version=settings.prompt_template_version,
    )
    user_prompt = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=REWRITE_INPUT_TEMPLATE,
        packet_json=packet_json,
        draft_text=draft_text,
        review_json=review_json,
    )
    return instructions, user_prompt


def build_prompt_cache_key(
    settings: Settings,
    instructions: str,
    *,
    model_name: str | None = None,
) -> str:
    namespace = settings.openai_prompt_cache_key or DEFAULT_CACHE_KEY
    normalized_namespace = _sanitize_cache_segment(namespace)
    if not normalized_namespace:
        normalized_namespace = DEFAULT_CACHE_KEY

    static_digest = hashlib.sha256(instructions.encode("utf-8")).hexdigest()[:12]
    cache_model = (model_name or settings.openai_model).strip() or settings.openai_model
    namespace_segment = _fit_cache_segment(
        normalized_namespace,
        max_len=MAX_NAMESPACE_SEGMENT_LEN,
    )
    template_segment = _fit_cache_segment(
        settings.prompt_template_version,
        max_len=MAX_TEMPLATE_SEGMENT_LEN,
    )
    model_segment = _fit_cache_segment(
        cache_model,
        max_len=MAX_MODEL_SEGMENT_LEN,
    )
    raw_key = f"{namespace_segment}:{template_segment}:{model_segment}:{static_digest}"
    return raw_key[:MAX_CACHE_KEY_LEN]


def _sanitize_cache_segment(value: str) -> str:
    return _INVALID_CACHE_KEY_CHARS.sub("-", value).strip("-")


def _fit_cache_segment(value: str, *, max_len: int) -> str:
    normalized = _sanitize_cache_segment(value) or "default"
    if len(normalized) <= max_len:
        return normalized

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:6]
    prefix_len = max(max_len - len(digest) - 1, 1)
    return f"{normalized[:prefix_len]}-{digest}"
