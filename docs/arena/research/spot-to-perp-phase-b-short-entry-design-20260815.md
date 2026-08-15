# Spot→Perp Phase B — 알고별 숏 진입 로직 설계 (2026-08-15, 설계안·미구현)

**상태**: 설계 문서만. 코드 변경 없음. 이 문서에서 확정한 방향에 대해 사용자 승인 후
알고별로 하나씩 구현→백테스트→(통과 시) `PERP_LIVE_ENABLED_ALGOS` 추가를 진행한다.

> **다음 세션은 이 문서 하나만 읽고 바로 시작 가능하도록 작성됨.** 새 세션에서 처음
> 할 일은 §7("다음 세션 시작 가이드")로 바로 이동 — §1~§6은 §7에서 참조하는 배경/근거이므로
> 필요할 때만 되짚어 읽으면 된다. 이 문서 자체가 코드 변경을 반영하지 않으므로,
> 구현 세션 시작 시 §3의 코드 앵커(줄번호 포함)가 여전히 유효한지 먼저 grep으로
> 스팟체크할 것(다른 세션이 그 사이 `algorithms.py`/`parameters.py`를 건드렸을 수 있음).

## 0. 배경 — 지금 뭐가 왜 막혀 있나

[Phase A](spot-to-perp-phase-a-infrastructure-20260815.md)/[A2](spot-to-perp-phase-a2-root-track-split-20260815.md)로
"선물이라는 독립 자본 트랙"은 실거래 중(`ARENA_PERP_LIVE_ENABLED=True`, BTC/ETH/SOL
perp 트랙 각 6알고×$1,000). 하지만 `PERP_LIVE_ENABLED_ALGOS`(숏 opt-in 허용목록,
`parameters.py:81`)는 여전히 빈 집합이라 6개 알고 전부 롱/관망(`None`)만 낸다 — 선물
트랙도 실질은 "현물과 동일 신호 + 펀딩비만 추가"인 상태.

**기계적으로는 이미 준비됨** (Phase A에서 확인·검증):
- `perp_policy.py` — 방향 무관 열림/보유/반전/청산 상태머신(`spot_policy.py` 대칭).
- `execution_rules.py`(손절·트레일 사이징)·`risk.py`(포지션 캡) — 원래부터 long/short 대칭
  (2026-06-20 이전 실제 perp 시뮬레이션 유산).
- `positions.py.close_position()` — 펀딩 정산이 `direction` 부호를 반영
  (`market_structure.funding_return_pct`: 롱은 양의 펀딩비 지불, 숏은 수취).
- 캡: `MAX_SHORT_POSITIONS=6`, `MAX_NET_SHORT_EXPOSURE=6.0` — 롱과 동일 값으로 이미 설정됨
  (`parameters.py:169,171`). 단, `_risk_policy()`의 숏 캡 개방은 "`PERP_LIVE_ENABLED_ALGOS`가
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
빠지고 기존 롱 로직·PERP_LIVE_ENABLED_ALGOS 비가입 상태(선물 트랙에서도 롱온리)로
유지.

## 5. 롤아웃 절차 (알고 1개 통과 시)

1. `algorithms.py`에 숏 조건 구현(§3 설계안 기준, 백테스트에서 확정된 버전).
2. 패리티 백테스트 재확인(§4-6, 회귀 없음 확인) + 신규 테스트 추가(`test_arena_perp_policy.py`
   패턴 참고 — 숏 오픈/반전/청산 케이스).
3. `PARAMS_VERSION` bump(신호 로직 변경이므로 — 기존 Phase A/A2는 bump 없었음, 이번엔
   실제 신호가 바뀌므로 필요).
4. `parameters.PERP_LIVE_ENABLED_ALGOS`에 해당 algo_id **1개만** 추가(한 번에 여러 개
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
`PERP_LIVE_ENABLED_ALGOS`를 건드리는 건 백테스트 결과를 사용자에게 보고하고 승인받은
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
   `PARAMS_VERSION` bump → `PERP_LIVE_ENABLED_ALGOS`에 `macd_momentum` 1개만 추가 →
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
  `tests/test_arena_scheduler_perp.py`(`PERP_LIVE_ENABLED_ALGOS` 배선 테스트).

### 7-3. 로컬 검증 커맨드

```bash
.venv/bin/python -m pytest tests/test_arena_perp_policy.py tests/test_arena_scheduler_perp.py tests/test_arena_positions_perp_funding.py -q
.venv/bin/ruff check src/arena scripts/analysis
```

(`pyproject.toml`이 `pythonpath = ["src", "scripts"]`를 이미 설정하므로 `PYTHONPATH=src`
수동 지정 불필요 — 로컬 개발 환경에 `.venv`가 없다면 프로젝트 표준 셋업(`requirements-dev.txt`)
먼저 확인.)
