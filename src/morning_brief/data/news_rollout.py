from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROLLOUT_STATE_RELATIVE_PATH = Path("news/perplexity_rollout_state.json")
ROLLOUT_HISTORY_LIMIT = 7
STABLE_RUN_STREAK = 3


def _state_file(cache_dir: Path) -> Path:
    return cache_dir / ROLLOUT_STATE_RELATIVE_PATH


def load_news_rollout_state(cache_dir: Path) -> dict:
    path = _state_file(cache_dir)
    if not path.exists():
        return {"runs": []}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"runs": []}

    runs = payload.get("runs", [])
    if not isinstance(runs, list):
        return {"runs": []}
    return {"runs": [run for run in runs if isinstance(run, dict)]}


def should_reduce_legacy_broad_fallback(cache_dir: Path) -> bool:
    state = load_news_rollout_state(cache_dir)
    recent_runs = state.get("runs", [])[-STABLE_RUN_STREAK:]
    if len(recent_runs) < STABLE_RUN_STREAK:
        return False

    return all(
        bool(run.get("perplexity_only_ready")) and not bool(run.get("legacy_used"))
        for run in recent_runs
    )


def record_news_rollout_run(
    *,
    cache_dir: Path,
    fallback_review: dict,
    used_legacy: bool,
    allow_broad_fallback: bool,
    provider_breakdown: dict[str, int],
) -> None:
    path = _state_file(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    state = load_news_rollout_state(cache_dir)
    runs = state.get("runs", [])
    runs.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "perplexity_count": int(fallback_review.get("count", 0)),
            "unique_domains": int(fallback_review.get("unique_domains", 0)),
            "topic_coverage_count": int(fallback_review.get("topic_coverage_count", 0)),
            "fresh_count": int(fallback_review.get("fresh_count", 0)),
            "citation_backed_count": int(fallback_review.get("citation_backed_count", 0)),
            "perplexity_only_ready": not bool(fallback_review.get("needs_legacy_fallback")),
            "fallback_reasons": list(fallback_review.get("reasons", [])),
            "legacy_used": used_legacy,
            "allow_broad_fallback": allow_broad_fallback,
            "provider_breakdown": provider_breakdown,
        }
    )
    payload = {"runs": runs[-ROLLOUT_HISTORY_LIMIT:]}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
