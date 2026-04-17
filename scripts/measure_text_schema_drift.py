#!/usr/bin/env python3
"""§2: why_it_matters 포함/미포함 감성 점수 차이 측정 스크립트.

실시간 파이프라인의 최근 기사 샘플에 대해, 동일 기사를
  - "title_summary": title + summary만 사용 (백필 방식)
  - "title_summary_whyitmatters": title + summary + why_it_matters 포함 (실시간 방식)
두 가지 방식으로 스코어링한 뒤 차이(|Δscore|)를 산출합니다.

결과 해석:
  |Δmean_daily| p95 < 0.03  → Option B(메타데이터 마킹만) 충분
  |Δmean_daily| p95 >= 0.03 → Option A(단일 빌더 통일 + 재집계) 권장

사용법:
    python scripts/measure_text_schema_drift.py \\
        --r2-bucket https://your-r2-bucket-url \\
        --lookback-days 60 \\
        --output drift_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 프로젝트 루트를 sys.path에 추가
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


def _check_deps() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401

        return True
    except ImportError:
        logger.error("transformers/torch 미설치. pip install -r requirements-ml.txt 로 설치하세요.")
        return False


def _build_minimal(item: dict[str, Any]) -> str:
    """title + summary만 사용 (백필 방식)."""
    from morning_brief.data.finbert_sentiment import FinBertScorer

    return FinBertScorer.combine_fields(
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
    )


def _build_full(item: dict[str, Any]) -> str:
    """title + summary + why_it_matters 포함 (실시간 방식)."""
    from morning_brief.data.finbert_sentiment import build_news_sentiment_text

    return build_news_sentiment_text(item)


def _load_sample_articles(r2_bucket: str, lookback_days: int) -> list[dict[str, Any]]:
    """R2에서 최근 lookback_days일치 기사를 수집합니다."""
    from datetime import date, timedelta

    from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry

    articles: list[dict[str, Any]] = []
    today = date.today()
    for i in range(lookback_days):
        d = today - timedelta(days=i + 1)
        date_str = d.strftime("%Y-%m-%d")
        url = f"{r2_bucket.rstrip('/')}/analytics/btc/{date_str}.json"
        try:
            payload = get_json_with_retry(url, provider="r2", timeout=15)
        except HttpFetchError as exc:
            if exc.status_code == 404:
                continue
            logger.warning("R2 fetch 실패 date=%s reason=%s", date_str, exc)
            continue
        except Exception as exc:
            logger.warning("R2 fetch 오류 date=%s reason=%s", date_str, exc)
            continue

        news_items = payload.get("newsItems") or []
        for item in news_items:
            if item.get("why_it_matters"):
                item["_date"] = date_str
                articles.append(item)

    logger.info("why_it_matters 있는 기사 %d건 수집 완료", len(articles))
    return articles


def _score_articles(
    articles: list[dict[str, Any]],
    batch_size: int = 16,
) -> list[dict[str, Any]]:
    """각 기사에 대해 두 방식으로 스코어링."""
    import os

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    from morning_brief.config import Settings
    from morning_brief.data.finbert_sentiment import FinBertScorer

    settings = Settings()
    scorer = FinBertScorer(settings)

    minimal_texts = [_build_minimal(a) for a in articles]
    full_texts = [_build_full(a) for a in articles]

    logger.info("스코어링 시작 (기사 %d건 × 2방식)…", len(articles))
    minimal_results = scorer.score_texts(minimal_texts)
    full_results = scorer.score_texts(full_texts)

    records = []
    for article, r_min, r_full in zip(articles, minimal_results, full_results):
        if r_min.score is None or r_full.score is None:
            continue
        records.append(
            {
                "date": article.get("_date"),
                "title": article.get("title", "")[:80],
                "score_minimal": r_min.score,
                "score_full": r_full.score,
                "delta": abs(r_full.score - r_min.score),
            }
        )

    return records


def _compute_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """일별 집계 후 |Δmean_daily| 통계 산출."""
    from collections import defaultdict

    import numpy as np

    by_date: dict[str, list[float]] = defaultdict(list)
    for r in records:
        if r["date"]:
            by_date[r["date"]].append(r["delta"])

    daily_mean_deltas = [float(np.mean(v)) for v in by_date.values() if v]

    if not daily_mean_deltas:
        return {"error": "데이터 없음"}

    arr = np.array(daily_mean_deltas)
    return {
        "n_articles": len(records),
        "n_days": len(daily_mean_deltas),
        "delta_p50": float(np.percentile(arr, 50)),
        "delta_p95": float(np.percentile(arr, 95)),
        "delta_mean": float(np.mean(arr)),
        "delta_max": float(np.max(arr)),
        "recommendation": (
            "Option B (메타데이터 마킹만)"
            if float(np.percentile(arr, 95)) < 0.03
            else "Option A (단일 빌더 통일 + 재집계 권장)"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r2-bucket", required=True, help="R2 공개 버킷 URL")
    parser.add_argument("--lookback-days", type=int, default=60, help="수집 일수 (기본: 60)")
    parser.add_argument("--output", default="-", help="결과 출력 경로 (기본: stdout)")
    args = parser.parse_args()

    if not _check_deps():
        sys.exit(1)

    articles = _load_sample_articles(args.r2_bucket, args.lookback_days)
    if not articles:
        logger.error("why_it_matters 있는 기사를 찾을 수 없습니다.")
        sys.exit(1)

    records = _score_articles(articles)
    stats = _compute_stats(records)

    result = {"stats": stats, "sample_records": records[:20]}

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(output)
    else:
        Path(args.output).write_text(output, encoding="utf-8")
        logger.info("결과 저장: %s", args.output)

    logger.info(
        "완료 — p95 |Δmean_daily|=%.4f → %s",
        stats.get("delta_p95", float("nan")),
        stats.get("recommendation", "?"),
    )


if __name__ == "__main__":
    main()
