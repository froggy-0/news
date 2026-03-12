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
MAX_CACHE_KEY_LEN = 180

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


def render_brief_prompts(packet: dict, settings: Settings) -> tuple[str, str]:
    packet_json = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    instructions = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=INSTRUCTIONS_TEMPLATE,
        prompt_template_version=settings.prompt_template_version,
    )
    user_prompt = _render_template(
        template_dir=settings.prompt_template_dir,
        template_name=INPUT_TEMPLATE,
        packet_json=packet_json,
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
    normalized_namespace = _INVALID_CACHE_KEY_CHARS.sub("-", namespace).strip("-")
    if not normalized_namespace:
        normalized_namespace = DEFAULT_CACHE_KEY

    static_digest = hashlib.sha256(instructions.encode("utf-8")).hexdigest()[:12]
    cache_model = (model_name or settings.openai_model).strip() or settings.openai_model
    raw_key = (
        f"{normalized_namespace}:"
        f"{settings.prompt_template_version}:"
        f"{cache_model}:"
        f"{static_digest}"
    )
    return raw_key[:MAX_CACHE_KEY_LEN]
