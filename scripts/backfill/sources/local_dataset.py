"""로컬 dataset/ 디렉터리에서 기사를 읽어 RawArticle 리스트로 반환.

dataset/data/processed/{YYYY}/{MM}/{YYYY-MM-DD}.jsonl 파일을 날짜 범위로
순회한다. 파일 미존재 날짜는 건너뛴다.

RawArticle.source 는 dedup/통계용 Literal 필드이므로 "coindesk"로 고정.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from backfill.sources.coindesk import RawArticle

logger = logging.getLogger(__name__)

_DEFAULT_DATASET_ROOT = Path(__file__).resolve().parents[3] / "dataset" / "data" / "processed"


def fetch_local_articles(
    start: str,
    end: str,
    *,
    dataset_root: Path | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> list[RawArticle]:
    """dataset/data/processed/ 에서 start~end(포함) 기사를 읽어 반환.

    Args:
        start: 시작 날짜 YYYY-MM-DD
        end:   종료 날짜 YYYY-MM-DD (포함)
        dataset_root: processed/ 루트 경로. None이면 프로젝트 루트 기준 자동 탐지.
        progress_callback: {"status", "date", "loaded", "total_dates", "done_dates"} 이벤트 콜백.
    """
    root = dataset_root or _DEFAULT_DATASET_ROOT
    start_dt = date.fromisoformat(start)
    end_dt = date.fromisoformat(end)

    date_range = [start_dt + timedelta(days=i) for i in range((end_dt - start_dt).days + 1)]
    total_dates = len(date_range)
    articles: list[RawArticle] = []

    for done, dt in enumerate(date_range, start=1):
        path = root / str(dt.year) / f"{dt.month:02d}" / f"{dt}.jsonl"
        if not path.exists():
            logger.debug("로컬 파일 없음: %s", path)
            if progress_callback:
                progress_callback(
                    {
                        "status": "running",
                        "date": str(dt),
                        "loaded": len(articles),
                        "total_dates": total_dates,
                        "done_dates": done,
                    }
                )
            continue

        day_articles = _read_jsonl(path, str(dt))
        articles.extend(day_articles)
        logger.debug("로컬 로드 %s: %d건", dt, len(day_articles))

        if progress_callback:
            progress_callback(
                {
                    "status": "running",
                    "date": str(dt),
                    "loaded": len(articles),
                    "total_dates": total_dates,
                    "done_dates": done,
                }
            )

    if progress_callback:
        progress_callback(
            {
                "status": "completed",
                "loaded": len(articles),
                "total_dates": total_dates,
                "done_dates": total_dates,
            }
        )

    logger.info("로컬 데이터셋 로드 완료: %d건 (%s ~ %s)", len(articles), start, end)
    return articles


def _read_jsonl(path: Path, expected_date: str) -> list[RawArticle]:
    articles: list[RawArticle] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("JSON 파싱 실패: %s 라인 %d", path, lineno)
                continue

            article_id = str(obj.get("id", ""))
            title = str(obj.get("title", "")).strip()
            body = str(obj.get("body", "") or "").strip()
            published_ts = int(obj.get("published_ts", 0))
            date_str = str(obj.get("date", expected_date))

            if not title:
                continue

            articles.append(
                RawArticle(
                    source="coindesk",
                    article_id=article_id,
                    date=date_str,
                    title=title,
                    body=body,
                    published_ts=published_ts,
                )
            )
    return articles
