"""raw/ → processed/ 전처리 레이어.

raw/ 는 API 응답을 그대로 보존한다 (불변).
processed/ 는 ML 학습에 바로 쓸 수 있도록 정제된 사본이다.

적용되는 정제 작업 (_CLEANING_OPS):
  - rss_suffix   : "appeared first on X." 형태의 RSS 배포 꼬리말 제거
  - whitespace   : 연속 공백/줄바꿈 정규화
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 정제 규칙 ────────────────────────────────────────────────────────────────

# RSS 배포 꼬리말: "The post TITLE appeared first on SOURCE." 또는
#                  "… appeared first on SOURCE."
# 기사 본문 마지막에만 매칭 (DOTALL 불필요, $ 앵커 사용)
_RSS_RE = re.compile(
    r"\s*(?:The post\s+.+?\s+)?[Aa]ppeared first on\s+.+?\.?\s*$",
    re.MULTILINE,
)

_CLEANING_OPS = ["rss_suffix", "whitespace"]


def _clean_body(text: str) -> str:
    text = _RSS_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)  # 연속 공백 → 단일 공백
    text = re.sub(r"\n{3,}", "\n\n", text)  # 3줄 이상 빈 줄 → 2줄
    return text.strip()


def _process_article(article: dict, processed_at: str) -> dict:
    """article dict를 정제하여 새 dict 반환. 원본은 변경하지 않는다."""
    clean_body = _clean_body(article.get("body", ""))
    return {
        **article,
        "body": clean_body,
        "body_char_count": len(clean_body),
        "_schema_version": article.get("_schema_version", "1"),
        "_cleaning_ops": _CLEANING_OPS,
        "_processed_at": processed_at,
    }


# ── 파일 단위 처리 ────────────────────────────────────────────────────────────


def process_day(
    data_root: Path,
    date: str,
    *,
    force: bool = False,
) -> tuple[int, int]:
    """raw/YYYY/MM/YYYY-MM-DD.jsonl 을 정제하여 processed/ 에 저장.

    Returns (article_count, file_size_bytes).
    raw 파일이 없으면 (0, 0) 반환.
    """
    year, month, _ = date.split("-")
    raw_path = data_root / "raw" / year / month / f"{date}.jsonl"
    if not raw_path.exists():
        logger.debug("raw 파일 없음, 건너뜁니다: %s", raw_path)
        return 0, 0

    out_dir = data_root / "processed" / year / month
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}.jsonl"

    if out_path.exists() and not force:
        return 0, 0

    processed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(raw_path, encoding="utf-8") as f:
        raw_articles = [json.loads(line) for line in f if line.strip()]

    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for article in raw_articles:
            cleaned = _process_article(article, processed_at)
            f.write(json.dumps(cleaned, ensure_ascii=False) + "\n")

    tmp_path.rename(out_path)
    return len(raw_articles), out_path.stat().st_size
