"""WI-9: Binance 선물 강제청산(forceOrder) 스트림 — 4h 버킷 집계 → 저장(수집 전용).

역발산 계열(fng_contrarian·omnibus REBOUND)의 '매도 소진(캐피출레이션)' 직접 증거 데이터.
현재 v23의 MACD 히스토그램 프록시보다 직접적. 이번 범위는 수집·저장까지 — 지표 연결/알고
반영은 30일+ 축적 후 별도 WI(v2).

⚠️ forceOrder는 **선물 스트림**(fstream)이라 현물 kline 커넥션과 별도 태스크/커넥션.
트레이딩 경로와 완전 분리 — 이 태스크가 죽어도 스케줄러·스트림·리스크는 무영향.

forceOrder 이벤트 side(S) 해석:
  SELL = 롱 포지션이 강제 매도됨(롱 청산) → long_liq_usd
  BUY  = 숏 포지션이 강제 매수됨(숏 청산) → short_liq_usd
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from . import config, data_lake, parameters

logger = logging.getLogger(__name__)

_BUCKET_SECONDS = 4 * 3600  # 4h — arena 기본 봉과 정렬


def _bucket_start(ts_ms: int) -> datetime:
    """이벤트 타임스탬프(ms)를 4h 버킷 시작(UTC)으로 내림."""
    epoch = ts_ms // 1000
    floored = epoch - (epoch % _BUCKET_SECONDS)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


class _Bucket:
    __slots__ = ("start", "long_usd", "short_usd", "long_n", "short_n")

    def __init__(self, start: datetime) -> None:
        self.start = start
        self.long_usd = 0.0
        self.short_usd = 0.0
        self.long_n = 0
        self.short_n = 0

    def add(self, side: str, notional: float) -> None:
        if side == "SELL":  # 롱 강제청산
            self.long_usd += notional
            self.long_n += 1
        else:  # BUY — 숏 강제청산
            self.short_usd += notional
            self.short_n += 1


async def _flush(bucket: _Bucket) -> None:
    result = await data_lake.record_liquidation_bar(
        bar_start=bucket.start,
        symbol=parameters.BINANCE_SYMBOL,
        long_liq_usd=round(bucket.long_usd, 2),
        short_liq_usd=round(bucket.short_usd, 2),
        long_liq_count=bucket.long_n,
        short_liq_count=bucket.short_n,
    )
    logger.info(
        "Liquidation bar flushed: %s long=$%.0f(%d) short=$%.0f(%d) ok=%s",
        bucket.start.isoformat(),
        bucket.long_usd,
        bucket.long_n,
        bucket.short_usd,
        bucket.short_n,
        result.ok,
    )


async def run() -> None:
    """무한 재접속 루프. server가 asyncio.create_task로 실행.

    ⚠️ server의 asyncio.wait(FIRST_COMPLETED)는 태스크 하나라도 '완료'되면 전체 종료한다.
    플래그 off 시 return하면 이 태스크가 즉시 완료 → 서버 전체 종료 버그. 따라서 비활성
    시에도 return하지 않고 영구 park(다른 상시 태스크들과 동일 수명 유지)한다.
    """
    if not config.ARENA_LIQUIDATION_STREAM_ENABLED:
        logger.info("Liquidation stream disabled (ARENA_LIQUIDATION_STREAM_ENABLED=false) — parked")
        await asyncio.Event().wait()  # 영구 대기 — 완료되지 않아 FIRST_COMPLETED를 트리거 안 함
        return
    current: _Bucket | None = None
    while True:
        try:
            async with websockets.connect(
                config.BINANCE_FUTURES_LIQUIDATION_WS_URL,
                ping_interval=parameters.WEBSOCKET_PING_INTERVAL_SECONDS,
            ) as ws:
                logger.info("Liquidation WebSocket connected (fstream forceOrder)")
                async for raw in ws:
                    data = json.loads(raw)
                    o = data.get("o") or {}
                    try:
                        side = str(o.get("S") or "")
                        price = float(o.get("p") or 0.0)
                        qty = float(o.get("q") or 0.0)
                        ts_ms = int(o.get("T") or o.get("E") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not side or price <= 0 or qty <= 0 or ts_ms <= 0:
                        continue
                    start = _bucket_start(ts_ms)
                    if current is None:
                        current = _Bucket(start)
                    elif start > current.start:
                        # 새 4h 버킷 시작 → 직전 버킷 flush.
                        await _flush(current)
                        current = _Bucket(start)
                    current.add(side, price * qty)
        except asyncio.CancelledError:
            if current is not None:
                await _flush(current)  # 종료 시 진행 중 버킷 보존(best-effort)
            raise
        except Exception as exc:
            logger.warning(
                "Liquidation WebSocket error: %s — reconnecting in %ss",
                exc,
                parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS)
