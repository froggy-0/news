# omnibus 손절폭 재설계 — DOWN_TREND(REBOUND) 레그 국소 처방 (2026-08-04)

> **상태: 변형 X 구현·검증 완료 → ❌ 기각.** §8 참조. 플래그(`OMNIBUS_PRICE_STOP_DISABLED_LEGS`/
> `OMNIBUS_LEG_TIME_STOP_HOURS`)는 코드에 남아있으나 기본값 off 유지(PARAMS_VERSION
> bump 없음). `entry-exit-separation-implementation-plan-20260804.md` §12가 "이벤트/상태
> 분리로는 해결 안 되는 손절폭 문제"로 재분류한 것의 후속 설계.

---

## 0. 한 줄 요약

**omnibus의 손절 문제는 3개 레그 전체가 아니라 DOWN_TREND(REBOUND) 레그 하나에
집중돼 있다.** 과거(2026-07-25) "가격손절 제외+시간손절" 시도가 전/후반 불일치로
보류된 건 **omnibus 전체에 블랑켓 적용해 문제없는 UP_TREND·RANGE 레그까지 같이
건드려 신호가 희석됐기 때문일 가능성**이 새 레그별 분해로 드러났다. 이번엔 **DOWN_TREND
레그에만 국소 적용**하는 설계를 제안한다.

---

## 1. 배경

`entry-exit-separation-implementation-plan-20260804.md` §12가 omnibus을 진단하며
"flat_signal은 여기서도 지배적이지만 건당 손실이 거의 0. 실제 손실은 stop_loss/
trailing_stop(건당 −3.4~−3.75%)에서 나온다"고 결론지었다. 이 문서는 그 다음 —
"그럼 어느 레그의 손절이 문제인가, 왜 이전 시도는 실패했는가, 뭘 다르게 해야
하는가"에 답한다.

---

## 2. 레그별 진단 — 문제는 DOWN_TREND(REBOUND)에 집중

`arena_ohlcv_bars`(2023-05~2024-07 백필 + 기존 2024-11~) 기반 두 창(상승장/하락장)에서
omnibus 거래를 `algorithms._omnibus_regime(trade.macro_snapshot, trade.indicator_snapshot)`로
레그 태깅해 재현(코드 읽기 전용, 이번 세션 실측).

### 2.1 레그별 ATR%·손절% 클램프 히트율

| leg | ATR% 중앙 | 손절% 중앙 | 하한(2%) 히트 |
|---|---:|---:|---:|
| DOWN_TREND | 1.50~1.59% | 3.75~3.98% | 2~5% |
| UP_TREND | 1.31~1.45% | 3.28~3.61% | 2~7% |
| **RANGE** | **0.99~1.00%** | **2.48~2.50%** | **7~39%** |

RANGE만 하한(2%)에 자주 걸린다 — ATR이 작아 2.5×ATR이 자연 하한보다 작아지는
구간이 잦다는 뜻. 그러나:

### 2.2 레그별 stop_loss/trailing_stop 발생 시 실제 손실 — RANGE는 문제가 아니다

| leg | 손절 비중(레그 내) | 손절당 평균손실 |
|---|---:|---:|
| **DOWN_TREND** | **10~14%(최고)** | **−3.59~−4.19%(최악)** |
| UP_TREND | 4~7% | −3.35~−3.87% |
| RANGE | 4~11%(최저권) | −2.13~−2.59%(최소) |

**RANGE는 손절 클램프에 가장 자주 걸리지만(§2.1), 실제로 손절이 발동하는 빈도와
손실 크기는 3레그 중 가장 작다(§2.2).** RANGE의 낮은 PF(0.31~0.47, root-cause 문서
§12-2)는 손절폭이 아니라 다른 원인(승률 자체가 낮음 — flat_signal 청산의 품질
문제로 추정, 별도 진단 필요, 이 문서 범위 밖)이다.

**DOWN_TREND(REBOUND)는 반대로 손절 빈도·손실크기 둘 다 최악**이며, 거래량도
가장 많다(레그 중 최다, 59~134건) — omnibus 전체 손절 손실의 다수를 차지하는
실질적 병목이다. **이 문서는 DOWN_TREND 레그로 범위를 좁힌다.**

---

## 3. 왜 이전 시도(2026-07-25)가 실패했는가 — 레그 혼합 가설

CLAUDE.md 기록(2026-07-25):

> omnibus REBOUND 레그 내 target_exit은 순수 알파(43건 전승 +6.06%)지만
> stop_loss+trailing_stop(19건 -7.13%)이 거의 다 잡아먹음. "가격손절 제외+시간손절"
> (fng v22와 동일 로직) A/B 테스트 → 전체는 개선(-6.71→-4.69%)되나 **전/후반 분할
> 검증에서 개선이 전반부에만 몰리고 후반 10개월은 무개선** → 채택하지 않음(근거
> 부족으로 보류, 재시도 금지 아님).

이 시도는 `PRICE_STOP_DISABLED_ALGOS`에 `"omnibus"`를 추가하는 방식으로 추정된다
(fng_contrarian과 "동일 로직"이라는 문구, `PRICE_STOP_DISABLED_ALGOS`가 알고 단위
튜플이라 레그 구분이 구조적으로 불가능— `backtest.py:697`
`price_stop_on = algo_id not in parameters.PRICE_STOP_DISABLED_ALGOS`).

**가설**: 이 조정이 DOWN_TREND뿐 아니라 UP_TREND·RANGE의 가격손절까지 전부
비활성화했다. §2.2가 보여주듯 UP_TREND는 손절 손실이 작지 않고(−3.35~−3.87%,
DOWN_TREND와 비슷한 수준), RANGE는 원래도 손절 문제가 아니다 — 즉 **효과가 있는
레그(DOWN_TREND)와 효과가 불확실하거나 무관한 레그(UP_TREND, RANGE)가 하나의
스위치로 묶여 있었다.** 전/후반 불일치는 "DOWN_TREND에서의 진짜 개선"이
"UP_TREND에서의 부수 손실"과 섞여 순물림 된 결과일 수 있다 — 이번 문서가
검증하려는 가설이다(재현 실험은 §6).

⚠️ 이 가설 자체는 아직 미검증이다 — 과거 실행의 원본 스크립트/커밋을 이번 세션에서
찾지 못해 정확히 어떤 코드 경로였는지 확인 못함. §6 재현에서 직접 확인 필요.

---

## 4. 문헌 근거

- **ATR 배수는 전략 유형별로 다르다는 게 실무 컨센서스**: 스캘핑 1~1.5×, 데이트레이딩
  1.5~2×, 스윙 2~3×, 포지션 트레이딩 3~4×
  ([LuxAlgo](https://www.luxalgo.com/blog/5-atr-stop-loss-strategies-for-risk-control/),
  [FasterCapital](https://fastercapital.com/content/Stop-Loss--Optimizing-Stop-Loss-Positions-with-Average-True-Range-Calculations.html)).
  **현재 아레나 전역값 2.5×는 "스윙 트레이딩"(추세추종, regime_trend 기준) 대에
  해당** — DOWN_TREND(REBOUND)는 성격이 다른 저빈도 역발산(평균회귀에 가까움)인데
  같은 배수를 쓰고 있다.
- **평균회귀형은 1.5~2.0×ATR이 "논리적 레벨"에 가깝다는 정리**
  ([Medium/FMZ, Bollinger+RSI+ATR 동적손절](https://medium.com/@redsword_23261/mean-reversion-strategy-with-bollinger-bands-rsi-and-atr-based-dynamic-stop-loss-system-02adb3dca2e1)).
  단 이 출처들은 peer-review 논문이 아니라 실무 정리 글 — **근거강도는 약함**,
  방향성 참고용.
- **손절폭의 근본 트레이드오프**: "너무 타이트하면 소액손실 빈도가 늘고, 너무
  넓으면 개별 손실은 커지지만 전체 수익성이 개선될 수도 있다" — 어느 방향이
  맞는지는 전략·자산·구간마다 다르므로 **A/B로 실측하지 않고는 방향조차 예단
  불가**(이번 세션 전체를 관통한 원칙과 정합).
- **아레나 기존 정책과의 정합성**: `fng_contrarian`(같은 역발산형)은 이미
  "가격손절은 평균회귀를 악화시킨다"(Alvarez Quant 등, CLAUDE.md 기존 기록)는
  근거로 가격손절을 아예 빼고 시간손절(72h)로 대체해 **채택·검증 완료** 상태다.
  DOWN_TREND(REBOUND)도 구조적으로 같은 유형(가격 기준 역발산 반등 베팅)이라
  같은 원칙이 적용될 가능성이 있다 — 다만 fng_contrarian은 **omnibus 밖의 독립
  알고**라 레그 혼합 문제가 없었고, 그래서 안정적으로 채택됐을 수 있다는 점도
  이번 가설(§3)과 정합적이다.

---

## 5. 설계

### 5.1 원칙

**omnibus 손절 정책을 레그 인지형(leg-aware)으로 만든다** — 현재 `PRICE_STOP_DISABLED_ALGOS`/
`ATR_MULTIPLE`이 알고 단위인 것을 DOWN_TREND 레그 단위로 좁힐 수 있는 메커니즘을
추가한다. `omnibus_target_price()`/`omnibus_position_multiplier()`가 이미 진입
시점에 `_omnibus_regime(macro, ind)`를 계산해 레그별 값을 산출하는 정확히 같은
패턴이 존재한다(`algorithms.py:775-799`, `backtest.py:385,394` 호출부) — 신규
아키텍처 불필요, 이 패턴을 손절에도 확장.

### 5.2 두 변형 (방향을 예단하지 않고 A/B)

**변형 X — DOWN_TREND 전용 가격손절 제외 + 시간손절** (fng_contrarian v22 원칙을
레그 단위로 재적용, §3 가설의 직접 검증):
- DOWN_TREND 레그로 태깅된 포지션만 `stop_loss`/`trailing_stop` 비활성화
- 대체 상한: 시간손절(구체 시간은 그리드 — fng의 72h를 시작값으로, REBOUND는
  이미 `OMNIBUS_REBOUND_TARGET_ATR_MULT=1.0` 목표가 익절이 있으므로 시간손절은
  "익절도 손절도 안 된 채 오래 묵는" 포지션만 정리하는 역할)
- UP_TREND·RANGE는 기존 가격손절 그대로 유지(레그 분리로 §3의 희석 문제 원천 차단)

**변형 Y — DOWN_TREND 전용 ATR 배수 조정** (§4 문헌의 "평균회귀는 더 타이트하게"
원칙 검증, 가격손절 자체는 유지):
- DOWN_TREND만 `ATR_MULTIPLE` 별도값 적용 — 그리드 후보 {1.5, 2.0}(문헌 권고 하한)
  및 대조군으로 {3.5}(반대 방향: 더 넓게 줘서 낙폭 중 흔들림에 안 털리게) 포함.
  방향을 예단하지 않고 양쪽 다 넣는 이유: §4가 "어느 쪽이 맞는지 A/B 없이는 모름"
  이라고 명시.
- UP_TREND·RANGE는 기존 2.5× 그대로.

변형 X와 Y는 상호배타적이지 않다 — 이론상 병행 가능(가격손절 제외 + 시간손절만
쓰면 ATR 배수 자체가 무의미해지므로, 실제로는 X를 채택하면 Y는 자동 기각).
**우선순위: X를 먼저 검증**(fng_contrarian이라는 검증된 선례와 원칙이 동일해
사전 확률이 더 높음), Y는 X가 기각될 경우의 대안으로 순차 검토.

### 5.3 구현 스케치 (코드 변경 없음 — 방향만 표시, §1 정정 관행과 동일하게
실제 구현 시 재확인 필요)

```python
# parameters.py (신규 dict, 기존 PRICE_STOP_DISABLED_ALGOS 패턴과 구분되는
# "알고+레그" 단위 확장 — omnibus 전용이라 범용화하지 않고 최소 범위로)
OMNIBUS_PRICE_STOP_DISABLED_LEGS: tuple[str, ...] = ()  # 기본 빈 튜플(off).
                                                          # 예: ("DOWN_TREND",)
OMNIBUS_LEG_TIME_STOP_HOURS: dict[str, float] = {}       # 기본 빈 dict(off).
                                                          # 예: {"DOWN_TREND": 72.0}
```

`backtest.py:697`(`price_stop_on = algo_id not in parameters.PRICE_STOP_DISABLED_ALGOS`)
근처에 omnibus 전용 분기 추가 — 정확한 삽입 지점·`_omnibus_regime` 호출에 필요한
macro/ind 가용성은 **구현 계획 단계에서 코드 재확인 필수**(이번 세션에서
`entry-exit-separation-implementation-plan-20260804.md` §1처럼 의사코드 오류가
실제로 5건 나온 전례가 있음 — 같은 검증 절차를 여기도 적용해야 함).

---

## 6. 검증 계획 (구현 시 반드시 적용 — 이전 라운드와 동일 방법론)

### 6-1. 채택 기준
1. **엣지/비용 비율** — DOWN_TREND 레그 단독 기준(전체 omnibus가 아니라 레그
   단위로 측정, §2 방법론)
2. **양쪽 창(상승장 2023-08~2024-07 / 하락장 2024-11~2026-07) 동시 개선**
3. **특이성 검증**: UP_TREND·RANGE 레그의 성적이 이 변경으로 (의도대로) 불변인지
   확인 — 만약 다른 레그도 같이 흔들리면 구현 버그(레그 태깅 오류) 의심
4. **부트스트랩**: DOWN_TREND 레그 거래풀 재표본 95% CI 대비 개선폭이 벗어나는지
   (regime_trend/macd_momentum 라운드에서 표면적 개선 2건이 전부 이 검증에서
   탈락한 전례 — 반드시 반복)
5. **전/후반 분할**: 2026-07-25 시도가 실패한 바로 그 기준(전반부만 개선되는
   패턴 재발 여부) — 이번엔 레그 분리로 이 문제가 해소되는지가 핵심 가설이므로
   각별히 확인

### 6-2. 재현 데이터
`entry-exit-separation-implementation-plan-20260804.md` §6-2와 동일 창·동일 명령
패턴(`regime_trend_exit_tuning.py`/`macd_momentum_exit_tuning.py`를 omnibus·
레그인지형으로 변형한 신규 하니스 필요 — 레그 태깅 로직은 §2의 진단 스크립트
방식 재사용).

---

## 7. 리스크·캐비어트

- **§3의 "레그 혼합" 가설 자체가 미검증**이다 — 과거 실행 코드를 못 찾아 진짜
  원인인지 확인 못했다. 검증 결과 레그 분리로도 여전히 전/후반 불일치가 재발하면
  가설이 틀렸다는 뜻이고, 그땐 "가격손절 제외"라는 처방 자체를 이 레그에서도
  포기해야 한다.
- **RANGE 레그의 저PF는 이 문서로 해결되지 않는다**(§2.2) — 별도 진단 필요,
  손절이 아니라 진입 품질(승률) 문제로 추정.
- **regime_trend·macd_momentum 라운드의 전적(0/2)**을 감안하면 이번도 기각될
  가능성을 낮게 볼 근거는 없다 — 다만 이번엔 (a) 이미 한 번 부분적으로 통했던
  전례(fng_contrarian)가 있고 (b) 실패 원인에 대한 구체적 가설(레그 혼합)이
  있다는 점이 앞의 두 라운드와 다르다.
- n 규모: DOWN_TREND 레그 단독 거래수는 상승장 59건·하락장 134건으로
  regime_trend(n=10~16)보다 표본이 커 통계적 판정이 상대적으로 더 신뢰 가능.

## 8. 구현 및 검증 결과 (2026-08-04) — 변형 X

### 8.1 구현

`parameters.py`(`OMNIBUS_PRICE_STOP_DISABLED_LEGS: tuple[str, ...] = ()`,
`OMNIBUS_LEG_TIME_STOP_HOURS: dict[str, float] = {}`) + `algorithms.omnibus_regime_for()`
(신규 공개 래퍼, `_omnibus_regime`을 module 밖에서 진입 시점 macro/indicator 스냅샷으로
재호출) + `backtest.py`/`stream.py`/`scheduler.py` 3경로 배선(§5.3 설계 그대로 구현,
코드 재확인 완료). 신규 테스트 5건(`tests/test_arena_backtest.py`) 전부 통과, 기존
165개 arena 테스트 무회귀, ruff 통과.

테스트 작성 중 발견한 순수 테스트-픽스처 이슈(프로덕션 버그 아님): `run_replay()`
루프가 매 bar `regime.classify_regime_variant()`로 `arena_regime_state`를 지표에서
직접 재계산해 macro에 주입(라이브 로컬레짐 패리티 유지 목적) — 테스트 프레임이
macro에 직접 넣은 `arena_regime_state`는 이 재계산으로 덮어써진다. `regime.classify_regime_variant`를
monkeypatch로 고정해 해결(`_force_local_regime` 헬퍼).

### 8.2 검증 — `scripts/analysis/omnibus_leg_stop_tuning.py`

시간손절 그리드 {48h, 72h, 96h} 전부 **완전히 동일한 결과**를 냈다 — 즉 이 구간에서
time_stop이 한 번도 실제 청산 트리거로 작동하지 않았다(target_exit/flat_signal이
그보다 먼저 청산시킴). 이는 "익절도 손절도 안 된 채 오래 묵는 포지션 정리"라는
§5.2의 설계 의도가 이 데이터셋에서는 사실상 발동하지 않았다는 뜻 — 관측된 개선은
전부 가격손절 제외 자체에서만 나온다.

| 창 | 지표 | baseline | 변형X | Δ |
|---|---|---:|---:|---:|
| 상승장(2023-08~2024-07) | DOWN_TREND sum_w_ret | -1.09% | -1.03% | **+0.06%p** |
| 하락장(2024-11~2026-07) | DOWN_TREND sum_w_ret | -2.05% | -1.31% | **+0.74%p** |

**특이성 체크(§6-1 기준3): ✅ 완전 통과.** UP_TREND·RANGE 레그는 두 창 모두
baseline과 **소수점까지 완전히 동일** — 레그 태깅·손절 스위치 분리가 코드 레벨에서
의도대로 정확히 격리됨을 확인. §3의 "레그 혼합" 가설 중 **메커니즘(격리 자체)은
검증됨**.

**전/후반 분할(§6-1 기준5, 2026-07-25 실패 재현 여부 — 이 문서의 핵심 질문):**

| 창 | 전반 Δ | 후반 Δ | 판정 |
|---|---:|---:|---|
| 상승장 | +0.53%p(n=29) | **-0.47%p(n=30)** | ❌ 불일치 (2026-07-25와 동일 패턴 재발) |
| 하락장 | +0.60%p(n=67) | +0.15%p(n=67) | ✅ 양쪽 개선(단 후반 효과 미미) |

**부트스트랩 95% CI(§6-1 기준4):** 두 창 모두 변형X의 DOWN_TREND sum_w_ret이
baseline 95% CI **안쪽**에 위치 — 노이즈와 통계적으로 구분 불가
(상승장 CI=[-3.69,+1.43] vs 변형=-1.03%, 하락장 CI=[-6.17,+1.89] vs 변형=-1.31%).

### 8.3 판정: ❌ 기각 (regime_trend·macd_momentum에 이어 0/3)

- 기준1(엣지/비용비) — 소폭 개선(하락장) 또는 악화(상승장), 결정적이지 않음
- 기준2(양쪽 창 개선) — 형식적으로는 양쪽 다 양수(+0.06%p, +0.74%p)나 상승장 쪽은
  사실상 0에 가까움
- 기준3(특이성) — **✅ 통과**(레그 격리 메커니즘 자체는 깨끗하게 작동)
- 기준4(부트스트랩) — **❌ 탈락**(두 창 다 baseline 노이즈 범위 안)
- 기준5(전/후반) — **❌ 상승장에서 재발**(핵심 가설 반증, 아래 참고)

**§3 "레그 혼합" 가설에 대한 결론: 반증됨(falsified).** 특이성 체크가 완전히
통과했다는 것은 이번 구현이 UP_TREND·RANGE를 전혀 건드리지 않았다는 뜻인데도
상승장 창에서 전/후반 불일치가 다시 나타났다 — 즉 2026-07-25의 실패는 "여러
레그가 하나의 스위치로 묶여 신호가 희석됐기 때문"이 아니라, **DOWN_TREND 레그
자체의 손실 패턴이 애초에 기간에 따라 방향이 바뀌는 비정상성(non-stationarity)을
갖고 있기 때문**일 가능성이 높다. 레그를 아무리 깨끗하게 분리해도 이 비정상성은
해소되지 않는다.

부트스트랩 탈락까지 겹쳐 변형X는 **채택하지 않는다**. 우선순위(§5.2)에 따라
변형Y(DOWN_TREND ATR 배수 조정)를 검토할 수 있으나, 변형X가 이미 "가격손절 제외"라는
개입 자체의 방향성(더 느슨하게)이 유효하지 않음을 시사하므로, 변형Y(같은 방향,
배수만 다르게)도 사전확률이 낮아진 상태로 봐야 한다 — 시도한다면 그 판단을
명시하고 진행.

이로써 P1 라운드(entry-exit-separation 계열) 전적은 **0/4**
(regime_trend, macd_momentum, omnibus 변형X, 그리고 §12 진단 자체가 이미
"이벤트/상태 분리로 해결 안 됨"으로 1차 기각됐던 것까지 포함하면 실질적으로
"청산 타이밍/폭 조정" 계열 가설이 전방위로 소진됨).

## 관련 문서
- [entry-exit-separation-implementation-plan-20260804.md §12](entry-exit-separation-implementation-plan-20260804.md) — 이 설계의 출발점(레그별 진단 원본)
- [root-cause-diagnosis-where-to-look-20260803.md](root-cause-diagnosis-where-to-look-20260803.md) — P1 상위 진단
- CLAUDE.md — 2026-07-25 이전 시도 기록, fng_contrarian v22(가격손절 제외 선례)
