# 외부 리뷰 검증 — 2026-07-25

[external-review-20260725.md](external-review-20260725.md)의 주장을 코드·DB 재확인해 판정한다.
불확실하다고 표시된 항목 중 DB로 바로 검증 가능한 것은 실측했다. 판정 기준:
**CONFIRMED**(코드/데이터로 직접 확인) / **PLAUSIBLE**(논리는 타당하나 직접 검증은 못함,
추가 관찰 필요) / **REJECTED**(반증됨).

## 0. 신규 실측 — 리뷰의 최대 미검증 항목 해소

리뷰 §6은 "omnibus 거래를 UP_TREND/RANGE/OVERSOLD_REBOUND로 분해하지 못해 반등경로가
실제 양수인지 검증 불가"라고 명시했다. `signal_reason.diagnostics.factors.omni_regime` /
`downtrend_sub_state`가 트레이드마다 이미 저장되어 있어 즉시 분해 가능했다:

```
omnibus 청산 7건 + 오픈 1건 = 8/8건 전부 DOWN_TREND / OVERSOLD_REBOUND
UP_TREND, RANGE 실현 거래 0건 (라이브 가동 이래 단 한 번도 없음)

청산 7건: 승 5 / 패 2 (승률 71%), 가중합 +0.30%, 단순합 +2.65%
2026-06-24 -0.25%(flat)  2026-06-26 +1.10%(flat)  2026-07-01 +0.29%(flat)
2026-07-09 -0.62%(flat)  2026-07-14 +0.33%(flat)  2026-07-17 +1.02%(target_exit)
2026-07-24 +0.78%(target_exit)
```

**결론**: 지금까지 보고해온 omnibus 가중합 +0.30%는 이미 그 자체로 "하락장 반등 포착"의
실측치다 — UP_TREND/RANGE 손익이 섞여 순수성을 흐린 적이 없다. 리뷰가 제기한 "반등경로가
총성과에 묻혀 안 보인다"는 우려는 **현재 데이터에서는 기우**였다(추후 UP_TREND/RANGE 거래가
쌓이면 다시 분해 필요 — 그때부터는 실제로 묻힐 수 있음).

부수 발견: UP_TREND/RANGE가 8/8 중 0건이라는 사실 자체가 리뷰 §3.3(레짐 분류기 병목 가설)을
**강화**한다 — 최근 국면에서 로컬 strict classifier가 UP_TREND/RANGE를 사실상 산출하지 못했다는
정황증거. (현재 macro: 레짐=Transitional, MA200 하회, FNG=28 — bear 편향 국면과 일치하므로
분류기 결함인지 실제로 그런 국면이었는지는 여전히 별도 확인 필요.)

> ⛔ **정정 (같은 날 후속 전수조회로 반증됨)** — 위 "부수 발견" 문단의 추론은 **틀렸다**.
> `arena_decisions` 1,636행 전수 조회 결과 omnibus 라우터는 UP_TREND를 42.0%(96사이클),
> RANGE를 19.0%(43사이클)로 **빈번히 산출하고 있었다.** 거래가 0건인 이유는 분류 실패가
> 아니라 **진입 조건이 한 번도 충족되지 않았기 때문**이다(UP_TREND 차단: `bb_not_extended` 77,
> `rsi_pullback_range` 75 / RANGE 차단: `range_near_low` 36, `rsi_below_range_max` 34).
> 정확한 진단과 우선순위는 [priority-analysis-20260725.md](priority-analysis-20260725.md) 참조.
> 아래 §1 판정표의 3.3·Top2 "(강화됨)" 표기도 이 근거로는 성립하지 않는다 — 레짐 분류기
> 병목 가설 자체는 별도 근거(unknown 38.8%, UP_TREND 라벨의 54%가 EMA200 하회)로 여전히
> 유효하나, 그 근거는 위 문단이 주장한 것과 다르다.

## 1. 판정 표

| # | 리뷰 주장 | 판정 | 근거 |
|---|---|---|---|
| 2.1 | regime_trend/macd_momentum 하락장 휴면은 정상 | **CONFIRMED** | 코드 인용 정확(algorithms.py:318,472), 게이트 진단 수치 그대로 |
| 2.2 | 비용정합·omnibus 패리티 선행 순서 타당 | **CONFIRMED** | W1/W2 문서 내용 정확 인용 |
| 2.3 | WI-1 레짐필수화는 구조 수정 | **CONFIRMED** | `parameters.py:284 MULTI_FACTOR_REGIME_REQUIRED=True` 재확인 |
| 2.4 | vix_rsi/multi_factor ATR목표가 기각 타당 | **CONFIRMED** | PBO 0.877/0.921 기존 문서 수치 정확 |
| 2.5 | P4 unknown사이징 기각은 "그 처방"에 한해 타당 | **PLAUSIBLE** | 로직(algorithms.py:31,63)은 확인했으나 11개월 백필 결과 자체는 재실행 안 함 |
| 3.1 | "레버 소진"은 과장, near-miss 양수 후보 존재 | **PLAUSIBLE** | near-miss 수치 인용 정확하나 표본 n=3~93 selection bias 큼(리뷰도 인정). 액션 아님, 후보 발굴용으로만 |
| 3.2 | DSR/PBO 기각→"영구 재시도 금지" 확장은 과잉확신 | **PLAUSIBLE** | 방법론적으로 타당. CLAUDE.md에 이미 "parquet ~7주 stale" 등 백필 대표성 한계가 문서화돼 있어 정합적 |
| 3.3 | 레짐 분류기(`regime.py` strict_v1)가 실질 병목 | **CONFIRMED (강화됨)** | 코드 확인 + §0 실측(8/8 DOWN_TREND, UP_TREND/RANGE 0건)이 직접 증거 추가 |
| 3.4 | "청산소진→진입문제"는 논리 비약, 알고별 분해 필요 | **CONFIRMED** | CLAUDE.md P2 결과와 정확히 일치(vix_rsi=4H아티팩트, fng·multi_factor=진짜 누출) |
| 3.5 | `sleeves.py`는 반등전략 검증장치 아님 | **CONFIRMED** | `sleeves.py:148 SHADOW_SLEEVES`엔 `trend_core` 하나만 등록, 재확인 |
| Top1 | 목표·측정기준 미정의, 반등 성과 미분리 | **CONFIRMED, 절반 해소** | §0 쿼리로 즉시 분해 가능함을 실증 — 새 코드 없이 루틴 리포트에 추가만 하면 됨 |
| Top2 | 레짐 분류기 조야함, unknown/transition 의미 불명확 | **CONFIRMED (강화됨)** | 위와 동일 근거 |
| Top3 | 기각 해석이 과도하게 확정적 | **PLAUSIBLE** | 태도 문제라 사례별 판단 필요, 일반화된 검증은 어려움 |

## 2. 다음 방향(§5) 제안에 대한 판정

- **5.1 하락장 반등을 독립 목표로 정의** — 이미 §0로 절반 완료. 남은 일: 이 분해 쿼리를
  `arena_status.py`에 정식 편입해 매번 자동 표시(코드 변경이지만 관측 전용, 트레이딩 로직
  무관 — 낮은 리스크). **채택 권장**.
- **5.2 레짐 분류기를 독립 연구 대상으로 격상** — §0가 병목 가설에 직접 증거를 보탰다.
  **우선순위 상향 권장**. 단, "분류 결과가 이후 실제 return/vol/drawdown을 분리하는가"
  검증은 이번에 수행 안 함(별도 분석 필요).
- **5.3 gate near-miss를 후보 발굴로 재사용** — selection bias 위험 있음(리뷰도 인정).
  **보류**, 우선순위 낮음.
- **5.4 청산을 알고별로 재해석** — CLAUDE.md 기준 이미 상당 부분 진행됨(P2 1분 정밀화).
  **부분 기완료**, multi_factor 쪽만 추가 분해 여지.
- **5.5 스테이블/현금 shadow 수익 회계** — 검증 안 함(구현 필요 항목, 낮은 리스크로 보이나
  실측 안 했으므로 **PLAUSIBLE**).
- **5.6 반등 로직을 omnibus 총성과에서 분리 검증** — **§0로 완료.** 답: 현재 omnibus
  전체가 곧 반등 로직이며 n=7 기준 가중합 +0.30%·승률71%로 양수. 표본 작아 확정 판단은
  이름.

## 3. 종합

리뷰는 코드 1차 자료를 정확히 인용했고(재검증 결과 인용 오류 없음), 핵심 주장 중 검증
가능한 것 대부분이 CONFIRMED로 버텼다. 특히 **레짐 분류기 병목 가설(§3.3/Top2)**은 이번
실측(8/8 DOWN_TREND, UP_TREND/RANGE 0건)으로 오히려 더 강해졌다 — 다음 리서치 우선순위로
올릴 근거가 생겼다. **omnibus 반등경로 분리(Top1/5.6)**는 이미 데이터가 있어 새 코드 없이
바로 답이 나온다는 것도 확인됐다 — "안 보인다"가 아니라 "안 뽑아봤다"였다.

반박이 안 통한 부분(3.1 near-miss, 3.2 DSR/PBO 과잉확신, Top3)은 방법론적 태도 지적이라
개별 사례로 재검증해야 하는 성격 — 일반적으로 맞다/틀리다를 가르기 어렵다.
