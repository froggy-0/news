"""Perp 전용 숏 신호 레지스트리와 롱/숏 충돌 해결.

기존 ``algorithms.ALGORITHMS``는 spot 롱/플랫 계약을 그대로 유지한다. 검증을
통과한 숏 함수만 ``PERP_SHORT_ALGORITHMS``에 별도 등록해 spot 신호와
실행 경로를 분리한다. 현재는 승인된 숏 알고가 없어 레지스트리가 비어 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

SignalFn = Callable[[dict, dict], str | None]

# 자산×알고 백테스트 통과 후에만 함수를 등록한다.
PERP_SHORT_ALGORITHMS: dict[str, SignalFn] = {}


@dataclass(frozen=True)
class DirectionalSignalDecision:
    long_signal: str | None
    short_signal: str | None
    resolved_signal: str | None
    conflict: bool = False

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "long_signal": self.long_signal,
            "short_signal": self.short_signal,
            "resolved_signal": self.resolved_signal,
            "signal_conflict": self.conflict,
        }


def resolve(
    *,
    algo_id: str,
    long_signal: str | None,
    macro: dict,
    indicators: dict,
    short_enabled: bool,
    current_direction: str | None = None,
) -> DirectionalSignalDecision:
    """롱 신호와 승인된 perp 숏 신호를 합성한다.

    동일 봉에서 롱·숏이 동시 성립하면 신규 진입을 하지 않고, 기존 포지션이
    있으면 그 방향을 유지한다. 충돌을 None으로만 반환해 보유 포지션을
    의도치 않게 청산하는 것을 막기 위한 규칙이다.
    """
    if long_signal not in (None, "long"):
        raise ValueError(f"long signal function returned unsupported direction: {long_signal}")

    short_signal: str | None = None
    if short_enabled:
        short_fn = PERP_SHORT_ALGORITHMS.get(algo_id)
        if short_fn is None:
            raise ValueError(
                f"short-enabled algo has no registered short signal function: {algo_id}"
            )
        short_signal = short_fn(macro, indicators)
        if short_signal not in (None, "short"):
            raise ValueError(
                f"short signal function returned unsupported direction: {short_signal}"
            )

    conflict = long_signal == "long" and short_signal == "short"
    if conflict:
        resolved = current_direction if current_direction in ("long", "short") else None
    else:
        resolved = long_signal or short_signal
    return DirectionalSignalDecision(
        long_signal=long_signal,
        short_signal=short_signal,
        resolved_signal=resolved,
        conflict=conflict,
    )
