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
    # PERP_SHORT_ENABLED_TRACKS 자산×알고의 정상 방향 — "숏"으로 명확히 라벨링돼야 한다.
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


def test_notify_open_labels_perp_long_as_futures_not_spot(monkeypatch) -> None:
    # spot→perp Phase A2: perp 트랙("BTCUSDT-PERP")의 direction="long"은 현물 매수가
    # 아니라 선물 롱이다 — 과거엔 헤더가 "-F" 접미사만 붙고 문구는 "현물 매수 진입"으로
    # 남아 있어(예: meridian 추세 leg) spot/perp 구분이 텍스트에서 모순됐다.
    captured: dict[str, Any] = {}

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["text"] = text
        captured["blocks"] = blocks

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_open(
            symbol="BTCUSDT-PERP",
            algo_id="meridian",
            direction="long",
            price=100.0,
            stop_loss_price=95.0,
            ind={"rsi": 40.0, "atr": 2.0, "atr_pct": 0.02},
            macro={"arena_regime_state": "bull_trend"},
            position_id=111,
            strategy_version="arena-spot-v4",
        )
    )

    assert "[BTC-F]" in captured["text"]
    assert "선물 롱 진입" in captured["text"]
    assert "현물 매수" not in captured["text"]
    assert "메리디안" in captured["text"]  # algo_id 라벨 누락 회귀 가드
    assert "추세(TSMOM_NL)" in captured["blocks"][3]["text"]["text"]  # leg 서술 존재


def test_notify_open_spot_track_still_says_spot(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["text"] = text

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_open(
            symbol="BTCUSDT",
            algo_id="regime_trend",
            direction="long",
            price=100.0,
            stop_loss_price=95.0,
            ind={"rsi": 40.0, "atr": 2.0, "atr_pct": 0.02},
            macro={},
            position_id=222,
            strategy_version="arena-spot-v4",
        )
    )

    assert "[BTC]" in captured["text"]
    assert "-F" not in captured["text"].split("─")[0]
    assert "현물 매수 진입" in captured["text"]


def test_notify_close_maps_all_live_close_reasons(monkeypatch) -> None:
    # 과거 reason_map엔 "reverse_signal"(오타)만 있었는데 실제 close_reason은
    # perp_policy.py가 내보내는 "signal_reverse"였다 — 절대 매칭되지 않아 원문 문자열이
    # 그대로 노출되던 버그. time_stop/target_exit/spot risk-off/legacy migration도
    # 매핑이 아예 없었다. 전부 한글 문구로 치환되는지 회귀 검증.
    captured: list[str] = []

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured.append(blocks[5]["text"]["text"])  # 청산 서술 블록

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    cases = [
        ("signal_reverse", "방향 반전"),
        ("time_stop", "최대 보유시간 초과"),
        ("target_exit", "목표가 도달"),
        ("short_signal_spot_risk_off", "리스크오프 청산"),
        ("spot_semantics_migration", "레거시 포지션 정리"),
        ("flat_signal", "신호 소멸"),
    ]
    for reason, expected_ko in cases:
        captured.clear()
        asyncio.run(
            slack_notify.notify_close(
                algo_id="omnibus",
                direction="long",
                open_price=100.0,
                close_price=101.0,
                ret_pct=0.01,
                hold_hours=4.0,
                position_id=1,
                is_stop_loss=False,
                close_reason=reason,
            )
        )
        assert expected_ko in captured[0], f"{reason} -> {captured[0]}"
        assert reason not in captured[0], f"raw close_reason leaked for {reason}"


def test_notify_close_trailing_stop_does_not_force_loss_wording(monkeypatch) -> None:
    # 버그: is_stop_loss=True 분기가 stop_loss/trailing_stop을 구분 안 하고 "손실로 강제
    # 청산"을 하드코딩했다 — 래칫 트레일링 스톱은 이익 방향으로만 이동하므로 profit-lock
    # 청산이 이익으로 종료될 수 있는데도 항상 "손실"이라 표시되던 오도 문구.
    captured: dict[str, Any] = {}

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["text"] = text
        captured["blocks"] = blocks

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_close(
            algo_id="regime_trend",
            direction="long",
            open_price=100.0,
            close_price=103.0,
            ret_pct=0.03,
            hold_hours=8.0,
            position_id=333,
            is_stop_loss=True,
            close_reason="trailing_stop",
        )
    )

    narrative = captured["blocks"][5]["text"]["text"]
    assert "트레일링 청산" in narrative
    assert "수익" in narrative
    assert "손실로 강제 청산" not in narrative


def test_notify_close_plain_stop_loss_still_says_loss(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(client: object, text: str, blocks: list[dict[str, Any]]) -> None:
        captured["blocks"] = blocks

    monkeypatch.setattr(slack_notify, "_get_client", lambda: object())
    monkeypatch.setattr(slack_notify, "_post", fake_post)

    asyncio.run(
        slack_notify.notify_close(
            algo_id="regime_trend",
            direction="long",
            open_price=100.0,
            close_price=95.0,
            ret_pct=-0.05,
            hold_hours=3.0,
            position_id=444,
            is_stop_loss=True,
            close_reason="stop_loss",
        )
    )

    narrative = captured["blocks"][5]["text"]["text"]
    assert "🛑 손절" in narrative
    assert "손실로 강제 청산" in narrative
