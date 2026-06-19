from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TABLES = [
    "arena_runs",
    "arena_strategy_versions",
    "arena_ohlcv_bars",
    "arena_run_ohlcv_bars",
    "arena_feature_registry",
    "arena_macro_snapshots",
    "arena_indicator_snapshots",
    "arena_decisions",
    "arena_decision_mart_v1",
]


def _count_from_content_range(value: str | None) -> int | None:
    if not value or "/" not in value:
        return None
    total = value.rsplit("/", maxsplit=1)[-1]
    if total == "*":
        return None
    try:
        return int(total)
    except ValueError:
        return None


def _check_table(base_url: str, api_key: str, table: str) -> dict[str, object]:
    req = urllib.request.Request(
        f"{base_url}/rest/v1/{table}?select=*",
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Prefer": "count=exact",
            "Range": "0-0",
            "Range-Unit": "items",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return {
                "exists": True,
                "status": res.status,
                "rows": _count_from_content_range(res.headers.get("content-range")),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"message": body[:200]}
        return {
            "exists": False,
            "status": exc.code,
            "code": payload.get("code"),
            "message": payload.get("message"),
        }


def main() -> int:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    api_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not supabase_url or not api_key:
        print(
            "Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY in environment.",
            file=sys.stderr,
        )
        return 2

    results = {table: _check_table(supabase_url, api_key, table) for table in TABLES}
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result.get("exists") is True for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
