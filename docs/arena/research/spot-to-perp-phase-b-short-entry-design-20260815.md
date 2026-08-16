# Spot→Perp Phase B — 알고별 숏 진입 로직 설계 (2026-08-15, 설계안·미구현)

**상태**: 실행 인프라와 자산×알고 게이트는 운영 반영. §1원칙3 순서대로 6개 알고
(`macd_momentum`§8·`omnibus`§9·`regime_trend`§10·`multi_factor`§11·`vix_rsi`§12·
`fng_contrarian`§13) 전부 검증 완료(2026-08-15, §14 종합) — **전부 ❌기각**되어
`PERP_SHORT_ENABLED_TRACKS`는 여전히 빈 집합이다. `vix_rsi`(ETH)만 채택선에 근접
(DSR 0.934, 기준 0.95)했으나 문자 그대로는 미달 — 최종 판단은 §14에서 사용자에게
넘김.

> **다음 세션은 이 문서 하나만 읽고 바로 시작 가능하도록 작성됨.** 새 세션에서 처음
> 할 일은 §7("다음 세션 시작 가이드")로 바로 이동 — §1~§6은 §7에서 참조하는 배경/근거이므로
> 필요할 때만 되짚어 읽으면 된다. 이 문서 자체가 코드 변경을 반영하지 않으므로,
> 구현 세션 시작 시 §3의 코드 앵커(줄번호 포함)가 여전히 유효한지 먼저 grep으로
> 스팟체크할 것(다른 세션이 그 사이 `algorithms.py`/`parameters.py`를 건드렸을 수 있음).

## 0. 배경 — 지금 뭐가 왜 막혀 있나

[Phase A](spot-to-perp-phase-a-infrastructure-20260815.md)/[A2](spot-to-perp-phase-a2-root-track-split-20260815.md)로
"선물이라는 독립 자본 트랙"은 실거래 중(`ARENA_PERP_LIVE_ENABLED=True`, BTC/ETH/SOL
perp 트랙 각 6알고×$1,000). 하지만 `PERP_SHORT_ENABLED_TRACKS`(숏 opt-in 허용목록,
`parameters.py:81`)는 여전히 빈 집합이라 6개 알고 전부 롱/관망(`None`)만 낸다 — 선물
트랙도 실질은 "현물과 동일 신호 + 펀딩비만 추가"인 상태.

**기계적으로는 이미 준비됨** (Phase A에서 확인·검증):
- `perp_policy.py` — 방향 무관 열림/보유/반전/청산 상태머신(`spot_policy.py` 대칭).
- `execution_rules.py`(손절·트레일 사이징)·`risk.py`(포지션 캡) — 원래부터 long/short 대칭
  (2026-06-20 이전 실제 perp 시뮬레이션 유산).
- `positions.py.close_position()` — 펀딩 정산이 `direction` 부호를 반영
  (`market_structure.funding_return_pct`: 롱은 양의 펀딩비 지불, 숏은 수취).
- 캡: `MAX_SHORT_POSITIONS=6`, `MAX_NET_SHORT_EXPOSURE=6.0` — 롱과 동일 값으로 이미 설정됨
  (`parameters.py:169,171`). 단, `_risk_policy()`의 숏 캡 개방은 "`PERP_SHORT_ENABLED_TRACKS`가
  하나라도 있으면 portfolio 전체 캡 개방"이라 algo_id 단위가 아니다 — 실제 이중 방어는
  `positions.open_position()`의 algo_id별 허용목록(`positions.py:144-150`).

**막혀 있는 건 신호 생성 그 자체**: `algorithms.py`의 6개 함수(`macd_momentum`,
`omnibus`, `regime_trend`, `multi_factor`, `vix_rsi`, `fng_contrarian`)가 전부
`"long" | None`만 반환한다. 숏 진입 조건 자체가 정의돼 있지 않다. 이 문서는 6개
알고 각각에 대해 숏 진입 조건 설계안과, 그걸 백테스트로 검증하는 방법론을 정한다.

## 1. 설계 원칙

1. **거울 대칭은 기본값이지 결론이 아니다.** 롱 로직을 기계적으로 뒤집는 것을 1차
   가설로 삼되, 각 필터가 실제로 방향 대칭적인 정보인지 개별 확인한다(아래 §3에서
   비대칭 필터 다수 발견 — 단순 반전이 아니라 별도 임계값·별도 필드가 필요한 경우 있음).
2. **알고당 독립 가설 = 독립 검증.** "숏도 되더라"가 아니라 알고별로 개별 DSR·부트스트랩
   CI·워크포워드를 통과해야 한다(롱 로직이 좋다고 숏도 좋다는 보장 없음 — 특히
   암호화폐는 상승 추세가 하락보다 통계적으로 더 매끄러운 경향이 반복 보고됨).
3. **한 번에 하나씩 순차 승격.** 이미 합의된 순서(§배경 대화, 세션 요약 문서
   `session-summary-spot-to-perp-live-20260815.md` §6) 그대로:
   `macd_momentum` → `omnibus`(DOWN_TREND 레그) → `regime_trend` → `multi_factor` →
   `vix_rsi`/`fng_contrarian`. 근거: 앞쪽일수록 이미 연속·부호형 신호(TSMOM_NL)이거나
   "계산은 되는데 버려지는" 상태(STRUCTURAL_DOWN/PANIC_DROP)라 설계 리스크가 낮고,
   뒤쪽(vix_rsi/fng_contrarian)은 "역발산 알고의 반대 극단이 대칭 엣지를 갖는다"는
   가정 자체가 검증 대상이라 리스크가 크다.
4. **레버리지·사이징 정책 무변경.** Phase A 스코프 결정 유지 — 1x, 포지션 사이징은
   기존 `combined_position_weight`/변동성 타깃 그대로. 숏 전용 사이즈 배수를 새로
   만들지 않는다(다르게 할 근거가 생기면 별도 문서).
5. **채택 기준은 이 프로젝트가 이미 쓰는 기준선 그대로.** `p4-overfitting-audit`·
   `relative-strength-candidate-vanguard` 등에서 써온 DSR(n_trials=1) ≥ 0.95,
   부트스트랩 95% CI가 0을 배제, 전/후반 분할 부호 일관 — 새 기준을 발명하지 않는다
   (§4에서 상세).

## 2. 인프라 쪽 확인이 아직 필요한 것 (설계 단계에서 발견, 구현 시 처리)

- `tsmom_nl_position_multiplier()`(`algorithms.py:578`)가 음수 신호를 **의도적으로**
  0에 클립하는 주석이 있다: "아레나는 스팟 롱온리라 숏을 실행하지 않는다". perp 숏
  트랙에서는 이 클립을 걷어내고 `f(s)=s/(s²+1)`의 음수 쪽(이미 홀함수라 부호 대칭)을
  그대로 써야 한다 — product_type 분기 필요(spot/롱온리 perp는 기존 클립 유지, 숏
  허용 perp는 abs 사용).
- `_below_ma200()`/`_below_ema_trend()` 등은 "하회 여부" 자체를 반환하는 boolean이라
  **그대로 재사용 가능**(롱 필터는 `not _below_ma200(...)`로 쓰지만 숏 필터는
  `_below_ma200(...)`를 직접 요구하면 됨 — 반전이 아니라 동일 함수의 반대쪽 사용).
- `_funding_hot`/`_etf_outflow_heavy`/`_lsr_crowded`는 **방향 비대칭 필드**다(아래 §3
  각 알고에서 상술) — 단순 `not` 반전이 숏의 올바른 미러가 아니다. 새 임계값(예:
  "funding cold" = `funding_zscore <= -FUNDING_HOT_ZSCORE` 대칭, "ETF inflow heavy",
  "crowded short" = `long_short_ratio_zscore <= -LSR_CROWDED_ZSCORE`)이 필요하고,
  이 임계값들의 부호 대칭 가정 자체도 그리드가 아닌 백테스트로 1차 검증해야 한다.

## 3. 알고별 숏 진입 설계안

### 3.1 macd_momentum (1순위)

**현재 롱 로직** (`algorithms.py:596`, `TSMOM_NL_ENABLED=True` 기본): risk-off 레짐
veto → `s = tsmom_nl_signal(ind)`(T봉 누적수익률/(√T·σ̂)) → `s > TSMOM_NL_MIN_SIGNAL`이면
롱. 이미 연속·부호형 신호라 숏 설계가 가장 단순.

**숏 설계안**: `s < -TSMOM_NL_MIN_SIGNAL` → 숏(대칭 임계값 1차 가정 — 비대칭
가능성은 백테스트에서 확인). 사이징은 `f(s)=s/(s²+1)`의 절댓값(§2, 클립 제거).
레거시 MACD 히스토그램 경로(`TSMOM_NL_ENABLED=False`일 때 폴백)도 대칭 설계는
필요하지만 현재 라이브 기본이 아니므로 우선순위 낮음(문서화만, 구현은 TSMOM_NL 경로
우선).

**미해결 설계 질문**:
- **risk-off veto를 숏에도 유지할지**: 현재 "risk-off(stress/BearPanic)면 무조건
  보류"가 안전장치로 설계됐는데, 숏 관점에서는 risk-off가 오히려 숏이 가장 잘 먹히는
  국면일 수 있다(급락 지속). veto 유지안/제거안 둘 다 백테스트 변형으로 비교.
- **6개 품질필터(`_macd_momentum_secondary_votes`)의 방향 비대칭**: `funding_not_hot`
  (롱 과밀 아님) → 숏은 `funding_not_cold`(숏 과밀 아님, 새 임계값)가 맞는 미러.
  `above_ema200_4h`/`above_ma200_daily` → `_below_ema_trend_strict`/`_below_ma200`를
  직접 요구(그대로 재사용, §2). `lsr_not_crowded` → `lsr_not_crowded_short`(새
  임계값). `oi_not_diverged`는 부호 정의 자체를 재검토 필요(가격-OI 7일 방향 불일치가
  숏에서도 동일 의미인지 `_oi_diverged` 구현 재확인 필요).

### 3.2 omnibus — DOWN_TREND 레그 (2순위)

**현재 롱 로직** (`algorithms.py:850`): `_omnibus_regime()`이 5-state 분류
(UP_TREND/RANGE/DOWN_TREND/RISK_OFF/TRANSITION). DOWN_TREND는
`_downtrend_sub_state()`가 다시 3분기: **PANIC_DROP**(24h 수익률 절댓값이 ATR
스트레스 배수 초과 — 급락 진행 중), **OVERSOLD_REBOUND**(RSI/BB위치/MACD개선/낙폭
4지표 중 3개 이상 투표), **STRUCTURAL_DOWN**(위 둘 다 아님 — 추세적 하락 지속).
현재는 OVERSOLD_REBOUND만 롱 허용, STRUCTURAL_DOWN·PANIC_DROP은 계산되고 버려짐.

**숏 설계안**: 이미 존재하는 3분기 구조가 정확히 숏 설계와 맞아떨어진다 —
- **STRUCTURAL_DOWN → 숏 진입**(추세추종 숏, 반등 신호 3표 미만 = 하락 지속 중).
  UP_TREND 롱이 "눌림목"인 것과 대칭으로, funding/ETF/LSR 품질필터를 §3.1과 동일한
  방향 비대칭 처리로 미러링.
- **PANIC_DROP → 진입 없음 유지**(급락 한복판 숏 추격은 청산 캐스케이드 반전 리스크가
  커서 현재 risk-off류와 동일하게 안전장치로 제외 — OVERSOLD_REBOUND가 바로 이
  구간의 반전을 롱으로 포착하도록 설계돼 있는 것과 정합적).
- **OVERSOLD_REBOUND는 그대로 롱 전용 유지**(이미 반전 가설).

**부가 스코프(선택)**: RANGE 레짐의 `NEAR_HIGH` 서브상태(현재 `_range_sub_state()`가
계산은 하지만 롱 진입에 안 씀)도 숏 평균회귀 후보가 될 수 있음 — 이 문서 스코프
밖(별도 후보로 취급), 6개 알고 숏 1순환 완료 후 검토.

**미해결 설계 질문**: STRUCTURAL_DOWN 진입에 UP_TREND 롱과 동일하게
EMA역배열+MA200 하회 확인을 요구할지, 아니면 더 느슨하게(하락 지속의 정의 자체가
이미 `_downtrend_sub_state`에서 확인됨) 할지 — 백테스트 변형 비교 대상.

### 3.3 regime_trend (3순위)

**현재 롱 로직** (`algorithms.py:356`): 핵심 4조건(강세 레짐 + Donchian(20) 상단
돌파 + ADX≥20 + EMA 정배열·상승) 전부 필수, 부차 8개 품질필터
(`_regime_trend_secondary_votes`, `algorithms.py:339`) N-of-M 또는 전부.

**숏 설계안**: 핵심 4조건 거울 — 약세 레짐(`_is_bearish`, 신규 헬퍼 필요 — 현재
`_is_bullish`/`_is_risk_off`만 있고 "명확히 약세이되 risk-off는 아닌" 상태 판별
로직 확인 필요) + Donchian(20) **하단** 돌파(신저가) + ADX≥20(추세 강도, 방향
무관이라 그대로 재사용) + EMA **역배열**(`ema_fast < ema_slow and ema_fast_slope < 0`).

8개 부차조건 개별 방향성 확인 결과:
| 필터 | 롱 정의 | 숏 미러 |
|---|---|---|
| `rsi_below_long_max` | RSI 과열 전 | RSI 과매도 전(신규 상한 대칭, 예: RSI > 하한) |
| `funding_not_hot` | 롱 과밀 아님 | 숏 과밀 아님(신규 "funding cold" 임계값) |
| `etf_outflow_not_heavy` | 대량 유출 아님 | 대량 유입 아님(신규 "ETF inflow heavy" 임계값) |
| `above_ema200_4h` | `not _below_ema_trend_strict` | `_below_ema_trend_strict` 직접 요구(그대로 재사용) |
| `taker_confirms` | 테이커 매수 우위 ≥ 임계 | 테이커 **매도** 우위(신규 대칭 임계값 — `taker_ratio_4h` 하한) |
| `volume_confirms` | 돌파봉 거래량 확인 | **방향 무관, 그대로 재사용**(신저가 돌파도 동일 로직) |
| `lsr_not_crowded` | 롱 과밀 아님 | 숏 과밀 아님(신규 대칭 임계값) |
| `oi_not_diverged` | 가격↑·OI↓ 불일치 아님 | 가격↓·OI↑(공매도 증가 없이 하락) 불일치 아님(부호 재정의 필요) |

**미해결 설계 질문**: `taker_confirms`/`funding_not_hot`류의 "대칭 임계값"이 실제로
롱 임계값과 동일 크기여야 하는지(예: `FUNDING_HOT_ZSCORE`를 그대로 부호만 뒤집어
쓸지, 별도 캘리브레이션이 필요한지) — 1차는 대칭 가정으로 백테스트하고, 결과가
애매하면(DSR 통과 근처) 그리드가 아닌 단일 대안값(예: 분포 대칭성 확인 후 조정)
비교만 추가.

### 3.4 multi_factor (4순위)

**현재 롱 로직** (`algorithms.py:664`): 5팩터 투표(레짐/FNG<60/VIX calm/RSI<50/
funding_not_hot) 중 4+ 충족(또는 `MULTI_FACTOR_REGIME_REQUIRED` 모드에서는 레짐
필수+나머지 N-of-4), 5개 하드 veto(risk-off/ETF유출/LSR과밀/breadth붕괴/스테이블
코인수축).

**숏 설계안**: 5팩터 거울 — 약세 레짐(또는 risk-off 자체를 숏 방향성으로 재해석,
§3.1과 동일 열린 질문) / FNG > 40(과도한 공포 아님, "바닥 근접 반등 리스크" 회피) /
VIX 고조(calm 아님, elevated) / RSI > 50(과매도 전) / funding_not_cold(숏 과밀
아님). 하드 veto 5개도 각각 방향 재검토 필요:
- `risk_off` veto — §3.1과 동일 열린 질문.
- `etf_outflow_heavy` → 숏에는 **오히려 진입 근거**에 가까울 수 있음(기관 매도세 확인)
  — veto가 아니라 팩터로 편입할지 검토 대상.
- `lsr_crowded`(과밀 롱) → 숏에는 veto가 아니라 오히려 청산 리스크 신호로 볼 여지
  (crowded long = 숏 스퀴즈 소지) — 이 필터가 숏에서 veto/팩터 어느 쪽인지가 이
  알고 숏 설계의 핵심 불확실성.
- `breadth_collapsed`/`stablecoin_contracting` → 시장 전반 건전성 훼손 신호라
  방향 무관하게 "저유동성/불안정 국면이니 진입 보류" veto로 그대로 유지가 자연스러움
  (1차 가정, 백테스트로 확인).

이 알고는 5개 하드 veto의 방향 재해석 여지가 6개 알고 중 가장 크다 — 순서상
4번째로 둔 것도 이 불확실성 때문(§배경 합의 순서와 일치).

### 3.5 vix_rsi / fng_contrarian (5순위, 최후순)

**현재 롱 로직**: 둘 다 "공포/침체 국면에서 반등을 사는" 역발산(contrarian) 전략
— `fng_contrarian`은 FNG<30(+90일 낙폭·안정화 게이트), `vix_rsi`는 VIX calm(!)+
RSI<50 크로스(반전 확인). **주의**: `vix_rsi`는 이름과 달리 이미 "VIX가 낮을 때"
진입하는 전략이라 "VIX가 높을 때 공포 숏"의 거울이 아니다 — 두 알고 모두 본질은
"과매도 반등을 노리는 롱 전용 설계".

**숏 설계안이 구조적으로 다른 이유**: 다른 4개 알고(추세추종·복합팩터)는 "롱
조건의 반대는 숏 조건"이라는 대칭 가정이 자연스럽다. 하지만 역발산 전략은 **"탐욕
구간에서 판다"**가 숏의 자연스러운 거울인데, 이건 롱 로직의 필터 부호를 뒤집는
정도가 아니라 **거의 별개의 진입 가설**(FNG>70/RSI 과열 크로스 하향 등)이다. 즉:
- `fng_contrarian` 숏 = FNG > `FNG_SHORT_ABOVE`(신규 상수, 70 근방 1차 가정) +
  대칭 낙폭 게이트를 "90일 저점 대비 충분한 상승폭"으로 재정의 + `momentum_not_worsening`의
  거울("momentum_not_improving" — 상승 모멘텀이 아직 꺾이지 않았는데 진입하는
  칼받기의 반대 패턴, 즉 상승 가속이 멈췄는지 확인).
- `vix_rsi` 숏 = VIX **고조**(현재 calm 조건과 정반대 레짐) + RSI 과열 하향 크로스.
  현재 롱 로직의 "VIX calm"이라는 전제 자체가 숏에는 성립하지 않으므로, 사실상
  새 알고에 가까운 재설계.

**따라서 이 두 알고는 순서상 마지막이자, "롱 조건 반전"이 아니라 "탐욕/과열
극단에서의 대칭 반전 전략이 통계적으로 유효한가"라는 별도 가설로 검증해야 한다.**
통과 못 해도(§1원칙2) 다른 4개 알고 숏 승격에는 영향 없음.

## 4. 검증 방법론 (기존 프로젝트 관행 그대로 재사용)

`new-algo-candidates-wellspring-undertow-chorus-20260814.md`와
`relative-strength-candidate-vanguard-20260815.md`에서 쓴 방식을 그대로 따른다 —
새 기준을 발명하지 않는다.

1. **격리 실행**: `backtest.run_replay(frames, strategy_fns={algo_id: <숏 후보 함수>})`
   오버라이드로만 검증 — `ALGORITHMS` dict·live 배선(scheduler.py 등) 무변경. 통과한
   알고만 실제 함수를 교체.
2. **product_type=usdm_perp로 실행**: `run_replay()`의 비-spot 분기(방향 무관 상태머신,
   `perp_policy.py`가 라이브에서 미러링하는 바로 그 로직)를 그대로 태워 숏 신호가
   실제로 열림/보유/반전/청산되는 경로까지 검증(단순 "숏 신호가 몇 번 떴는지"가
   아니라 실제 체결·청산·펀딩정산까지 포함).
3. **파라미터**: 그리드 튜닝 아님 — 단일 사전 설계값(§3의 각 미러 조건)으로 1회
   실행. DSR은 `n_trials=1`(선택편향 없음)으로 계산.
4. **표본**: 3자산(BTC/ETH/SOL) 전부, `arena_ohlcv_bars` 전체 커버리지(macro 백필
   포함, `backtest_with_macro_backfill.build_macro_rows()` 재사용).
5. **강건성**: 부트스트랩 95% CI(가중수익, 3000회 리샘플) + 전/후반 분할 부호 확인.
6. **패리티 우선 확인**: 알고별 숏 후보를 넣기 전, 먼저 "숏 신호를 항상 None으로
   고정한 채 product_type만 spot→usdm_perp로 바꾼" 패리티 백테스트를 각 알고에
   재실행해 Phase A 문서의 결과(거래수·방향 완전 동일, 손익차는 펀딩비만)가 여전히
   유효한지 스팟체크(회귀 확인, 매 알고 작업 시작 전 1회).

**채택 기준(이 프로젝트 기존 채택선 그대로, `p4-overfitting-audit` 근거)**:
- DSR(n_trials=1) ≥ 0.95
- 부트스트랩 95% CI가 0을 배제(양의 하한)
- 전/후반 분할에서 부호 일관(반전 없음)
- 3자산 중 최소 몇 개가 통과해야 승격할지는 알고 도입 시 개별 판단(예: 3/3 요구
  vs 다수결) — 이 문서에서 선결정하지 않음, §3에서 언급한 자산×전략 조합 결과를
  보고 사용자와 합의.

**기각 시 처리**: `new-algo-candidates` 문서의 선례대로 — DSR 미달·CI가 0을 크게
포함·전후반 부호 반전이 나오면 **그리드 재탐색 없이 기각**(이 프로젝트가 반복 확인한
패턴: 실패한 단일사양은 튜닝으로 잘 안 살아남음). 기각된 알고는 해당 방향(숏)만
빠지고 기존 롱 로직·PERP_SHORT_ENABLED_TRACKS 비가입 상태(선물 트랙에서도 롱온리)로
유지.

## 5. 롤아웃 절차 (알고 1개 통과 시)

1. `algorithms.py`에 숏 조건 구현(§3 설계안 기준, 백테스트에서 확정된 버전).
2. 패리티 백테스트 재확인(§4-6, 회귀 없음 확인) + 신규 테스트 추가(`test_arena_perp_policy.py`
   패턴 참고 — 숏 오픈/반전/청산 케이스).
3. `PARAMS_VERSION` bump(신호 로직 변경이므로 — 기존 Phase A/A2는 bump 없었음, 이번엔
   실제 신호가 바뀌므로 필요).
4. `parameters.PERP_SHORT_ENABLED_TRACKS`에 해당 `(track_symbol, algo_id)` **1개만** 추가(한 번에 여러 개
   묶지 않음 — 승격 시 문제 발생해도 원인 알고 특정 쉽게).
5. 로컬 검증 후 배포, 실거래 확인(1~2 사이클 관찰: 숏 포지션이 실제로 열리는지, 방향
   라벨(`slack_notify.py`/대시보드)이 올바른지, 펀딩 부호가 방향에 맞게 반영되는지).
6. 다음 알고로 §3 순서대로 반복.

## 6. 이 문서에서 결정하지 않은 것 (다음 단계에서 사용자 승인 필요)

- §3.1/§3.4의 "risk-off veto를 숏에 유지 vs 제거" — 알고별 구현 직전에 백테스트
  변형 비교로 결정.
- §3.4의 `etf_outflow_heavy`/`lsr_crowded`를 숏에서 veto로 유지할지 팩터/신호로
  재해석할지.
- §3.3/§3.4 다수 필터의 "대칭 임계값" 실제 캘리브레이션(1차는 부호만 뒤집은 동일
  크기 임계값으로 가정, 필요 시 조정).
- 자산별(3/3 vs 다수결) 승격 기준.
- 순서(§1원칙3)는 세션 합의사항을 그대로 반영한 것 — 이견 있으면 우선순위 조정 가능.

## 7. 다음 세션 시작 가이드

**첫 작업 = `macd_momentum` 숏 백테스트 후보 구현 및 검증**(§3.1). 순서(§1원칙3)상
1순위, 설계 리스크가 가장 낮음(이미 연속·부호형 신호). 사용자 승인 없이 바로 착수
가능한 범위는 **격리 백테스트 스크립트 작성·실행까지**(§4) — `ALGORITHMS` dict나
`PERP_SHORT_ENABLED_TRACKS`를 건드리는 건 백테스트 결과를 사용자에게 보고하고 승인받은
뒤(§6 미결정 사항도 이 시점에 같이 확인).

### 7-1. 작업 순서 (체크리스트)

1. **코드 앵커 재확인**(다른 세션이 그 사이 바꿨을 수 있음):
   ```
   grep -n "TSMOM_NL_ENABLED\|TSMOM_NL_MIN_SIGNAL\|TSMOM_NL_WEIGHT_CAP" src/arena/parameters.py
   grep -n "def tsmom_nl_position_multiplier\|def _tsmom_nl_signal\|def macd_momentum" src/arena/algorithms.py
   ```
   §3.1이 참조하는 `algorithms.py:578`(`tsmom_nl_position_multiplier`)·`:596`
   (`macd_momentum`)이 여전히 맞는지 확인.
2. **패리티 스팟체크**(§4-6) — 숏 후보 넣기 전에 macd_momentum만 product_type
   spot→usdm_perp 패리티가 아직 깨지지 않았는지 재확인(Phase A 문서의 검증 결과가
   유효한지 회귀 확인).
3. **격리 백테스트 스크립트 작성** — `scripts/analysis/new_algo_candidates_backtest.py`
   패턴을 그대로 재사용(`backtest.run_replay(frames, strategy_fns={...})` 오버라이드,
   `ALGORITHMS`/live 배선 무변경). 신규 파일 제안: `scripts/analysis/macd_momentum_short_backtest.py`.
   - 숏 후보 함수: §3.1 설계안 그대로(`s < -TSMOM_NL_MIN_SIGNAL`, `f(s)` 절댓값 사이징).
   - **risk-off veto 유지/제거 두 변형 모두 실행**(§3.1 미해결 질문 — 백테스트로 먼저
     방향성 확인 후 사용자에게 보고, §6에서 결정하지 않은 항목).
   - 6개 품질필터 미러는 1차로 "대칭 임계값 가정"으로 구현(§2 참조 — `_below_ma200`류는
     그대로 재사용, `funding_not_hot`류는 새 "cold" 상수를 부호만 뒤집어 1차 시도).
   - `product_type="usdm_perp"`로 `run_replay()` 실행(비-spot 상태머신 경로 태우기).
4. **§4 방법론대로 채점**: 3자산(BTC/ETH/SOL), DSR(n_trials=1), 부트스트랩95%CI(3000회),
   전/후반 분할. `backtest_with_macro_backfill.build_macro_rows()` 재사용.
5. **결과를 사용자에게 보고**(구현/배포로 넘어가기 전 필수 체크포인트):
   - DSR·CI·전후반 결과표.
   - risk-off veto 변형 중 어느 쪽이 나은지.
   - §6 미결정 사항 중 이 알고에 해당하는 것(리스크오프 veto) 확정 요청.
6. **통과 시**(§5 롤아웃 절차 그대로): `algorithms.py`에 실제 반영 → 신규 테스트
   (`test_arena_perp_policy.py` 패턴 참고, 숏 오픈/반전/청산 케이스) →
   `PARAMS_VERSION` bump → `PERP_SHORT_ENABLED_TRACKS`에 해당 트랙의 `macd_momentum` 1개만 추가 →
   로컬 검증 → 배포 → 1~2 사이클 라이브 관찰(숏 포지션 오픈 여부, 방향 라벨, 펀딩
   부호).
7. **기각 시**: §4 "기각 시 처리" 그대로(그리드 재탐색 없이 기각, 롱 로직 무변경 유지) →
   §1원칙3 순서대로 다음 알고(`omnibus` DOWN_TREND 레그, §3.2)로 이동.

### 7-2. 참고할 기존 코드/문서 (그대로 재사용, 새로 안 만듦)

- 백테스트 스크립트 템플릿: `scripts/analysis/new_algo_candidates_backtest.py`,
  `scripts/analysis/tsmom_nl_walk_forward.py`(TSMOM_NL 자체 검증 시 이미 쓴 워크포워드
  하니스 — 숏 변형에도 구조 재사용 가능).
- DSR·부트스트랩 계산 로직: 위 두 스크립트가 이미 구현해 둔 유틸 재사용(중복 구현 금지).
- 패리티 백테스트 방법: Phase A 문서 §검증("스크래치, product_type spot↔usdm_perp
  대조, 4h 366봉") 그대로.
- 테스트 패턴: `tests/test_arena_perp_policy.py`(숏 오픈/반전/청산 단위 테스트),
  `tests/test_arena_scheduler_perp.py`(`PERP_SHORT_ENABLED_TRACKS` 배선 테스트).

### 7-3. 로컬 검증 커맨드

```bash
.venv/bin/python -m pytest tests/test_arena_perp_policy.py tests/test_arena_scheduler_perp.py tests/test_arena_positions_perp_funding.py -q
.venv/bin/ruff check src/arena scripts/analysis
```

(`pyproject.toml`이 `pythonpath = ["src", "scripts"]`를 이미 설정하므로 `PYTHONPATH=src`
수동 지정 불필요 — 로컬 개발 환경에 `.venv`가 없다면 프로젝트 표준 셋업(`requirements-dev.txt`)
먼저 확인.)

## 8. macd_momentum 숏 후보 1차 검증 결과 (2026-08-15, ❌기각)

§7 체크리스트대로 `scripts/analysis/macd_momentum_short_backtest.py` 신규 작성 —
`s < -TSMOM_NL_MIN_SIGNAL` 숏 후보(§3.1), 사이징은 `f(s)` 절댓값(스크립트 프로세스
내 `algorithms.tsmom_nl_position_multiplier` 몽키패치로만 구현, **소스 무변경**).
`product_type="usdm_perp"`, macro 백필(446일) × 3자산 × risk-off veto 유지/제거
2변형 = 6셀. 패리티 회귀(`test_arena_perp_policy.py` 등 4개 스위트) 선통과 확인.

**결과 — 18개 판정기준 전부 미달**(DSR≥0.95 / CI하한>0 / 전후반 부호일관):
DSR 최댓값 0.586(SOL veto제거), 6개 조합 전부 부트스트랩95%CI가 0 포함(하한 전부
음수), BTC veto유지는 전후반 둘 다 손실. 방향성만 보면 veto제거가 veto유지보다
3자산 전부 일관되게 우세(sum_w%·PF 개선)했으나 기준선 근처에도 못 미침 — 요약표는
스크립트 실행 로그 참조(재현 가능, 그리드 아닌 단일사양이라 결과 고정).

**❌ 기각, 그리드 재탐색 없음**(§4 기각 처리 원칙 그대로) — macd_momentum은 선물
트랙에서도 롱온리 유지, `PERP_SHORT_ENABLED_TRACKS` 미가입. 사용자 확인 완료.
**다음: `omnibus` DOWN_TREND 레그(§3.2)로 동일 방법론 반복.**

## 9. omnibus STRUCTURAL_DOWN 숏 후보 검증 결과 (2026-08-15, ❌기각)

`scripts/analysis/omnibus_short_backtest.py`로 Supabase 쓰기 없이 Binance 공개 4H 봉과
기존 macro 백필을 사용해 격리 검증했다. 사전 설계한 두 변형만 비교했다.

- `structural`: DOWN_TREND이면서 `STRUCTURAL_DOWN`이면 숏.
- `confirmed`: 위 조건에 EMA 역배열·하락 기울기·EMA200/MA200 하회를 추가.

검증 구간은 2025-04-16~2026-07-11, 자산별 2,712 프레임이다. 비용 반영 perp
상태머신으로 실행했으며 DSR은 두 사전 변형을 고려해 `n_trials=2`로 계산했다.

| 변형 | 자산 | n | 가중수익 | PF | 부트스트랩 95% CI | 전반/후반 | DSR |
|---|---|---:|---:|---:|---:|---:|---:|
| structural | BTC | 161 | -19.29% | 0.63 | [-35.71%, -1.90%] | -5.46% / -13.82% | 0.004 |
| confirmed | BTC | 79 | -9.32% | 0.61 | [-19.58%, +1.46%] | -5.59% / -3.74% | 0.018 |
| structural | ETH | 170 | -28.00% | 0.54 | [-47.48%, -8.37%] | -22.72% / -5.28% | 0.000 |
| confirmed | ETH | 70 | -13.41% | 0.49 | [-24.54%, -2.34%] | -5.11% / -8.30% | 0.003 |
| structural | SOL | 170 | -11.78% | 0.74 | [-32.70%, +9.03%] | -15.34% / +3.55% | 0.022 |
| confirmed | SOL | 71 | -1.27% | 0.96 | [-11.30%, +8.68%] | -2.36% / +1.09% | 0.258 |

6개 셀 모두 가중수익이 음수이고 DSR 0.95 및 CI 양의 하한 기준을 충족하지 못했다.
SOL은 전·후반 부호까지 반전됐다. 따라서 `omnibus` 숏도 **기각, 그리드 재탐색 없음**이며
`PERP_SHORT_ENABLED_TRACKS`는 빈 집합을 유지한다.

## 10. regime_trend 숏 후보 검증 결과 (2026-08-15, ❌기각)

§3.3 설계안 그대로 `scripts/analysis/regime_trend_short_backtest.py` 신규 작성 —
핵심 4조건(약세 레짐·Donchian(20) 하단 돌파·ADX≥20·EMA 역배열)은 롱의 직접 거울,
부차 8조건은 §3.3 표의 부호 대칭 임계값을 1차 가정으로 구현했다(`oi_not_diverged`만
부호 재정의를 보류하고 롱과 동일 불리언 재사용 — 스크립트 docstring에 명시).
약세 레짐 판정은 별도 상태를 신설하지 않고 기존 `_is_risk_off`(bear_trend/stress/
BearPanic)를 그대로 재사용했다. STRICT(8개 전부 충족)와 RELAXED(라이브 롱과 동일한
`REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES=4/8`) 두 사전 변형을 비교했다(그리드 아님).
`product_type="usdm_perp"`, macro 백필(446일, 2025-04-16~2026-07-10) × 3자산 × 2변형
= 6셀. 패리티 회귀(`test_arena_perp_policy.py`·`test_arena_scheduler_perp.py`·
`test_arena_spot_policy.py`) 선통과 확인.

| 변형 | 자산 | n | sum_w% | PF | 부트스트랩 95% CI | 전반/후반 | DSR |
|---|---|---:|---:|---:|---:|---:|---:|
| strict_8of8 | BTC | 8 | -1.18% | 0.56 | [-4.57%, +3.06%] | -1.44% / +0.26% | 0.164 |
| relaxed_4of8 | BTC | 45 | -2.01% | 1.01 | [-12.53%, +9.52%] | -3.10% / +1.09% | 0.312 |
| strict_8of8 | ETH | 5 | -0.05% | 0.71 | [-4.77%, +5.25%] | (n<6) | 0.218 |
| relaxed_4of8 | ETH | 49 | -0.16% | 0.95 | [-10.54%, +10.34%] | -0.32% / +0.16% | 0.259 |
| strict_8of8 | SOL | 10 | +0.14% | 0.98 | [-5.15%, +6.47%] | +0.37% / -0.23% | 0.293 |
| relaxed_4of8 | SOL | 54 | -5.78% | 0.76 | [-16.74%, +6.74%] | -2.86% / -2.92% | 0.112 |

6개 셀 전부 DSR(n_trials=2) 0.95 기준에 크게 미달(최댓값 0.312, RELAXED/BTC)하고,
부트스트랩 95% CI가 전부 0을 포함한다(양의 하한 없음). PF도 6셀 중 5셀이 1.0 미만
(SOL strict만 0.98로 근접했으나 CI 폭이 [-5.15%, +6.47%]로 방향성이 없다). 신저가
돌파가 relaxed 모드에서 거래수는 늘렸지만(BTC 8→45, SOL 10→54) 손익은 오히려 악화
(BTC -1.18→-2.01%, SOL +0.14→-5.78%) — macd_momentum·omnibus에서 이미 확인된
"완화가 표본만 늘리고 엣지를 만들지 않는다" 패턴이 반복됐다.

**❌ 기각, 그리드 재탐색 없음**(§4 기각 처리 원칙 그대로) — `regime_trend`는 선물
트랙에서도 롱온리 유지, `PERP_SHORT_ENABLED_TRACKS` 미가입.

## 11. multi_factor 숏 후보 검증 결과 (2026-08-15, ❌기각)

§3.4 미해결 질문(하드 veto 방향 재해석)을 그리드가 아닌 두 사전 설계값으로
비교했다(`scripts/analysis/multi_factor_short_backtest.py`).

- **variant A(direction_soft)**: WI-1 이전 원래 설계로 레짐을 5팩터 중 하나의
  소프트 투표로만 쓰고, risk-off·ETF유출·LSR과밀 veto는 롱과 동일하게 유지. 5팩터
  거울(약세 레짐/FNG>40/VIX 고조/RSI>45/펀딩 not-cold) 합산 ≥4면 숏.
- **variant B(direction_hard_reinterpreted)**: 약세 레짐을 hard 요구조건으로 승격하고
  (그러면 risk-off veto와 모순이라 제거), ETF유출·LSR과밀은 veto에서 팩터로 편입
  (§3.4가 제안한 재해석 그대로). breadth·stablecoin veto는 방향 무관이라 유지.

| 변형 | 자산 | n | sum_w% | PF | CI | 전반/후반 | DSR |
|---|---|---:|---:|---:|---|---|---:|
| direction_soft | BTC | 12 | +2.12% | 1.37 | [-6.90%,+12.11%] | -1.01%/+3.12% | 0.443 |
| direction_hard_reint | BTC | 72 | -7.33% | 0.72 | [-23.66%,+9.94%] | -2.06%/-5.27% | 0.066 |
| direction_soft | ETH | 10 | +1.11% | 1.20 | [-4.90%,+7.18%] | -1.01%/+2.12% | 0.377 |
| direction_hard_reint | ETH | 92 | -24.59% | 0.37 | [-40.59%,-7.16%] | -19.19%/-5.41% | 0.000 |
| direction_soft | SOL | 11 | +0.94% | 1.19 | [-5.28%,+6.97%] | -1.94%/+2.88% | 0.386 |
| direction_hard_reint | SOL | 73 | -11.10% | 0.61 | [-26.16%,+5.94%] | -3.60%/-7.51% | 0.041 |

`direction_soft`는 3자산 전부 방향성이 양(PF 1.19~1.37, DSR 최댓값 0.443)이지만
기준 0.95에 크게 못 미치고 CI가 전부 0을 포함한다. `direction_hard_reinterpreted`는
명백히 악화(ETH는 CI가 전부 음수로 "확실히 나쁨"에 가까움, DSR 0.000) — 방향
재해석(ETF유출·LSR과밀을 veto에서 팩터로)이 이 알고에서는 개선이 아니라는 신호.

**❌ 기각, 그리드 재탐색 없음** — `multi_factor`는 선물 트랙에서도 롱온리 유지,
`PERP_SHORT_ENABLED_TRACKS` 미가입.

## 12. vix_rsi 숏 후보 검증 결과 (2026-08-15, ❌기각 — 가장 근접한 미달)

§3.5가 명시한 대로 롱 조건의 단순 반전이 아니라 별개 가설(VIX 고조 + RSI 과열)로
설계했다(`scripts/analysis/vix_rsi_short_backtest.py`). risk-off veto 유지/제거
2변형, `momentum_not_improving`(칼받기 방지 필터의 거울) 공통 적용.

| 변형 | 자산 | n | sum_w% | PF | CI | 전반/후반 | DSR |
|---|---|---:|---:|---:|---|---|---:|
| veto유지 | BTC | 48 | -2.65% | 0.93 | [-14.90%,+10.18%] | -6.61%/+3.97% | 0.238 |
| veto제거 | BTC | 51 | -7.64% | 0.75 | [-20.10%,+5.72%] | -10.13%/+2.49% | 0.094 |
| veto유지 | ETH | 48 | +11.09% | 2.16 | [-0.37%,+22.07%] | +4.56%/+6.52% | **0.934** |
| veto제거 | ETH | 46 | +9.65% | 1.92 | [-1.00%,+21.09%] | +2.56%/+7.09% | 0.886 |
| veto유지 | SOL | 48 | +5.37% | 1.51 | [-4.96%,+15.58%] | -0.08%/+5.45% | 0.724 |
| veto제거 | SOL | 52 | -1.10% | 0.95 | [-14.03%,+11.37%] | -0.75%/-0.34% | 0.253 |

ETH veto유지가 지금까지 검증한 6개 알고 전체 중 채택선에 가장 근접했다(DSR
0.934 vs 기준 0.95, CI 하한 -0.37% vs 기준 양수, PF 2.16, 전/후반 둘 다 양수로
방향 일관). 그러나 §4 채택 기준(DSR≥0.95 **그리고** CI 하한>0)을 문자 그대로 적용하면
근소하게 미달이고, BTC는 두 변형 모두 명확히 음수라 3자산 동시 통과가 아니다.

**❌ 기각(자산별 전원 통과 기준 미달)** — 단, 지금까지 5개 알고 중 유일하게 "명확한
반증"이 아니라 "근접 미달"인 사례라 §4 하단의 "3자산 중 최소 몇 개 통과해야 승격할지는
개별 판단" 여지가 남아있다. 그리드 재탐색은 하지 않았고(§4 원칙 준수), ETH 단일자산
승격 여부는 사용자 판단으로 남긴다. `PERP_SHORT_ENABLED_TRACKS` 미가입 상태 유지.

## 13. fng_contrarian 숏 후보 검증 결과 (2026-08-15, ❌기각) + 코드 결함 발견

§3.5가 명시한 별개 가설(FNG>70 탐욕 + `momentum_not_improving`)로 설계했다
(`scripts/analysis/fng_contrarian_short_backtest.py`). 낙폭 거울 게이트는 대칭
데이터 필드가 없어 no-op 처리(파일 docstring에 명시, 향후 재검증 필요 항목으로 남김).

**구현 중 실제 코드 결함 발견**: algo_id="fng_contrarian"를 재사용해 첫 실행했을 때
3자산×2변형 전부 승률 0%·`exit_reason` 전량 `target_exit`·평균 보유 4h(=1봉)라는
병리적 결과가 나왔다. 원인은 `backtest.py:783-810`의 P-A 이익포착 로직 —
`fng_target = open_price * (1.0 + fng_target_pct)`를 항상 `bar.high`와 비교하는데,
이 코드는 `algo_id=="fng_contrarian"`으로만 게이팅되고 `position.direction`을 보지
않는다. 롱에는 맞는 로직(목표가는 진입가 위, 최고가와 비교)이지만 숏에 그대로
적용하면 진입가보다 **위**의 가격을 "목표가"로 잡고 그 지점을 향해 거의 항상
바로 도달해버려 손실이 확정된 상태로 매 거래가 종료된다. `FNG_CONTRARIAN_SCALE_IN_ENABLED`
(가격 하락 시 물타기)도 같은 방식으로 algo_id만 게이팅돼 있고, 애초에 숏에 대응하는
물타기 미러가 이 코드베이스에 없다. 두 메커니즘 모두 이 스크립트의 §3.5 설계에는
포함돼 있지 않으므로(내가 의도한 로직이 아님), 재실행 전 두 플래그를
프로세스 로컬로 비활성화했다(`parameters.FNG_TARGET_EXIT_ENABLED = False`,
`parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED = False` — 소스 무변경, macd 스크립트의
몽키패치 관행과 동일). **현재 라이브·기존 테스트에는 영향 없음** — `fng_contrarian`은
지금도 항상 롱만 반환하므로(algorithms.py) 이 경로에 숏 방향 포지션이 진입할 방법이
없어 잠들어 있는 결함이다. 다만 향후 `PERP_SHORT_ENABLED_TRACKS`에 fng_contrarian이
승격되는 날이 오면 `backtest.py`의 두 메커니즘에 `position.direction` 분기를
추가해야 한다 — 이 세션에서는 수정하지 않음(현재 도달 불가능한 코드 경로,
연구용 스크립트에서 몽키패치로 우회하는 것으로 충분).

수정 후 재실행 결과(정상):

| 변형 | 자산 | n | sum_w% | PF | CI | 전반/후반 | DSR |
|---|---|---:|---:|---:|---|---|---:|
| veto유지 | BTC | 23 | -2.24% | 0.82 | [-11.85%,+8.02%] | -2.89%/+0.65% | 0.183 |
| veto제거 | BTC | 24 | -1.21% | 0.92 | [-11.60%,+9.54%] | -1.39%/+0.18% | 0.248 |
| veto유지 | ETH | 24 | -4.83% | 0.65 | [-16.18%,+7.34%] | -1.50%/-3.34% | 0.103 |
| veto제거 | ETH | 25 | -6.14% | 0.58 | [-17.62%,+5.78%] | -0.88%/-5.26% | 0.069 |
| veto유지 | SOL | 21 | +6.39% | 2.07 | [-4.75%,+18.66%] | +4.38%/+2.01% | 0.760 |
| veto제거 | SOL | 24 | +4.90% | 1.65 | [-6.34%,+16.70%] | +3.22%/+1.68% | 0.642 |

SOL이 가장 좋지만(DSR 0.760, PF 2.07) 기준 0.95엔 못 미치고 BTC/ETH는 음수 —
6셀 전부 채택 기준 미달.

**❌ 기각, 그리드 재탐색 없음** — `fng_contrarian`은 선물 트랙에서도 롱온리 유지,
`PERP_SHORT_ENABLED_TRACKS` 미가입.

## 14. Phase B 1순환 종합 (2026-08-15)

`macd_momentum`(§8)·`omnibus`(§9)·`regime_trend`(§10)·`multi_factor`(§11)·
`vix_rsi`(§12)·`fng_contrarian`(§13) — §1원칙3 순서대로 6개 알고 전부 검증
완료했다. **6개 알고 전부 §4 채택 기준(DSR≥0.95, CI 하한>0, 전/후반 부호일관)을
문자 그대로 충족하지 못해 `PERP_SHORT_ENABLED_TRACKS`는 여전히 빈 집합이다.**

- 명확히 기각(음수 방향 또는 DSR<0.5 수준): `macd_momentum`, `omnibus`, `regime_trend`.
- 방향은 양이나 유의성 부족(DSR 0.3~0.5대): `multi_factor`(direction_soft).
- 근접 미달(가장 눈여겨볼 사례): `vix_rsi` ETH veto유지(DSR 0.934, CI 하한 -0.37%).
- 자산별로 갈림(SOL만 양호): `fng_contrarian`(SOL DSR 0.760, BTC/ETH 음수).

**1순환 결론**: 이 6개 알고를 롱 조건의 거울반전(또는 §3.4/§3.5가 제안한 재해석)으로
그대로 숏에 쓰는 접근은 이 데이터 구간(2025-04~2026-07, 446일)에서 통계적으로
신뢰할 만한 엣지를 만들지 못했다. `vix_rsi`/ETH만 예외적으로 근접했으나 자산 단일
통과이고 기준선에 살짝 못 미쳐, 이 문서의 원칙(§4 "3자산 중 최소 몇 개 통과해야
승격할지는 개별 판단")에 따라 최종 판단은 사용자에게 남긴다.

**다음 선택지(우선순위 아님, 병렬 옵션)**:
1. 6개 전부 기각을 최종 결론으로 받아들이고 선물 트랙을 계속 롱온리로 운영한다.
2. `vix_rsi` ETH만 표본이 더 쌓일 때까지 관찰(그리드 재탐색 없이 대기)한 뒤 재평가한다.
3. §13에서 발견한 `backtest.py`의 fng 전용 메커니즘 direction 미분기 결함을
   (현재 도달 불가능하더라도) 정합성 차원에서 수정할지 별도로 결정한다.

## 15. Phase B 2순환 §3-1 — GJR-GARCH 비대칭 계수 진단 (2026-08-15, 진단 완료·결론 애매)

[문헌 조사](short-entry-asymmetry-literature-review-20260815.md) §3-1이 제안한 사전
진단. `scripts/analysis/gjr_garch_leverage_diagnosis.py`(신규) — `arena_ohlcv_bars`
4H 전체 커버리지(2023-05-01~2026-08-15, BTC 6649봉·ETH/SOL 6664봉)를 Supabase에서
직접 페이지네이션 로드해 일간 리샘플 로그수익률(주 사양, n≈1109~1111)과 4H 로그수익률
(교차확인용, 참고)에 각각 GJR-GARCH(1,1)(`arch` 패키지, Student-t 오차, `o=1`)을
그리드 없이 단일 사양으로 1회 적합했다.

```
symbol     freq        n     gamma        p   sig 방향
BTCUSDT    daily    1109   +0.0472   0.1652     N 유의하지 않음
BTCUSDT    4h       6648   +0.0710   0.0596     N 유의하지 않음(경계 근접, 정방향 쪽)
ETHUSDT    daily    1111   +0.0364   0.8943     N 유의하지 않음
ETHUSDT    4h       6663   -0.0071   0.9072     N 유의하지 않음(사실상 0)
SOLUSDT    daily    1111   +0.0369   0.2814     N 유의하지 않음
SOLUSDT    4h       6663   -0.0018   0.8443     N 유의하지 않음(사실상 0)
```

전 모델 `converged=True`. persistence(α+β+γ/2)는 0.97~1.00으로 세 자산 모두 변동성
군집성 자체는 강하게 확인되나(GARCH 구조 자체는 데이터에 잘 맞음), 비대칭
계수(γ)는 6개 테스트(3자산×2빈도) **전부 5% 유의수준 미달**이다.

**해석 — 문서의 이분법(§3-1)에 정확히 들어맞지 않는 결과**:
- 역방향 레버리지 효과(γ<0 유의)는 **어디서도 나타나지 않았다** — ETH/SOL 4H에서
  점추정치가 음수이긴 하나 p=0.84~0.91로 잡음과 구분 불가.
- 정방향(주식시장형, γ>0 유의)도 **확인되지 않았다** — BTC 4H가 p=0.06으로 가장
  근접했지만 5% 기준 미달, 나머지는 전부 p>0.16.
- 점추정치 방향은 6개 중 4개(BTC daily/4h, ETH daily, SOL daily)가 양(+)으로
  약하게 정방향 쪽에 쏠려 있으나, 어느 것도 통계적으로 유의하지 않아 "확인됐다"고
  말할 수 없다.

**종합**: 이 프로젝트의 실제 15개월+ 표본에서는 문헌이 보고하는 "크립토 역방향
레버리지 효과"도, 일반적인 정방향 레버리지 효과도 **둘 다 통계적으로 뒷받침되지
않는다** — 순수 가격 변동성 비대칭이라는 축 자체가 이 자산·이 구간에서는 뚜렷한
신호가 아니다(null 결과). 이는 §1-2(A가설, 크립토 역방향 효과)를 "숏이 왜 안
통하는지"의 근거로 쓸 근거가 약해졌다는 뜻이지, §1-1(C가설, 모멘텀 크래시)을
반박하는 것은 아니다 — 모멘텀 크래시는 가격 변동성의 부호 비대칭이 아니라
"과거 루저의 베타가 급등락 시 옵션처럼 행동"하는 다른 메커니즘이라 이 진단이
직접 검정하는 대상이 아니다.

문서 지시(§3-1)는 "역방향 확인 시 사용자 확인 후 §3-2", "정방향 확인 시 바로
§3-2"의 이분법이었으나, 실제 결과는 둘 다 아닌 **null**이라 어느 분기에도 정확히
해당하지 않는다 — §3-2(macd_momentum 모멘텀 vol 사이징) 착수 여부는 사용자에게
확인한다(진단 자체는 "레버리지 효과 축은 약한 신호"라는 근거이지 §3-2를 막는
근거도, 강력히 지지하는 근거도 아니다).

사용자 확인 결과: §3-2 진행.

## 16. Phase B 2순환 §3-2 — macd_momentum 숏 모멘텀 고유 변동성 사이징 검증 (2026-08-15, ❌기각)

[문헌 조사](short-entry-asymmetry-literature-review-20260815.md) §3-2가 제안한
Barroso & Santa-Clara(2015) 처방 — §8의 risk-off veto 축은 그대로 두되(§8 결과:
veto제거가 3자산 전부 일관 우세, 그 변형으로 고정), **모멘텀 신호 s 자체의 롤링
변동성**에 기반한 사이징 축만 새로 추가했다(D017 "같은 사양 재시도 금지"에
해당하지 않는 새 가설).

`scripts/analysis/macd_momentum_short_vol_sizing_backtest.py`(신규) —
σ_momentum,t = s의 최근 30봉(문헌 제시 범위 20~60봉의 중앙값, 그리드 아님) 롤링
표준편차, target_t = σ_momentum의 확장평균(1봉 시차, look-ahead 방지), scale_t =
clamp(target_t/σ_momentum,t, 0.2, 1.0)(모멘텀 신호가 평소보다 불안정할 때만 사이즈
축소, 상한 1.0이라 증폭은 없음). 최종 사이징 = §8의 abs(f(s)) × scale_t. patch는
`algorithms.tsmom_nl_position_multiplier` 런타임 몽키패치, frame.indicators에
`mom_vol_scale` 사전 주입(ReplayFrame은 frozen이나 indicators dict 자체는 가변,
attribute 재할당 아니라 frozen 제약과 무관 — 이 프로세스 로컬 사본에만 영향).
사이즈 축소가 실제로 걸린 봉 비율: BTC 34%·ETH 27%·SOL 33%(scale<1.0 적용 봉수/전체).

**결과 — 3자산×2변형(baseline/vol_scaled) 전부 채택 기준 미달**:

```
label                                  symbol    n  win%  sum_w%   PF  CI_lo%  CI_hi%  전반%  후반%   DSR
noveto/baseline(사이징미적용)          BTCUSDT  97  30.9   +4.01 0.97   -6.29  +15.74  -0.16  +4.17 0.459
noveto/vol_scaled(사이징적용)          BTCUSDT  97  30.9   +3.88 0.97   -5.93  +14.67  +0.14  +3.75 0.459
noveto/baseline(사이징미적용)          ETHUSDT 112  35.7   +6.16 0.96   -7.00  +21.39  -0.80  +6.96 0.452
noveto/vol_scaled(사이징적용)          ETHUSDT 112  35.7   +6.31 0.96   -6.40  +21.39  -1.17  +7.48 0.452
noveto/baseline(사이징미적용)          SOLUSDT 110  37.3   +3.77 1.02   -6.84  +15.73  +1.45  +2.32 0.527
noveto/vol_scaled(사이징적용)          SOLUSDT 110  37.3   +3.66 1.02   -6.63  +15.10  +1.07  +2.59 0.527
```

- **DSR은 사이징 적용 여부와 무관하게 baseline과 완전히 동일**(0.459/0.452/0.527) —
  DSR은 거래별 미가중 수익률(`ret_pct`)로 계산되는데, 포지션 사이징은 진입/청산
  시점(신호·트레일링스탑·시간손절)을 바꾸지 않고 비중만 조절하므로 거래 자체의
  분포는 불변이다. 이는 버그가 아니라 "사이징으로 진입 품질 자체를 못 바꾼다"는
  당연한 결과이지만, 동시에 **DSR 채택 기준(≥0.95)을 사이징으로는 원리적으로
  넘을 수 없다**는 뜻이기도 하다(3자산 전부 0.45~0.53, 기준의 절반 수준).
- 3자산 전부 부트스트랩95%CI 하한이 여전히 음수(-5.93~-7.00%) — 사이징으로 소폭
  개선(예: BTC -6.29→-5.93)됐지만 0 배제에는 한참 못 미친다.
- 전/후반 분할도 BTC·ETH는 사이징 적용 후에도 부호 불일치가 남거나(BTC baseline
  -0.16/+4.17 → vol_scaled +0.14/+3.75, 여전히 근소해 신뢰 못할 수준) ETH는 두
  변형 다 전반 음수·후반 양수로 일관 반전.
- sum_w%(가중합)는 세 자산 모두 사이징 적용 전후 거의 무변화(±0.1~0.2%p) — scale<1.0이
  걸린 봉 비율(27~34%)에 비해 실질적인 손익 개선 효과가 미미하다.

**해석**: §3-1(GJR-GARCH)이 이미 "가격 변동성 비대칭" 자체가 이 표본에서 약한
신호였다고 진단했는데, §3-2(모멘텀 신호 고유 변동성 사이징)도 독립적으로 같은
결론에 도달했다 — 사이징 축을 아무리 정교화해도 **진입 신호 자체의 통계적
유의성 부족**(DSR이 진입 시점 분포에 종속돼 사이징으로 개선 불가)이라는 근본
한계를 못 넘는다.

**❌ 기각, 그리드 재탐색 없음**(§4 기각 처리 원칙·문헌 조사 §3-2 "통과 못 하면"
조건 그대로) — MOM_VOL_LOOKBACK_BARS 대안값(20/40/60 등) 추가 탐색은 하지 않는다.
`PERP_SHORT_ENABLED_TRACKS` 미가입 유지, macd_momentum 숏은 여전히 비활성.

## 17. Phase B 2순환 종합 및 권고 (2026-08-15)

거울반전(§8~§13, 1순환) → 문헌 기반 재해석 가설 A/C(§15 GJR-GARCH 진단, null) →
모멘텀크래시 처방 사이징(§16, 기각) 순서로 시도했다. **세 갈래 전부 실패** —
문헌 조사(§3) 문서가 미리 표시해 둔 "통과 못 하면 그리드 재탐색 없이 종결, 이
경우 '거울반전·재해석·모멘텀크래시 처방까지 전부 실패'가 최종 결론"에 정확히
해당한다.

**권고**: Phase B는 여기서 종결하고 선물 트랙은 무기한 롱온리로 확정하는 것을
권고한다. 근거:
1. 6개 알고 거울반전(1순환) 전부 기각 + macd_momentum에 문헌이 제시하는 두 가지
   개선 축(레버리지효과 진단, 모멘텀크래시 사이징)을 추가로 시도했으나 둘 다
   근본적 개선을 만들지 못함 — 진입 신호 자체가 무엣지라는 게 반복 확인됨.
2. DSR이 사이징에 불변이라는 §16의 발견은 구조적이다 — 앞으로 다른 알고에
   사이징류 개선을 시도해도 동일한 상한(진입 신호의 원래 DSR)에 막힐 가능성이
   높다.
3. `vix_rsi`(ETH, DSR 0.934)만 유일하게 근접 미달 상태로 남아 있고, 이건 §14가
   이미 "표본 부족 대기"로 분류한 별개 트랙 — Phase B 종결과 무관하게 그대로
   관찰만 지속한다(§3-3, 이번 세션에서 미변경).
4. 리소스는 CLAUDE.md 로드맵의 다른 항목(P5 청산데이터·P6 숏/스테이블 슬리브
   등 사용자 결정 대기 항목)으로 재배치하는 게 합리적.

**최종 판단은 사용자 확인 필요** — 이 권고를 받아들이면 `decision-log.md` D017과
`next-session-handoff.md`를 "Phase B 종결" 상태로 갱신한다(아래 실행 완료).

## 18. 3자산 풀링 DSR 재검증 (2026-08-16, ❌기각 — 마지막 미시도 각도)

사용자가 "나머지 5개 알고도 숏 적용하고 싶다"고 재요청 — §1~17이 이미 자산별
개별 DSR로 6개 알고를 두 라운드 검증했지만, **자산을 풀링한 적은 없었다**는 갭을
발견했다. 방향 일관성이 3자산 전부 양(+)이고 DSR도 밀집된(0.38~0.44) 유일한
후보인 `multi_factor`의 `direction_soft`(§11)에 대해서만 풀링 테스트를 실행했다
(`scripts/analysis/multi_factor_short_pooled.py`, 신규, 로직 무변경·재실행만).

**결과**: 풀링 DSR 0.688(개별 최댓값 0.443 대비 개선)이나 여전히 기준 0.95 미달,
부트스트랩95%CI [-8.56%, +17.57%]도 여전히 0 포함. **결정적으로 풀링된 33건 중
97%(32건)가 다른 자산 거래와 보유기간이 겹친다** — BTC/ETH/SOL이 거의 항상
동시에 진입·청산된다는 뜻으로, "33개 독립표본"이 아니라 매크로 조건(약세
레짐+FNG>40+VIX고조 등) 하나가 3자산에 동시발화하는 **사실상 단일 신호**임이
확인됐다. 이게 개별 DSR이 세 자산에서 서로 비슷했던 이유이자, 풀링이 통계적
힘을 크게 못 준 이유다(유효 독립표본은 33이 아니라 ~11에 더 가까움).

**❌ 기각, 그리드 재탐색 없음** — 자산 풀링이라는 마지막 미시도 각도까지 소진.
사용자에게 세 가지 선택지(현 결론 유지 / vix_rsi ETH만 meridian 선례처럼 승격 /
5개 알고 meridian식 재설계)를 제시한 결과 **"지금 결론 유지"** 선택 — 6개 레거시
알고는 계속 롱온리, `PERP_SHORT_ENABLED_TRACKS`는 `meridian` 3트랙만 유지.
`vix_rsi`/ETH(DSR 0.934)는 §14와 동일하게 "표본 부족, 재탐색 없이 관찰 대기"
상태 유지 — 재평가 트리거는 라이브 표본이 쌓였을 때이지 새로운 백테스트 각도가
아니다. **Phase B는 이것으로 완전히 종결**(1순환·2순환·풀링 3갈래 전부 소진).

> ### ⚠️ 정정 (2026-08-16) — §8~§18의 "기각" 표현 중 일부는 "판정 불가"가 정확하다
>
> [증거기준 프레임워크](evidence-criteria-framework-20260816.md)가 이 문서의 판정들을
> 검정력 기준으로 재분해한 결과, **§4 채택기준(DSR≥0.95)을 이 표본크기에 적용한 것
> 자체가 부적합**했음이 확인됐다. 구체적으로:
>
> - **`vix_rsi` 숏 ETH(§12)는 실제로는 통과다.** 사전등록 단일사양이므로 맞는 지표는
>   PSR이고 **PSR=0.970 ≥ 0.95**, 게다가 **MinTRL 37건 ≤ 보유 48건**으로 이 검정은
>   검정력도 충분했다(Phase B 전체에서 유일). DSR 0.913은 사전설계된 2변형에 대한
>   선택편향 보정인데, 사전등록 변형에 이를 적용한 것은 과보정에 가깝다.
> - **§18 `multi_factor` 풀링은 "기각"이 아니라 "판정 불가"다** — MinTRL 219건 vs
>   보유 33건(유효표본 보정 시 ≈521건 필요)으로 **6.6배 부족**. 재시도 금지 목록에
>   넣을 근거가 없다.
> - §8~§11·§13의 나머지 기각은 대부분 SR 자체가 음수라 **"기각"이 맞다**(표본을
>   늘려도 방향이 안 바뀜).
>
> 즉 Phase B의 "6개 전부 기각"은 **"5개 기각 + 1개(vix_rsi/ETH) 실제 통과 + 풀링건
> 판정불가"**로 정정되어야 한다. 승격 여부는 여전히 사용자 결정 사항이지만,
> **"증거 부족"은 더 이상 `vix_rsi`/ETH의 기각 사유가 아니다.**
