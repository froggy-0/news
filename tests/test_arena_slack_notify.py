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


def test_notify_close_keeps_legacy_short_label_explicit(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["text"] = text
        captured["blocks"] = blocks

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_close(
            algo_id="legacy_algo",
            direction="short",
            open_price=105.0,
            close_price=100.0,
            ret_pct=0.046,
            hold_hours=2.0,
            position_id=456,
            is_stop_loss=False,
            close_reason="legacy_cleanup",
        )
    )

    assert "legacy synthetic short" in captured["text"]
    assert "legacy synthetic short" in captured["blocks"][0]["text"]["text"]
