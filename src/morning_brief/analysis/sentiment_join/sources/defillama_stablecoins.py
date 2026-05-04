from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

from morning_brief.data.sources.http_client import get_json_with_retry, get_list_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

DEFILLAMA_STABLECOINS_URL = "https://stablecoins.llama.fi/stablecoins"
DEFILLAMA_CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/all"

SUPABASE_TABLE = "stablecoin_supply_daily"

# DefiLlama ID가 바뀌는 경우를 대비한 동적 조회 + 하드코딩 폴백
_FALLBACK_IDS: dict[str, str] = {"USDT": "1", "USDC": "2"}


# ---------------------------------------------------------------------------
# DefiLlama 수집
# ---------------------------------------------------------------------------


def _lookup_id(symbol: str) -> str | None:
    try:
        payload = get_json_with_retry(
            DEFILLAMA_STABLECOINS_URL,
            params={"includePrices": "false"},
            provider="defillama",
            timeout=20,
        )
        items = payload.get("peggedAssets", []) if isinstance(payload, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("symbol", "").upper() == symbol.upper():
                return str(item["id"])
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message=f"DefiLlama stablecoin ID 조회 실패: {symbol}",
            level=logging.WARNING,
            source="defillama",
            reason=str(exc),
        )
    fallback = _FALLBACK_IDS.get(symbol.upper())
    if fallback:
        log_structured(
            logger,
            event="source.skipped",
            message=f"DefiLlama ID 조회 실패 — fallback ID 사용: {symbol}={fallback}",
            source="defillama",
        )
    return fallback


def _fetch_chart(stablecoin_id: str, cutoff_date: str) -> dict[str, float]:
    """전체 이력을 가져와 cutoff_date 이후 행만 반환합니다.

    date 필드는 unix timestamp 문자열입니다.
    totalCirculatingUSD.peggedUSD를 사용합니다.
    """
    try:
        rows = get_list_with_retry(
            DEFILLAMA_CHART_URL,
            params={"stablecoin": stablecoin_id},
            provider="defillama",
            timeout=30,
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message=f"DefiLlama stablecoin chart 수집 실패: id={stablecoin_id}",
            level=logging.WARNING,
            source="defillama",
            reason=str(exc),
        )
        return {}

    result: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        if raw_date is None:
            continue
        try:
            day = datetime.fromtimestamp(int(raw_date), tz=timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            continue
        if day < cutoff_date:
            continue
        try:
            val = float(row["totalCirculatingUSD"]["peggedUSD"])
        except (KeyError, TypeError, ValueError):
            continue
        if val > 0:
            result[day] = val
    return result


# ---------------------------------------------------------------------------
# Supabase 읽기 / 쓰기
# ---------------------------------------------------------------------------


def _get_supabase_client():
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        return None
    from supabase import create_client

    return create_client(supabase_url, service_role_key)


def _read_from_supabase(start_date: str, end_date: str) -> dict[str, dict[str, float | None]]:
    """stablecoin_supply_daily에서 USDT·USDC 일별 supply를 읽습니다.

    반환: {YYYY-MM-DD: {"USDT": float|None, "USDC": float|None}}
    SUPABASE_URL 미설정 또는 오류 시 빈 dict 반환.
    """
    client = _get_supabase_client()
    if client is None:
        log_structured(
            logger,
            event="supabase.stablecoin.skipped",
            message="SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY 미설정 — 캐시를 건너뜁니다.",
            level=logging.WARNING,
        )
        return {}
    try:
        resp = (
            client.table(SUPABASE_TABLE)
            .select("date,symbol,supply_usd")
            .in_("symbol", ["USDT", "USDC"])
            .gte("date", start_date)
            .lte("date", end_date)
            .order("date")
            .limit(5000)
            .execute()
        )
        data = getattr(resp, "data", None)
        if not isinstance(data, list):
            return {}

        result: dict[str, dict[str, float | None]] = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            d = row.get("date")
            sym = row.get("symbol")
            val = row.get("supply_usd")
            if not d or sym not in ("USDT", "USDC"):
                continue
            if d not in result:
                result[d] = {"USDT": None, "USDC": None}
            if val is not None:
                result[d][sym] = float(val)

        log_structured(
            logger,
            event="supabase.stablecoin.read",
            message="Supabase stablecoin 캐시 읽기 완료.",
            rows=len(data),
            dates=len(result),
            start=start_date,
            end=end_date,
        )
        return result
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Supabase stablecoin 캐시 읽기 실패.",
            level=logging.WARNING,
            source="supabase_stablecoin",
            reason=str(exc),
        )
        return {}


def _write_to_supabase(records: list[dict]) -> None:
    """stablecoin_supply_daily에 upsert합니다. 오류 시 로그만, 파이프라인 무중단."""
    if not records:
        return
    client = _get_supabase_client()
    if client is None:
        return
    try:
        BATCH = 500
        for i in range(0, len(records), BATCH):
            client.table(SUPABASE_TABLE).upsert(
                records[i : i + BATCH], on_conflict="date,symbol"
            ).execute()
        log_structured(
            logger,
            event="supabase.stablecoin.write",
            message="Supabase stablecoin 캐시 저장 완료.",
            rows=len(records),
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Supabase stablecoin 캐시 저장 실패.",
            level=logging.WARNING,
            source="supabase_stablecoin",
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def fetch_stablecoin_supply(start_date: str, end_date: str) -> pd.DataFrame:
    """USDT+USDC 일별 공급량 합계 기반 7일 변화율 피처를 반환합니다.

    반환: DataFrame(date, usdt_usdc_supply_change_7d)
    실패 또는 데이터 부족 시 빈 DataFrame 반환.
    """
    # pct_change(7) lookback 버퍼: 최소 10일 앞
    buffer_start = (datetime.fromisoformat(start_date) - timedelta(days=10)).strftime("%Y-%m-%d")

    # 1) Supabase 캐시 읽기
    cached = _read_from_supabase(buffer_start, end_date)

    # 2) 빠진 날짜 계산
    start_dt = datetime.fromisoformat(buffer_start).date()
    end_dt = datetime.fromisoformat(end_date).date()
    all_dates = [
        (start_dt + timedelta(days=i)).isoformat() for i in range((end_dt - start_dt).days + 1)
    ]
    missing = [
        d
        for d in all_dates
        if d not in cached or cached[d].get("USDT") is None or cached[d].get("USDC") is None
    ]

    # 3) 빠진 날짜가 있으면 DefiLlama에서 수집
    if missing:
        fetch_from = missing[0]
        log_structured(
            logger,
            event="source.fetch",
            message=f"DefiLlama stablecoin 수집 시작 ({len(missing)}일 누락).",
            missing_from=fetch_from,
            missing_to=missing[-1],
        )
        usdt_id = _lookup_id("USDT")
        usdc_id = _lookup_id("USDC")

        usdt_chart: dict[str, float] = _fetch_chart(usdt_id, fetch_from) if usdt_id else {}
        usdc_chart: dict[str, float] = _fetch_chart(usdc_id, fetch_from) if usdc_id else {}

        if not usdt_chart and not usdc_chart:
            log_structured(
                logger,
                event="source.failed",
                message="DefiLlama USDT·USDC 수집 모두 실패.",
                level=logging.WARNING,
                source="defillama",
            )
            return pd.DataFrame({"date": pd.Series(dtype="object")})

        # Supabase에 upsert할 레코드 구성
        new_dates = set(usdt_chart) | set(usdc_chart)
        new_records: list[dict] = []
        for d in new_dates:
            if usdt_val := usdt_chart.get(d):
                new_records.append(
                    {"date": d, "symbol": "USDT", "supply_usd": usdt_val, "source": "defillama"}
                )
            if usdc_val := usdc_chart.get(d):
                new_records.append(
                    {"date": d, "symbol": "USDC", "supply_usd": usdc_val, "source": "defillama"}
                )
        _write_to_supabase(new_records)

        # cached에 병합
        for d, val in usdt_chart.items():
            cached.setdefault(d, {"USDT": None, "USDC": None})["USDT"] = val
        for d, val in usdc_chart.items():
            cached.setdefault(d, {"USDT": None, "USDC": None})["USDC"] = val

    # 4) 전체 합계 시리즈 구성
    rows = []
    for d in sorted(cached):
        usdt_val = cached[d].get("USDT") or 0.0
        usdc_val = cached[d].get("USDC") or 0.0
        total = usdt_val + usdc_val
        rows.append({"date": d, "_total_supply": total if total > 0 else float("nan")})

    if not rows:
        return pd.DataFrame({"date": pd.Series(dtype="object")})

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df["usdt_usdc_supply_change_7d"] = df["_total_supply"].pct_change(periods=7)
    df = df.drop(columns=["_total_supply"])

    # start_date~end_date만 반환
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].reset_index(drop=True)

    valid = int(df["usdt_usdc_supply_change_7d"].notna().sum())
    log_structured(
        logger,
        event="source.complete",
        message="stablecoin supply feature 생성 완료.",
        source="defillama",
        rows=len(df),
        valid_rows=valid,
        start=df["date"].iloc[0] if len(df) else None,
        end=df["date"].iloc[-1] if len(df) else None,
    )
    return df


__all__ = ["fetch_stablecoin_supply"]
