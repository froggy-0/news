#!/usr/bin/env python3
"""fill_signal_outcomes.py — 7일 전 signal_log 레코드에 실제 BTC 수익률/적중 여부를 채운다.

매일 크론으로 실행. 환경변수:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# src 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_OUTCOME_LAG_DAYS = 7  # 신호 발송 후 성과 측정 기준일


def _supabase_client():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        logger.info("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 미설정 — 건너뜀")
        return None
    from supabase import create_client

    return create_client(url, key)


def _fetch_pending_rows(client) -> list[dict]:
    """btc_price_7d가 비어 있고, 이미 평가 가능한 날짜(signal_date + 7 <= today)인 레코드."""
    cutoff = (date.today() - timedelta(days=_OUTCOME_LAG_DAYS)).isoformat()
    resp = (
        client.table("signal_log")
        .select("id, signal_date, confidence, btc_price_open")
        .is_("btc_price_7d", "null")
        .lte("signal_date", cutoff)
        .execute()
    )
    return resp.data or []


def _fetch_btc_price_on(target_date: date) -> float | None:
    """target_date 의 BTC 종가 (yfinance). 없으면 None."""
    try:
        from morning_brief.analysis.sentiment_join.sources.btc_prices import (
            fetch_btc_close_yfinance,
        )

        start = target_date.isoformat()
        end = (target_date + timedelta(days=2)).isoformat()  # +2로 주말 대응
        df = fetch_btc_close_yfinance(start, end)
        if df is None or df.empty:
            return None
        # 날짜 컬럼 정규화
        if "date" in df.columns:
            df["date"] = df["date"].astype(str).str[:10]
            row = df[df["date"] == target_date.isoformat()]
        else:
            df.index = df.index.astype(str).str[:10]
            row = df[df.index == target_date.isoformat()]
        if row.empty:
            # 가장 가까운 날짜 사용 (주말 등)
            close_col = next((c for c in df.columns if "close" in c.lower()), df.columns[0])
            return float(df[close_col].iloc[0])
        close_col = next((c for c in row.columns if "close" in c.lower()), row.columns[0])
        return float(row[close_col].iloc[0])
    except Exception as exc:
        logger.warning("BTC 가격 조회 실패 (%s): %s", target_date, exc)
        return None


def _compute_hit(
    confidence: str | None,
    btc_price_open: float | None,
    btc_price_7d: float | None,
) -> bool | None:
    """신호 방향과 실제 7일 수익이 일치하면 True.

    confidence가 None(신호 없음)이면 hit 평가 대상 아님 → None.
    신호는 항상 long 방향 (현재 파이프라인이 long-only).
    """
    if confidence is None or btc_price_open is None or btc_price_7d is None:
        return None
    ret = (btc_price_7d / btc_price_open) - 1
    return bool(ret > 0)


def main() -> None:
    client = _supabase_client()
    if client is None:
        return
    pending = _fetch_pending_rows(client)

    if not pending:
        logger.info("채울 레코드 없음 — 완료")
        return

    logger.info("처리 대상 레코드 %d건", len(pending))
    updated = 0

    for row in pending:
        signal_date = date.fromisoformat(row["signal_date"])
        outcome_date = signal_date + timedelta(days=_OUTCOME_LAG_DAYS)

        price_7d = _fetch_btc_price_on(outcome_date)
        if price_7d is None:
            logger.warning("BTC 가격 없음: %s (signal_date=%s)", outcome_date, signal_date)
            continue

        price_open = row.get("btc_price_open")
        ret_7d = ((price_7d / price_open) - 1) if price_open else None
        hit = _compute_hit(row.get("confidence"), price_open, price_7d)

        try:
            client.table("signal_log").update(
                {
                    "btc_price_7d": price_7d,
                    "ret_7d": ret_7d,
                    "hit": hit,
                }
            ).eq("id", row["id"]).execute()
            logger.info(
                "업데이트: signal_date=%s price_7d=%.0f ret_7d=%.2f%% hit=%s",
                signal_date,
                price_7d,
                (ret_7d or 0) * 100,
                hit,
            )
            updated += 1
        except Exception as exc:
            logger.error("업데이트 실패 id=%s: %s", row["id"], exc)

    logger.info("완료: %d/%d 건 업데이트", updated, len(pending))


if __name__ == "__main__":
    main()
