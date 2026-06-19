"""scheduler ↔ stream 공유 상태. asyncio 단일 스레드이므로 락 불필요."""

from __future__ import annotations

# 실시간 BTC 현재가 (stream.py가 업데이트)
current_price: float = 0.0

# 알고리즘별 현재 오픈 포지션 캐시 (scheduler.py가 갱신, stream.py가 참조)
# { algo_id: { id, algo_id, direction, open_price, ... } | None }
open_positions: dict[str, dict | None] = {}
