"""raw/ → by_category/ 분기 후처리기.

raw/YYYY/MM/YYYY-MM-DD.jsonl 을 읽어 기사의 categories 필드 기준으로
by_category/CATNAME/YYYY/MM/YYYY-MM-DD.jsonl 을 생성한다.
하나의 기사가 여러 카테고리에 속하면 각 카테고리 파일에 모두 기록된다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_CATEGORIES: frozenset[str] = frozenset(
    {
        # 주요 코인
        "BTC",
        "ETH",
        "XRP",
        "SOL",
        "BNB",
        "ADA",
        "DOGE",
        "AVAX",
        # 시장 / 거래
        "MARKET",
        "TRADING",
        "EXCHANGE",
        "ALTCOIN",
        # 산업 구조
        "REGULATION",
        "BLOCKCHAIN",
        "MINING",
        "TECHNOLOGY",
        # 거시 / 리서치
        "MACROECONOMICS",
        "RESEARCH",
        # 전체 umbrella
        "CRYPTOCURRENCY",
    }
)


def split_raw_to_categories(data_root: Path, force: bool = False) -> None:
    """data_root/raw 하위 모든 JSONL을 by_category 로 분기."""
    raw_root = data_root / "raw"
    cat_root = data_root / "by_category"

    raw_files = sorted(raw_root.rglob("*.jsonl"))
    if not raw_files:
        logger.warning("raw/ 에 수집된 파일이 없습니다.")
        return

    logger.info("%d개 날짜 파일을 카테고리로 분기합니다...", len(raw_files))

    total_written = 0
    for raw_file in raw_files:
        date = raw_file.stem  # YYYY-MM-DD
        year, month, _ = date.split("-")

        with open(raw_file, encoding="utf-8") as f:
            articles = [json.loads(line) for line in f if line.strip()]

        by_cat: dict[str, list[dict]] = {}
        for article in articles:
            for cat in article.get("categories", []):
                if cat in TARGET_CATEGORIES:
                    by_cat.setdefault(cat, []).append(article)

        for cat, cat_articles in by_cat.items():
            out_dir = cat_root / cat / year / month
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{date}.jsonl"

            if out_path.exists() and not force:
                continue

            tmp_path = out_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                for article in cat_articles:
                    f.write(json.dumps(article, ensure_ascii=False) + "\n")
            tmp_path.rename(out_path)
            total_written += 1

    logger.info("분기 완료. 생성/갱신된 파일: %d개", total_written)
