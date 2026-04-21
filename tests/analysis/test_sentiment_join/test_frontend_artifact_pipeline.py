"""frontend_artifact pipeline 통합 테스트.

pipeline.py의 artifact 생성·skip 분기를 검증한다.
실제 파이프라인 전체를 실행하지 않고,
build_frontend_artifact + should_skip_artifact + write_frontend_artifact 호출 흐름만 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from morning_brief.analysis.sentiment_join.frontend_artifact import (
    build_frontend_artifact,
    should_skip_artifact,
    write_frontend_artifact,
)


def _make_stats_bytes(full_quality: str = "ok", core_quality: str = "ok") -> bytes:
    payload = {
        "run_id": "sentiment-join-20260421",
        "generated_at_utc": "2026-04-21T08:00:00+00:00",
        "granger_executed": True,
        "granger_results": [],
        "granger_correction": {"correction_method": "fdr_bh", "n_tests": 63},
        "hybrid_indices": {
            "full": {
                "quality_status": full_quality,
                "quality_reasons": [],
                "pca_summary": {
                    "status": "ok",
                    "selected_features": ["news_sentiment_mean_lag1"],
                    "n_components": 1,
                    "explained_variance": 0.8,
                    "loadings": {"news_sentiment_mean_lag1": 0.5},
                },
                "coverage": {"ratio": 0.9},
                "excluded_features": [],
            },
            "core": {
                "quality_status": core_quality,
                "quality_reasons": [],
                "pca_summary": {
                    "status": "ok",
                    "selected_features": ["news_sentiment_mean_lag1"],
                    "n_components": 1,
                    "explained_variance": 0.75,
                    "loadings": {"news_sentiment_mean_lag1": 0.52},
                },
                "coverage": {"ratio": 0.92},
                "excluded_features": [],
            },
        },
    }
    return json.dumps(payload).encode("utf-8")


class TestSkipCondition:
    def test_skip_when_both_critical(self):
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes("critical", "critical"),
            reference_date="2026-04-21",
        )
        assert should_skip_artifact(artifact) is True

    def test_no_skip_when_one_ok(self):
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes("critical", "ok"),
            reference_date="2026-04-21",
        )
        assert should_skip_artifact(artifact) is False

    def test_no_skip_when_both_ok(self):
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes("ok", "ok"),
            reference_date="2026-04-21",
        )
        assert should_skip_artifact(artifact) is False

    def test_no_skip_when_degraded(self):
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes("degraded", "degraded"),
            reference_date="2026-04-21",
        )
        assert should_skip_artifact(artifact) is False


class TestWriteFrontendArtifact:
    def test_returns_two_paths(self, tmp_path: Path):
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes(),
            reference_date="2026-04-21",
        )
        latest, dated = write_frontend_artifact(tmp_path, artifact, "20260421")
        assert latest.name == "latest.json"
        assert dated.name == "20260421.json"

    def test_skip_condition_prevents_write(self, tmp_path: Path):
        """should_skip_artifact가 True면 write_frontend_artifact를 호출하지 않는다."""
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes("critical", "critical"),
            reference_date="2026-04-21",
        )
        # skip 조건 True 확인
        assert should_skip_artifact(artifact) is True

        # 파이프라인과 동일한 분기 패턴으로 실행
        written = False
        if not should_skip_artifact(artifact):
            write_frontend_artifact(tmp_path, artifact, "20260421")
            written = True

        assert not written
        assert not (tmp_path / "latest.json").exists()

    def test_normal_condition_writes_files(self, tmp_path: Path):
        """should_skip_artifact가 False면 두 파일이 생성된다."""
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes("ok", "ok"),
            reference_date="2026-04-21",
        )
        assert not should_skip_artifact(artifact)

        latest, dated = write_frontend_artifact(tmp_path, artifact, "20260421")
        assert latest.exists()
        assert dated.exists()

    def test_written_content_is_valid_json(self, tmp_path: Path):
        artifact = build_frontend_artifact(
            stats_metadata_bytes=_make_stats_bytes(),
            reference_date="2026-04-21",
        )
        latest, _ = write_frontend_artifact(tmp_path, artifact, "20260421")
        parsed = json.loads(latest.read_text())
        assert "granger" in parsed
        assert "pca" in parsed
        assert parsed["referenceDate"] == "2026-04-21"
