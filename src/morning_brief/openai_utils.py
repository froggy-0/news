from __future__ import annotations


def cached_input_tokens(response: object) -> int | None:
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


def usage_snapshot(response: object) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
        }

    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cached_tokens = cached_input_tokens(response) or 0
    reasoning_tokens = getattr(usage, "reasoning_tokens", None)

    if reasoning_tokens is None:
        output_details = getattr(usage, "output_tokens_details", None)
        reasoning_tokens = getattr(output_details, "reasoning_tokens", 0) if output_details else 0

    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cached_input_tokens": int(cached_tokens),
        "reasoning_tokens": int(reasoning_tokens or 0),
    }
