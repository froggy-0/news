"""Arena trading parameter registry.

This module intentionally has no environment-variable reads. Runtime secrets and
deployment-specific overrides stay in config.py; pure trading defaults live here
so EC2 code has one local source of truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STRATEGY_VERSION = "arena-spot-v4"
# v25(2026-07-01): fng·vix_rsi breadth/stablecoin veto — 커밋 2475efb가 버전 스트링을
#   v24로 남겨 라이브 DB가 v25 동작을 v24로 기록했음(재현성 버그). v26에서 정정.
# v27(2026-07-09): 알고별 특화 개선 WI-1~10 배선(전부 플래그 off로 배포).
# v28(2026-07-09): macro 백필 백테스트 검증 통과분 활성화 — WI-1(multi_factor 레짐필수,
#   -2.63→+3.77) + WI-7(omnibus 목표가익절 atr1.0, -6.24→-4.57·승률+4%p). WI-2/4/5/6은
#   백테스트가 개선 미지지(악화 또는 노이즈) → off 유지. 검증: scripts/analysis/wi_tuning.py.
# v29(2026-07-10): P-A fng 이익포착(profit target) 활성화 — 라이브 MFE 진단(손실 6건 평균
#   MFE +2.09%인데 실현 -1.41%, 포착률 -58%)이 "이익 증발" 정량화 → 익절 메커니즘 추가.
#   백테스트 -3.02→-1.91(Δ+1.11)·승률 48→71%. WI-2(보유 연장)와 정반대 방향이 데이터로 옳음.
# v30(2026-07-11): fng target ATR 배수 1.0→2.0 재채택(walk-forward 6윈도 검증) + time_stop
#   72→60h·min_hold 48→36h 재튜닝(fng_optimize 재그리드, P-A익절과의 상호작용 반영).
#   ⚠️ 커밋(b9e3c7e·21bcdd8) 메시지엔 v30 명시했으나 이 상수 bump가 누락돼 v29로 오기록되던
#   버그를 2026-07-14 발견·수정(v25 때와 동일 클래스 재발 — 위 주석 참조).
# v33(2026-08-06): regime_trend(12-AND→핵심4+부차8중5)·macd_momentum(7veto→핵심+
#   부차6중4) 진입완화 활성화 — P1~P4·P2(4h/1d) 감사 종결로 "엣지 정밀화" 레버 소진,
#   로드맵 거래량 마일스톤 미달(45/500건)이 계기. 그리드 미검증(사용자 결정: 검증보다
#   표본 확보 우선). risk-off는 여전히 hard veto.
# v34(2026-08-07): v33 배포 1일 후 재확인 — 실제 차단 1위는 core 조건(bullish_regime/
#   bb_width_sufficient)이라 여지 자체가 제한적이나, 남은 N-of-M 레버 4개를 1단계씩
#   추가 완화 + fng_contrarian/vix_rsi에 환경필터(낙폭/시장폭/스테이블코인) N-of-M
#   최초 도입. momentum_not_worsening·risk-off·핵심 트리거는 여전히 hard veto.
# v35(2026-08-08): macd_momentum 레거시 MACD 신호를 Nonlinear TSMOM으로 전면 교체
#   (TSMOM_NL_ENABLED=True, algo_id 슬롯 재사용). 레거시가 3년 백테스트 전 구간(상승장
#   포함)에서 -31.79%·DSR 0.012로 완전 기각(macd_hard_gate_tuning.py)된 데 이어, 대체
#   신호(Moskowitz·Sabbatucci·Tamoni·Uhl 2025 S자형 연속사이징 TSMOM)를 walk-forward
#   6윈도로 검증 → 레거시 대비 6/6 구간 전부 개선(예외 없음)이나 절대수익은 2023-2024
#   상승장 구간에 집중(윈도1 +8.7~+9.7%), 2024H2 이후는 손실축소는 확실해도 자체 절대
#   수익 미증명(DSR 0.110, 부트스트랩95%CI [-7.27%,+21.75%]로 0 포함) — "증명된 엣지"가
#   아니라 "확실히 죽은 레거시보다 우위" 근거로 활성화. 사용자 결정: 거래량 우선
#   (LOOKBACK_BARS=126, VOL_MODE=ewma, MIN_SIGNAL=0.0 — n≈254/3년). 설계·grid·walk-forward
#   전체: docs/arena/research/nonlinear-tsmom-design-20260808.md.
# 롤백: TSMOM_NL_ENABLED을 False로 되돌리면 레거시 MACD 로직으로 100% 원복.
# v36(2026-08-15): 신규 7번째 알고 `meridian` 추가 — 기존 6알고와 다른 채택 경로
#   (D019): 사전 DSR≥0.95 게이트(D017) 대신, 지금까지의 전체 리서치(6알고 진단 +
#   Phase B 롱/숏 검증 + GJR-GARCH·모멘텀크래시 문헌)를 종합한 설계를 라이브
#   페이퍼트레이딩 표본으로 검증한다(vision.md "증명보다 표본" 원칙을 신규 알고
#   설계 단계부터 적용). 롱: 추세(TSMOM_NL, bull_trend 한정) + 역발산(fng_contrarian/
#   vix_rsi 핵심조건, 레짐 무관) 재사용. 숏: 역발산-fade(FNG>70·RSI과열)만 —
#   추세미러 숏은 Phase B 6알고 전부 기각 근거로 의도적 배제. perp 트랙 전용
#   (ALGORITHM_TRACK_SCOPE), 독립자본 3트랙×$1,000. 설계:
#   docs/arena/research/meridian-combined-long-short-design-20260815.md.
# v37(2026-08-16): D017 경로(자산×알고 사전통계 게이트)로 첫 숏 승격 —
#   `vix_rsi` 숏을 ETHUSDT-PERP 트랙 하나에만 추가. Phase B §12가 DSR(n_trials=2)
#   0.934로 "근접 미달" 처리했던 걸 증거기준 프레임워크(evidence-criteria-
#   framework-20260816.md)로 재검증: 사전등록 단일가설에는 DSR이 아니라 PSR이
#   맞는 지표이고, ETH는 PSR=0.970(≥0.95)·MinTRL 37건(≤보유 48건, 검정력도
#   충족) — Phase B 전체에서 유일하게 판정 가능하고 통과한 사례. BTC는 SR
#   음수로 기각, SOL은 방향은 양(+)이나 MinTRL 132건>48건으로 판정 불가라
#   제외(재시도 대상 아님, 표본이 더 쌓이면 재평가). 함수: algorithms.vix_rsi_short
#   (Phase B §3.5 veto유지 변형 그대로), 등록: short_signals.PERP_SHORT_ALGORITHMS.
# 롤백: PERP_SHORT_ENABLED_TRACKS에서 ("ETHUSDT-PERP", "vix_rsi") 제거.
# v38(2026-08-16): regime_trend 진입완화 부분 롤백(§514 부근 v33/v34 블록 주석 참조) —
#   2×2 사후귀속 재검증에서 유일하게 뚜렷한 해악(−7.62%p, 전/후반 방향 일관) 확인된
#   알고 하나만 원복. 나머지 5알고 완화는 무변경.
# v39(2026-08-16): perp 트랙 스코프 정리 — PERP_SHORT_ENABLED_TRACKS에 없는 (트랙,알고)는
#   숏을 전혀 안 쓰고 spot_policy(롱/플랫) 그대로라 perp에서 spot 복제본 + 펀딩비만 부담하는
#   구조였음(실측: BTC/ETH/SOL 평균 펀딩 전부 양수 — 롱이 항상 지불, 거래당 0.5~3.4bps
#   드래그). 숏을 실제로 쓰는 조합(meridian 전자산·vix_rsi ETH)만 perp에 남기고 나머지
#   5알고(regime_trend·fng_contrarian·macd_momentum·multi_factor·omnibus) + vix_rsi의
#   BTC/SOL-PERP는 perp 신규진입을 차단(spot에는 그대로 유지). 기존 오픈 포지션은 고아화
#   방지를 위해 scheduler.py가 스코프와 무관하게 계속 관리(시간손절·손절·트레일링·flat청산)
#   하도록 분리했다(scheduler.py의 스코프 체크 위치 변경 참조). 롤백:
#   ALGORITHM_TRACK_SCOPE에서 이번에 추가된 5개 항목 제거 + vix_rsi를 ETH-PERP만으로 되돌림.
PARAMS_VERSION = "arena-params-v40"
FEATURE_SET_VERSION = "arena-features-v8"
RISK_MODEL_VERSION = "portfolio-risk-v2"
REALTIME_RISK_MODEL_VERSION = "realtime-risk-v1"
RUNTIME = "ec2"

BINANCE_SYMBOL = "BTCUSDT"
BINANCE_KLINE_INTERVAL = "4h"
BINANCE_KLINES_LIMIT = 300

# 윈도우 재업서트 시 "무조건 다시 쓰는" 최신 봉 개수 (2026-08-16 Disk I/O 감사).
# 바이낸스는 매 사이클 같은 300봉 윈도우를 돌려주는데 마감된 과거 봉은 값이 불변이라
# 재기록이 순수 낭비였다(실측: mark_price_bars 2,866행에 UPDATE 412,334회 = 행당 144회).
# 마감 전 봉만 갱신하면 되므로 최신 N봉만 다시 쓰고 나머지는 키가 이미 있으면 건너뛴다.
# 1이면 형성 중인 봉 하나만 커버 — 3은 지연/경계 오차에 대한 안전 여유분.
# 0으로 두면 "키가 없는 행만 기록", 음수면 필터 비활성(전량 업서트, 이전 동작).
MARKET_WINDOW_HOT_TAIL_BARS = 3
# 멀티자산 확장 1차 실험대상(2026-07-31, docs/arena/research/structural-priority-
# multi-asset-expansion-20260730.md). BINANCE_SYMBOL은 라이브 BTC 경로 전용이라 불변 —
# 이 상수는 shadow 전용 신규 경로에서만 참조된다.
MULTI_ASSET_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
ARENA_MULTI_ASSET_SHADOW_ENABLED = False
ARENA_MULTI_ASSET_SHADOW_SYMBOLS = ("ETHUSDT", "SOLUSDT")
ARENA_SHADOW_VNEXT_ENABLED = True
ARENA_FREQUENCY_SHADOW_ENABLED = False
ARENA_FREQUENCY_SHADOW_PROFILES = ("research_1h",)
ARENA_REALTIME_COLLECTOR_ENABLED = True
ARENA_REALTIME_RISK_ENABLED = True
ARENA_REALTIME_RISK_LIVE_ENABLED = False
ARENA_EXECUTION_GATE_SHADOW_ENABLED = True
ARENA_EXECUTION_GATE_LIVE_ENABLED = False
TARGET_PRODUCT = "spot"
POSITION_SEMANTICS = "spot_long_flat"
SHORT_SIGNAL_ACTION = "exit_or_no_trade"
ALLOW_LIVE_SHORT = False
RESEARCH_PERP_SHADOW_ENABLED = True

# Spot→perp Phase B(2026-08-15): 숏 승격 단위는 알고가 아니라
# (선물 트랙 심볼, 알고) 쌍이다. 자산별 백테스트 결과가 다른데 algo_id만
# 허용하면 미통과 자산에도 숏이 열리는 문제가 있었다. 기존 6알고는 기본 빈
# 집합이며, D017 기준(사전 DSR≥0.95 게이트) 통과 쌍만 추가한다.
# v36(2026-08-15, D019): `meridian`은 리서치종합 설계 자체가 검증 절차이므로
# 3자산 perp 트랙 전부 처음부터 등록 — D017 기준 사전클리어를 요구하지 않는다
# (설계: meridian-combined-long-short-design-20260815.md §3-3).
PERP_SHORT_ENABLED_TRACKS: frozenset[tuple[str, str]] = frozenset(
    {
        ("BTCUSDT-PERP", "meridian"),
        ("ETHUSDT-PERP", "meridian"),
        ("SOLUSDT-PERP", "meridian"),
        # v37: D017 경로 첫 승격 — PSR 0.970·MinTRL 37≤48로 검정력까지 충족된
        # 유일한 자산×알고 쌍. BTC/SOL은 각각 기각/판정불가라 추가하지 않는다.
        ("ETHUSDT-PERP", "vix_rsi"),
    }
)
PERP_TARGET_PRODUCT = "usdm_perp"
PERP_POSITION_SEMANTICS = "usdm_perp_long_short"

# meridian 숏 leg 임계값(설계 §2-3, 그리드 아닌 단일 사전값 — 롱 임계값 30/50과
# 대칭은 아니고 "명백한 극단"만 잡도록 보수적으로 설정).
MERIDIAN_SHORT_FNG_ABOVE = 70.0
MERIDIAN_SHORT_RSI_ABOVE = 70.0
# 숏 leg 사이징 감쇠 — 문헌·자체검증 둘 다 롱보다 근거가 약해 명시적으로 절반만
# 배분한다(백테스트로 최적화된 값이 아니라 증거 비대칭을 자본배분에 반영한 설계
# 판단, 설계 §2-3). combined_position_weight() 결과에 곱셈으로 적용.
MERIDIAN_SHORT_SIZE_DAMPENER = 0.5

# 역발산 leg 모멘텀 안정화 게이트 (2026-08-16) — fng_contrarian/vix_rsi가 실제
# 진입함수에서 쓰는 _momentum_not_worsening()을 meridian 역발산 leg(FNG/VIX+RSI 둘 다)
# 에도 동일 적용. 원래 설계문서는 "핵심조건만 재사용"하며 이 조건을 빠뜨렸는데,
# fng_contrarian(algorithms.py:463)·vix_rsi(algorithms.py:530) 코드상 이건 v22/v23
# 부가 메커니즘(물타기·시간손절)이 아니라 실제 진입 AND조건 중 하나라 재사용 대상에
# 포함돼야 했던 것 — fng_contrarian/vix_rsi와의 일관성 회복 + 칼받기 방지 목적으로
# 기본 True(이미 검증된 필터 재적용). ⚠️ 자산 간 상관 완화 효과는 실측 결과 거의
# 없었음(20개월 macro 백필: 역발산 leg 동시진입률 27.1%→28.7%, 무변화) — FNG/VIX
# 자체가 자산 무관 매크로 트리거라 실제 공포장에선 자산별 모멘텀도 같이 움직여
# 차별화가 안 됨. 상관 완화는 MERIDIAN_LEG_CONCURRENCY_CAP(아래)이 담당.
MERIDIAN_REVERSION_STABILIZATION_ENABLED = True

# 3자산(perp) 동시진입 상관캡 (2026-08-16) — 모멘텀 게이트가 상관관계를 못 줄인 것을
# 확인한 뒤 설계. 새 meridian 포지션을 열기 직전, 같은 leg로 이미 열려 있는 "다른"
# perp 트랙 수를 세어 이 값 이상이면 신규 진입을 막는다(scheduler.py
# `_meridian_concurrent_leg_count`). dict에 leg가 없으면 비활성(무제한, 기존 동작).
#
# leg별로 다르게 설정 — 20개월 macro 백필 사후 시뮬레이션(scripts/analysis/
# meridian_reversion_correlation_check.py) 근거:
#   reversion(FNG/VIX, 자산 무관 매크로 트리거): cap=1(완전 직렬화)이 cap=2보다도
#     압도적으로 나음 — 동시진입 28.7%→0%(완전 제거) *동시에* 3자산 합산 sum_w%
#     -52.33→-20.94(캡이 없을 때보다 손실이 60% 줄어듦, trade-off가 아니라 양쪽 다
#     개선). 거래수는 889→673(레그 전체 기준, -24%) — 표본 감소보다 상관 리스크
#     제거·손실 축소가 우선이라는 판단(설계 §1 원칙과 별개로, 이 leg는 손실 원흉).
#   short(FNG>70/RSI>70 fade, 마찬가지로 매크로 트리거): 실거래 표본이 아직 0건이라
#     직접 검증은 못 했으나 reversion과 신호 성격이 동일(같은 매크로 값이 3자산에
#     동시 발화)해 선제적으로 cap=1 적용.
#   trend(TSMOM_NL, 자산별 고유 trailing return): cap을 걸어도 동시진입률 자체가
#     낮고(14.4%, 매크로가 아니라 가격 데이터라 원래 덜 상관됨) sum_w 개선도 없음
#     (-52.33→-53.14, 사실상 무변화) — 이 leg는 넣지 않음(불필요한 표본 손실 방지).
MERIDIAN_LEG_CONCURRENCY_CAP_BY_LEG: dict[str, int] = {"reversion": 1, "short": 1}

# 알고별 실행 트랙 범위 — 미등록 알고는 제한 없음. `meridian`은 롱/숏 판단이 핵심이라
# spot(롱only)에서 중복 자본을 만들지 않도록 perp 트랙에만 한정한다(scheduler._run_cycle이
# 이 스코프로 필터링). 설계 §3-1(신규 스코핑 메커니즘).
#
# v39(2026-08-16): 나머지 5알고 + vix_rsi(BTC/SOL)를 perp에서 제외 — PERP_SHORT_ENABLED_TRACKS에
# 없는 (트랙,알고)는 perp에서도 숏을 전혀 안 쓰고 spot_policy 그대로라, perp가 "숏 못 쓰는
# spot 복제본 + 펀딩비"일 뿐이었음(펀딩비가 항상 양수라 롱 전용 알고에게 perp는 spot보다
# 기댓값이 구조적으로 나쁨, 실측 거래당 0.5~3.4bps 드래그). 숏을 실제로 쓰는 조합만 perp에
# 남긴다: meridian(전자산) + vix_rsi(ETH-PERP만, PERP_SHORT_ENABLED_TRACKS 참조).
# ⚠️ 이 스코프는 "신규 진입"만 막는다 — 이미 열린 포지션은 스코프 밖이어도
# scheduler._run_cycle()이 계속 관리한다(고아 포지션 방지, 스코프 체크 위치 참조).
ALGORITHM_TRACK_SCOPE: dict[str, frozenset[str]] = {
    "meridian": frozenset({"BTCUSDT-PERP", "ETHUSDT-PERP", "SOLUSDT-PERP"}),
    "regime_trend": frozenset(MULTI_ASSET_SYMBOLS),
    "fng_contrarian": frozenset(MULTI_ASSET_SYMBOLS),
    "macd_momentum": frozenset(MULTI_ASSET_SYMBOLS),
    "multi_factor": frozenset(MULTI_ASSET_SYMBOLS),
    "omnibus": frozenset(MULTI_ASSET_SYMBOLS),
    "vix_rsi": frozenset(MULTI_ASSET_SYMBOLS) | {"ETHUSDT-PERP"},
}


def algorithm_in_track_scope(algo_id: str, track_symbol: str) -> bool:
    """algo_id가 이 트랙에서 신규 진입 대상인지. ALGORITHM_TRACK_SCOPE에 없으면 무제한(True).

    ⚠️ 이미 열린 포지션의 관리(청산·손절 등)는 이 함수와 무관하게 항상 계속된다 —
    scheduler.py가 신규 진입 게이팅에만 이 함수를 쓴다.
    """
    scope = ALGORITHM_TRACK_SCOPE.get(algo_id)
    return scope is None or track_symbol in scope


# Phase A2(2026-08-15) — 자산×시장 루트 트랙 분리. product_type은 알고가 아니라
# frequency.FrequencyProfile이 결정한다. 위 허용목록은 perp 트랙 안의 숏만
# 게이트하며, 빈 집합인 현재 선물 트랙은 롱온리+펀딩 정산으로 동작한다.
# 2026-08-15 사용자 결정으로 활성화 — BTC/ETH/SOL perp_live 트랙(각 6알고×$1000
# 독립자본) 실거래 시작. 롤백: False로 되돌리면 트랙이 스케줄 안 됨(기존 spot 무영향).
ARENA_PERP_LIVE_ENABLED = True


PERP_TRACK_SUFFIX = "-PERP"


def perp_track_symbol(binance_symbol: str) -> str:
    """실제 바이낸스 티커에서 perp 트랙 심볼을 만든다(예: "BTCUSDT" -> "BTCUSDT-PERP").

    이 접미사 컨벤션의 유일한 생성 지점 — frequency.py의 _register_perp_live_profiles와
    config.py의 트랙 매핑이 둘 다 이 함수를 쓴다(문자열 리터럴 중복 금지).
    """
    return f"{binance_symbol}{PERP_TRACK_SUFFIX}"


def real_ticker_for_track(symbol: str) -> str:
    """트랙 심볼(예: "BTCUSDT-PERP")에서 실제 바이낸스 티커("BTCUSDT")를 복원.

    perp_track_symbol()의 역함수 — 이 함수가 그 파싱을 전 코드베이스에서 유일하게
    담당한다(중복 파싱 금지). spot 트랙(symbol == binance_symbol)은 그대로 반환.
    """
    return symbol.split(PERP_TRACK_SUFFIX)[0]


def perp_short_enabled(*, track_symbol: str, product_type: str, algo_id: str) -> bool:
    """해당 자산×알고의 실행 숏이 승인됐는지 확인.

    product_type과 트랙 접미사를 모두 검증해 spot 트랙이 허용목록의
    algo_id 때문에 perp_policy를 타던 기존 결함을 막는다.
    """
    return (
        product_type == PERP_TARGET_PRODUCT
        and track_symbol.endswith(PERP_TRACK_SUFFIX)
        and (track_symbol, algo_id) in PERP_SHORT_ENABLED_TRACKS
    )


def perp_short_enabled_for_track(*, track_symbol: str, product_type: str) -> bool:
    return any(
        perp_short_enabled(
            track_symbol=track_symbol,
            product_type=product_type,
            algo_id=algo_id,
        )
        for enabled_track, algo_id in PERP_SHORT_ENABLED_TRACKS
        if enabled_track == track_symbol
    )


HTTP_TIMEOUT_SECONDS = 30
WEBSOCKET_PING_INTERVAL_SECONDS = 20
WEBSOCKET_RECONNECT_DELAY_SECONDS = 5
REALTIME_FEATURE_WINDOW_SECONDS = 60
REALTIME_RISK_HISTORY_WINDOWS = 60
REALTIME_RISK_FRESHNESS_SECONDS = 180
SCHEDULER_CRON_HOUR = "*/4"
SCHEDULER_CRON_MINUTE = 5
SERVER_IDLE_SLEEP_SECONDS = 3600

STOP_LOSS_FALLBACK_PCT = 0.05
# arena-cost-v3(2026-08-07): 5.0→10.0. 이전 5.0(0.05%)은 근거 문서·주석 없이 설정돼 있었음
# (/arena-status 세션에서 "실제 수수료가 명확히 반영돼 있는지" 검증 요청 계기로 감사).
# Binance 현물 표준(VIP0) taker 수수료는 0.10%(10bps) — BNB 25% 할인 적용해도 0.075%(7.5bps).
# 코드에 maker/limit 주문 개념이 없어(전량 즉시체결 가정) taker 기준이 맞고, 무할인을
# 보수적 기본값으로 채택(vision.md "손실도 숨기지 않는 정직한 트랙레코드" 원칙과 정합 —
# 낙관적 비용 가정은 실성과를 부풀릴 위험). 왕복비용 13bps→23bps(2×(10+1)+1).
# 근거: docs/arena/spot-deep-research-report.md:116 "실거래소 maker/taker 수수료" 요구.
FEE_BPS = 10.0
ATR_MULTIPLE = 2.5
STOP_LOSS_MIN_PCT = 0.02
STOP_LOSS_MAX_PCT = 0.08

# 래칫 트레일링 스톱 (arena-spot-v4, 2026-06-21 신규)
# arxiv 2602.11708: S_t = max(S_{t-1}, P_t − α·ATR), α=2.5 plateau[2.0,3.5], 6h봉 최적.
# 트레일링 거리는 진입 시 (open − initial_stop) = ATR_MULTIPLE×ATR(클램핑) 거리를 그대로 재사용.
# 단조 래칫이라 손실 방향으론 절대 안 움직임 → 초기 손절 대비 무조건 안전(수익 고정만 추가).
TRAILING_STOP_ENABLED = True
# 인메모리 래칫은 매 틱 갱신, DB persist는 ≥이 bps 이동 시에만(쓰기 빈도 제한).
TRAIL_PERSIST_STEP_BPS = 5.0
MACRO_STALE_HOURS = 48.0  # 일간 매크로(FNG/VIX/ETF) — 브리프 1일 지연 허용

POSITION_UNIT = 1.0
# 알고별 독립 자본 경쟁 구조 — 공통(cross-algo) 동시보유 캡을 알고 수(6)로 설정해
#   각 알고가 자기 신호를 항상 독립 실행하게 한다. (portfolio-risk-v2, 2026-06-26)
#   이전 3/2 캡은 6개 롱온리 알고가 롱 슬롯 2개를 경쟁 → 각 알고 트랙레코드가 "다른
#   알고의 슬롯 점유 타이밍"에 좌우되어 서로 오염됐음(투명 독립 트랙레코드 제품 핵심과
#   충돌). 백테스트 검증: 캡 해제 시 fng 필터 토글이 타 알고에 무영향(커플링 제거),
#   vix_rsi 진짜 성과 -1.26→+0.48%(캡이 좋은 거래를 차단하던 것) 등 왜곡 해소.
#   per-trade 사이징(combined_position_weight≤0.7)이 알고별 노출을 이미 통제하므로
#   count 캡 해제로 인한 개별 계정 리스크 증가는 없음(독립 $1,000 계정 6개).
#   v36(2026-08-15): 7개 알고(meridian 추가)로 캡도 함께 상향 — "알고 추가 시 캡도
#   함께 올릴 것"(CLAUDE.md) 원칙 그대로.
MAX_OPEN_POSITIONS_TOTAL = 7
MAX_LONG_POSITIONS = 7
MAX_SHORT_POSITIONS = 7
MAX_NET_LONG_EXPOSURE = 7.0
MAX_NET_SHORT_EXPOSURE = 7.0
DAILY_LOSS_LIMIT_PCT = 0.05
ALGO_MAX_DRAWDOWN_KILL_PCT = 0.10
COOLDOWN_AFTER_KILL_HOURS = 24.0

# Supertrend (ATR-based dynamic band trend signal)
SUPERTREND_ATR_PERIOD = 10
SUPERTREND_MULT = 3.0

# Multi-period EMA (ema_cross algo)
EMA_21_PERIOD = 21
EMA_55_PERIOD = 55
EMA_200_PERIOD = 200

# BB Squeeze mean-reversion thresholds
BB_SQUEEZE_WIDTH_MAX_PCT = 3.5
BB_SQUEEZE_BB_POS_LONG_MIN = 0.60
BB_SQUEEZE_BB_POS_SHORT_MAX = 0.40
BB_SQUEEZE_RSI_THRESHOLD = 50.0

# Donchian 채널 브레이크아웃 (추세추종 코어 진입 트리거)
DONCHIAN_PERIOD = 20  # 직전 20봉(4h 기준 ~3.3일) 고점 돌파 = 롱 트리거

# ADX 추세강도 (whipsaw 차단 게이트)
ADX_PERIOD = 14
ADX_TREND_MIN = 20.0  # ADX < 20 = 추세 약함, 추세추종 진입 차단

# 변동성 타깃 포지션 사이징 (보고서 최우선: 변동성 스케일링)
# weight = clamp(TARGET_VOL_PER_BAR / realized_vol_24h, MIN, MAX)
# realized_vol_24h = 4h 봉 로그수익률 표준편차(직전 6봉). 고변동 → 축소, 저변동 → 확대.
VOL_TARGET_PER_BAR = 0.02  # 목표 4h 봉 변동성(2%)
VOL_WEIGHT_MIN = 0.25  # 최소 노출 (현물: 자본의 25%)
# 상한 0.7: 현물 long-only는 gross ~70%를 풀 사이징 기준으로 권장
#   (arxiv 2602.11708, Feb 2026 — 6H BTC 추세추종 적응형 포트폴리오 구성).
#   단일 알고가 자기 자본 100%를 단일 4H 롱에 올인하는 것을 방지.
VOL_WEIGHT_MAX = 0.7  # 최대 노출 (현물: 레버리지 없음, 자본의 70%)

# ── R2: 견고한 변동성 추정기 (2026-07-10) ──────────────────────────────────
# 문제: realized_vol_24h(표본 6개 표준편차)는 추정 분산이 커서 사이징이 최근 몇 봉의
#   우연에 좌우됨(저변동 착시 → 과대 사이징 → 다음 봉 손실 확대). 근거: Moreira·Muir
#   변동성 관리는 예측 품질에 의존(Cederburg 반증) → 추정기 개선이 관건.
# 방식: EWMA(RiskMetrics σ²=λσ²+(1−λ)r², λ≈0.94)를 6봉 표본과 블렌드. 보수 원칙으로
#   max(6봉, EWMA) 채택 — 저변동 착시로 과대 사이징하는 것만 막고(노출 축소 방향), 확대
#   방향은 건드리지 않아 무회귀에 가깝다. 사이징에만 사용(realized_vol_24h는 레짐·진단 유지).
VOL_ESTIMATOR_ROBUST_ENABLED = False  # ✅ 백테스트 통과 후 on
VOL_EWMA_LAMBDA = 0.94  # RiskMetrics 표준. 1에 가까울수록 과거 가중↑(부드러움)
VOL_EWMA_MIN_BARS = 20  # EWMA 시드에 필요한 최소 봉 수 (미달 시 6봉값 사용)

# 거래당 자본위험 예산 (고정분율 위험 사이징).
#   weight = clamp(RISK_PER_TRADE_PCT / stop_distance_pct, MIN, MAX).
#   손절 도달 시 손실을 자본의 ~1.5%로 균질화 → 단일 올인 진입의 꼬리손실 제거.
#   변동성타깃과 min() 결합: 더 보수적인 레버가 바인딩(execution_rules.combined_position_weight).
RISK_PER_TRADE_PCT = 0.015

# 펀딩/OI 과열 회피 (선물 데이터를 현물 진입 필터로 활용)
FUNDING_HOT_ZSCORE = 1.5  # funding zscore 초과 시 롱 과열 — 진입 억제

# 기관 ETF 순유입 (펀더멘털 레짐 = 포지션 허용 스위치)
ETF_OUTFLOW_HEAVY_Z = -1.5  # ETF 순유입 z-score 미만 시 기관 대량 유출 — 롱 보류

# ── 일간 매크로 보강 게이트 (R2 latest.json, KST ~08:49 1일 1회 갱신) ──────────
# 설계 원칙: 일간 피처는 "레짐 게이트/veto/사이징"으로만 사용하고 4h 진입 트리거로
# 쓰지 않는다. 트리거는 항상 4h 기술지표(돌파·MACD·RSI)가 담당.
#
# 200일 이동평균 구조적 강세 게이트.
#   근거: Faber(2007) "A Quantitative Approach to Tactical Asset Allocation",
#   Moskowitz·Ooi·Pedersen(2012) "Time Series Momentum" — 가격이 장기 MA 위일 때만
#   롱을 허용하면 장기 하락장 노출과 whipsaw가 줄고 위험조정수익이 개선됨.
#   arena는 4h klines 300봉(~50일)만 받아 200일 MA를 직접 계산할 수 없으므로
#   일간 parquet에서 btc_above_ma200(0/1)을 macro로 받아 게이트로 쓴다.
MA200_REGIME_GATE_ENABLED = True

# 선물 롱숏 포지셔닝 군중 과밀 veto (contrarian).
#   근거: 다수 시장 분석이 극단 롱숏비를 "crowded long → 조정 선행" 신호로 사용.
#   단독 예측력은 약하므로(2025 연구: 단독 사용 시 신뢰도 낮음) 진입 차단(veto)
#   용도로만 쓰고 진입 트리거로는 쓰지 않는다. 30일 롤링 z≥2.0은 과거 분포상
#   상위 ~7% 빈도(선별적).
LSR_CROWDED_ZSCORE = 2.0

# 체결 공격성(테이커 매수 우위) 확인 임계.
#   추세추종 돌파가 실제 공격적 매수로 뒷받침되는지 확인. z>0 = 매수 우위.
#   데이터 미수집(None) 시 확인 통과(차단하지 않음).
TAKER_CONFIRM_ZSCORE = -0.5

# fng_contrarian 품질 게이트: 극단 공포만으로는 약하고(연구상 즉시 바닥 아님),
# 90일 고점 대비 충분한 낙폭이 동반될 때 역발산 진입 품질이 높아진다.
#   btc_drawdown_90d <= -0.10 (10% 이상 낙폭) 조건. 미수집 시 게이트 미적용.
FNG_CONTRARIAN_MIN_DRAWDOWN = -0.10

# ── fng_contrarian 역발산(평균회귀) 전용 설계 ──────────────────────────────
# 근거: 가격 손절은 평균회귀 전략을 악화시킨다(AR(1) 프로세스 연구 Kaminski·Lo;
#   Alvarez Quant 백테스트: 손절 추가 시 지표 악화). 떨어져서 사는 전략인데 가격
#   손절은 바로 그 딥에 되팔기 때문. 대신 (1)공포 심화 시 점증 분할매수(scaling-in),
#   (2)가격 손절 제거 + 시간 손절(평균회귀는 초기 봉에 수익 집중)로 대체한다.
#   익절·risk-off 청산은 기존 로직 재사용(FNG 중립 복귀 → flat, risk-off → 청산).
FNG_CONTRARIAN_SCALE_IN_ENABLED = True
# 진입 안정화(v23, 2026-06-26): MACD 히스토그램이 직전 봉 대비 하락 중(모멘텀 악화)이면
#   진입 보류 — freefall 한복판 칼받기 회피. macro 백필 6개월 백테스트에서 fng 종가자산
#   1.002→1.011·MaxDD -4.9→-2.9%·2월(최악월) -2.47→-1.40%(전 지표 개선, 월별 무회귀).
FNG_CONTRARIAN_STABILIZATION_ENABLED = True
# 진입 게이트는 FNG<30(일별). 분할매수(물타기)는 **가격 기준 실시간** — 최초 진입가
#   대비 하락률에서 추가 체결한다. FNG는 일별이라 장중 불변 → 장중 변하는 가격으로
#   물타기해야 실시간 대응이 의미를 가진다(고전적 물타기). live는 stream.py 1m 틱,
#   backtest는 봉 저가로 평가(패리티). (진입가 하락률, 추가 비중) — 점증 누적 ≤ 0.70.
FNG_CONTRARIAN_PRICE_TRANCHES: tuple[tuple[float, float], ...] = (
    (0.00, 0.15),  # 최초 진입(4h)
    (-0.03, 0.25),  # 진입가 -3% → 실시간 추가
    (-0.06, 0.30),  # 진입가 -6% → 실시간 추가
)

# ── ❌ P3: FNG 지속기간 피처 (fng_days_below_30) — 무효과/미채택 (2026-07-21 실측) ──
# 근거: 공포 1일차(뉴스 쇼크)와 N일 지속(매도 소진)의 평균회귀 품질이 다르다(Kaminski·Lo)는
#   가설로 sizing(0.5/0.3)·gate(N=2/3/5) 그리드를 11개월 백테스트+WF 6윈도로 검증
#   (`scripts/analysis/fng_duration_tuning.py`, 결과 docs/arena/research/
#   fng-duration-tuning-results.json). **sizing형은 거래수 불변에 sum_w_ret Δ+0.04~0.05
#   (baseline +2.45%의 <2%) — 사실상 무효과.** gate형 N=2/3은 Δ+0.06~0.11로 근소한
#   개선처럼 보이나 DSR=0.447(약한 신호, 채택 기준 미달)이고 WF 6윈도 전체에서 양의윈도
#   비율이 baseline과 동일(4/6, 전 config 무차이) — 노이즈와 구분 불가. N=5는 거래수
#   51→48·Δ-0.47로 명확히 악화. **결론: 채택하지 않음**(파라미터 핏이라 DSR 엄격 적용,
#   구조적 결함이 아니므로 완화 불가) — day1 vs N일+ 진입 품질 차이 가설 자체가 이 데이터셋
#   에서 기각. 인프라(risk_overlay.py 산출·algorithms.fng_duration_scale/fng_scaled_tranches·
#   backtest/scheduler/positions 배선·유닛테스트)는 재사용 가능하게 보존, 기본 off.
FNG_DURATION_FEATURE_ENABLED = False
FNG_DURATION_MODE = "sizing"  # "sizing" | "gate"
FNG_DAY1_SIZE_MULT = 0.5
FNG_DURATION_MIN_DAYS = 2
# 시간 손절: 15 x 4h봉 = 60h 내 회귀 없으면 청산. 평균회귀 시간 손절.
#   v22(2026-06-26): 48→72h(평균회귀 회복 시간 확보).
#   v30(2026-07-11): 72→60h. P-A익절(atr2.0) 활성화 후 이익 거래가 조기 종료되면서
#   남은 건 손실 거래 — ts를 줄여 빠른 손절이 더 유리(fng_optimize 재그리드:
#   3단 ts60·mh36 종가자산 1.0269 vs 3단 ts72·mh48 1.0214, Δ+0.55%p).
FNG_CONTRARIAN_TIME_STOP_HOURS = 60.0
# 가격(ATR·트레일) 손절을 적용하지 않는 알고 — 역발산 계열은 가격 손절이 독.
PRICE_STOP_DISABLED_ALGOS: tuple[str, ...] = ("fng_contrarian",)
# 시간 손절을 적용하는 알고 → 최대 보유시간(h). 위 가격 손절 제거를 보완.
TIME_STOP_HOURS_BY_ALGO: dict[str, float] = {
    "fng_contrarian": FNG_CONTRARIAN_TIME_STOP_HOURS,
}
#
# P1 후속(2026-08-04): omnibus 손절폭 레그별 진단 — DOWN_TREND(REBOUND) 레그만
#   손절 비중·손절당 손실이 최악(10~14%/−3.6~−4.2%), RANGE·UP_TREND은 문제 아님
#   (root-cause 문서 §12, omnibus-stop-distance-design-20260804.md §2). 2026-07-25
#   시도가 omnibus 전체에 블랑켓 적용해 전/후반 불일치로 보류된 데 대한 가설(레그
#   혼합)을 검증하기 위해, 위 PRICE_STOP_DISABLED_ALGOS/TIME_STOP_HOURS_BY_ALGO와
#   같은 원칙을 omnibus 레그 단위로 좁혀 재적용한다. 기본값 전부 off/빈 컨테이너.
#   설계: docs/arena/research/omnibus-stop-distance-design-20260804.md
OMNIBUS_PRICE_STOP_DISABLED_LEGS: tuple[str, ...] = ()  # 예: ("DOWN_TREND",)
OMNIBUS_LEG_TIME_STOP_HOURS: dict[str, float] = {}  # 예: {"DOWN_TREND": 72.0}

# ── P-A: fng_contrarian 이익 포착(profit target) — 청산이 이익을 흘리는 문제 대응 ──
# 근거(2026-07-10): 라이브 청산 6건 평균 MFE +2.09%인데 실현 -1.41%, 손실 5건 중 4건이
#   보유 중 한때 +1% 이상이었음(MFE 포착률 -58% = 이익 증발). WI-2(청산 히스테리시스=보유
#   연장)는 백테스트 기각됐으나(더 오래 보유는 답 아님), MFE 데이터가 가리키는 방향은
#   "이익이 있을 때 잡기"(profit capture). omnibus v28 target_exit과 동일 메커니즘 재사용
#   (execution_rules.target_exit_triggered, live 1m틱·backtest 봉high 체결 패리티).
#   ⚠️ 하방 스톱은 여전히 없음(Kaminski·Lo 가격손절 금지 유지) — 이익 방향 익절만 추가.
#   ⚠️ 물타기 상호작용: 목표가는 평단(가중평균 진입가) 기준 → scale-in 시 재계산(omnibus는
#   진입 시 고정, fng는 평단이 움직이므로 다름). 설계: docs/arena/research/improvement-plan-v2.
# ✅ v29 활성화: 백테스트 atr1.0 -3.02→-1.91(Δ+1.11)·승률 48→71%·거래 54→94(회전↑).
#   wi_tuning P-A 최초 gridsearch(stale macro)에서 atr1.0 채택했으나, walk-forward 6윈도
#   검증(master_20260710, fresh macro)에서 atr2.0이 5/6 윈도 우위·fng 평균 +0.36 vs +0.03
#   → atr2.0으로 재채택(arena-params-v30). 거래수 58→43 감소는 감수.
FNG_TARGET_EXIT_ENABLED = True
FNG_TARGET_MODE = "atr"  # "atr"(평단+ATR×mult) | "bb_mid"(BB 중앙선 복귀)
FNG_TARGET_ATR_MULT = 2.0  # atr 모드 배수 (walk-forward 6윈도 검증→2.0 채택, arena-params-v30)

# 시장 폭(breadth) 건전성: Binance top10 알트 중 7일 수익률 양(+) 비율.
#   이 값 미만이면 BTC 단독/협소 랠리 → 복합 투표 알고 진입 보류.
#   미수집(None) 시 게이트 미적용. 0~1 유계라 절대 임계값 사용.
BREADTH_HEALTHY_MIN = 0.30

# 온체인 유동성: 스테이블코인(USDT+USDC) 7일 공급증가율 롤링 z.
#   이 값 미만이면 유동성 수축(자본 이탈) → 복합 투표 알고 롱 보류.
#   근거: 공급 증가=대기 매수력, 수축=자본 이탈(SSR 연구). etf 유출과 동일 임계.
STABLECOIN_CONTRACTION_Z = -1.5

# ── omnibus (6번째 알고) 임계값 ────────────────────────────────────────────
# UP_TREND 눌림목 롱: regime_trend(돌파 추종)와 보완적 — 추세 내 건강한 되돌림 구간만 진입
# RSI 32~55: 과매도 극단 아님(추세 신뢰) + 아직 과열 아님(눌림목 확인)
# Ref: "Buy the Dip in Bull Market" (Dichtl et al. 2016), Wilder RSI pullback logic
OMNIBUS_RSI_TREND_MIN = 32.0  # 이 값 미만이면 추세 의심 → 진입 보류
OMNIBUS_RSI_TREND_MAX = 55.0  # 65→55: 눌림목 구간으로 좁힘 (과열 아닌 중간 되돌림)
OMNIBUS_BB_POS_TREND_MAX = 0.65  # BB 중상단 이상에서 매수 금지 (고점 추격 방지)
# RANGE 평균회귀: BB 하단 + RSI + ADX (Bollinger 2002 mean-reversion logic)
OMNIBUS_BB_POS_RANGE_ENTRY = 0.30  # 0.25→0.30: 발동 빈도 개선 (밴드 하단 30% 이하)
OMNIBUS_RSI_RANGE_MAX = 45.0
OMNIBUS_ADX_RANGE_MAX = 25.0  # 20→25: ADX<25도 비추세로 간주 (0~25 = weak trend)
# DOWN_TREND OVERSOLD_REBOUND: 4-AND → 4개 중 3개 투표 방식
# 근거: RSI<30 폭락 구간에서 MACD 반전은 통상 1~3봉 지연 → 동시 발생 불가 (4-AND 실패)
# Ref: Jegadeesh (1990) short-term mean reversion, Lehmann (1990) oversold bounce
OMNIBUS_RSI_REBOUND_MAX = 35.0  # 30→35: 완화 (극단 35 이하도 충분히 과매도)
OMNIBUS_BB_POS_REBOUND_ENTRY = 0.25  # 0.20→0.25: 완화 (하단 25% = 충분히 낮음)
OMNIBUS_REBOUND_MIN_RETURN_24H = -0.015  # -0.02→-0.015: 1.5% 낙폭으로 완화
OMNIBUS_REBOUND_MIN_VOTES = 3  # 4개 조건 중 최소 3개 충족 시 OVERSOLD_REBOUND 인정
# 포지션 사이즈 배수 (combined_position_weight에 추가 곱함)
OMNIBUS_TREND_SIZE_MULT = 1.0
OMNIBUS_RANGE_SIZE_MULT = 0.40
OMNIBUS_REBOUND_SIZE_MULT = 0.25

# ── WI-1~10 알고별 특화 개선 플래그 (arena-params-v27, 2026-07-09) ───────────
# 전부 기본 off/현행유지 — macro 백필 백테스트 통과 후 개별 on. 미충족 데이터는
# None→graceful. 설계: docs/arena/research/next-steps-design-v1-20260709.md
#
# WI-1: multi_factor 레짐 필수화 — "조용한 하락장에서 방향성 팩터 없이 4표 충족→진입"
#   구조 결함 제거. 레짐(f1)을 필수로, 나머지 4팩터 중 MIN_VOTES_EX_REGIME 득표 요구.
#   ✅ v28 활성화: 백테스트 variant C(횡보허용) -2.63→+3.77(Δ+6.40), 거래 84→89(유지).
MULTI_FACTOR_REGIME_REQUIRED = True
MULTI_FACTOR_MIN_VOTES_EX_REGIME = 3
# WI-1 중간안(C, 11개월 데이터로 채택) → v32(2026-07-30)에서 False로 번복.
# 정성분석(/arena-status 세션, 라이브 39건 원문 판독): multi_factor 손실 7건 중 6건이
# arena_regime_state=sideways 진입에 집중(승률14% vs 비횡보 67%) — 발견 계기로 20개월
# 백필(3766봉) 재검증: True(현행) sum_w=-10.02%(n=146) → False(강세전용) sum_w=-0.57%
# (n=51, Δ+9.45). 전/후반 분할(2025-09-19 기준)에서도 양쪽 다 개선(Δ+2.79/+6.60,
# 한쪽 쏠림 아님) — omnibus stop A/B(2026-07-25)가 기각된 이유였던 "전반부에만 몰림"
# 패턴과 다름. ⚠️ DSR=0.181로 낮음(여전히 PF<1, "엣지 발견"이 아니라 "손실 축소" —
# P7 macd RSI 완화와 동일 해석 프레임) — 후속 라이브 트랙레코드로 재확인 필요.
# 재현: scripts/analysis/qual_hypothesis_tuning.py. 근거: docs/arena/research/
# qualitative-analysis-multi-factor-sideways-20260730.md
MULTI_FACTOR_ALLOW_SIDEWAYS = False
#
# WI-2: fng_contrarian 청산 히스테리시스 — 진입(FNG<30)과 동일 임계로 청산(FNG≥30)하던
#   반쪽 구조 분리. 반등 초입 조기 flat 청산이 물타기 평단 이점을 버리는 문제(라이브
#   flat 청산 4건 평균 -0.52%). risk-off·breadth·stablecoin veto는 즉시 청산(양보 없음),
#   time_stop(72h)이 보유 상한 보장. vix_rsi v26과 동일 메커니즘.
FNG_EXIT_HYSTERESIS_ENABLED = False
FNG_EXIT_NEUTRAL_MIN = 45.0  # 그리드 {40,45,50,55}에서 결정
#
# WI-4: kline volume 돌파 확인 — 이미 수신 중인 volume을 지표화(rel_volume)해 regime_trend
#   Donchian 돌파의 진위 필터로 사용. 돌파봉 볼륨 ≥ 20봉 평균 ×MIN_REL. rel_volume None시 통과.
VOLUME_CONFIRM_ENABLED = False
VOLUME_CONFIRM_MIN_REL = 1.5
VOLUME_SMA_PERIOD = 20
#
# WI-5: vix_rsi 구조 판정 — Step1: 일간 MA200 게이트 추가. Step2: 트리거를 "RSI<50 상태"에서
#   "RSI 과매도선 상향 크로스 이벤트"로 재정의(반전 확인 매수).
VIX_RSI_MA200_GATE_ENABLED = False
VIX_RSI_TRIGGER_MODE = "state"  # "state"(현행) | "cross"
VIX_RSI_CROSS_OVERSOLD = 35.0
#
# WI-6: macd_momentum 트리거 재정의 — "h>0 상태+증가"(늦은 진입, regime_trend와 중복)에서
#   "h가 0선 상향 크로스한 봉"(모멘텀 전환 초기)으로. 보유는 exit_hold_override가 h>0 동안
#   flat 청산 보류(v26 vix_rsi 히스테리시스와 동일 구조).
MACD_MOMENTUM_TRIGGER_MODE = "state"  # "state"(현행) | "zero_cross"
MACD_MOMENTUM_ZERO_CROSS_DROP_BB_GATE = False  # 크로스 모드에서 BB폭 게이트 제거 여부(그리드)
MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED = False
#
# P1(2026-08-04): regime_trend 청산 히스테리시스 — 진입조건(이벤트 포함)이 곧 보유조건인
#   구조를 분리. donchian_breakout 지속확률 30.1%(이벤트, 정의상 1회성)인데 보유
#   판정에 재사용돼 진입 12회 중 9회가 다음 봉에 조기청산(2023-2024 상승장 실측).
#   근거: MOP 2012(JFE) 추세 지속 1~12개월 vs 실측 중앙보유 8h(4H봉 2개).
#   설계: docs/arena/research/entry-exit-separation-design-20260804.md
#   구현계획: docs/arena/research/entry-exit-separation-implementation-plan-20260804.md
REGIME_TREND_EXIT_HYSTERESIS_ENABLED = False
REGIME_TREND_EXIT_MODE = (
    "state"  # "state"(변형A: 상태조건 유지) | "donchian_exit"(변형B: 반대편 채널 이탈)
)
REGIME_TREND_EXIT_STATE_REQUIRE_SLOPE = (
    False  # 변형A만: True=A2(기울기 포함) False=A1(기울기 제외, 권장)
)
#
# WI-7: omnibus RANGE/REBOUND 목표가 청산 — 평균회귀에 이론 정합적 익절(BB 중앙선) 부여.
#   진입 시점 목표가 고정(signal_reason.omni_target_price). live는 1m 틱 감시, backtest는
#   봉 high 도달 시 한계가 체결. UP_TREND은 목표가 미적용(트레일링이 담당). 익절이므로
#   min_hold보다 우선(손절과 비대칭).
# ✅ v28 활성화: 백테스트 atr1.0 -6.24→-4.57(Δ+1.67)·승률 57→61%·거래 98→106(회전↑).
OMNIBUS_TARGET_EXIT_ENABLED = True
OMNIBUS_REBOUND_TARGET_ATR_MULT = 1.0  # REBOUND: 진입가 + ATR×mult (그리드 {1.0,1.5,2.0}→1.0 채택)
#
# WI-10: regime_trend 테이커 확인을 일간 lag1 z에서 로컬 4h 값으로 — 하루 지연 제거.
#   macro["taker_ratio_4h"](buySellRatio, 1.0=중립)가 있으면 우선 사용. 없으면 일간 z 폴백.
#   ⚠️ live는 market_structure 모듈 캐시(직전 4h 사이클 features) 사용 — backtest는 미주입→
#   기존 일간 z 폴백(검증된 경로). 4h 캐시는 daily lag1보다 훨씬 신선.
TAKER_CONFIRM_4H_ENABLED = False
TAKER_CONFIRM_RATIO_4H_MIN = 0.95

# ── 볼륨우선 진입완화 (arena-params-v33, 2026-08-06) ─────────────────────────
# 배경: P1(청산정책 0/4)·P4(과최적화, fng_contrarian/vix_rsi 둘 다 DSR<0.95)·P2
#   (엣지/비용, 4h·1d 감사 둘 다 3자산 전부 실패)로 "이 신호 세트에서 엣지를 더 짜낼
#   레버가 소진됐다"는 결론(2026-08-04~06, docs/arena/research/p2-1d-frequency-audit-
#   20260806.md). 동시에 로드맵(docs/arena/product/roadmap.md) 자체 마일스톤(2026-08
#   500건)에 실거래가 크게 못 미침(2026-08-06 확인: 45건, 목표의 9%) — regime_trend는
#   12-AND·macd_momentum은 7veto로 과잉필터돼 진입 자체가 거의 안 남(1d 감사에서
#   regime_trend 거래 0건 확인). 사업 비전(docs/arena/product/vision.md — "손실도
#   숨기지 않는" 투명 트랙레코드가 핵심가치, 텔레그램 승률자랑 채널과의 차별화)상 지금
#   단계는 "엣지 정밀화"보다 "정직한 표본 확보"가 우선이라는 사용자 판단(2026-08-06).
# 설계: 각 알고의 핵심조건(그 알고를 그 알고답게 만드는 정의)은 그대로 hard 유지하고,
#   품질필터 성격의 부차조건만 unanimous AND에서 N-of-M 투표로 완화. risk-off류
#   안전장치(레짐 stress/BearPanic)는 완화 대상이 아니다 — 목적이 "손실 포함 정직한
#   기록"이지 "무모한 진입"이 아니기 때문. 그리드 탐색 없이 설계값(과반+1)으로
#   즉시 활성화 — 이번 결정 자체가 "검증보다 표본"이라 재현 그리드를 또 돌리지 않는다.
# 롤백: 각 ENABLED를 False로 되돌리면 기존(2026-08-04 이전) 동작과 100% 동일.
#
# v38(2026-08-16) 부분 롤백 — regime_trend만 원복, macd_momentum 이하 나머지는 유지.
#   근거: [증거기준 프레임워크](docs/arena/research/evidence-criteria-framework-20260816.md)
#   재검증 중 발견한 부수 결과(v33/v34 진입완화 2×2 사후귀속)를 4개 알고 개별로
#   분해하니 효과가 균일하지 않았다 — regime_trend −7.62%p(6알고 중 최대, 거래
#   7→37건 폭증)로 압도적, multi_factor는 오히려 +0.48%p, macd_momentum은 0.00%p
#   (v35 TSMOM_NL 전환으로 이 플래그가 이미 죽은 코드였을 가능성). 전/후반 분할
#   재검증(완화ON 전반 −1.60%/후반 −8.37%, 완화OFF 전반 +0.56%/후반 −0.77%)에서도
#   방향 일관 — regime_trend에 한해서만 신뢰할 만한 해악 근거. 라이브 데이터는
#   regime_trend 청산 n=2뿐이라 판단 근거로 못 씀(백테스트 단독 근거).
#   전면 롤백은 안 함 — "표본 확보" 전략 자체를 부정하는 과잉대응이고, 나머지
#   3개(macd_momentum/fng_contrarian·vix_rsi 환경필터/multi_factor/omnibus)는
#   해악 근거가 약하거나(0~+0.5%p) 무효.
REGIME_TREND_ENTRY_RELAXED_ENABLED = False
REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES = 5  # v38: v33 이전(8개 전부 요구)으로 원복 — RELAXED_ENABLED=False라 이 값 자체는 무효과, 문서화용
MACD_MOMENTUM_ENTRY_RELAXED_ENABLED = True
MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES = 3  # v33=4 → v34=3 (아래 블록 참조). 6개 중 최소 충족 개수

# ── 볼륨우선 진입완화 2차 (arena-params-v34, 2026-08-07) ──────────────────────
# 배경: v33 배포 1일 후 arena-status 재확인 — v33이 푼 것은 regime_trend/macd_momentum의
#   "부차조건"뿐인데, 실제 최근 14일(BTC) 차단 1위는 손대지 않은 core 조건이었음
#   (regime_trend: veto:bullish_regime 100/109 — 알고 정의 자체. macd_momentum:
#   veto:bb_width_sufficient 53/109 — core_trigger 이전 hard gate). BTC/ETH/SOL 3자산
#   교차확인(최근 24h arena_decisions)도 동일 패턴 — 현재 매크로(Transitional/MA200
#   하회/90일 낙폭 -21.8%)가 추세·모멘텀 알고에 구조적으로 불리한 국면이라 완화 여지가
#   본질적으로 제한적. 그럼에도 사용자 요청("더 완화 가능한 거 있으면")에 따라 남은
#   레버 4개를 원칙에 맞게 한 단계씩 더 완화한다: (1)(2) 기존 N-of-M 문턱 1단계 하향,
#   (3) multi_factor의 ex-regime 최소득표 1단계 하향(f1 방향성 필수는 그대로 — 2026-07-30
#   20개월 재검증으로 확정된 수정이라 미변경), (4) omnibus REBOUND 문턱 1단계 하향,
#   (5)(6) fng_contrarian/vix_rsi에 처음으로 환경필터(낙폭/시장폭/스테이블코인) N-of-M
#   도입. momentum_not_worsening(칼받기 방지, v23/v26 정량검증 완료)·risk-off·핵심
#   트리거(FNG<30, VIX calm+RSI<50)는 완화 대상에서 제외 — 개별 백테스트로 손실 방지
#   효과가 입증된 필터를 표본확보 명목으로 되돌리지 않는다는 v33 원칙 계승.
#   v33과 동일하게 그리드 탐색 없이 설계값(1단계 하향/과반)으로 즉시 배포.
# 롤백: REGIME_TREND/MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES를 위 주석의 v33 값(5,4)으로,
#   MULTI_FACTOR_MIN_VOTES_EX_REGIME을 3, OMNIBUS_REBOUND_MIN_VOTES를 3으로, 신규
#   ENABLED 2개(FNG_CONTRARIAN/VIX_RSI)를 False로 되돌리면 v33 상태로 원복.
MULTI_FACTOR_MIN_VOTES_EX_REGIME = 2  # f1 제외 4개 중 3→2 (f1 필수는 유지)
OMNIBUS_REBOUND_MIN_VOTES = 2  # 4개 중 3→2
FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED = True
FNG_CONTRARIAN_ENTRY_MIN_SECONDARY_VOTES = 2  # 환경필터 3개(낙폭/시장폭/스테이블코인) 중 최소 충족
VIX_RSI_ENTRY_RELAXED_ENABLED = True
VIX_RSI_ENTRY_MIN_SECONDARY_VOTES = 1  # 환경필터 2개(시장폭/스테이블코인) 중 최소 충족

# ── Tier 2: 범용 목표가 익절 (vix_rsi·multi_factor, 2026-07-15) ──────────────
# 근거: /arena-status(2026-07-14) — 거래 있는 4개 알고 전부 MFE 포착률<0%(청산이 이익
#   흘림). Tier 1(exit_tuning.py, time_stop/min_hold 그리드)로 vix_rsi·multi_factor를
#   실측했으나 개선 없음(포착률 그대로 -29~-92%) — 시간 배리어는 "언제 접을지"만 정할 뿐
#   "이익 난 순간을 붙잡는" 메커니즘이 아니기 때문. omnibus(WI-7)·fng_contrarian(P-A)는
#   이미 목표가 익절(상단 배리어)이 있음 — 이 dict는 그 두 알고 전용 필드
#   (omni_target_price/fng_target_pct, 물타기·레짐 조건부 로직 보유)는 그대로 두고,
#   신규 알고에 동일 메커니즘(algorithms.atr_target_price·execution_rules.
#   target_exit_triggered 재사용)을 붙이기 위한 범용 dict(TIME_STOP_HOURS_BY_ALGO와
#   동일 패턴). ⚠️ 기본 빈 dict(off) — ATR 배수는 반드시 그리드→walk-forward→DSR/PBO
#   검증 통과 후에만 항목 추가. 설계: docs/arena/research/big-candle-no-pnl-diagnosis-20260715.md
GENERIC_TARGET_EXIT_ENABLED = True  # 스위치 자체는 on, 대상 알고는 아래 dict가 결정(빈 dict=무효과)
TARGET_EXIT_ATR_MULT_BY_ALGO: dict[str, float] = {}

# ── 트레일링 거리 분리 (vix_rsi·multi_factor, 2026-08-10) ──────────────────────
# 근거: /arena-status MFE/MAE 진단 재확인 — vix_rsi 7건 중 5건, multi_factor 11건 중
#   10건이 MFE(보유중 최대유리이동) < 초기손절거리(=현재 trail_distance). ratchet_trailing
#   _stop()은 trail_distance=진입 시 손절거리를 그대로 재사용하므로, MFE가 그 거리에
#   못 미치는 대다수 거래에서 래칫이 사실상 손실구간에 머물러 익절 보호를 전혀 못 함
#   (예: risk 3.0%인데 MFE 0.5%면 래칫 최고점도 진입가 대비 -2.5% — 이익 잠금 0).
#   Tier2(TARGET_EXIT_ATR_MULT_BY_ALGO, 전량 익절)는 PBO 0.877~0.921로 기각됐는데, 이는
#   "어디서 전량 청산할지" 배수를 그리드 핏한 것이라 과최적화 위험이 컸던 것 — 이번 설계는
#   손절과 독립적으로 트레일링 거리만 좁혀 래칫이 더 일찍 반응하게 하는 것이라 자유도가
#   1개(배수)뿐이고, 손절폭(리스크 관리)은 그대로 유지돼 "승자를 일찍 자르는" 부작용도 없음
#   (목표가처럼 상단을 캡하지 않고 그냥 더 촘촘히 따라감). ⚠️ 기본 빈 dict(off) — 그리드→
#   walk-forward→DSR/PBO 검증 통과 후에만 항목 추가. execution_rules.trail_distance_from_stop
#   의 mult 인자로 배선(기본 1.0=기존과 동일, 다른 알고 무영향).
TRAIL_DISTANCE_MULT_BY_ALGO: dict[str, float] = {}

# ── 청산 소진 게이트 (fng_contrarian·omnibus REBOUND, WI-9 v2, 2026-08-10 설계) ────────
# 근거: WI-9 청산(forceOrder) 스트림이 2026-08-10 "/market" 라우팅 수정으로 실제 가동 시작
#   (docs/arena/research/liquidation-stream-market-routing-fix-20260810.md), 동시에
#   BTC/ETH/SOL 멀티자산 콤바인드 스트림으로 확장. "매도 소진(캐피출레이션) 사후확인"
#   용도로 설계(docs/arena/research/liquidation-feature-design-20260810.md) — 문헌
#   (arXiv:2607.27070, 2026, 바이낸스 BTCUSDT 7개 캐스케이드 분석)이 "캐스케이드 사전예측"
#   류 단일변수 조기경보의 취약함을 반증했으므로, backward-looking veto 전용으로만 설계
#   (방향예측·사이징 확대에는 안 씀). ⚠️ 기본 off — 청산 스파이크가 5건+ 관측되기 전엔
#   그리드/튜닝 착수하지 않는다(design doc §4 go/no-go). 임계값(MAX_ASYMMETRY=0.5)은
#   잠정 placeholder — 검증 착수 시 실측 분포로 재보정할 것, 지금 값 그대로 채택 근거 없음.
LIQUIDATION_EXHAUSTION_GATE_ENABLED = False
LIQUIDATION_EXHAUSTION_MAX_ASYMMETRY = 0.5

# ── ❌ 모멘텀 매그니튜드 게이트 (fng_contrarian·vix_rsi) — 기각 (2026-07-21 실측) ────
# 근거: /arena-status(2026-07-21) — fng·vix_rsi 라이브 손실의 다수가 진입 시 macd_hist
#   음수(칼받기 유사 패턴, 승률 25~33%)인데 _momentum_not_worsening()은 방향(mh>=mh_prev)만
#   보고 크기를 안 봐서 "직전보다 덜 나쁜 깊은 음수"를 걸러내지 못함 — 이라는 가설이었으나,
#   11개월 macro 백필 백테스트(master_20260710, W1 13bps 하니스)에서 ATR×{0.15,0.25,0.40}
#   전 변형이 baseline 대비 악화(fng Δ-0.35~-1.92, vix_rsi Δ-0.35~-6.25, 거래수·승률 동반
#   감소) — 걸러낸 "깊은 음수" 진입들이 실제로는 순양(+)이었음. **채택하지 않음**(재시도
#   금지). 재현: scripts/analysis/p4_momentum_unknown_tuning.py, 결과:
#   docs/arena/research/p4-momentum-unknown-tuning-results.json. 인프라(algorithms.
#   _momentum_magnitude_threshold·_momentum_not_worsening의 max_abs_hist)는 코드
#   재사용 가능하도록 보존(빈 dict=off, TARGET_EXIT_ATR_MULT_BY_ALGO와 동일 관례).
MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO: dict[str, float] = {}

# ── ❌ unknown 레짐 사이징 완화 (fng_contrarian·vix_rsi) — 기각 (2026-07-21 실측) ────
# 근거: return-improvement-priorities-20260715.md P4 — 라이브 손실의 레짐 분포가 unknown에
#   과대표집(fng 10건 중 6, vix_rsi 6건 중 5)돼 사이징을 낮추면 개선될 것이라는 가설이었으나,
#   11개월 macro 백필 백테스트에서 배수 {0.5, 0.65, 0.8} 전 변형이 baseline 대비 악화
#   (fng Δ-0.07~-0.18, vix_rsi Δ-0.62~-1.55, 거래수는 불변·sum_w_ret만 하락) — unknown
#   레짐 진입도 baseline 전체와 동일하게 순양(+)이었고, 사이징을 줄이면 그 기여분만
#   깎였을 뿐. 라이브 n=16 표본에서 관찰된 상관은 (오버레이가 이 기간 내내 'Transitional'
#   로 균일했던 것과 맞물려) 이 11개월 창에서는 재현되지 않음. **채택하지 않음**(재시도
#   금지). 재현·결과는 위 매그니튜드 게이트 항목과 동일 스크립트/파일. 인프라
#   (algorithms.fng_vix_unknown_multiplier)는 코드 재사용 가능하도록 보존. fng·vix_rsi는
#   반드시 독립 A/B — vix_rsi는 구조 게이트 추가 시 항상 악화된 전례(WI-5 기각).
UNKNOWN_REGIME_SIZE_MULT_BY_ALGO: dict[str, float] = {}

RSI_PERIOD = 14
RSI_NEUTRAL = 50.0
RSI_RECENT_MULTIPLE = 3
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9
MACD_NEUTRAL = 0.0
BOLLINGER_PERIOD = 20
BOLLINGER_STDDEV = 2.0
BOLLINGER_NEUTRAL = 0.5
ATR_PERIOD = 14
ATR_FALLBACK_PCT = 0.01

REGIME_LONG_STATE = "BullQuiet"
REGIME_SHORT_STATE = "BearPanic"
FNG_LONG_BELOW = 30.0
FNG_SHORT_ABOVE = 70.0
# 정성분석 가설(2026-07-30) — 라이브 12건(소표본) 중 손실 평균 FNG≈20.7 vs 승리 평균
# FNG≈26.4로 "얕은 공포가 유리"해 보였으나, 20개월 백필(n=52) 그리드 A/B에서 기각:
# min15/20/22 전부 baseline(+2.50%) 대비 악화(-1.76~-3.20). 깊은 공포 진입이 실제로는
# 순기여 중이었음 — 소표본 착시. ❌ 채택하지 않음(재시도 금지). 인프라는 재사용 가능하게
# 보존(qual_hypothesis_tuning.py 재현).
FNG_CONTRARIAN_MIN_FEAR: float | None = None
VIX_RSI_LONG_MAX = 50.0
# 정성분석 가설(2026-07-30) — 라이브 7건(소표본) 중 손실 RSI 36.7~47.0 vs 승리 RSI
# 48.95/49.5로 "얕은 침체가 유리"해 보였으나, 20개월 백필(n=35) 그리드 A/B에서 무효과
# 확정: min35 Δ0, min40 Δ+0.17(노이즈), min45 Δ-2.95(악화). ❌ 채택하지 않음(재시도
# 금지). 인프라는 재사용 가능하게 보존(qual_hypothesis_tuning.py 재현).
VIX_RSI_MIN_RSI: float | None = None
# VIX q40 임계값 허용 밴드: VIX가 q40보다 이 배수 이내로 높으면 "실질 calm"으로 인정.
# 근거: q40는 90일 롤링 추정치로 일일 오차 2~3%가 존재. 18.44 vs 17.85 = 3.3% — 통계적 노이즈.
# Ref: VIX percentile band interpretation (CBOE 2023 VIX whitepaper)
VIX_CALM_TOLERANCE_BAND = 1.05  # q40 기준 +5% 이내는 calm으로 처리
# P8(2026-07-26): execution_gate.py의 _expected_return_bps() 폴백에서만 사용(algorithms.py의
# 실제 macd_momentum 신호 로직과는 무관, v19에서 이미 제거됨). 과거엔 이 0.10 배수 단독으로
# 기대수익을 산출해 구조적으로 ecr_multiple(3.0) 요구선을 못 넘었음(신호 168/168 100% 거부,
# docs/arena/research/dormant-data-audit-20260726.md) — macd_hist와 max()로 묶어 완화.
MACD_ATR_THRESHOLD_MULTIPLE = 0.10
# P7(2026-07-25): 65.0→75.0. 20개월 백필(3740봉) near-miss 분석에서 rsi_below_long_max
# 유일차단 n=83·평균 이후6봉수익 +0.58%·승률64%로 알파 차단 확인(기존 11개월 near-miss는
# n=6~13로 판단 불가 수준이었음). 그리드 A/B(65/70/75/100)로 검증: PF 0.36→0.98 단조개선,
# 가중합 -3.23%→-0.19%(75에서 최적, 100은 -0.29%로 과잉완화). 다른 알고와 파라미터 격리
# (macd_momentum 전용), 손절 등 리스크 레이어 변경 없음. 그래도 PF<1이라 "엣지 발견"이
# 아니라 "과잉필터 완화로 손실 축소"로 해석할 것 — walk-forward 후반부(10개월) 표본이
# 여전히 작아(n=4) 재검증 필요. 재현: 백테스트 우선순위 분석 참조
# (docs/arena/research/priority-analysis-20260725.md §3.8).
MACD_MOMENTUM_RSI_LONG_MAX = 75.0  # 과매수 구간 롱 진입 차단
MACD_MOMENTUM_RSI_SHORT_MIN = 35.0  # 과매도 구간 숏 진입 차단
MACD_MOMENTUM_BB_WIDTH_MIN = 3.5  # BB 폭 최소값 (% of SMA): 미달 시 횡보장으로 판단, 진입 차단
# macd_momentum 전용 ADX 임계 — 공유 ADX_TREND_MIN(20)보다 약간 완화.
# 이유: macd_momentum은 모멘텀 '초기 형성'을 포착 목적이라 강한 추세(ADX≥20)보다
#       약한 추세(ADX≥18)에서도 모멘텀 신호가 유효하다.
MACD_MOMENTUM_ADX_MIN = 18.0
# ── Nonlinear TSMOM — macd_momentum 대체 후보 (2026-08-08) ────────────────────
# 배경: macd_momentum이 3년 백테스트(2023-08~2026-08, n=251) 전 구간(상승장 포함)에서
#   가중합 -31.79%·DSR 0.012로 완전 기각(hard gate 완화 6변형 전부 실패,
#   docs/arena/research/macd-hard-gate-tuning-20260808.json). 대체 후보로 Moskowitz·
#   Sabbatucci·Tamoni·Uhl(2025-12-10, "Nonlinear Time Series Momentum")의 연속
#   비선형 사이징 TSMOM을 설계·루브릭검증(docs/arena/research/
#   nonlinear-tsmom-design-20260808.md) 후 구현. algo_id "macd_momentum" 슬롯 재사용
#   (자본캡·DB 연속성 유지) — 신호 로직은 완전 교체. s_t = T봉누적수익률/(√T·σ̂),
#   포지션배수 f(s)=clamp(s/(s²+1), 0, WEIGHT_CAP) — 논문 식(3)+Ferson&Siegel(2001).
# ✅ v35(2026-08-08) 활성화: DSR(0.110)·부트스트랩(95%CI가 0 포함)은 미달이나, 레거시
#   대비 walk-forward 6/6 구간 전부 개선(예외 없음, tsmom_nl_walk_forward.py) — "증명된
#   엣지"가 아니라 "확실히 죽은 레거시보다 확실한 우위"가 활성화 근거. 사용자 결정으로
#   거래량 우선 변형(min_signal=0.0) 채택. 롤백: TSMOM_NL_ENABLED=False.
TSMOM_NL_ENABLED = True
TSMOM_NL_LOOKBACK_CANDIDATES: tuple[int, ...] = (126, 180, 372)  # indicators.py 사전계산용(고정)
TSMOM_NL_LOOKBACK_BARS = 126  # walk-forward 6/6 구간 plateau(180/372는 혼조·약세)
TSMOM_NL_VOL_MODE = "ewma"  # "rv6"(6봉 realized_vol_24h) | "ewma"(장기 EWMA, R2와 동일 추정기)
TSMOM_NL_MIN_SIGNAL = 0.0  # 거래량 우선 채택값(3년 n≈254). 그리드 후보였던 {0.2,0.5}는 수익률 우선.
TSMOM_NL_WEIGHT_CAP = 0.5  # f(s)=s/(s²+1) 이론적 최댓값(s=1에서 0.5) — 상한 클램프

MULTI_FACTOR_LONG_RSI_MAX = 55.0
MULTI_FACTOR_SHORT_RSI_MIN = 55.0
# vix_rsi 진입 안정화(v26): RSI<50 딥매수 전 MACD 히스토그램 악화 중이면 보류.
#   fng v23 _momentum_not_worsening과 동일 메커니즘(칼받기 회피 — 매도 소진 확인).
#   근거: 라이브 4거래 -5.43%(승률 25%)·백테스트 11개월 -10.71%로 6알고 중 최악,
#   손실 진입이 히스토그램 하락 가속 구간에 집중(2026-07-08 진입 hist -191<-140 등).
#   백테스트(11개월): sum_w_ret -10.71→-0.57%·거래 63→39·스톱 11→3 (타 알고 무영향).
VIX_RSI_STABILIZATION_ENABLED = True
# vix_rsi 청산 히스테리시스(v26): 진입 임계(RSI<50·VIX<q40×1.05)가 곧 청산 임계라
#   경계 진동 시 진입가 부근 whipsaw 손실 청산 반복. 청산측 임계를 분리 —
#   RSI≥60(모멘텀 소진) 또는 VIX≥q40×1.15(환경 실질 악화)일 때만 flat 청산.
#   risk-off·breadth·stablecoin veto는 즉시 청산(히스테리시스 미적용), 하방은
#   래칫 트레일링 스톱이 방어. algorithms.exit_hold_override 참조.
VIX_RSI_EXIT_HYSTERESIS_ENABLED = True
VIX_RSI_EXIT_RSI_MAX = 60.0
VIX_EXIT_TOLERANCE_BAND = 1.15

TREND_EMA_FAST_PERIOD = 12
TREND_EMA_SLOW_PERIOD = 26
TREND_RETURN_24H_BARS = 6
TREND_RETURN_72H_BARS = 18
TREND_REALIZED_VOL_24H_BARS = 6
TREND_CORE_RSI_LONG_MAX = 70.0
TREND_CORE_RSI_SHORT_MIN = 30.0
TREND_CORE_MACD_ATR_THRESHOLD_MULTIPLE = 0.10
REGIME_STRESS_RETURN_ATR_MULTIPLE = 3.0
REGIME_STRESS_RANGE_ATR_MULTIPLE = 5.0
REGIME_TREND_BB_WIDTH_MIN = 3.5
REGIME_SIDEWAYS_BB_WIDTH_MAX = 3.5
REGIME_SIDEWAYS_RETURN_ATR_MULTIPLE = 1.0

ALLOCATOR_BUDGET_TREND_CORE = 0.60
ALLOCATOR_BUDGET_LEGACY_RULE = 0.40
ALLOCATOR_BUDGET_CARRY = 0.00

EXEC_GATE_ECR_MULTIPLE = 3.0
EXEC_GATE_MAX_SPREAD_BPS = 5.0
EXEC_GATE_MAX_SLIPPAGE_BPS = 8.0
EXEC_GATE_MIN_DEPTH_SCORE = 0.5
EXEC_GATE_MAX_LATENCY_MS = 750.0
EXEC_GATE_VOL_SPIKE_MAX = 1.0
# 2026-07-30 진단(논문 λ 재현 세션 중 발견): REST /depth limit=20은 BTCUSDT 10bps 밴드의
# 5~6%만 커버(실측: mid 대비 20번째 레벨이 0.5~0.65bps 거리, 10bps 밴드 안 채움) —
# depth_10bp_bid/ask_usd가 실제값의 ~1.5~2%로 과소추정(실측 $98K vs 실제 $6.26M, 60배차)
# → depth_too_thin/slippage_too_high 오탐 유발. limit={100,500,1000,5000} 실측 결과
# 1000부터 양쪽(bid/ask) 10bps 완전 커버(5000과 동일 값, 추가 이득 없음).
EXEC_GATE_MIN_DEPTH_10BP_USD = 1_000_000.0
# 2026-08-14: 자산별 정상 유동성 실측(arena_execution_gates.feature_snapshot, 2026-07-31
# depth limit 수정 반영분만, BTC n=606·ETH/SOL n=324) 기반 캘리브레이션. 위 전역값은
# BTC 전용으로 잡힌 것이었음 — SOL은 정상 상태에서도 10bp 밴드 유동성이 항상 $1M 밑
# (관측 min $241K~p90 $575K, 절대 못 넘김)이라 그대로 쓰면 신호의 62.5%가 "체결이
# 나빠서"가 아니라 "SOL이라서" depth_too_thin으로 거부됨(실측). ETH는 관측 min이 $1.07M로
# $1M 위이긴 하나 여유폭 7%뿐이라 정상 변동에도 오탐 가능 — BTC(여유폭 2.9x)와 동일 원칙
# (관측 최소값 대비 ~3x 여유)으로 재산출. 재현: scripts/analysis/exec_gate_depth_calibration.py
EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL: dict[str, float] = {
    "BTCUSDT": 1_000_000.0,  # 기존값 유지 — 관측 min $2.93M, 이미 여유폭 2.9x로 안전
    "ETHUSDT": 400_000.0,  # 관측 min $1.07M 대비 여유폭 2.7x(기존 $1M은 마진 7%로 위험)
    "SOLUSDT": 80_000.0,  # 관측 min $241K 대비 여유폭 3.0x
}
EXEC_GATE_DEPTH_SNAPSHOT_LIMIT = 1000
SHADOW_ORDER_NOTIONAL_USD = 1_000.0
SHADOW_ORDER_TIMEOUT_SEC = 30
SHADOW_ARRIVAL_BENCHMARK_SEC = 1

REALTIME_RISK_WEIGHT_VOLATILITY_SPIKE = 0.18
REALTIME_RISK_WEIGHT_SPREAD_WIDENING = 0.18
REALTIME_RISK_WEIGHT_DEPTH_COLLAPSE = 0.22
REALTIME_RISK_WEIGHT_VOLUME_SHOCK = 0.10
REALTIME_RISK_WEIGHT_ORDER_FLOW_IMBALANCE = 0.12
REALTIME_RISK_WEIGHT_EXPECTED_SLIPPAGE = 0.15
REALTIME_RISK_WEIGHT_FUTURES_STRESS = 0.05
REALTIME_RISK_CAUTION_THRESHOLD = 0.35
REALTIME_RISK_BLOCK_ENTRY_THRESHOLD = 0.55
REALTIME_RISK_EXIT_CANDIDATE_THRESHOLD = 0.70
REALTIME_RISK_FORCE_EXIT_THRESHOLD = 0.85
REALTIME_RISK_SUSTAINED_WINDOWS = 2

MIN_HOLD_HOURS: dict[str, float] = {
    "regime_trend": 12.0,
    "fng_contrarian": 36.0,  # v22: 24→48h. v30: 48→36h(P-A익절 상호작용, fng_optimize 재그리드)
    "vix_rsi": 12.0,
    "macd_momentum": 8.0,
    "multi_factor": 12.0,
    "omnibus": 8.0,
    "meridian": 12.0,  # 추세/역발산 혼합 — regime_trend·multi_factor와 동일 중간값(v36)
}
MIN_HOLD_FALLBACK_HOURS = 4.0

# Walk-forward split configuration
WF_VERSION = "wf-v1"
WF_TRAIN_BARS = 500  # expanding anchor window (~83 days of 4H)
WF_TEST_BARS = 120  # test window per split (~20 days of 4H)
WF_STEP_BARS = 120  # advance per split (non-overlapping test windows)
WF_EMBARGO_BARS = 6  # gap between train end and test start (24 h of 4H)
WF_MIN_TOTAL_BARS = WF_TRAIN_BARS + WF_EMBARGO_BARS + WF_TEST_BARS


def base_params_snapshot() -> dict[str, Any]:
    """Return JSON-serializable default parameters for trade reproducibility."""
    return {
        "params_version": PARAMS_VERSION,
        "runtime": RUNTIME,
        "feature_set_version": FEATURE_SET_VERSION,
        "risk_model_version": RISK_MODEL_VERSION,
        "market_data": {
            "symbol": BINANCE_SYMBOL,
            "kline_interval": BINANCE_KLINE_INTERVAL,
            "klines_limit": BINANCE_KLINES_LIMIT,
            "shadow_vnext_enabled": ARENA_SHADOW_VNEXT_ENABLED,
            "frequency_shadow_enabled": ARENA_FREQUENCY_SHADOW_ENABLED,
            "frequency_shadow_profiles": list(ARENA_FREQUENCY_SHADOW_PROFILES),
            "realtime_collector_enabled": ARENA_REALTIME_COLLECTOR_ENABLED,
            "realtime_feature_window_seconds": REALTIME_FEATURE_WINDOW_SECONDS,
        },
        "execution_product": {
            "target_product": TARGET_PRODUCT,
            "position_semantics": POSITION_SEMANTICS,
            "short_signal_action": SHORT_SIGNAL_ACTION,
            "allow_live_short": ALLOW_LIVE_SHORT,
            "research_perp_shadow_enabled": RESEARCH_PERP_SHADOW_ENABLED,
            "spot_execution_only": True,
            "derivatives_data_usage": "research_features_only",
        },
        "schedule": {
            "cron_hour": SCHEDULER_CRON_HOUR,
            "cron_minute": SCHEDULER_CRON_MINUTE,
            "min_hold_hours": deepcopy(MIN_HOLD_HOURS),
            "min_hold_fallback_hours": MIN_HOLD_FALLBACK_HOURS,
        },
        "indicators": {
            "rsi_period": RSI_PERIOD,
            "rsi_neutral": RSI_NEUTRAL,
            "rsi_recent_multiple": RSI_RECENT_MULTIPLE,
            "macd_fast_period": MACD_FAST_PERIOD,
            "macd_slow_period": MACD_SLOW_PERIOD,
            "macd_signal_period": MACD_SIGNAL_PERIOD,
            "macd_neutral": MACD_NEUTRAL,
            "bollinger_period": BOLLINGER_PERIOD,
            "bollinger_stddev": BOLLINGER_STDDEV,
            "bollinger_neutral": BOLLINGER_NEUTRAL,
            "atr_period": ATR_PERIOD,
            "atr_fallback_pct": ATR_FALLBACK_PCT,
        },
        "strategy_thresholds": {
            "fng_long_below": FNG_LONG_BELOW,
            "vix_rsi_long_max": VIX_RSI_LONG_MAX,
            "macd_atr_threshold_multiple": MACD_ATR_THRESHOLD_MULTIPLE,
            "macd_momentum_rsi_long_max": MACD_MOMENTUM_RSI_LONG_MAX,
            "macd_momentum_bb_width_min": MACD_MOMENTUM_BB_WIDTH_MIN,
            "multi_factor_long_rsi_max": MULTI_FACTOR_LONG_RSI_MAX,
            "trend_core_rsi_long_max": TREND_CORE_RSI_LONG_MAX,
            "trend_core_macd_atr_threshold_multiple": TREND_CORE_MACD_ATR_THRESHOLD_MULTIPLE,
            "donchian_period": DONCHIAN_PERIOD,
            "adx_period": ADX_PERIOD,
            "adx_trend_min": ADX_TREND_MIN,
            "funding_hot_zscore": FUNDING_HOT_ZSCORE,
            "etf_outflow_heavy_z": ETF_OUTFLOW_HEAVY_Z,
            "ma200_regime_gate_enabled": MA200_REGIME_GATE_ENABLED,
            "lsr_crowded_zscore": LSR_CROWDED_ZSCORE,
            "taker_confirm_zscore": TAKER_CONFIRM_ZSCORE,
            "fng_contrarian_min_drawdown": FNG_CONTRARIAN_MIN_DRAWDOWN,
            "vix_rsi_stabilization_enabled": VIX_RSI_STABILIZATION_ENABLED,
            "vix_rsi_exit_hysteresis_enabled": VIX_RSI_EXIT_HYSTERESIS_ENABLED,
            "vix_rsi_exit_rsi_max": VIX_RSI_EXIT_RSI_MAX,
            "vix_exit_tolerance_band": VIX_EXIT_TOLERANCE_BAND,
            "breadth_healthy_min": BREADTH_HEALTHY_MIN,
            "stablecoin_contraction_z": STABLECOIN_CONTRACTION_Z,
            "regime_stress_return_atr_multiple": REGIME_STRESS_RETURN_ATR_MULTIPLE,
            "regime_stress_range_atr_multiple": REGIME_STRESS_RANGE_ATR_MULTIPLE,
            "regime_trend_bb_width_min": REGIME_TREND_BB_WIDTH_MIN,
            "regime_sideways_bb_width_max": REGIME_SIDEWAYS_BB_WIDTH_MAX,
            "regime_sideways_return_atr_multiple": REGIME_SIDEWAYS_RETURN_ATR_MULTIPLE,
        },
        "position_sizing": {
            "vol_target_per_bar": VOL_TARGET_PER_BAR,
            "vol_weight_min": VOL_WEIGHT_MIN,
            "vol_weight_max": VOL_WEIGHT_MAX,
            "risk_per_trade_pct": RISK_PER_TRADE_PCT,
        },
        "risk_defaults": {
            "stop_loss_fallback_pct": STOP_LOSS_FALLBACK_PCT,
            "fee_bps": FEE_BPS,
            "atr_multiple": ATR_MULTIPLE,
            "stop_loss_min_pct": STOP_LOSS_MIN_PCT,
            "stop_loss_max_pct": STOP_LOSS_MAX_PCT,
            "trailing_stop_enabled": TRAILING_STOP_ENABLED,
            "trail_persist_step_bps": TRAIL_PERSIST_STEP_BPS,
            "macro_stale_hours": MACRO_STALE_HOURS,
            "position_unit": POSITION_UNIT,
            "max_open_positions_total": MAX_OPEN_POSITIONS_TOTAL,
            "max_long_positions": MAX_LONG_POSITIONS,
            "max_short_positions": MAX_SHORT_POSITIONS,
            "max_net_long_exposure": MAX_NET_LONG_EXPOSURE,
            "max_net_short_exposure": MAX_NET_SHORT_EXPOSURE,
            "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
            "algo_max_drawdown_kill_pct": ALGO_MAX_DRAWDOWN_KILL_PCT,
            "cooldown_after_kill_hours": COOLDOWN_AFTER_KILL_HOURS,
        },
        "allocator": {
            "trend_core_budget": ALLOCATOR_BUDGET_TREND_CORE,
            "legacy_rule_budget": ALLOCATOR_BUDGET_LEGACY_RULE,
            "carry_budget": ALLOCATOR_BUDGET_CARRY,
        },
        "execution_gate": {
            "shadow_enabled": ARENA_EXECUTION_GATE_SHADOW_ENABLED,
            "live_enabled": ARENA_EXECUTION_GATE_LIVE_ENABLED,
            "ecr_multiple": EXEC_GATE_ECR_MULTIPLE,
            "max_spread_bps": EXEC_GATE_MAX_SPREAD_BPS,
            "max_slippage_bps": EXEC_GATE_MAX_SLIPPAGE_BPS,
            "min_depth_score": EXEC_GATE_MIN_DEPTH_SCORE,
            "max_latency_ms": EXEC_GATE_MAX_LATENCY_MS,
            "vol_spike_max": EXEC_GATE_VOL_SPIKE_MAX,
            "min_depth_10bp_usd": EXEC_GATE_MIN_DEPTH_10BP_USD,
            "shadow_order_notional_usd": SHADOW_ORDER_NOTIONAL_USD,
            "shadow_order_timeout_sec": SHADOW_ORDER_TIMEOUT_SEC,
            "shadow_arrival_benchmark_sec": SHADOW_ARRIVAL_BENCHMARK_SEC,
        },
        "realtime_risk": {
            "risk_model_version": REALTIME_RISK_MODEL_VERSION,
            "enabled": ARENA_REALTIME_RISK_ENABLED,
            "live_enabled": ARENA_REALTIME_RISK_LIVE_ENABLED,
            "history_windows": REALTIME_RISK_HISTORY_WINDOWS,
            "freshness_seconds": REALTIME_RISK_FRESHNESS_SECONDS,
            "weights": {
                "volatility_spike": REALTIME_RISK_WEIGHT_VOLATILITY_SPIKE,
                "spread_widening": REALTIME_RISK_WEIGHT_SPREAD_WIDENING,
                "depth_collapse": REALTIME_RISK_WEIGHT_DEPTH_COLLAPSE,
                "volume_shock": REALTIME_RISK_WEIGHT_VOLUME_SHOCK,
                "order_flow_imbalance": REALTIME_RISK_WEIGHT_ORDER_FLOW_IMBALANCE,
                "expected_slippage": REALTIME_RISK_WEIGHT_EXPECTED_SLIPPAGE,
                "futures_stress": REALTIME_RISK_WEIGHT_FUTURES_STRESS,
            },
            "thresholds": {
                "caution": REALTIME_RISK_CAUTION_THRESHOLD,
                "block_entry": REALTIME_RISK_BLOCK_ENTRY_THRESHOLD,
                "exit_candidate": REALTIME_RISK_EXIT_CANDIDATE_THRESHOLD,
                "force_exit_candidate": REALTIME_RISK_FORCE_EXIT_THRESHOLD,
                "sustained_windows": REALTIME_RISK_SUSTAINED_WINDOWS,
            },
            "spot_execution_only": True,
        },
    }
