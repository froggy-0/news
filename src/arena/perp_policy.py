"""Perp(무기한 선물) long/short 실행 정책 — spot_policy.py의 대칭 버전.

`spot_policy.decide()`는 롱 오픈/보유/청산만 허용하고 숏 신호는 항상 청산·무시한다.
이 모듈은 `backtest.py`의 `run_replay()`가 `product_type != "spot"`일 때 이미 쓰는
(열림/보유/반전/청산을 방향 무관하게 처리하는) 상태머신과 동일한 의미론을 라이브
스케줄러에 제공한다 — 백테스트가 이미 검증해온 로직을 그대로 미러링한 것이지 새로
설계한 것이 아니다. `parameters.PERP_LIVE_ENABLED_ALGOS`에 포함된 algo_id만 이 정책을
탄다(기본 빈 집합 — 전 알고 spot_policy 그대로).

레버리지 없음(1x) — notional = position_weight × 자본단위, spot과 동일 사이징. 청산가격·
마진모드 개념은 도입하지 않는다(스코프 결정: docs/arena/research/spot-to-perp 기획 참조).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TARGET_PRODUCT = "usdm_perp"
POSITION_SEMANTICS = "usdm_perp_long_short"


@dataclass(frozen=True)
class PerpExecutionDecision:
    raw_signal: str | None
    executable_signal: str | None
    action: str
    close_reason: str | None = None
    skipped_reason: str | None = None
    should_open: bool = False
    should_close: bool = False
    # spot_policy.SpotExecutionDecision과 필드 shape을 맞춰 호출부(scheduler.py)가
    # product_decision 타입을 몰라도 동일하게 다룰 수 있게 함. perp에는 legacy short
    # 청산 개념이 없어 항상 False.
    legacy_short_close: bool = False

    def policy_snapshot(self) -> dict[str, Any]:
        return {
            "target_product": TARGET_PRODUCT,
            "position_semantics": POSITION_SEMANTICS,
            "raw_signal": self.raw_signal,
            "executable_signal": self.executable_signal,
            "action": self.action,
            "close_reason": self.close_reason,
            "skipped_reason": self.skipped_reason,
            "allow_live_short": True,
            "spot_execution_only": False,
            "derivatives_data_usage": "live_execution",
        }


def decide(raw_signal: str | None, current: dict[str, Any] | None) -> PerpExecutionDecision:
    """방향 무관 열림/보유/반전/청산.

    `backtest.py`의 `run_replay()` 비-spot 분기(직접 raw_signal 통과 후 same-direction=hold
    /opposite-direction=close+reopen/None=flat-close 상태머신)와 동일 의미론 — 상태머신
    자체를 미러링한 것. min-hold·exit_hold_override 같은 타이밍 판단은 호출부(scheduler.py/
    backtest.py) 책임으로 남겨둔다(spot_policy.decide()와 동일한 관례).
    """
    current_direction = current.get("direction") if current else None

    if raw_signal is None:
        if current_direction is not None:
            return PerpExecutionDecision(
                raw_signal=raw_signal,
                executable_signal=None,
                action="close_flat",
                close_reason="flat_signal",
                should_close=True,
            )
        return PerpExecutionDecision(
            raw_signal=raw_signal, executable_signal=None, action="flat_skip"
        )

    if raw_signal == current_direction:
        return PerpExecutionDecision(
            raw_signal=raw_signal, executable_signal=raw_signal, action="hold"
        )

    if current_direction is not None:
        # 반대 방향 신호 — 같은 사이클에서 청산 후 반전 재진입(backtest.py exit_reason과
        # 동일 명명: "signal_reverse").
        return PerpExecutionDecision(
            raw_signal=raw_signal,
            executable_signal=raw_signal,
            action="signal_reverse",
            close_reason="signal_reverse",
            should_close=True,
            should_open=True,
        )

    return PerpExecutionDecision(
        raw_signal=raw_signal,
        executable_signal=raw_signal,
        action="open",
        should_open=True,
    )
