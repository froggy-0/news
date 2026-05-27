# Walk-Forward Validation — 시계열 검증의 정공법
### 상세 이론 참고 자료
> 데이터 기준: R2 latest.json (2026-05-25, n=539)  
> 전체 연구 서사 (질문→데이터→PCA→WFV→61.8% 흐름): [research-narrative.md](research-narrative.md)  
> 슬라이드 스크립트: [wfv-slide-script.md](wfv-slide-script.md)  
> 고민·실패·결정 기록: [signal-design-log.md](signal-design-log.md)

---

## 목차

1. [배경: 이 프로젝트와 검증의 관계](#1-배경)
2. [시계열 데이터가 특별한 이유](#2-시계열-데이터가-특별한-이유)
3. [함정 1 — K-Fold: Lookahead Bias](#3-함정-1--k-fold-lookahead-bias)
4. [함정 2 — 단순 분할: 안정성 불확실](#4-함정-2--단순-분할-안정성-불확실)
5. [Walk-Forward Validation](#5-walk-forward-validation)
6. [핵심 개념: Embargo](#6-핵심-개념-embargo)
7. [Sliding vs. Expanding Window](#7-sliding-vs-expanding-window)
8. [이 프로젝트의 실제 적용](#8-이-프로젝트의-실제-적용)
9. [검증이 보장하는 것 / 보장하지 않는 것](#9-검증이-보장하는-것--보장하지-않는-것)
10. [한 눈에 비교](#10-한-눈에-비교)
11. [이론 배경 & 참고문헌](#11-이론-배경--참고문헌)

---

## 1. 배경

### 1.1 프로젝트 파이프라인

```
암호화폐 뉴스 텍스트
     │
     ▼  FinBERT (ProsusAI/finbert)
     │  article_score = p_positive − p_negative  ∈ [−1, +1]
     │  daily_score = 해당일 기사 평균
     │
     ▼  PCA 하이브리드 지수
     │  8개 시장 지표(F&G, VIX, 펀딩비, ETF 순유입 등) + 뉴스 감성
     │  → PC1이 분산 85.4% 설명 → 시장 위험선호 복합 점수 (0~100)
     │
     ▼  vol_regime_v2 신호
     │  VIX < 90일 q40  AND  실현변동성 < 45일 q45  AND  20 < F&G < 80
     │  조건 충족 시 포지션 진입 (coverage ≈ 56.2%)
     │
     ▼  T+7 예측
        7일 후 BTC 상승/하락 방향 → Hit Rate(적중률) 측정
```

**Hit Rate**: 예측 방향이 실제와 일치한 비율. 50%는 동전 던지기 수준.

### 1.2 핵심 질문

> 모델이 학습에 사용하지 않은 데이터에서도 61.8%를 낼 수 있는가?

이 질문에 올바르게 답하는 절차가 **Walk-Forward Validation**이다.
잘못된 검증법을 쓰면 실전에서 무너지는 모델을 "좋다"고 착각하게 된다.

---

## 2. 시계열 데이터가 특별한 이유

### 2.1 일반 ML 데이터 vs. 시계열 데이터

| 구분 | 일반 ML 데이터 | 시계열 데이터 |
|---|---|---|
| 예시 | 이미지, 설문 응답, 고객 데이터 | BTC 가격, 뉴스 감성, 펀딩비 |
| 샘플 간 관계 | **독립(i.i.d.)** | **순서 의존** — 어제가 오늘에 영향 |
| 셔플 가능? | ✅ 가능 | ❌ 불가 — 순서 자체가 정보 |
| 검증 방법 | K-Fold 사용 가능 | Walk-Forward 필수 |

### 2.2 순서가 왜 결정적인가 — 실수치로

> **Granger F-통계**: "A의 과거값을 추가했을 때 B의 미래 예측력이 얼마나 향상되는가"를 수치화. 값이 클수록 A가 B를 더 강하게 선행함. F-분포 기반 가설검정으로, p<0.05면 우연이 아닌 통계적 선행성.

이 프로젝트의 Granger 인과성 검정 결과(n=539, BH-FDR 보정 후):

```
방향                                    F-통계   해석
──────────────────────────────────────────────────────────
btc_log_return → long_short_ratio       F=483    ← 가격이 포지션을 즉각 바꿈
btc_log_return → fng_value              F=420    ← 가격이 공포탐욕지수를 만듦
btc_log_return → news_sentiment_mean    F=104    ← 가격이 뉴스 논조를 만듦
─────────────────────────── (역방향이 압도적으로 강함)
news_sentiment_mean → btc_log_return    F=  8    ← 뉴스 → BTC: 52배 약함
```

**BTC가 오른 날 이후 며칠간 긍정적 뉴스가 만들어진다.** 가격이 뉴스를 만들지, 뉴스가 가격을 만드는 게 아니다. 시계열에서 순서를 무시하면 이 인과 방향이 뒤집혀 보인다.

> **검정 규모**: 순방향 18쌍 + 역방향 5쌍, 각 lag=1,2,3 → 전체 **69 검정**에 BH-FDR 보정 적용. 위 F값 4개는 대표 수치이며, 현재 표본(539행) 기준 2%p Hit Rate 차이를 감지하려면 통계적으로 ~15,000행이 필요해 파워가 약 8~10% 수준이다.

---

## 3. 함정 1 — K-Fold: Lookahead Bias

### 3.1 시험지 비유

> 시험 전날 밤, 친구가 말한다.
> **"나 이번 시험 다 맞을 것 같아. 어제 답안지 보고 공부했거든."**
>
> 그건 실력이 아니다. K-Fold를 시계열에 쓰면 머신러닝 모델이 정확히 같은 실수를 저지른다.

### 3.2 K-Fold가 시계열에서 저지르는 실수

K-Fold는 데이터를 무작위로 섞어 Train/Test를 구성한다. 시계열에 적용하면:

```
시간 →   1월    2월    3월    4월    5월    6월
─────────────────────────────────────────────────
fold 1: [TEST] ─────────── TRAIN ───────────────
fold 2:        [TEST] ─────── TRAIN ────────────
fold 3:               [TEST] ──── TRAIN ────────
```

fold 1: Test가 1월, Train에 2~6월이 포함.
→ **2월, 3월을 보고 1월을 예측 — 미래로 과거를 맞히는 것.**

모델은 "2월에 BTC가 올랐고, 1월 뉴스 감성도 높았다"는 사실을 역방향으로 학습한다.
실전에는 미래 정보가 없으니 **실전 성능이 검증 성능보다 현저히 낮다.**

이를 **Lookahead Bias** 또는 **Data Leakage**라고 한다.

### 3.3 K-Fold가 적합한 상황

K-Fold는 이미지, 텍스트 분류, 설문 분석처럼 **샘플 간 순서가 없는 경우에만 올바르다.**
시계열 데이터에 K-Fold를 쓰는 것은 방법론 오류다.

---

## 4. 함정 2 — 단순 분할: 안정성 불확실

K-Fold 대신 시간 순서를 지켜 앞 80%를 Train, 뒤 20%를 Test로 나누면 Lookahead Bias는 없다. 그러나 문제가 하나 남는다.

```
시간 →  ──────────────────────────────────────────────────►
        [─────────── TRAIN 80% ────────────][── TEST 20% ──]
                                             ↑
                                    딱 한 번만 평가
```

**단 한 번의 평가는 충분하지 않다.** 테스트 기간이 운 좋게 Bull 시장이었다면 모델이 좋아 보이고, Bear 시장이었다면 나빠 보인다.

> 코인 투자자가 "나 지난 달 수익 냈어"라고 말해도, 그 달에 시장 전체가 폭등했다면 실력인지 운인지 알 수 없다.

**다양한 시장 환경에서 성능이 안정적인지 알려면 여러 번 평가해야 한다.** 이것이 Walk-Forward가 여러 fold를 쓰는 이유다.

---

## 5. Walk-Forward Validation

### 5.1 핵심 원칙

> **"미래를 절대 보면 안 된다"는 원칙을 슬라이딩 윈도우로 기계적으로 반복한다.**

### 5.2 작동 방식

아래는 이 프로젝트의 기본 신호 검증 경로(경로 A, train=120일/test=30일)를 기준으로 한 다이어그램이다.

```
시간 →
┌──────────────────────┐  [Embargo 7일]  ┌──────────┐
│   TRAIN (120일)      │ ──────────────► │ TEST 30일│  fold 1
└──────────────────────┘                 └──────────┘
         ↓ 30일 앞으로 이동
  ┌──────────────────────┐  [Embargo 7일]  ┌──────────┐
  │   TRAIN (120일)      │ ──────────────► │ TEST 30일│  fold 2
  └──────────────────────┘                 └──────────┘
            ↓ 30일 앞으로 이동
    ┌──────────────────────┐  [Embargo 7일]  ┌──────────┐
    │   TRAIN (120일)      │ ──────────────► │ TEST 30일│  fold 3
    └──────────────────────┘                 └──────────┘
              ↓ 반복 (~13회)
```

각 fold는 독립된 검증 실험이다. 여러 fold에 걸친 평균 성능이 "다양한 시장 환경에서의 안정성"을 의미한다.

> **파라미터가 두 가지인 이유**: ML 모델(컴포짓 스코어)을 검증하는 경로 B는 train=240일/test=45일로 파라미터가 다르다. 두 경로의 차이는 §8에서 상세히 설명한다.

### 5.3 각 Fold의 세 단계

**① TRAIN — 모델 학습**
- 이 구간 데이터만으로 PCA fit, Scaler fit, 파라미터 확정
- 이 구간 바깥은 절대 참조하지 않는다

**② EMBARGO — 격리 구간 (건너뜀)**
- 아무것도 하지 않고 비워둠
- T+7 예측에서 발생하는 label leakage 차단 (§6에서 상세 설명)

**③ TEST — transform-only, 성능 측정**
- TRAIN 구간으로 fit한 모델을 그대로 가져와 적용만 한다 (다시 fit 하지 않음)
- 모델 입장에서 이 구간은 "처음 보는 데이터"
- 여기서 나온 Hit Rate가 진짜 OOS 성능

> **Transform-only가 중요한 이유**: PCA를 test 구간에 다시 fit하면, test 구간의 통계(평균·분산)가 모델에 스며든다. 이 역시 미래 정보 유출이다. Train으로만 fit한 모델을 그대로 test에 적용해야 진짜 OOS 검증이 된다.

---

## 6. 핵심 개념: Embargo

### 6.1 비유로 먼저 이해하기

> 시험장 입장 전 대기실이 없으면, 먼저 시험 본 사람이 나오면서 문제를 알려줄 수 있다.
> Embargo는 이 정보 유출을 물리적으로 막는 격리 구간이다.

### 6.2 T+7 예측에서 왜 7일을 비워야 하는가

```
[TRAIN 구간]                            [TEST 구간]
  ...  12월 30일 / 12월 31일  |  1월 1일  1월 2일  ...
                  │
        이 날의 정답(label)
        = 7일 후 = 1월 7일 가격 방향
                                 ↑
                  Test 첫 날(1월 1일)의 피처에는
                  12월 31일 시장 정보(lag1)가 포함됨
                  → Train 마지막 날의 label 정보가 간접적으로 새어나감
```

**해결**: Train과 Test 사이에 7일을 비워두면, Train 마지막 날(12-31)의 label이 닿는 시점(1-7)이 TEST 시작(1-8)보다 앞에 위치해 leakage가 원천 차단된다.

```
TRAIN 마지막 날   │←────── Embargo 7일 ──────→│  TEST 시작
   (12-31)        1/1  1/2  1/3  1/4  1/5  1/6    (1-8~)
                  ────────────────────────────
                         비워둠 (학습도 평가도 하지 않음)
```

### 6.3 Embargo 계산 공식

$$\text{Embargo} = \max(\text{예측 horizon},\ \text{최소 안전 마진}\ 5\text{일})$$

| 예측 Horizon | Embargo |
|---|---|
| T+1 | 5일 (최소 마진 적용) |
| T+3 | 5일 (최소 마진 적용) |
| **T+7** | **7일 ← 이 프로젝트** |
| T+14 | 14일 |

---

## 7. Sliding vs. Expanding Window

### 7.1 Sliding Window — Train 크기 고정

```
시간 ───────────────────────────────────────────────────►
fold 1:  [══════ TRAIN 240일 ══════]  [E]  [TEST]
fold 2:        [══════ TRAIN 240일 ══════]  [E]  [TEST]
fold 3:              [══════ TRAIN 240일 ══════]  [E]  [TEST]
                     ↑ 앞 구간이 버려지고 뒤 구간이 추가됨
```

- Train 크기 **항상 240일로 고정**
- 오래된 데이터가 빠지고 최신 데이터가 들어옴
- 시장 구조가 시간에 따라 변할 때 유리 (오래된 패턴이 잡음이 되는 경우)

### 7.2 Expanding Window — 시작점 고정, Train이 커짐

```
시간 ───────────────────────────────────────────────────►
fold 1:  [═══ TRAIN 240일 ═══]  [E]  [TEST]
fold 2:  [═══════ TRAIN 270일 ═══════]  [E]  [TEST]
fold 3:  [═══════════ TRAIN 300일 ═══════════]  [E]  [TEST]
         ↑ 시작점은 항상 첫 날(고정), Train이 점점 길어짐
```

- Train 크기 **증가** (데이터가 쌓일수록)
- 전체 역사적 패턴 누적 반영 (Bull/Bear 사이클 모두 포함)
- 매일 실시간으로 점수를 갱신하는 운영 모델에 적합

### 7.3 비교

| 구분 | Sliding | Expanding |
|---|---|---|
| Train 크기 | 고정 | 점점 증가 |
| 오래된 데이터 | 제외 | 유지 |
| 최근 패턴 강조 | ✅ | 보통 |
| 장기 사이클 반영 | 약함 | ✅ |
| 실시간 운영 | 보통 | ✅ 적합 |

**이 프로젝트는 두 방식 모두 사용한다.**
- 다중 fold 검증 → Sliding (경로 A: Train 120일/~13 fold, 경로 B: Train 240일/9 fold)
- 매일 자동 운영 → Expanding (어제까지 전체로 학습, 오늘만 예측)

---

## 8. 이 프로젝트의 실제 적용

### 8.1 구현 파라미터 — 검증 경로가 두 개 존재한다

이 프로젝트는 검증 대상에 따라 서로 다른 WFV 파라미터를 사용한다. 하나의 WFV가 아니다.

#### 경로 A — 기본 신호 검증 (`walk_forward_validate`)
vol_regime_v2, fng_contrarian 등 규칙 기반 신호의 Hit Rate·Sharpe를 측정한다.

> **vol_regime_v2 조건**: `VIX < 90일 rolling q40 AND 실현변동성 < 45일 rolling q45 AND 20 < F&G < 80`  
> 세 조건 모두 만족하는 날에만 진입(coverage ≈ 56.2%). 파라미터 선택 근거는 [signal-design-log.md §4-B](signal-design-log.md#4-b-왜-vol_regime_v2-조건이-vix-q40-rv-q45-fg-20-80인가)를 참조.

| 파라미터 | 값 | 설정 이유 |
|---|---|---|
| Train window | **120일** | PCA(8 피처) 안정적 fit 최소치, T+7 레이블 40일 확보 여유 포함 |
| Test window | **30일** | 1개월 단위 독립 평가 |
| Embargo | 7일 | T+7 horizon과 정확히 일치 |
| Step size | 30일 | test_days와 동일 — 겹침 없음 |

**fold 1 최소 데이터**: 120 + 7 + 30 = **157일**  
**539행 기준 fold 수**: `(539 − 157) / 30 ≈` **~13 fold**

#### 경로 B — 컴포짓 스코어 검증 (`_composite_folds`)
L1Logistic, ElasticNet, LightGBM 등 ML 모델 조합 점수를 검증한다.

| 파라미터 | 값 | 설정 이유 |
|---|---|---|
| Train window | **240일** | ML 모델이 충분한 표본으로 피처 가중치를 안정적으로 추정 |
| Test window | **45일** | OOS 레이블 최소 38개(T+7 제외 후) 확보 |
| Embargo | 7일 | T+7 horizon |
| Step size | 30일 | 1개월 단위 슬라이딩 |

**fold 1 최소 데이터**: 240 + 7 + 45 = **292일**  
**539행 기준 fold 수**: `floor((539 − 292) / 30) + 1 =` **9 fold**

> 이전 버전 문서의 "240일/45일/9 fold"는 경로 B(컴포짓 스코어) 기준으로 정확하지만, vol_regime_v2 검증(경로 A)에는 적용되지 않는 수치다.

### 8.3 매일 자동 운영: Expanding Window OOS

다중 fold 검증과 별개로, 파이프라인은 매일 Expanding Window 방식으로 점수를 산출한다.

```
[매일 자동 실행]

전체 과거 데이터 (2024-11-30 ~ 어제)
     ↓  PCA fit + Scaler fit (이 데이터로만 학습)
오늘 데이터 (오늘 하루 — 학습에 쓰인 적 없음)
     ↓  transform-only (pipeline.py: today_score_method = "oos_expanding")
오늘의 하이브리드 지수 점수 → 실전 OOS 예측값
```

정상 작동 시 매일 생성되는 점수는 학습에 쓰인 적 없는 데이터에서 나온 OOS 값이다.

**주의**: OOS 계산이 실패하면 파이프라인은 조용히 in-sample 점수로 대체한다 (`today_score_method = "in_sample_fallback"`). 이 경우 해당 날짜의 점수는 OOS 보장이 없다. 아티팩트의 `todayScoreMethod` 필드로 구분할 수 있다.

### 8.4 Walk-Forward가 보장한 성능 수치

R2 기준 2026-05-25, n=539 (경로 A 기준, train=120/test=30):

| 신호 | Hit Rate | 95% CI | CI 하한 > 50%? | Sharpe |
|---|---|---|---|---|
| `news_sentiment_mean` (뉴스 단독) | 48.9% | [45.2%, 52.6%] | ❌ | — |
| `fng_value` (F&G 단독) | 50.0% | [46.3%, 53.5%] | ❌ | — |
| `full_hybrid_index_score` (PCA Full) | 47.6% | [42.9%, 52.0%] | ❌ | — |
| `core_hybrid_index_score` (PCA Core) | 49.3% | [45.7%, 52.8%] | ❌ | — |
| **`vol_regime_v2`** (변동성 필터) | **61.8%** | **[52.0%, 71.6%]** | **✅ 유일** | **5.24** |

95% CI 계산에는 **Circular Block Bootstrap** (n=1,000, block=14일)을 사용한다.
T+7 예측값은 7일씩 레이블이 겹쳐 자기상관이 있기 때문에, 일반 정규분포 CI는 지나치게 좁다.
14일 단위 연속 블록으로 샘플링해 자기상관 구조를 보존하며 CI를 산출한다.

**주의 — Worst Fold**: vol_regime_v2의 Fold 1(2024-11-18 ~ 2025-03-27)의 Hit Rate는 **0.508** 으로 동전 던지기 수준이다. 평균 61.8%는 이후 fold들이 끌어올린 결과이며, 데이터가 부족했던 초기 구간의 신호 불안정성이 반영된 수치다.

**vol_regime_v2 drift 검증** (R2, 2026-05-25 기준):
- 신호가 발화한 날(n=275)의 7일 평균 수익: **+58.9%** 적중
- 신호가 발화하지 않은 날(n=253)의 7일 평균 수익: +49.6% 적중
- kept > dropped 검정 p-value: **0.018** — 신호가 실제로 좋은 날을 골라낸다는 통계적 근거

---

## 9. 검증이 보장하는 것 / 보장하지 않는 것

### ✅ Walk-Forward가 보장하는 것

| 항목 | 내용 |
|---|---|
| Lookahead Bias 없음 | 모델이 미래를 학습에 사용하지 않았음 |
| 시계열 순서 존중 | 항상 과거 → 미래 방향으로만 예측 |
| Label Leakage 없음 | Embargo 7일로 T+7 label 정보 유출 차단 |
| 다양한 환경 평가 | 경로 A ~13 fold, 경로 B 9 fold — 다수의 독립된 시장 구간 |

### ❌ Walk-Forward가 보장하지 않는 것

| 항목 | 이유 |
|---|---|
| 미래 성능 보장 | 과거 OOS가 좋아도 미래 시장 구조가 바뀔 수 있음 |
| Regime Change 대응 | Train 기간에 없던 새 패턴(BTC ETF 승인 등)에 취약 |
| 실전 수익 보장 | Hit Rate는 거래 비용·슬리피지를 반영하지 않음 |
| 통계적 유의성 | BH-FDR 보정 후 현재 표본에서 어떤 예측자도 q ≤ 0.10 미달 |
| OOS 점수의 순수성 | `today_score_method = "in_sample_fallback"` 발생 시 룩어헤드 가능 |

### 추가 맥락 — 운영 적용 보류 이유

WFV Hit Rate 61.8%가 좋아 보여도 운영 적용이 보류된 이유는 두 가지 층위의 검증이 있기 때문이다.

**`decision = "promote"`** (롤링 overlay gate 기준, 3조건 모두 통과):
- rolling 14일 hit_rate ≥ 55% ✅
- rolling 14일 coverage [45%–70%] ✅
- rolling p-value 중앙값 < 0.10 ✅

**`decision_strict = "research_only"`** (통계적 유의성 기준):
- 69 검정에 BH-FDR 보정 → 현재 표본에서 `fdr_q = 1.0` (전체 예측자 미달)
- 2% Hit Rate 차이 감지에 ~15,000행 필요 → 현재 539행으로 파워 ~8–10%
- CI hard separation 미충족 → advisory 수준에 그침
- BH-FDR을 선택한 이유(Bonferroni 대비), 가설 축소 전략: [signal-design-log.md §4-D·§4-F](signal-design-log.md#4-d-왜-bh-fdr인가-bonferroni-대신)

> 거래 비용: vol_regime_v2의 breakeven fee는 **~53.5 bps/leg**로 taker 수수료(7bps) 대비 충분한 마진이 있다. 수익성 측면의 장벽은 아니지만, 통계 파워 문제가 해소(60일 drift 누적)될 때까지 운영 적용을 보류 중이다.

> 참고: 백테스트 기준 `vol_regime_v2`의 Sharpe 95% CI는 [0.48, 10.24]로 하한이 0을 초과한다.
> 거래 비용(taker ≈7bps) 차감 후에도 양의 Sharpe 가능성이 있으나, CI 폭이 넓어 표본 확대 후 재확인이 필요하다.

---

## 10. 한 눈에 비교

| 방법 | Lookahead Bias | 시계열 순서 | 다중 평가 | Label Leakage 방지 | 이 프로젝트 사용 |
|---|---|---|---|---|---|
| K-Fold | ❌ 있음 | ❌ 무시 | ✅ | ❌ | ❌ 금지 |
| Train/Test 단순 분할 | ✅ 없음 | ✅ | ❌ 1회 | ✅ 가능 | 초기 확인용 |
| Walk-Forward Sliding (경로 A) | ✅ 없음 | ✅ | ✅ ~13 fold | ✅ Embargo 7일 | **기본 신호 검증** |
| Walk-Forward Sliding (경로 B) | ✅ 없음 | ✅ | ✅ 9 fold | ✅ Embargo 7일 | **ML 컴포짓 스코어** |
| Walk-Forward Expanding | ✅ 없음 | ✅ | ✅ | ✅ Embargo | **매일 실시간 운영** |
| Purged K-Fold + Embargo | ✅ 없음 | ✅ | ✅ | ✅ 최강 | 복수 horizon 시 고려 |

**한 줄 요약**:
> Walk-Forward는 "미래를 절대 보면 안 된다"는 원칙을 기계적으로 강제하는 검증 방법이다.  
> Embargo는 T+N 예측에서 레이블 정보가 새는 것을 막는 격리 구간이다.  
> 시계열에서 K-Fold를 쓰는 것은 답안지 보고 공부하는 것과 같다.  
> 이 프로젝트는 검증 대상(규칙 기반 신호 vs. ML 모델)에 따라 파라미터가 다른 두 경로를 병행한다.

---

## 11. 이론 배경 & 참고문헌

### 11.1 Lookahead Bias (수식)

시계열 예측 모델 $f$가 시점 $t$에서 $t+k$를 예측할 때, 올바른 학습 조건:

$$f \text{ 는 } \{x_1, x_2, \ldots, x_t\} \text{ 만으로 학습되어야 한다}$$

K-Fold 문제: Test set에 $t' < t$ 가 있고 Train set에 $t'' > t'$가 있으면 $x_{t''}$가 $x_{t'}$의 결과를 이미 담고 있다 → 정보 유출.

### 11.2 Embargo 계산 근거

T+$k$ 예측에서 Train 마지막 시점 $T_{end}$의 레이블 $y_{T_{end}+k}$는 $T_{end}+1, \ldots, T_{end}+k$ 시점의 미래 정보를 포함한다. Test는 최소 $T_{end}+k+1$ 시점부터 시작해야 한다.

$$\text{Embargo} = \max(k,\ \text{safety\_margin})$$

이 프로젝트: $k=7$, safety\_margin=5 → Embargo = 7일.

### 11.3 Block Bootstrap — CI 계산

T+7 예측값은 7일씩 레이블이 겹쳐 자기상관을 가진다. 일반 정규분포 CI는 이를 무시해 지나치게 좁다. **Circular Block Bootstrap** (Politis & Romano, 1992):

- 블록 길이 = 14일 (= T+7 × 2, ACF 기반 선택 — 겹치는 레이블 구조 보정)
- n = 1,000번 반복 시뮬레이션
- 14일 단위 연속 블록으로 샘플링 → 자기상관 구조 보존

결과: vol_regime_v2 Hit Rate 61.8%의 **95% CI = [52.0%, 71.6%]** (R2 확인 수치)

### 11.4 참고문헌

| 저자 | 제목 | 핵심 기여 |
|---|---|---|
| Lopez de Prado (2018) | *Advances in Financial Machine Learning* | Purged K-Fold + Embargo 이론 정립 |
| Politis & Romano (1992) | "A Circular Block-Resampling Procedure for Stationary Data" | Circular Block Bootstrap 원전 |
| Politis & White (2004) | "Automatic Block-Length Selection for the Dependent Bootstrap" | ACF 기반 블록 길이 자동 선택 |
| Bergmeir & Benítez (2012) | "On the use of cross-validation for time series predictor evaluation" | 시계열 CV 방법론 종합 비교 |
| Hyndman & Athanasopoulos (2021) | *Forecasting: Principles and Practice* | 시계열 검증 교과서 기준 |

---

*슬라이드 스크립트: [wfv-slide-script.md](wfv-slide-script.md)*  
*메인 보고서: [report_final.md](../../report_final.md)*
