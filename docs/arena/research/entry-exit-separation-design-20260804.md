# 진입/보유 조건 분리 설계 — "이벤트를 상태로 오용" 수정안 (2026-08-04)

> **상태: 설계 제안, 미구현.** [root-cause-diagnosis-where-to-look-20260803.md](root-cause-diagnosis-where-to-look-20260803.md)
> P1(청산 설계)의 구체적 처방. 코드 변경 없음 — 이 문서는 "무엇을 어떻게 고칠지"의
> 설계와 그 근거만 담는다. 구현·A/B 백테스트는 사용자 승인 후 별도 세션.

---

## 0. 한 줄 요약

**진입 조건과 보유(청산 유예) 조건을 분리한다.** 현재 아레나는 "진입조건이 거짓이
되는 순간 청산"(`spot_policy.py:88-95`, 6알고 공용)이라 **1회성 이벤트 조건**(예:
Donchian 돌파)까지 매 봉 재검사해 청산 트리거로 오작동한다. 진입 조건 중 **지속성
있는 상태 조건만 보유 판정에 남기고**, 이벤트성 조건은 진입 게이트로만 쓴다.

---

## 1. 배경 — 어떻게 여기에 도달했는가

[root-cause-diagnosis-where-to-look-20260803.md](root-cause-diagnosis-where-to-look-20260803.md)가
측정으로 확정한 사실:
- 청산의 84.1%가 `flat_signal`(진입조건 소멸), 그 거래 평균수익 **−0.01%**
- 중앙 보유시간이 `MIN_HOLD_HOURS` 설정값과 사실상 동일(6개 중 5개 일치) — 포지션이
  "허용되는 가장 이른 순간"에 나감
- 코드 확인 결과 **아레나에 독립적인 청산 규칙이 없다**(`spot_policy.decide()`가
  `raw_signal != "long"`이면 곧바로 `close_reason="flat_signal"`)

이 문서는 그 다음 질문 — **"그럼 청산 규칙을 어떻게 다시 설계해야 하는가"**에 대한
실측 기반 답이다.

---

## 2. 진단 — 이벤트 조건과 상태 조건이 섞여 있다

`regime_trend`의 진입 조건 7개 각각에 대해, "지금 참이면 바로 다음 4H봉에도 참일
확률"(지속확률)을 상승장 구간(2023-08~2024-07 BTC, 2172봉)에서 직접 측정했다.

| 조건 | 참인 봉 수 | 다음봉도 참 | 지속확률 | 성격 |
|---|---:|---:|---:|---|
| **`donchian_breakout`** | 113 | 34 | **30.1%** | **이벤트(1회성)** |
| `bullish_regime` | 455 | 328 | 72.1% | 중간 |
| `ema_aligned_up` | 933 | 814 | 87.2% | 상태(지속) |
| `adx_trending` | 1683 | 1648 | 97.9% | 상태(지속) |
| `above_ema200_4h` | 1575 | 1539 | 97.7% | 상태(지속) |
| `rsi_below_long_max` | 1945 | 1902 | 97.8% | 상태(지속) |
| `funding_not_hot` | 1914 | 1898 | 99.2% | 상태(지속) |

`donchian_breakout`(Donchian20 상단 돌파)의 지속확률이 30.1%로 나머지(72~99%)와
확연히 다르다. **이건 정의상 당연하다** — 상단 돌파는 "최근 20봉 신고가 경신"이라는
사건이고, 돌파한 순간 그 고점이 다음 채널에 편입되므로 매 봉 신고가를 계속 경신하지
않는 한 조건은 스스로 거짓이 된다. 이벤트 조건이 원래 그렇게 설계돼야 정상이다
(§4.2의 문헌 근거 참조).

**문제는 이 이벤트 조건이 보유 판정에도 그대로 재사용된다는 것.** `raw_signal`을
매 봉 재계산해 `spot_policy.decide()`에 넘기는 구조라, 진입에 쓴 7개 조건 전부가
보유 여부도 결정한다.

### 2.1 직접 증거 — 진입 다음 봉에 뭐가 깨지는가

같은 구간에서 `regime_trend`의 `raw_signal="long"` 발생 12회를 추적, 바로 다음 봉에
어떤 조건이 거짓으로 바뀌는지 집계:

| 조건 | 발생 | 비율 |
|---|---:|---:|
| **`donchian_breakout`** | 9 / 12 | **75.0%** |
| `rsi_below_long_max` | 3 / 12 | 25.0% |
| `bullish_regime` | 2 / 12 | 16.7% |
| `above_ema200_4h` | 1 / 12 | 8.3% |

**진입 12건 중 9건(75%)이 바로 다음 봉에 `donchian_breakout` 소멸로 청산 후보가
된다.** 이게 §2(root-cause 문서)의 "중앙 보유 8시간(2봉)"의 직접 원인이다.

### 2.2 부차 가설 검증 — RSI 상한

"RSI<70 보유조건이 강한 상승 구간에서 조기청산을 유발하는가"를 검증:

| | RSI 중앙값 | RSI>70 비율 |
|---|---:|---:|
| 전체 봉 | 52.4 | 10.5% |
| 강한 상승 직전 봉(다음 6봉 수익 상위 20%) | 53.2 | **16.4%** |

방향은 가설과 일치(강한 상승 직전에 RSI>70이 더 잦음)하지만 **효과 크기는 작다**
(16.4% vs 10.5%, 절대차 6%p). §2.1의 75% 대비 부차적 요인 — 주범은
`donchian_breakout`이고 RSI는 보조 원인 정도로 해석해야 한다. 과대해석 금지.

---

## 3. 기존 반례 — 이미 검증된 유사 사례가 존재한다

`algorithms.py:886`에 `exit_hold_override(algo_id, macro, ind)` 훅이 이미 구현돼
있다. "raw flat 신호에도 청산을 보류할지"를 알고별로 분기하는, 정확히 이 문서가
제안하는 것과 같은 패턴이다. 활성화 상태:

| algo | 훅 구현 | 활성화 | 엣지/비용(20개월) | PF |
|---|---|---|---:|---:|
| **vix_rsi** | ✅ | **✅ True(유일)** | **5.04** | **1.44** |
| fng_contrarian | ✅ | ❌ False | 3.31 | 1.37 |
| macd_momentum | ✅ | ❌ False | −1.43 | 0.36 |
| regime_trend | ❌ 미구현 | — | −3.34 | 0.43 |
| multi_factor | ❌ 미구현 | — | 1.92 | 0.81 |
| omnibus | ❌ 미구현 | — | 0.35 | 0.76 |

(엣지/비용·PF 출처: `root-cause-diagnosis-where-to-look-20260803.md` §2.3, §4.3.6.
`vix_rsi` 히스테리시스 도입 배경은 `algorithms.py:889-895` 주석 — "라이브 id16
−2.52%" 등 진입가 부근 whipsaw 손실 반복이 계기였다고 기록돼 있음.)

**독립 청산 로직이 켜진 유일한 알고가 엣지/비용 1위다.** 우연으로 치부하기엔
훅 없는 3개 알고가 정확히 하위권에 몰려있다는 점이 겹친다. 인과를 단정할 정도의
표본은 아니지만(n=6 알고), 방향은 이 문서의 제안과 일치한다.

---

## 4. 설계

### 4.1 원칙

```
진입 게이트 = 이벤트 조건 + 상태 조건 (전부) — 선별력 유지, 변경 없음
보유 판정   = 상태 조건만            — 이벤트 조건 제외
청산       = 상태 붕괴 OR 트레일링 OR 손절 OR 목표가 OR risk-off/breadth/stablecoin veto(양보 없음)
```

이벤트/상태 분류 기준은 §2의 **지속확률 실측**을 따른다(임의 지정 아님). 지속확률
<50%는 이벤트로 분류해 보유 판정에서 제외하는 것을 기본 규칙으로 삼는다.

### 4.2 `regime_trend` 구체안

- **보유 유지 조건** (지속확률 87~99%): `ema_aligned_up`, `above_ema200_4h`,
  `adx_trending`, `funding_not_hot`, `rsi_below_long_max`
- **보유 판정에서 제외**(진입 전용): `donchian_breakout`(30.1%, §2의 핵심 발견)
- **즉시 청산, 양보 없음**(기존 관례 유지): risk-off 레짐, breadth 붕괴,
  stablecoin 수축 — `vix_rsi`/`fng_contrarian` 히스테리시스와 동일 원칙
  (`algorithms.py:897-900`, `:914-915` 참조)
- **하방 방어**: 기존 래칫 트레일링 스톱 재사용(`execution_rules.py`, 이미 구현).
  현재 발동률 1.2%(root-cause 문서 §2.2)로 사실상 `flat_signal`에 선점당해
  사문화된 상태 — 이 설계가 통과하면 트레일링이 실제로 작동할 여지가 생긴다.
- `bullish_regime`(지속확률 72.1%, "중간")은 경계 사례 — 1차안은 보유 조건에
  포함(레짐 붕괴 시 청산은 합리적), A/B에서 제외 버전도 병행 비교 권장.

### 4.3 구현 방식 — 새 아키텍처 불필요

`exit_hold_override()`에 `regime_trend` 분기 추가 + `parameters.py`에 플래그
(`REGIME_TREND_EXIT_HYSTERESIS_ENABLED`, 기본 `False`) 신설. `vix_rsi`가 이미 쓰는
정확히 같은 패턴이며, 이 함수는 scheduler(live)·backtest 공용이라 패리티가 자동
확보된다(기존 원칙, `algorithms.py:895` 주석 참조).

의사코드(§4.2를 그대로 표현, 실제 조건 함수는 기존 `_record_condition` 대상 재사용):

```python
if algo_id == "regime_trend" and parameters.REGIME_TREND_EXIT_HYSTERESIS_ENABLED:
    if _is_risk_off(_regime_state(macro)):
        return False
    if _breadth_collapsed(macro) or _stablecoin_contracting(macro):
        return False
    state = _regime_state(macro)
    ema_fast, ema_slow = ind.get("ema_fast", 0.0), ind.get("ema_slow", 0.0)
    return (
        _is_bullish(state)
        and ema_fast > ema_slow                      # ema_aligned_up
        and ind.get("close", 0.0) > ind.get("ema200", 0.0)   # above_ema200_4h
        and ind.get("adx", 0.0) >= parameters.ADX_TREND_MIN  # adx_trending
        and ind.get("rsi", 50.0) < parameters.TREND_CORE_RSI_LONG_MAX
        and not _funding_hot(macro)
    )
```

### 4.4 문헌 대조 — 진단·설계가 학술 근거와 일치하는가 (2026-08-04 추가)

root-cause 문서 §4가 "출처 품질 고지"로 남겨둔 공백(실무 블로그 위주)을 보강하기 위해
peer-review 원논문을 직접 대조했다. 결과: **진단(보유기간 부족)과 설계(돌파는 진입
전용) 모두 원논문과 정합**하며, 문헌에서 **새 대안 청산 설계 1개**가 추가로 도출됐다.

#### (a) 추세 지속 지평 vs 실제 보유기간 — 자릿수 불일치

[Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", *Journal of Financial
Economics* 104:228-250](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463)
— 58개 유동성 자산에서 추세(과거 수익의 미래 예측력)는 **1~12개월** 지속 후 반전.
크립토 특화 연구도 같은 방향, 더 짧은 스케일: [Dynamic time series momentum of
cryptocurrencies (NAJEF, 2021)](https://www.sciencedirect.com/science/article/abs/pii/S1062940821000590)은
**단기(일 단위) lookback**이 유효, 실무 정리로는 ~10일 lookback이 최적 —
즉 크립토 추세의 특성 시간은 **일~주 단위**다.

아레나 실측 중앙 보유 **8시간(2봉)**은 전통시장 기준(월)과는 수백 배, 크립토 기준
(일~주)과 비교해도 **10~30배 짧다**. "추세가 만드는 수익의 시간 지평보다 보유가
한참 짧다"는 진단이 원논문 스케일로 정량 확인된 것.

#### (b) 신고가 돌파의 예측력은 "돌파 이후"에 실현된다 — 설계 §4.2의 직접 근거

크립토 실증([QuantPedia 정리, Trend-following and Mean-reversion in
Bitcoin](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/);
[Time-series momentum and market timing in Bitcoin, *Risk Management*
(Springer, 2026)](https://link.springer.com/article/10.1057/s41283-026-00234-7)):
**BTC가 x일 신고가를 경신한 "이후" 구간에서 강한 모멘텀**이 관측되며, "신고가일 때만
보유(at MAX)" 전략이 buy&hold보다 높은 수익·낮은 변동성을 기록.

이 문헌은 현재 아레나의 오류를 정확히 겨냥한다: **Donchian 돌파(신고가 경신)는
문헌상 "미래 수익의 예측 신호"인데, 아레나는 돌파가 유지되지 않으면(=다음 봉에
신고가가 아니면) 청산해버려 문헌이 문서화한 바로 그 수익 구간을 스스로 버린다.**
§2.1의 "진입 12회 중 9회가 다음 봉 donchian 소멸"이 이 낭비의 실측이다.
→ §4.2의 "donchian은 진입 전용, 보유 판정 제외"가 문헌으로 직접 지지됨.

#### (c) 문헌이 주는 대안 청산 설계 — 반대편 채널 이탈 (A/B 후보 추가)

고전 Donchian/터틀 계열 시스템의 원형 설계는 "진입: 20일 신고가 돌파 / 청산:
**10일 신저가 이탈**" — 청산이 "진입조건 소멸"이 아니라 **반대 방향의 더 짧은
채널 돌파**라는 독립 사건이다(§4.1 원칙의 역사적 원형). 이는 §4.2의 "상태 붕괴
청산"과 별개의, 구현이 단순한 대안이므로 A/B 변형에 추가한다:

- **변형 A(§4.2 원안)**: 보유 = 상태 조건 유지(EMA 정배열 ∧ MA200 상회 ∧ ...)
- **변형 B(문헌 원형)**: 보유 무조건 유지, 청산 = Donchian**10 하단** 이탈
  (`indicators.donchian_channel()` 이미 구현돼 있어 하단 참조만 추가하면 됨)
- 두 변형 모두 트레일링·손절·risk-off 즉시청산은 공통 유지

#### (d) 근거 강도 요약

| 주장 | 근거 | 강도 |
|---|---|---|
| 추세 지속은 일~월 지평, 8h 보유는 불일치 | MOP 2012(JFE) + NAJEF 2021 | **peer-review 원논문** |
| 신고가 돌파 후 모멘텀 지속(돌파=진입신호) | Springer Risk Mgmt 2026 + QuantPedia 실증 | peer-review + 실증 재현 |
| 다중검정 보정 필요(P4) | Bailey & López de Prado(DSR) | peer-review 원논문 |
| 히스테리시스(진입≠청산 임계) 일반론 | 실무 표준 관행(학술 원논문 미확보) | **약함 — 자체 실측(§3)이 1차 근거** |
| 반대편 채널 청산(변형 B) | 터틀 시스템 역사적 원형(학술 검증 아님) | 중간 — A/B로 실측 판정 |

히스테리시스 자체의 학술 원논문은 이번 검색에서 확보하지 못했다 — 해당 주장은
문헌이 아니라 **아레나 자체 실측(§3: 히스테리시스 켜진 유일한 알고가 엣지/비용
1위)**을 1차 근거로 유지한다.

---

## 5. 검증 계획 (구현 시 반드시 적용)

### 5.1 채택 기준

**승률·PF가 아니라 엣지/비용 비율을 1차 기준으로 삼는다**(root-cause 문서 §2.4/P2
원칙). 현재 `regime_trend` −3.34 → 목표 **≥1**(생존), 이상적으로 **≥3**.

### 5.2 검증 창 — 양쪽 다 통과해야 채택

| 창 | 현재 성적 | 최소 통과 조건 |
|---|---|---|
| 상승장(2023-08~2024-07, BTC/ETH/SOL) | 참여 자체가 거의 없음(n=11/11/22) | 엣지/비용 개선 + n 유의미 증가 |
| 하락장(2024-11~2026-07, 20개월) | PF 0.43 | PF 상승, sum_w_ret 개선 |

한쪽만 개선되고 다른 쪽이 악화되면 **채택하지 않는다**(과거 P-A/WI-7 재검증
관행과 동일 원칙 — CLAUDE.md 참조).

### 5.3 순열/블록부트스트랩

n이 작은 구간(상승장 n=11)에서는 Newey-West만으로 부족 — 이 세션의 뉴스감성
검증(§블록순열, `news-sentiment-trading-integration-verdict-20260803.md` §6)과
동일하게 순열검정 병행.

### 5.4 롤아웃 순서

1. **`regime_trend`** 먼저 — §2.1에서 75% 조기청산이 확인된 알고, 효과 기대가 가장 큼.
   **변형 A(상태 유지)·변형 B(Donchian10 하단 이탈, §4.4-c)를 같은 창에서 병행 A/B**
   — 둘 다 baseline 대비 개선이면 단순한 쪽(B)을 우선 검토(파라미터 수 최소 원칙)
2. **`macd_momentum`** — 훅은 이미 구현돼 있고(`MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED`,
   현재 `False`) 활성화 A/B만 필요
3. **`omnibus`** — root-cause 문서에서 "가장 많이 거래하고 가장 많이 잃음"으로
   별도 원인 분해가 선행되어야 함(root-cause §7-1과 동일 항목)

---

## 6. 캐비어트

- **`regime_trend` 표본이 작다**(상승장 12개월에 진입 12회). §3의 알고 간 비교
  (엣지/비용 vs 훅 활성화)는 n=6 알고 수준 상관 관찰이지 인과 증명이 아니다.
- **RSI 가설은 부분 확인**(§2.2) — 방향은 맞으나 효과 작음. §4.2에서 RSI 조건을
  보유 판정에 남긴 이유이기도 함(제거 근거로 쓰기엔 약함).
- 이 설계는 **`regime_trend`에 한정된 진단**(§2가 이 알고 기준)이다. `omnibus`·
  `multi_factor`는 조건 구성이 달라 같은 이벤트/상태 분해를 별도로 실측해야 한다
  (§5.4 순서가 이를 반영).
- ~~§4.2의 의사코드는 설계 의도 표현이며 실제 구현 시 정확한 필드명을 재확인해야 한다~~
  → **2026-08-04 확인 완료. §4.2 의사코드에 오류 5건이 있었다**(`ema200`→`ema_200`,
  `above_ema200_4h`가 레짐 조건부 게이트인 점, `ema_aligned_up`이 기울기 포함 2조건인 점,
  진입조건이 7개가 아니라 12개인 점, backtest 호출부 2곳). 정정 내용과 구현 작업분해는
  **[entry-exit-separation-implementation-plan-20260804.md §1](entry-exit-separation-implementation-plan-20260804.md)**
  참조 — **구현 시 이 문서 §4.2가 아니라 계획문서 §1/§4를 따를 것.**

---

## 7. 재현

```bash
# §2, §2.1, §2.2의 실측 스크립트는 root-cause-diagnosis 문서와 동일 데이터
# (arena_ohlcv_bars BTC 2023-05~2024-07, /tmp/bullval/macro_rows.json)로
# algorithms.explain_signal()을 매 봉 재현해 passed_conditions 시계열을 추출,
# 조건별 지속확률(lag-1 자기상관)과 진입 다음봉 조건 이탈을 집계한 것.
# 임시 스크립트(/tmp/bullval/exit_trigger.py)는 세션 종료 시 소멸 —
# 재실행 시 이 문서 §2/§2.1/§2.2 표의 정의대로 재작성.
```

## 관련 문서
- [root-cause-diagnosis-where-to-look-20260803.md](root-cause-diagnosis-where-to-look-20260803.md) — 이 설계가 답하는 진단(P1)
- [historical-bull-market-backtest-20260803.md](historical-bull-market-backtest-20260803.md) — §2/§2.1이 사용한 상승장 데이터 출처
- `src/arena/algorithms.py:886` — 기존 `exit_hold_override()` 구현(§3 근거, §4.3 확장 대상)
- `src/arena/spot_policy.py:88-95` — 현재 청산 트리거 코드(§1 근거)
