"""signal_logger.py — 발송된 신호를 Supabase signal_log 테이블에 기록."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


def _get_supabase_client(supabase_url: str, service_role_key: str):  # type: ignore[return]
    try:
        from supabase import create_client

        return create_client(supabase_url, service_role_key)
    except Exception as exc:
        logger.warning("Supabase 클라이언트 초기화 실패: %s", exc)
        return None


def log_signal(
    *,
    supabase_url: str,
    service_role_key: str,
    signal_date: date,
    regime_state: str,
    vol_level: str,
    vol_trend: str,
    overlay_decision: str,
    confidence: str | None,
    reasons: list[str],
    btc_price_open: float | None,
) -> bool:
    """signal_log 테이블에 오늘 신호를 upsert.

    Returns True if successful, False otherwise.
    """
    client = _get_supabase_client(supabase_url, service_role_key)
    if client is None:
        return False

    row: dict[str, Any] = {
        "signal_date": signal_date.isoformat(),
        "regime_state": regime_state,
        "vol_level": vol_level,
        "vol_trend": vol_trend,
        "overlay_decision": overlay_decision,
        "confidence": confidence,
        "reasons": reasons,
        "btc_price_open": btc_price_open,
    }

    try:
        client.table("signal_log").upsert(row, on_conflict="signal_date").execute()
        logger.info(
            "signal_log 기록 완료: date=%s regime=%s confidence=%s",
            signal_date,
            regime_state,
            confidence,
        )
        return True
    except Exception as exc:
        logger.warning("signal_log upsert 실패: %s", exc)
        return False


def fetch_track_record(
    *,
    supabase_url: str,
    service_role_key: str,
    days: int = 90,
) -> dict[str, Any]:
    """최근 N일 신호 적중률 통계 반환.

    Returns:
        {
            "signal_count": int,       # 신호가 있었던 날 수
            "hit_count": int,          # 적중 수
            "hit_rate": float | None,  # 적중률
            "days_evaluated": int,     # 평가된 날 수 (hit 컬럼이 채워진 날)
        }
    """
    client = _get_supabase_client(supabase_url, service_role_key)
    if client is None:
        return _empty_track_record()

    try:
        from datetime import timedelta

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        resp = (
            client.table("signal_log")
            .select("confidence, hit")
            .gte("signal_date", cutoff)
            .not_.is_("confidence", "null")  # 신호 있는 날만
            .execute()
        )
        rows = resp.data or []
        evaluated = [r for r in rows if r.get("hit") is not None]
        hit_count = sum(1 for r in evaluated if r["hit"] is True)
        return {
            "signal_count": len(rows),
            "hit_count": hit_count,
            "hit_rate": round(hit_count / len(evaluated), 3) if evaluated else None,
            "days_evaluated": len(evaluated),
        }
    except Exception as exc:
        logger.warning("track_record 조회 실패: %s", exc)
        return _empty_track_record()


def _empty_track_record() -> dict[str, Any]:
    return {"signal_count": 0, "hit_count": 0, "hit_rate": None, "days_evaluated": 0}
