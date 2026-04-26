"""SQLite 기반 수집/처리 진행 상태 추적.

completed_dates: 수집 완료 날짜 + 파일 크기 (manifest 통합)
processed_dates: processed/ 레이어 완료 날짜
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Checkpoint:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._migrate()

    def _migrate(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS completed_dates (
                date            TEXT PRIMARY KEY,
                article_count   INTEGER NOT NULL DEFAULT 0,
                file_size_bytes INTEGER NOT NULL DEFAULT 0,
                completed_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS processed_dates (
                date            TEXT PRIMARY KEY,
                article_count   INTEGER NOT NULL DEFAULT 0,
                file_size_bytes INTEGER NOT NULL DEFAULT 0,
                processed_at    TEXT NOT NULL
            );
        """)
        # 구 스키마(file_size_bytes 없는 버전) 마이그레이션
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(completed_dates)")}
        if "file_size_bytes" not in existing:
            self._conn.execute(
                "ALTER TABLE completed_dates ADD COLUMN file_size_bytes INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()

    # ── 수집 완료 (raw) ────────────────────────────────────────────────────

    def is_done(self, date: str) -> bool:
        return (
            self._conn.execute("SELECT 1 FROM completed_dates WHERE date = ?", (date,)).fetchone()
            is not None
        )

    def mark_done(self, date: str, article_count: int, file_size_bytes: int = 0) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO completed_dates
               (date, article_count, file_size_bytes, completed_at)
               VALUES (?, ?, ?, ?)""",
            (date, article_count, file_size_bytes, now),
        )
        self._conn.commit()

    # ── 처리 완료 (processed) ──────────────────────────────────────────────

    def is_processed(self, date: str) -> bool:
        return (
            self._conn.execute("SELECT 1 FROM processed_dates WHERE date = ?", (date,)).fetchone()
            is not None
        )

    def mark_processed(self, date: str, article_count: int, file_size_bytes: int = 0) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO processed_dates
               (date, article_count, file_size_bytes, processed_at)
               VALUES (?, ?, ?, ?)""",
            (date, article_count, file_size_bytes, now),
        )
        self._conn.commit()

    # ── 요약 ───────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        raw = self._conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(article_count),0),
                      COALESCE(SUM(file_size_bytes),0),
                      MIN(date), MAX(date)
               FROM completed_dates"""
        ).fetchone()
        proc = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(article_count),0) FROM processed_dates"
        ).fetchone()
        return {
            "completed_dates": raw[0] or 0,
            "total_articles": raw[1] or 0,
            "total_raw_bytes": raw[2] or 0,
            "earliest_date": raw[3],
            "latest_date": raw[4],
            "processed_dates": proc[0] or 0,
            "processed_articles": proc[1] or 0,
        }

    def done_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM completed_dates").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
