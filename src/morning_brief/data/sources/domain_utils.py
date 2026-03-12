from __future__ import annotations

from urllib.parse import urlparse


def normalize_domain(value: str) -> str:
    candidate = value.strip().lower()
    if not candidate:
        return ""

    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    return (parsed.hostname or "").strip(".")


def domain_matches(value: str, preferred_domain: str) -> bool:
    domain = normalize_domain(value)
    target = normalize_domain(preferred_domain)
    if not domain or not target:
        return False
    return domain == target or domain.endswith(f".{target}")

