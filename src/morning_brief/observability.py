from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from morning_brief.data.sources.domain_utils import normalize_domain

PREFERRED_PROVIDER_ORDER = ("openai", "perplexity", "grok")


@dataclass
class ProviderUsageTotals:
    requests: int = 0
    response_sources: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    usage_parse_failures: int = 0


class PipelineObserver:
    def __init__(self, *, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.run_started_at = datetime.now(timezone.utc)
        self.run_id = self.run_started_at.strftime("%Y%m%dT%H%M%SZ")
        self.events: list[dict] = []
        self.phase_durations_ms: dict[str, int] = {}
        self.provider_usage: dict[str, ProviderUsageTotals] = {}
        self.anomalies: list[dict[str, object]] = []
        self.cache_statuses: list[dict[str, object]] = []
        self.perplexity_topic_audit: dict[str, dict[str, object]] = {}

    def _emit(self, event: str, **payload: object) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        self.events.append(record)
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)

    def log_event(self, event: str, **payload: object) -> None:
        self._emit(event, **payload)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started_at = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = int(round((time.perf_counter() - started_at) * 1000))
            self.phase_durations_ms[name] = self.phase_durations_ms.get(name, 0) + duration_ms
            self._emit("phase_duration", phase=name, duration_ms=duration_ms)

    def record_provider_usage(self, provider: str, **metrics: int | None) -> None:
        totals = self.provider_usage.setdefault(provider, ProviderUsageTotals())
        for key, value in metrics.items():
            if not hasattr(totals, key):
                continue
            current_value = getattr(totals, key)
            if key in {"requests", "response_sources", "usage_parse_failures"}:
                if value is None:
                    continue
                setattr(totals, key, int(current_value) + int(value))
                continue

            if value is None:
                continue

            normalized = int(value)
            if current_value is None:
                setattr(totals, key, normalized)
            else:
                setattr(totals, key, int(current_value) + normalized)

    def record_phase_duration(self, name: str, duration_ms: int) -> None:
        self.phase_durations_ms[name] = self.phase_durations_ms.get(name, 0) + int(duration_ms)
        self._emit("phase_duration", phase=name, duration_ms=int(duration_ms))

    def record_anomaly(self, point: dict) -> None:
        status = str(point.get("validation_status", "")).strip().lower()
        if status in {"", "ok"}:
            return
        item = {
            "canonical_key": str(point.get("canonical_key", "")).strip(),
            "label": str(point.get("label", "")).strip(),
            "validation_status": status,
            "raw_value": point.get("raw_value"),
            "resolved_value": point.get("resolved_value"),
            "resolution_reason": str(point.get("resolution_reason", "")).strip(),
        }
        self.anomalies.append(item)

    def record_market_anomalies(self, packet: dict) -> None:
        for section in ("macro", "us_indices", "tech_stocks"):
            for point in packet.get(section, []):
                if isinstance(point, dict):
                    self.record_anomaly(point)

        bitcoin = packet.get("bitcoin", {})
        spot = bitcoin.get("spot")
        if isinstance(spot, dict):
            self.record_anomaly(spot)
        for point in bitcoin.get("etf_points", []):
            if isinstance(point, dict):
                self.record_anomaly(point)

        if self.anomalies:
            self._emit(
                "market_anomalies",
                count=len(self.anomalies),
                items=self.anomalies,
            )

    def record_cache_status_from_env(self) -> None:
        cache_specs = (
            ("btc_etf_snapshots", "CACHE_BTC_ETF_KEY", "CACHE_BTC_ETF_HIT", "CACHE_BTC_ETF_STATUS"),
            ("market_snapshot", "CACHE_MARKET_KEY", "CACHE_MARKET_HIT", "CACHE_MARKET_STATUS"),
            ("pip", "CACHE_PIP_KEY", "CACHE_PIP_HIT", "CACHE_PIP_STATUS"),
        )
        for cache_name, key_env, hit_env, status_env in cache_specs:
            key = os.getenv(key_env, "").strip()
            if not key:
                continue
            hit = os.getenv(hit_env, "").strip().lower() == "true"
            status = os.getenv(status_env, "").strip() or ("primary_hit" if hit else "miss")
            payload = {"cache": cache_name, "key": key, "hit": hit, "status": status}
            self.cache_statuses.append(payload)
            self._emit("cache_status", **payload)

    def record_perplexity_topic_results(self, topic: str, urls: list[str]) -> None:
        topic_audit = self.perplexity_topic_audit.setdefault(
            topic,
            {
                "candidate_urls": [],
                "candidate_domains": [],
                "final_urls": [],
                "final_domains": [],
            },
        )
        unique_urls = list(dict.fromkeys(urls))
        topic_audit["candidate_urls"] = unique_urls
        topic_audit["candidate_domains"] = list(
            dict.fromkeys(normalize_domain(url) for url in unique_urls if normalize_domain(url))
        )

    def record_perplexity_final_selection(self, packet: list[dict]) -> None:
        final_by_topic: dict[str, list[str]] = {}
        for item in packet:
            if not isinstance(item, dict):
                continue
            if str(item.get("provider", "")).strip() != "perplexity_search":
                continue
            topic = str(item.get("topic", "")).strip() or "unknown"
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            final_by_topic.setdefault(topic, []).append(url)

        for topic, urls in final_by_topic.items():
            topic_audit = self.perplexity_topic_audit.setdefault(
                topic,
                {
                    "candidate_urls": [],
                    "candidate_domains": [],
                    "final_urls": [],
                    "final_domains": [],
                },
            )
            unique_urls = list(dict.fromkeys(urls))
            topic_audit["final_urls"] = unique_urls
            topic_audit["final_domains"] = list(
                dict.fromkeys(normalize_domain(url) for url in unique_urls if normalize_domain(url))
            )

    def _ordered_provider_names(self) -> list[str]:
        prioritized = [
            provider for provider in PREFERRED_PROVIDER_ORDER if provider in self.provider_usage
        ]
        remaining = sorted(
            provider for provider in self.provider_usage if provider not in PREFERRED_PROVIDER_ORDER
        )
        return [*prioritized, *remaining]

    def provider_usage_summary_payload(self) -> dict[str, dict[str, int | None]]:
        payload: dict[str, dict[str, int | None]] = {}
        for provider in self._ordered_provider_names():
            totals = self.provider_usage[provider]
            payload[provider] = {
                "requests": totals.requests,
                "input_tokens": totals.input_tokens,
                "output_tokens": totals.output_tokens,
                "cached_input_tokens": totals.cached_input_tokens,
                "reasoning_tokens": totals.reasoning_tokens,
                "response_sources": totals.response_sources,
                "usage_parse_failures": totals.usage_parse_failures,
            }
        return payload

    def provider_usage_summary_line(self) -> str:
        payload = self.provider_usage_summary_payload()
        if not payload:
            return ""

        def fmt(value: int | None) -> str:
            return "null" if value is None else str(value)

        parts = []
        for provider, metrics in payload.items():
            parts.append(
                (
                    f"{provider}[requests={metrics['requests']}, "
                    f"input={fmt(metrics['input_tokens'])}, "
                    f"output={fmt(metrics['output_tokens'])}, "
                    f"cached={fmt(metrics['cached_input_tokens'])}, "
                    f"reasoning={fmt(metrics['reasoning_tokens'])}, "
                    f"sources={fmt(metrics['response_sources'])}, "
                    f"parse_failures={fmt(metrics['usage_parse_failures'])}]"
                )
            )
        return " | ".join(parts)

    def write_outputs(
        self,
        *,
        status: str,
        provider_stats: dict[str, dict[str, int]] | None,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        observability_dir = self.output_dir / "observability"
        observability_dir.mkdir(parents=True, exist_ok=True)

        usage_summary = self.provider_usage_summary_payload()
        usage_summary_line = self.provider_usage_summary_line()
        summary = {
            "run_id": self.run_id,
            "status": status,
            "started_at_utc": self.run_started_at.isoformat(),
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "durations_ms": dict(sorted(self.phase_durations_ms.items())),
            "provider_usage": usage_summary,
            "provider_usage_line": usage_summary_line or None,
            "provider_runtime_stats": provider_stats or {},
            "anomaly_count": len(self.anomalies),
            "anomalies": self.anomalies,
            "cache_statuses": self.cache_statuses,
        }
        if extra:
            summary.update(extra)

        if usage_summary_line:
            self._emit(
                "provider_usage_summary",
                line=usage_summary_line,
                providers=usage_summary,
            )

        run_file = observability_dir / f"pipeline-run-{self.run_id}.json"
        run_file.write_text(
            json.dumps({"events": self.events, "summary": summary}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        audit_file = observability_dir / f"perplexity-audit-{self.run_id}.json"
        audit_file.write_text(
            json.dumps(
                {"run_id": self.run_id, "topics": self.perplexity_topic_audit},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._emit("pipeline_summary", summary=summary)
        self._emit("perplexity_audit_file", path=str(audit_file))
        self._emit("pipeline_log_file", path=str(run_file))
        return summary
