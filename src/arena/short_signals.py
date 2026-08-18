"""Perp 전용 숏 신호 레지스트리와 롱/숏 충돌 해결.

기존 ``algorithms.ALGORITHMS``는 spot 롱/플랫 계약을 그대로 유지한다. 검증을
통과한 숏 함수만 ``PERP_SHORT_ALGORITHMS``에 별도 등록해 spot 신호와
실행 경로를 분리한다.

``meridian``(2026-08-15, 리서치 종합 롱/숏 알고 — 설계:
docs/arena/research/meridian-combined-long-short-design-20260815.md)는 기존
6알고와 다른 채택 경로를 쓴다 — Phase B(D017)의 "자산별 사전 DSR≥0.95 게이트"
대신, 지금까지의 리서치·문헌 종합(D019)으로 설계한 뒤 라이브 표본으로 검증한다.

``vix_rsi``(2026-08-16, arena-params-v37)는 D017 경로로 등록된 첫 사례 — Phase B
§12가 DSR로 "근접 미달" 판정했던 걸 [증거기준 프레임워크](
docs/arena/research/evidence-criteria-framework-20260816.md)로 재검증한 결과 PSR·
MinTRL 기준으로는 ETH가 실제 통과였다(사전등록 단일가설에 DSR의 선택편향 보정을
적용한 게 과보정이었음). 자산 게이팅은 이 딕셔너리가 아니라
`parameters.PERP_SHORT_ENABLED_TRACKS`가 트랙 단위로 한다 — 이 함수는 자산 무관
로직이고 ETH-PERP 트랙 하나만 허용목록에 있다.

``macd_momentum``/``fng_contrarian``/``vix_rsi``(SOL 확장) (2026-08-16, arena-params-v41)는
새 경로 — [Phase B 전체 재감사](
docs/arena/research/phase-b-full-evidence-reaudit-20260816.md)가 원 문서의
"❌기각" 다수가 실제로는 DSR(그리드탐색 기준)을 단일가설에 오적용해 "SR 양수인데
표본부족"을 "엣지없음"으로 잘못 기록한 것이었음을 밝혔다. 사전 DSR≥0.95 게이트는
아직 통과 못 했으므로(그래서 D017이 아니다) meridian(D019)과 동일하게 페이퍼캐피털
라이브 관찰로 축적 검증한다 — 자산 게이팅은 이 딕셔너리가 아니라
`parameters.PERP_SHORT_ENABLED_TRACKS`가 담당(각 함수 docstring 참조).

**v42(2026-08-16, 같은 날 후속) — 숏 전용 트랙 도입**: [동적 결합
백테스트](docs/arena/research/joint-long-short-backtest-20260816.md)로 지적
"실제로는 무지성 숏이 아니라 동적 롱/숏 선택이라며?"에 답하려다 발견 —
v41(및 그 이전 v37 vix_rsi/ETH)이 승격한 6개 조합 전부, 롱·숏이 같은 포지션
슬롯을 공유하면 확실히 나쁜 롱이 자본회전을 잠식해 좋은 숏의 기여를
희석·반전시켰다(`vix_rsi/ETH`는 DSR 0.970→0.478로 추락, 부호까지 반전).
`resolve()`에 `long_enabled` 매개변수를 추가해 `parameters.
PERP_LONG_BLOCKED_TRACKS`에 등록된 (트랙,알고)는 롱 신호를 무시하고 숏만
실행하도록 분리했다 — short_only 통계를 그대로 보존하는 게 목적.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import algorithms

SignalFn = Callable[[dict, dict], str | None]

# 자산×알고 백테스트 통과(D017, PSR+MinTRL 기준) 또는 리서치종합 설계(D019, meridian
# 전용) 후에만 등록한다. 자산별 허용은 PERP_SHORT_ENABLED_TRACKS가 담당.
PERP_SHORT_ALGORITHMS: dict[str, SignalFn] = {
    "meridian": algorithms.meridian_short,
    "vix_rsi": algorithms.vix_rsi_short,
    "macd_momentum": algorithms.macd_momentum_short,
    "fng_contrarian": algorithms.fng_contrarian_short,
    # v43(2026-08-18): funding_carry — 세 번째 채택 경로. D017(사전 통계게이트)도
    # D019(리서치종합, meridian)도 아니다 — 방향 예측이 아예 없는 델타중립 펀딩비
    # 캐리라 애초에 그리드 통계 게이트의 대상이 아니고(사전 게이트가 검증하려는
    # 것은 "가격 방향을 맞추는 능력"인데 이 신호는 방향과 무관), 검증 근거는
    # arena_funding_rates 역사적 일관성(BTC/ETH 90%+ 양전)이다. 롱 다리와 정확히
    # 같은 게이트(algorithms._funding_carry_active)를 공유한다 — 자산 게이팅은
    # PERP_SHORT_ENABLED_TRACKS(BTC/ETH만)가 담당.
    "funding_carry": algorithms.funding_carry_short,
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
    long_enabled: bool = True,
) -> DirectionalSignalDecision:
    """롱 신호와 승인된 perp 숏 신호를 합성한다.

    동일 봉에서 롱·숏이 동시 성립하면 신규 진입을 하지 않고, 기존 포지션이
    있으면 그 방향을 유지한다. 충돌을 None으로만 반환해 보유 포지션을
    의도치 않게 청산하는 것을 막기 위한 규칙이다.

    `long_enabled=False`(v42, `parameters.PERP_LONG_BLOCKED_TRACKS`)면 롱
    신호를 무시한다 — 숏 전용 트랙에서 기존 알고 함수가 여전히 롱을 반환해도
    실행되지 않도록 한다(동적 결합 백테스트가 실측한 롱-숏 자본잠식 방지).
    """
    if not long_enabled:
        long_signal = None
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
