from __future__ import annotations

import asyncio
from typing import Any

from arena import slack_notify


def test_notify_close_posts_spot_long_payload_without_network(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    dummy_client = object()

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["client"] = client
        captured["text"] = text
        captured["blocks"] = blocks

    monkeypatch.setattr(slack_notify, "_get_client", lambda: dummy_client)
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_close(
            algo_id="macd_momentum",
            direction="long",
            open_price=100.0,
            close_price=105.0,
            ret_pct=0.0483,
            hold_hours=6.0,
            position_id=123,
            is_stop_loss=False,
            close_reason="p0_close_path_test",
        )
    )

    assert captured["client"] is dummy_client
    assert "MACD 모멘텀" in captured["text"]
    assert "현물 매수 청산" in captured["text"]
    assert "+4.83%" in captured["text"]
    header = captured["blocks"][0]["text"]["text"]
    assert "현물 매수 청산" in header
    assert "MACD 모멘텀" in header
    context = captured["blocks"][-1]["elements"][0]["text"]
    assert "Position #123" in context
    assert "정상 청산" in context


def test_notify_close_labels_short_direction_explicitly(monkeypatch) -> None:
    # spot→perp 전환 Phase A(2026-08-15): "short"는 더 이상 legacy 잔재 전용이 아니라
    # PERP_LIVE_ENABLED_ALGOS 알고의 정상 방향 — "숏"으로 명확히 라벨링돼야 한다.
    captured: dict[str, Any] = {}

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["text"] = text
        captured["blocks"] = blocks

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_close(
            algo_id="macd_momentum",
            direction="short",
            open_price=105.0,
            close_price=100.0,
            ret_pct=0.046,
            hold_hours=2.0,
            position_id=456,
            is_stop_loss=False,
            close_reason="signal_reverse",
        )
    )

    assert "숏 청산" in captured["text"]
    assert "숏 청산" in captured["blocks"][0]["text"]["text"]


def test_notify_open_sends_for_short_direction(monkeypatch) -> None:
    # 회귀 가드: 이전엔 notify_open()이 direction != "long"을 전부 무음 처리해 숏 진입
    # 알림이 아예 안 갔음(Phase A에서 수정) — 이제 short도 정상 발송돼야 한다.
    captured: dict[str, Any] = {}

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["text"] = text
        captured["blocks"] = blocks

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_open(
            algo_id="macd_momentum",
            direction="short",
            price=100.0,
            stop_loss_price=105.0,
            ind={"rsi": 40.0, "atr": 2.0, "atr_pct": 0.02},
            macro={},
            position_id=789,
            strategy_version="arena-spot-v4",
        )
    )

    assert captured  # notify_open이 더 이상 조용히 return하지 않았다는 것
    assert "숏 진입" in captured["text"]
