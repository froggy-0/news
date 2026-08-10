"""WI-9: Binance 선물 강제청산(forceOrder) 스트림 — 4h 버킷 집계 → 저장(수집 전용).

역발산 계열(fng_contrarian·omnibus REBOUND)의 '매도 소진(캐피출레이션)' 직접 증거 데이터.
현재 v23의 MACD 히스토그램 프록시보다 직접적.

⚠️ forceOrder는 **선물 스트림**(fstream)이라 현물 kline 커넥션과 별도 태스크/커넥션.
트레이딩 경로와 완전 분리 — 이 태스크가 죽어도 스케줄러·스트림·리스크는 무영향.

forceOrder 이벤트 side(S) 해석:
  SELL = 롱 포지션이 강제 매도됨(롱 청산) → long_liq_usd
  BUY  = 숏 포지션이 강제 매수됨(숏 청산) → short_liq_usd

2026-08-10: BTC 단일 심볼에서 parameters.MULTI_ASSET_SYMBOLS(BTC/ETH/SOL) 콤바인드 스트림으로
확장(stream.py의 kline 콤바인드 패턴과 동일 원칙 — 자산별 재튜닝 없이 심볼만 확장).
심볼별로 독립된 4h 버킷을 유지해야 하므로 단일 `current` 대신 `dict[symbol, _Bucket]`을 쓴다.
피처 연결(liquidation_features.py, macro 주입)은 도입됐지만 게이트는 기본 off — 설계 근거는
docs/arena/research/liquidation-feature-design-20260810.md 참조.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import websockets

from . import config, data_lake, parameters

logger = logging.getLogger(__name__)

_BUCKET_SECONDS = 4 * 3600  # 4h — arena 기본 봉과 정렬
# 2026-07-14 진단(오판정, 2026-08-10 정정): "서울 지역차단으로 프레임이 구조적으로 안 옴"이라고
# 봤었으나, 실제 원인은 config.BINANCE_FUTURES_LIQUIDATION_WS_URL에 "/market" 라우팅 경로가
# 빠져있던 것 — 이 경로 없이는 핸드셰이크는 성공해도(구버전 무라우팅 URL도 여전히 연결은 됨)
# forceOrder 프레임을 아예 안 준다. 로컬 실측(scripts/analysis/liquidation_ws_probe.py)으로
# /market/ws/... 는 정상 수신 확인. 상세: docs/arena/research/
# liquidation-stream-market-routing-fix-20260810.md. idle 경고는 향후 재발(다른 원인) 감지용으로
# 유지.
_IDLE_WARNING_SECONDS = 1800.0


def _combined_url(symbols: tuple[str, ...]) -> str:
    """멀티심볼 콤바인드 forceOrder 스트림 URL. stream.py._combined_stream_url과 동일 패턴이나
    forceOrder는 /market 라우팅이 필수라 베이스가 다르다(2026-08-10 실측 확인)."""
    streams = "/".join(f"{symbol.lower()}@forceOrder" for symbol in symbols)
    return f"{config.BINANCE_FUTURES_LIQUIDATION_COMBINED_WS_URL}?streams={streams}"


def _bucket_start(ts_ms: int) -> datetime:
    """이벤트 타임스탬프(ms)를 4h 버킷 시작(UTC)으로 내림."""
    epoch = ts_ms // 1000
    floored = epoch - (epoch % _BUCKET_SECONDS)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def parse_force_order_frame(raw: str) -> tuple[str, str, float, float, int] | None:
    """콤바인드 스트림 프레임(raw JSON 문자열) → (symbol, side, price, qty, ts_ms) 또는 None.

    콤바인드 모드는 {"stream": "<symbol>@forceOrder", "data": {...}} 래퍼가 붙는다(raw 단일
    스트림 모드의 {"e": "forceOrder", ...}와 다름). 순수함수 — 테스트 용이성을 위해 run()의
    수신 루프에서 분리.
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    data = parsed.get("data") if "data" in parsed else parsed
    o = (data or {}).get("o") or {}
    try:
        symbol = str(o.get("s") or "")
        side = str(o.get("S") or "")
        price = float(o.get("p") or 0.0)
        qty = float(o.get("q") or 0.0)
        ts_ms = int(o.get("T") or o.get("E") or 0)
    except (TypeError, ValueError):
        return None
    if not symbol or not side or price <= 0 or qty <= 0 or ts_ms <= 0:
        return None
    return symbol, side, price, qty, ts_ms


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


async def _flush(symbol: str, bucket: _Bucket) -> None:
    result = await data_lake.record_liquidation_bar(
        bar_start=bucket.start,
        symbol=symbol,
        long_liq_usd=round(bucket.long_usd, 2),
        short_liq_usd=round(bucket.short_usd, 2),
        long_liq_count=bucket.long_n,
        short_liq_count=bucket.short_n,
    )
    logger.info(
        "Liquidation bar flushed: %s %s long=$%.0f(%d) short=$%.0f(%d) ok=%s",
        symbol,
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
    url = _combined_url(parameters.MULTI_ASSET_SYMBOLS)
    buckets: dict[str, _Bucket] = {}
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=parameters.WEBSOCKET_PING_INTERVAL_SECONDS,
            ) as ws:
                logger.info(
                    "Liquidation WebSocket connected (fstream forceOrder, symbols=%s)",
                    parameters.MULTI_ASSET_SYMBOLS,
                )
                last_event_at = time.monotonic()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=_IDLE_WARNING_SECONDS)
                    except asyncio.TimeoutError:
                        idle_min = (time.monotonic() - last_event_at) / 60.0
                        logger.warning(
                            "Liquidation WebSocket idle %.0fmin — connected but no forceOrder "
                            "frames received (2026-08-10 fix: verify BINANCE_FUTURES_LIQUIDATION_"
                            "COMBINED_WS_URL still has /market routing prefix)",
                            idle_min,
                        )
                        continue
                    last_event_at = time.monotonic()
                    parsed = parse_force_order_frame(raw)
                    if parsed is None:
                        continue
                    symbol, side, price, qty, ts_ms = parsed
                    start = _bucket_start(ts_ms)
                    bucket = buckets.get(symbol)
                    if bucket is None:
                        buckets[symbol] = _Bucket(start)
                    elif start > bucket.start:
                        # 이 심볼의 새 4h 버킷 시작 → 직전 버킷 flush(심볼별 독립).
                        await _flush(symbol, bucket)
                        buckets[symbol] = _Bucket(start)
                    buckets[symbol].add(side, price * qty)
        except asyncio.CancelledError:
            for symbol, bucket in buckets.items():
                await _flush(symbol, bucket)  # 종료 시 진행 중 버킷 보존(best-effort)
            raise
        except Exception as exc:
            logger.warning(
                "Liquidation WebSocket error: %s — reconnecting in %ss",
                exc,
                parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS)
