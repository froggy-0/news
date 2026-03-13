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
