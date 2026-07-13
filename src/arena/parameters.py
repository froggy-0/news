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
PARAMS_VERSION = "arena-params-v30"
FEATURE_SET_VERSION = "arena-features-v8"
RISK_MODEL_VERSION = "portfolio-risk-v2"
REALTIME_RISK_MODEL_VERSION = "realtime-risk-v1"
RUNTIME = "ec2"

BINANCE_SYMBOL = "BTCUSDT"
BINANCE_KLINE_INTERVAL = "4h"
BINANCE_KLINES_LIMIT = 300
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
FEE_BPS = 5.0
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
MAX_OPEN_POSITIONS_TOTAL = 6
MAX_LONG_POSITIONS = 6
MAX_SHORT_POSITIONS = 6
MAX_NET_LONG_EXPOSURE = 6.0
MAX_NET_SHORT_EXPOSURE = 6.0
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
# WI-1 중간안(C): 레짐 필수화 시 강세뿐 아니라 sideways(횡보)도 허용, bear류만 배제.
MULTI_FACTOR_ALLOW_SIDEWAYS = True
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
VIX_RSI_LONG_MAX = 50.0
# VIX q40 임계값 허용 밴드: VIX가 q40보다 이 배수 이내로 높으면 "실질 calm"으로 인정.
# 근거: q40는 90일 롤링 추정치로 일일 오차 2~3%가 존재. 18.44 vs 17.85 = 3.3% — 통계적 노이즈.
# Ref: VIX percentile band interpretation (CBOE 2023 VIX whitepaper)
VIX_CALM_TOLERANCE_BAND = 1.05  # q40 기준 +5% 이내는 calm으로 처리
MACD_ATR_THRESHOLD_MULTIPLE = 0.10
MACD_MOMENTUM_RSI_LONG_MAX = 65.0  # 과매수 구간 롱 진입 차단
MACD_MOMENTUM_RSI_SHORT_MIN = 35.0  # 과매도 구간 숏 진입 차단
MACD_MOMENTUM_BB_WIDTH_MIN = 3.5  # BB 폭 최소값 (% of SMA): 미달 시 횡보장으로 판단, 진입 차단
# macd_momentum 전용 ADX 임계 — 공유 ADX_TREND_MIN(20)보다 약간 완화.
# 이유: macd_momentum은 모멘텀 '초기 형성'을 포착 목적이라 강한 추세(ADX≥20)보다
#       약한 추세(ADX≥18)에서도 모멘텀 신호가 유효하다.
MACD_MOMENTUM_ADX_MIN = 18.0
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
EXEC_GATE_MIN_DEPTH_10BP_USD = 1_000_000.0
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
