"""scheduler ↔ stream 공유 상태. asyncio 단일 스레드이므로 락 불필요.

2026-08-06: BTC 단일자산 가정을 깨고 심볼별 네임스페이스로 전환(ETH/SOL 실거래
승격 — docs/arena/product/vision.md "손실도 숨기지 않는 투명 트랙레코드"를 BTC
전용에서 멀티자산으로 확장). 심볼을 헷갈리면 한 자산의 스톱로스 체크가 다른
자산의 가격/포지션을 잘못 참조할 수 있어 반드시 이 모듈의 헬퍼를 통해서만
접근한다 — 원시 dict를 직접 만지지 않는다.
"""

from __future__ import annotations

# 심볼별 실시간 현재가 (stream.py가 업데이트). { symbol: price }
current_price: dict[str, float] = {}

# 심볼×알고리즘별 현재 오픈 포지션 캐시 (scheduler.py가 갱신, stream.py가 참조)
# { symbol: { algo_id: { id, algo_id, direction, open_price, ... } | None } }
open_positions: dict[str, dict[str, dict | None]] = {}


def positions_for(symbol: str) -> dict[str, dict | None]:
    """symbol의 알고별 오픈 포지션 dict(없으면 빈 dict로 초기화해 반환)."""
    return open_positions.setdefault(symbol, {})


def get_position(symbol: str, algo_id: str) -> dict | None:
    return positions_for(symbol).get(algo_id)


def set_position(symbol: str, algo_id: str, position: dict | None) -> None:
    positions_for(symbol)[algo_id] = position


def get_price(symbol: str) -> float:
    return current_price.get(symbol, 0.0)


def set_price(symbol: str, price: float) -> None:
    current_price[symbol] = price
