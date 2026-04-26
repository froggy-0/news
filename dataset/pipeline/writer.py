"""JSONL 원자적 쓰기."""

from __future__ import annotations

import json
from pathlib import Path


def write_day_raw(data_root: Path, date: str, articles: list[dict]) -> Path:
    """articles를 raw/YYYY/MM/YYYY-MM-DD.jsonl 에 원자적으로 기록.

    임시 파일(.tmp)에 쓴 뒤 rename하여 중단 시 부분 파일이 남지 않는다.
    """
    year, month, _ = date.split("-")
    out_dir = data_root / "raw" / year / month
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}.jsonl"
    tmp_path = out_path.with_suffix(".tmp")

    with open(tmp_path, "w", encoding="utf-8") as f:
        for article in articles:
            f.write(json.dumps(article, ensure_ascii=False) + "\n")

    tmp_path.rename(out_path)
    return out_path
