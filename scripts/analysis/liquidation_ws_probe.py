"""로컬에서 바이낸스 forceOrder WS 여러 URL 변형을 실측 — WI-9 재진단용 1회성 스크립트.

2026-07-14 진단: 서울 EC2에서 wss://fstream.binance.com/ws/btcusdt@forceOrder가 핸드셰이크는
성공하지만 프레임을 전혀 안 줌. 오늘(2026-08-10) 문서 확인 결과 라우팅 경로(/market/ws/...)가
필요할 수 있다는 정황 발견 — 로컬(비-서울 네트워크)에서 신·구 URL 패턴을 직접 비교 실측한다.

읽기 전용 진단 스크립트, DB/트레이딩 무관. 재현: .venv/bin/python3 scripts/analysis/liquidation_ws_probe.py
"""

from __future__ import annotations

import asyncio
import json
import time

import websockets

CANDIDATES = [
    ("all-market, no route prefix", "wss://fstream.binance.com/ws/!forceOrder@arr"),
    ("all-market, /market prefix", "wss://fstream.binance.com/market/ws/!forceOrder@arr"),
    (
        "btcusdt, no route prefix (= 현재 EC2 코드)",
        "wss://fstream.binance.com/ws/btcusdt@forceOrder",
    ),
    ("all-market, stream mode", "wss://fstream.binance.com/stream?streams=!forceOrder@arr"),
]

DURATION_S = 25.0


async def probe(label: str, url: str) -> None:
    print(f"\n=== {label} ===\n{url}")
    try:
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            print("  connected, listening %.0fs..." % DURATION_S)
            deadline = time.monotonic() + DURATION_S
            frames = 0
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except TimeoutError:
                    break
                frames += 1
                if frames <= 2:
                    try:
                        parsed = json.loads(msg)
                        print(f"  frame#{frames}: {json.dumps(parsed)[:200]}")
                    except Exception:
                        print(f"  frame#{frames} (raw): {str(msg)[:200]}")
            print(f"  -> total frames in {DURATION_S:.0f}s: {frames}")
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")


async def main() -> None:
    for label, url in CANDIDATES:
        await probe(label, url)


if __name__ == "__main__":
    asyncio.run(main())
