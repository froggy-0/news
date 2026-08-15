"""Perp 전용 숏 신호 레지스트리와 롱/숏 충돌 해결.

기존 ``algorithms.ALGORITHMS``는 spot 롱/플랫 계약을 그대로 유지한다. 검증을
통과한 숏 함수만 ``PERP_SHORT_ALGORITHMS``에 별도 등록해 spot 신호와
실행 경로를 분리한다.

``meridian``(2026-08-15, 리서치 종합 롱/숏 알고 — 설계:
docs/arena/research/meridian-combined-long-short-design-20260815.md)는 기존
6알고와 다른 채택 경로를 쓴다 — Phase B(D017)의 "자산별 사전 DSR≥0.95 게이트"
대신, 지금까지의 리서치·문헌 종합(D019)으로 설계한 뒤 라이브 표본으로 검증한다.
기존 6알고의 숏은 여전히 D017 기준(사전 통계 검증) 없이는 등록하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import algorithms

SignalFn = Callable[[dict, dict], str | None]

# 자산×알고 백테스트 통과(D017) 또는 리서치종합 설계(D019, meridian 전용) 후에만 등록한다.
PERP_SHORT_ALGORITHMS: dict[str, SignalFn] = {
    "meridian": algorithms.meridian_short,
}


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
