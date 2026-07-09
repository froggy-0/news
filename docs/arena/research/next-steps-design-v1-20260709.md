# 다음 단계 실행 설계 v1 (2026-07-09)

> **성격**: [algo-specific-improvements-20260709.md](algo-specific-improvements-20260709.md)의
> 실행 항목을 구현 가능한 수준(파일·함수·플래그·검증 명령)으로 상세화한 설계 문서.
> 아직 코드 미변경. 각 Work Item(WI)은 독립 배포 가능하며, 전부 다음 공통 원칙을 따른다.

**공통 원칙 (전 WI 적용)**
1. **플래그 게이트**: 모든 동작 변경은 `parameters.py` 플래그로 on/off — 기본값 off로 머지
   가능, 백테스트 통과 후 on.
2. **None→graceful**: 신규 피처 미수집 시 기존 동작 유지 (차단하지 않음).
3. **live/backtest 패리티**: 판정 로직은 `execution_rules.py`/`algorithms.py` 순수함수로만.
4. **버전 스트링 동시 변경 체크리스트**: 파라미터 동작 변경 커밋은 반드시 `PARAMS_VERSION`
   bump를 같은 커밋에 포함 (v25→v26 재현성 버그 재발 방지). 리뷰 항목으로 고정.
5. **채택 기준**: macro 백필 백테스트에서 대상 알고 개선 + 타 알고 무회귀 + (WI-8 완성 후)
   DSR>0.95·PBO<0.2 + plateau 중앙값 채택.

**의존성 그래프**

```
WI-3 진단 ──────────► WI-4 volume 게이트 (병목 확인 후 교환 설계)
WI-8 DSR/PBO ───────► 모든 WI의 채택 게이트 (그리드 검증류는 특히 WI-2·5·6·7)
WI-2 fng 히스테리시스 ◄─ v26 vix_rsi 패턴 (기존 코드 재사용)
WI-6 macd 크로스 ◄──── exit_hold_override 메커니즘 (v26에서 검증된 구조 재사용)
WI-9 forceOrder ─────► (30일+ 축적 후) fng·omnibus 지표 연결은 후속 v2
```

---

## WI-1. multi_factor 투표 구조 수정 — 레짐 필수화

**목표**: "조용한 하락장에서 방향성 팩터 없이 4표 충족→진입"하는 구조 결함 제거.

### 변경점
- `parameters.py`
  ```python
  MULTI_FACTOR_REGIME_REQUIRED = True   # 플래그 (백테스트 전 False로 머지 가능)
  MULTI_FACTOR_MIN_VOTES_EX_REGIME = 3  # 레짐 제외 4팩터 중 최소 득표
  ```
- `algorithms.py:multi_factor()` — veto 블록 뒤:
  ```python
  factors = _multi_factor_factors(macro, ind)
  if parameters.MULTI_FACTOR_REGIME_REQUIRED:
      if not factors["bullish_regime"]:
          return None
      if sum(v for k, v in factors.items() if k != "bullish_regime") \
              >= parameters.MULTI_FACTOR_MIN_VOTES_EX_REGIME:
          return "long"
      return None
  # 기존 경로 (플래그 off)
  if sum(factors.values()) >= 4: ...
  ```
- `explain_signal()`의 multi_factor 분기에 `regime_required` 통과/실패 기록 추가.
- `_multi_factor_factors()`는 무변경 (진단·히스테리시스 공용 유지).

### 실험 매트릭스 (백테스트)
| 변형 | 조건 |
|---|---|
| A (현행) | 5중 4 |
| B (제안) | 레짐 필수 + 4중 3 |
| C (중간) | 레짐 ∈ {강세, sideways} 필수 + 4중 3 — bear류만 배제 |

```bash
.venv/bin/python3 scripts/analysis/backtest_with_macro_backfill.py \
    --months 11 --algos multi_factor --variants regime_vote_ab
```
(스크립트에 variant 파라미터 오버라이드 지원 추가 — fng_optimize.py의 그리드 패턴 재사용)

### 채택 기준·리스크
- B 또는 C가 sum_w_ret·MaxDD 개선 AND 거래수 ≥ 현행의 50% (거래 소멸 방지).
- 리스크: 거래빈도 급감 → C안이 안전판. 롤백 = 플래그 off.
- 배포 시 `PARAMS_VERSION` → `arena-params-v27`.

---

## WI-2. fng_contrarian 청산 히스테리시스

**목표**: 진입(FNG<30)과 동일한 임계로 청산(FNG≥30 flat)하는 반쪽 구조를 분리 —
반등 초입 청산으로 물타기 평단 이점을 버리는 문제 해소. 라이브 flat 청산 4건 평균 -0.52%.

### 변경점
- `parameters.py`
  ```python
  FNG_EXIT_HYSTERESIS_ENABLED = True
  FNG_EXIT_NEUTRAL_MIN = 45.0   # 그리드 {40, 45, 50, 55}에서 결정
  ```
- `algorithms.py:exit_hold_override()` — vix_rsi 분기와 대칭으로 추가:
  ```python
  if algo_id == "fng_contrarian" and parameters.FNG_EXIT_HYSTERESIS_ENABLED:
      if _is_risk_off(_regime_state(macro)):        # 즉시 청산 양보 없음
          return False
      if _breadth_collapsed(macro) or _stablecoin_contracting(macro):
          return False
      fng = macro.get("fng")
      if fng is None:
          return False
      return float(fng) < parameters.FNG_EXIT_NEUTRAL_MIN
  ```

### 상호작용 확인 (설계 검증 완료)
- `exit_hold_override`는 scheduler에서 **`close_reason == "flat_signal"`일 때만** 개입
  (scheduler.py:772) → **time_stop(72h)·risk-off 청산은 영향 없음**. 히스테리시스로 보유가
  길어져도 72h 시간손절이 상한을 보장 — 꼬리 리스크 캡 유지.
- min_hold(48h)와 독립: min_hold는 조기 flat 차단, 히스테리시스는 그 이후 flat 차단.
- backtest 경로도 동일 함수 사용 (backtest.py가 exit_hold_override 호출하는지 확인 —
  미호출이면 **배선 추가가 이 WI의 선행 작업** ⚠️ 구현 시 최우선 확인 항목).

### 검증
```bash
.venv/bin/python3 scripts/analysis/fng_optimize.py \
    --grid exit_neutral_min=40,45,50,55 --months 6
```
- plateau 중앙값 채택 (v22 ts/mh 튜닝과 동일 절차). WI-8 완성 시 DSR 재확인.
- 주목 지표: flat 청산 트레이드의 평균수익 부호 반전 여부, time_stop 비중 변화.

---

## WI-3. 게이트 차단률 진단 스크립트 (분석만, 코드 무변경)

**목표**: regime_trend(11-AND)·macd_momentum이 백테스트 기간 중 "무엇에 막혔는지" 정량화.
조건 완화/교환(WI-4)의 사전 근거. 라이브 무거래 3주의 원인 분해.

### 설계
- 신규 `scripts/analysis/gate_block_rates.py`
  1. `backtest_with_macro_backfill.py`의 프레임 로더 재사용 (macro 백필 포함 11개월).
  2. 각 bar × 각 algo에 대해 `algorithms.explain_signal(algo_id, macro, ind)` 호출
     (이미 failed_conditions/vetoes/passed_conditions를 구조화 반환).
  3. 집계 출력:
     - 조건별 실패율 순위 (전 bar 기준 / "그 조건만 빼면 통과였던 near-miss bar" 기준)
     - near-miss 시점 목록 → 이후 N봉 수익 분포 ("막힌 진입이 실제로 나쁜 진입이었나")
  4. 출력: `docs/arena/research/gate-block-rates-<date>.md` 자동 생성 (markdown 테이블).
- **판단 기준**: near-miss 이후 수익 분포가 양(+)인 조건 = 알파를 막는 dead weight 후보,
  음(−)인 조건 = 유효 필터. 이 구분 없이 조건을 빼지 않는다.

---

## WI-4. kline volume 지표화 + regime_trend 볼륨 확인

**목표**: 이미 수신 중인 volume을 지표화(수집 비용 0), 돌파 확인의 표준 필터 추가.

### 변경점
- `indicators.py`
  ```python
  def relative_volume(volumes: list[float], period: int = 20) -> float | None:
      """직전 봉 볼륨 / 20봉 SMA. 데이터 부족 시 None (graceful)."""
  ```
  `compute()` 시그니처에 `volumes: list[float] | None = None` 추가 (기본 None →
  `ind["rel_volume"] = None`, 기존 호출부 무회귀) → `ind["rel_volume"]`.
- `scheduler.py:OHLCV`에 `volumes: list[float]` 필드 추가 (`k[5]` 파싱), `indicators.compute`에 전달.
- `backtest.py`: `ReplayBar.volume`은 이미 Supabase에서 채워짐(backtest.py:1074) —
  프레임 빌더에서 rolling 20봉 볼륨으로 `rel_volume` 산출해 indicators dict에 주입.
- `parameters.py`
  ```python
  VOLUME_CONFIRM_ENABLED = False       # WI-3 진단 결과 확인 후 백테스트 → on
  VOLUME_CONFIRM_MIN_REL = 1.5         # 돌파봉 볼륨 ≥ 20봉 평균 ×1.5 (업계 표준값에서 그리드)
  ```
- `algorithms.py`: 헬퍼 `_volume_confirms(ind)` — `rel_volume is None → True`(graceful),
  `regime_trend()` 진입 조건에 결합.

### 실험 매트릭스
| 변형 | 내용 |
|---|---|
| A | 현행 |
| B | 현행 + 볼륨 게이트 (순수 추가 — 거래 감소 방향) |
| C | 볼륨 게이트 추가 + WI-3에서 dead weight로 판명된 조건 1개 완화 (교환 — 거래수 유지) |

- 채택 기준: C 목표 — 통과율 유지·상향하며 진입 품질(평균수익) 개선.
- `signal_reason.inputs`에 `rel_volume` 추가 (재현성).

---

## WI-5. vix_rsi 2단계 실험 (구조 판정)

**목표**: 유일하게 엣지 증거가 없는 알고의 "구제 vs 은퇴" 판정을 데이터로 종결.

### Step 1 — 일간 MA200 게이트 A/B (변경 최소)
- `parameters.py`: `VIX_RSI_MA200_GATE_ENABLED = False` (실험 플래그)
- `algorithms.py:vix_rsi()`: veto 체인에 `_below_ma200(macro)` 추가 (macd v24와 동일 패턴).
- 백테스트 11개월 A/B. **판정선: sum_w_ret > 0 전환 여부.**

### Step 2 — 트리거 재정의: 상태 → 이벤트 (Step 1 미달 시)
- `parameters.py`
  ```python
  VIX_RSI_TRIGGER_MODE = "state"        # "state"(현행) | "cross"
  VIX_RSI_CROSS_OVERSOLD = 35.0         # 그리드 {30, 35}
  ```
- `indicators.py`: `ind["rsi_prev"]` 추가 — `rsi(closes[:-1])` 재계산 (경량).
  backtest 프레임에도 동일 주입 (패리티).
- `algorithms.py:vix_rsi()` cross 모드:
  ```python
  # RSI가 과매도선을 하향 후 상향 돌파한 봉만 진입 (반전 확인 매수)
  crossed = rsi_prev < parameters.VIX_RSI_CROSS_OVERSOLD <= rsi
  ```
  VIX calm 조건·veto 체인은 유지. **청산은 기존 v26 히스테리시스 그대로** (이벤트 진입 +
  히스테리시스 보유 = WI-6과 동일 구조).

### Step 3 — 판정
- Step 1·2 모두 sum_w_ret ≤ 0 → **은퇴 RFC 작성** (별도 문서). 교체 후보:
  (a) basis(현선물 스프레드, 이미 수집) 기반 캐리/컨탱고 신호,
  (b) Deribit DVOL(신규 수집, 일간) + RSI 크로스 — DVOL 조사는 병행 리서치 티켓.
- ⚠️ 슬롯 교체 시 `MAX_OPEN_POSITIONS_TOTAL` 등 캡은 알고 수 유지라 무변경.

---

## WI-6. macd_momentum 트리거 재정의 — 0선 크로스 진입 + 보유 히스테리시스

**목표**: "이미 강한 모멘텀"(늦은 진입, regime_trend와 중복) → "모멘텀 전환 초기"로 정체성 이동.

### 설계 핵심 — stateless 신호 함수 제약의 해법
신호 함수는 포지션 상태를 모르므로 "진입은 크로스 봉만, 보유는 h>0 동안"을 신호값 하나로
표현할 수 없다. **v26 vix_rsi에서 검증된 기존 메커니즘 조합으로 해결**:
- **진입** = 신호 함수가 크로스 봉에만 `"long"` 반환: `h_prev <= 0 < h`
- **보유** = `exit_hold_override("macd_momentum", ...)`가 `h > 0`인 동안 flat 청산 보류
- **청산** = `h <= 0` (0선 하향) 또는 risk-off/트레일링 스톱

### 변경점
- `parameters.py`
  ```python
  MACD_MOMENTUM_TRIGGER_MODE = "state"   # "state"(현행) | "zero_cross"
  ```
- `algorithms.py:macd_momentum()` zero_cross 모드: 진입 조건을
  `h_prev <= 0 < h` + 기존 veto 체인 유지. RSI<65·ADX≥18은 유지(크로스 시점엔 통상 여유).
  BB폭 게이트는 재검토 대상 — 크로스는 스퀴즈 직후 발생 가능 → 그리드에 포함.
- `exit_hold_override()`에 macd_momentum 분기 추가 (risk-off/veto 즉시 청산 예외 동일).

### 실험 매트릭스
| 변형 | 진입 | 보유 |
|---|---|---|
| A (현행) | h>0 ∧ h↑ | 신호 유지 |
| B | 0선 크로스 | h>0 히스테리시스 |
| C | B + BB폭 게이트 제거 | 동일 |

- 주목 지표: 진입 평균 시점(크로스 후 몇 봉), regime_trend와의 포지션 중복률
  (중복 감소 = 포트폴리오 다양화 목적 달성 확인).

---

## WI-7. omnibus RANGE/REBOUND 목표가 청산

**목표**: 평균회귀 트레이드에 이론 정합적 익절(BB 중앙선)을 부여 — 4h 재평가 대기보다
빠른 회전. 유일 순플러스 알고이므로 **가장 보수적으로**: 신규 close_reason 추가일 뿐
기존 청산 경로는 전부 유지.

### 변경점
- `indicators.py`: `ind["bb_mid"]` 노출 (`_bb_stats`의 mean — 이미 계산 중, 노출만).
- `parameters.py`
  ```python
  OMNIBUS_TARGET_EXIT_ENABLED = False
  OMNIBUS_RANGE_TARGET = "bb_mid"        # RANGE: BB 중앙선
  OMNIBUS_REBOUND_TARGET_ATR_MULT = 1.5  # REBOUND: 진입가 + ATR×mult (그리드 {1.0, 1.5, 2.0})
  ```
- `execution_rules.py`: 순수함수
  ```python
  def target_exit_triggered(direction, current_price, target_price) -> bool
  ```
- **진입 시 목표가 고정**: `positions.open_position()` 시 `signal_reason`에
  `omni_regime`·`target_price` 저장 (레짐·BB는 진입 후 변하므로 진입 시점 스냅샷 고정 —
  fng의 `fng_ref_price` 패턴 재사용).
- **live**: `stream.py`의 틱 처리(`_check_stop_loss` 옆)에 target 감시 추가 —
  도달 시 `close_reason="target_exit"`. **min_hold보다 우선** (익절이므로 조기 청산 허용 —
  명시 결정, 손절과 비대칭).
- **backtest**: 봉 `high >= target_price` → target 가격으로 체결 (종가 아님 — 한계가 모델,
  fng 트랜치와 동일 회계).

### 검증
- RANGE/REBOUND 트레이드만 분리 집계: 승률·평균보유·회전수·sum_w_ret.
- UP_TREND 트레이드는 목표가 미적용 (추세는 트레일링이 담당) — 회귀 없음 확인.

---

## WI-8. DSR/PBO 검증 유틸 (채택 게이트 인프라)

**목표**: WI-2·5·6·7의 그리드 실험에 과적합 보정 통계를 제공. 모든 후속 튜닝의 전제.

### 설계
- 신규 `scripts/analysis/validation_stats.py`
  - 입력: 그리드 실험 결과 (config별 트레이드 목록 JSON — 백테스트 스크립트가 이미 출력하는
    포맷에 `--dump-trades` 옵션 추가)
  - 출력:
    - **DSR** (Bailey–López de Prado): 시도 수 N·수익률 skew/kurtosis 보정 후 SR 유의확률
    - **PBO** (CSCV): S=16 분할 조합적 검증 — in-sample 최적 config의 OOS 순위 분포
  - 구현은 수식 직접 (외부 의존성 numpy/scipy만 — 이미 .venv에 있음). mlfinpy 구현 참고.
- 사용 규약 문서화: "그리드 실험 보고서에는 최적값·plateau·DSR·PBO 4개를 필수 기재"
  — `docs/arena/research/` 실험 보고서 템플릿에 반영.

---

## WI-9. forceOrder(강제청산) 스트림 수집 (수집만 선행)

**목표**: 역발산 계열(fng·omnibus REBOUND)의 "매도 소진" 직접 증거 데이터 축적.
**지표 연결은 30일+ 축적 후 별도 WI** — 이번 범위는 수집·저장까지.

### 설계
- ⚠️ forceOrder는 **선물 스트림** (`wss://fstream.binance.com/ws/btcusdt@forceOrder`) —
  현물 kline용 기존 커넥션(config.BINANCE_WS_URL)과 별도 커넥션/태스크.
- `stream.py`(또는 신규 `liquidation_stream.py`): 독립 asyncio 태스크 —
  이벤트 수신 → 인메모리 4h 버킷 집계 `(bucket_start, side, notional_usd, count)` →
  4h 마감 시 data_lake 저장. **트레이딩 경로와 완전 분리** (수집 실패 무영향).
- 신규 테이블 `arena_liquidation_bars` (마이그레이션):
  `bar_start timestamptz, symbol text, long_liq_usd numeric, short_liq_usd numeric,
   long_liq_count int, short_liq_count int` — PK (bar_start, symbol).
- 재접속 갭 허용: 버킷은 best-effort, `quality` 컬럼에 수신 커버리지 기록(선택).
- 후속 v2(축적 후): `long_liq_usd`의 30일 롤링 z → "청산 폭발 후 소강" 피처 →
  fng 진입 확인·omnibus REBOUND 투표 후보. 백테스트는 축적 구간만 가능(과거 데이터 없음)
  — 장기 과제임을 명시.

---

## WI-10. 4h taker ratio 게이트 배선 (수집 비용 0)

**목표**: regime_trend의 테이커 확인을 일간 lag1 z에서 로컬 4h 값으로 — 하루 지연 제거.

### 변경점
- `scheduler.py`: `market_structure` snapshot의 `taker_buy_sell_ratio`(v8에서 이미 수집)를
  macro dict에 `taker_ratio_4h`로 주입.
- `parameters.py`: `TAKER_CONFIRM_RATIO_4H_MIN = 0.95` (1.0=중립, 그리드 {0.90, 0.95, 1.0})
- `algorithms.py:_taker_confirms()`: `taker_ratio_4h` 존재 시 우선 사용, 없으면
  기존 일간 z 폴백 (이중 graceful).
- **패리티 확인 필수**: backtest 프레임의 `market_features`에 해당 필드가 snapshot.features
  에서 복원되는지 확인 — 미복원이면 백테스트 로더 보강이 선행 작업.

---

## 실행 일정 (재확인)

| 주차 | WI | 산출물 |
|---|---|---|
| 1주차 | WI-1 (multi_factor), WI-2 (fng), WI-3 (진단), WI-8 착수 | 백테스트 보고서 2건 + 차단률 리포트 |
| 2주차 | WI-4 (volume), WI-5 (vix_rsi Step1→2), WI-10 (taker 4h), WI-8 완성 | v27 파라미터 후보 확정 |
| 3주차~ | WI-6 (macd), WI-7 (omnibus), WI-9 (forceOrder 수집 개시) | v28 후보 + 수집 인프라 |

**배포 단위**: 백테스트 통과 WI들을 모아 `arena-params-v27`(1~2주차분) →
EC2 rsync + systemd 재시작 (기존 runbook). 플래그 off 상태 머지는 수시 가능.

**롤백**: 전 WI 공통 — 플래그 off + 재시작. DB 스키마 변경은 WI-7(signal_reason 필드 추가,
비파괴)·WI-9(신규 테이블, 독립)뿐이라 스키마 롤백 불필요.
