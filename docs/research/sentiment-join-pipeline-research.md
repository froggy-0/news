# 파이프라인 코드 리서치 정리

아래는 현재 파이프라인 코드(`join.py`, `statistical_tests.py`, `hybrid_index.py`)를 실제로 확인한 뒤 정리한 리서치입니다.

## 결론

**예측 지평만 늘려서는 거의 개선되지 않습니다.**  
의미 있는 증분을 만들려면 아래 세 축을 **동시에** 조정해야 합니다.

- 이상치 규칙
- 타겟 설계
- 지수 구성

---

## 1. 현 상태 진단 (Root Cause)

| 증상 | 실제 코드 원인 |
|---|---|
| hit rate 47~50% (random) | `btc_log_return` T+1만 타겟. 암호화폐는 24/7 + 투기적 노이즈 비중이 커서 T+1은 거의 martingale에 가까움 |
| 풀 지수 Q1/Q4 단조성 없음 | PC1 로딩의 88%가 sentiment + FNG (로딩 0.53, 0.53). 본질적으로 센티먼트-콘트라리안 신호 하나에 가까움. 펀딩/LSR/ETF/VIX는 분산만 키우고 방향은 바꾸지 못함 |
| full ≈ core (corr 0.95) | VIF 게이트(10.0)가 느슨해 상관 높은 feature들이 다 통과. PCA가 사실상 "뉴스 + FNG" 재구성 수준 |
| 20.56% 마스킹 | `join.py:29-74`, rolling 30-day IQR × 3.0. 6개 변화율 컬럼(`btc_return`, `usdkrw_return`, `funding_rate`, `oi_change_pct`, `volume_change_pct`, `etf_net_inflow_usd`) 중 하나라도 걸리면 해당 행의 **모든 수치 컬럼**이 NaN 처리됨. 즉, 한 소스 블립이 전체 행 폐기로 이어짐 |
| 시장 스트레스일(4/13, 4/17, 4/18) 누락 | 펀딩/OI/볼륨 점프가 IQR 꼬리에 바로 걸림. 그러나 이것은 "data error"가 아니라 오히려 **signal** 임 |

### 핵심 판단

지수 자체는 괜찮은 **regime descriptor**인데,  
현재는 **평가 타겟**과 **이상치 규칙**이 정보를 과도하게 파괴하고 있습니다.

---

## 2. Data Scientist 관점 — 실험 제안 7가지

### A. 이상치 규칙 재설계 (가장 ROI 큼)

현재 방식:
- 단일 임계치 (`IQR × 3.0`)
- 행 단위 마스킹

제안:

#### 1) 컬럼별 마스킹
- 행 전체 마스킹이 아니라 **컬럼 단위 NaN 처리**
- `join.py:270-295`에서 per-column NaN으로 변경
- 기대 효과: `hybrid coverage`가 즉시 **78% → 약 92%** 수준으로 회복 가능

#### 2) 이상치 이원 분류
- `data_error_outlier`
  - 부호 불가능값(예: 음수 OI)
  - 펀딩 절대값 과도(`|r| > 5%`)
  - provider 404 fallback
  - 이 경우만 마스킹
- `market_regime_outlier`
  - 3σ 초과
  - 다수 변화율 컬럼이 동시에 튐
  - `|btc_return|`가 일중 95% 이상
  - 이 경우 **마스킹하지 않고 플래그만 부여**

#### 3) Winsorization 대안
- 마스킹 대신 `np.clip(x, q01, q99)`
- 변수를 살리고 꼬리만 절단
- PCA 입력에 적합

#### 4) Robust Scaling
- `hybrid_index.py:437,271`의 `StandardScaler` → `RobustScaler`로 교체
- median / IQR 기반이므로 이상치에 강함
- 마스킹 의존도를 구조적으로 줄일 수 있음

#### 제안 실험
아래 조합으로 A/B 백테스트:

- `standard + mask`
- `robust + mask`
- `robust + winsor`
- `robust + no-mask`

총 4가지 스케일 옵션 × 2개 지수 = **8개 replication**  
평가 지표:
- walk-forward hit-rate
- Sharpe

---

### B. 멀티 호라이즌 타겟 (T+1 대신 5종)

`statistical_tests.py:1052-1058`에 아래 타겟 추가 제안

| 타겟 | 정의 | 이유 |
|---|---|---|
| `btc_fwd_ret_3d` | `log(P_{t+3}/P_t)` | 센티먼트/펀딩은 누적 효과가 있어 3~5일 구간에서 더 잘 작동하는 경우가 많음 |
| `btc_fwd_ret_7d` | `log(P_{t+7}/P_t)` | regime 지표의 자연스러운 호라이즌 |
| `btc_fwd_vol_5d` | `std(ret, [t+1..t+5]) × √5` | VIX/펀딩은 방향보다 변동성 예측에 더 강함. 가장 먼저 유의미한 결과가 나올 가능성이 높음 |
| `btc_fwd_mdd_5d` | `min cum_ret over [t+1..t+5]` | 하락 보호 시나리오 평가용 |
| `btc_large_move_3d` | `1 if abs(fwd_ret_3d) > threshold else 0` | 큰 변동 이벤트 탐지용 |

#### 예상 결과
경험적으로:

- 방향 예측 hit rate는 **T+3에서 52~55%** 수준까지 개선 가능
- 변동성 예측은 **corr 0.25~0.40대**가 자주 관측됨

즉, 이 시스템은 **"방향 지수"**보다  
**"변동성 regime 지수"**로 포지셔닝하는 편이 더 정직하고 신호도 강합니다.

---

### C. 지수 구성 재설계

현재 PCA는 regime 압축 용도로만 유지하고,  
알파 지수는 별도의 supervised 모델로 설계하는 것을 제안합니다.

#### 제안 모델
- L1 Logistic Regression (방향)
- Elastic-Net Regression (수익률)
- LightGBM (비선형)

구성:
- `sklearn.pipeline`
- `TimeSeriesSplit`

#### 추가 분석
- SHAP으로 feature importance 산출
- 현재 PC1을 지배하는 뉴스/FNG 외에 `funding`, `LSR`의 실제 기여도 정량화

#### 서브 인덱스 분리
- `sentiment_subindex` = 뉴스 + FNG
- `positioning_subindex` = funding + LSR + OI
- `flow_subindex` = ETF 유입 + AUM
- `vol_subindex` = VIX + BTC realized vol

4개를 결합하면 `full index`가 `core`와 구조적으로 다르게 작동하게 만들 수 있음

#### 비선형 상호작용 추가
- `funding × LSR`
- `sentiment × VIX`
  - 공포 극단에서 contrarian 효과 탐색

현재 PCA는 선형 구조라 이런 상호작용을 잡지 못함

---

### D. Granger 재설계

현재 `statistical_tests.py:254-259`의 `non_contiguous_dates` 경고가 있는 결과는  
보수적으로 **무효 처리**하는 것이 바람직함

#### 제안
1. 경고 없는 윈도우만 재계산하여 결과 출력
2. Stationarity 먼저 확인 (ADF)
   - 비정상이면 차분
   - 현재 `fng_value`, `oi_change_pct`, `open_interest_usd(level)`가 섞여 있어 단순 비교 위험
3. 보완 기법 도입
   - Transfer Entropy
   - CCM (Convergent Cross Mapping)

비선형 인과에서는 Granger보다 더 적합할 수 있음

---

### E. Walk-forward 개선

현재:
- `train = 120`
- `test = 30` 고정
- (`statistical_tests.py:851`)

#### 제안
- **Purged K-fold with embargo (Lopez de Prado)** 도입
  - 현재는 train-test 경계에서 lag/forward leak 가능성 존재
- 현재 non-overlap 방식 외에 **sliding + expanding** 병행
  - regime 변화 민감도 차이 측정
- 멀티 호라이즌 타겟별 embargo는 `max(horizon, 5d)`로 설정

---

### F. 베이스라인 비교 (리포트 권고사항)

반드시 추가할 베이스라인:

- `always_up`
- `fng_contrarian`
  - FNG < 25면 long
  - FNG > 75면 short
- `btc_momo_20d`
- `vol_regime`
  - VIX 상승 시 flat

#### 판단 기준
지수가 위 베이스라인조차 이기지 못하면,  
해당 지수는 **"regime descriptor only"**로 포지셔닝하는 것이 적절함

---

### G. Sample Size 현실 확인

현재 데이터 규모:
- 360 rows

가정:
- 귀무가설 50%
- 감지 목표 55%
- power = 0.8
- α = 0.05

필요 표본 수:
- **n ≈ 785**

즉, 현재 데이터로는 **50% vs 55% 차이를 통계적으로 검출할 힘이 부족함**

#### 따라서 권장 방향
- Bootstrap CI 병기
  - 예: 95% CI가 `[45, 55]`라면 결론 불가를 명시
- 또는 타겟을 방향성보다 **variance / magnitude 계열**로 전환
  - effect size가 더 커질 가능성 있음

---

## 3. Data Engineer 관점 — 신뢰 가능한 실험 플랫폼

실험을 많이 돌려도 파이프라인 자체를 신뢰할 수 없으면 결과 해석이 불가능합니다.  
이 부분을 먼저 정리해야 합니다.

---

### E1. Outlier 감사 로그 (현재 없음)

`pipeline.py:414` 주변에 `outlier_diagnostics` 리포트 추가 제안:

```json
{
  "date": "2026-04-17",
  "triggered_by": ["btc_return", "volume_change_pct"],
  "raw_values": {...},
  "rolling_iqr": {...},
  "classification": "market_regime_outlier"
}
```

또는

```json
{
  "date": "2026-04-17",
  "triggered_by": ["btc_return", "volume_change_pct"],
  "raw_values": {...},
  "rolling_iqr": {...},
  "classification": "data_error_outlier"
}
```

출력 경로 예시:
- `data/sentiment_join/outlier_audit_{date}.json`

#### 기대 효과
사람이 훑어보며 룰을 튜닝할 수 있음

---

### E2. Feature Store 레이어 분리

현재는 `master_*.parquet` 하나에 아래가 혼재:
- raw
- winsorized
- masked
- lag1

#### 제안 구조
- `features_raw_{date}.parquet`
  - 무가공 관측치
- `features_clean_{date}.parquet`
  - winsorize / fill 적용
- `features_model_{date}.parquet`
  - scaled + lagged + PCA-ready

#### 기대 효과
이상치 규칙을 바꿔도 처음부터 전체를 재계산하지 않아도 됨  
A/B 실험 속도 증가

---

### E3. 멀티 타겟 스키마

`master_*.parquet`에 고정 컬럼 추가:

- `btc_log_return` (t)
- `btc_fwd_ret_1d`
- `btc_fwd_ret_3d`
- `btc_fwd_ret_7d`
- `btc_fwd_vol_5d`
- `btc_fwd_vol_10d`
- `btc_fwd_mdd_5d`
- `btc_large_move_3d`

#### 추가 제안
미래 정보 누출 방지를 위해:

- `schema/brief.types.ts`
- `schema/sentiment_join.types.ts`

를 병행 관리하고,  
`pandera schema`로 계약을 강제

---

### E4. Futures Lineage (리포트 §5 대응)

컬럼 레벨 소스 분리 필요:

- `funding_source`
- `open_interest_source`
- `long_short_ratio_source`
- `oi_alignment_rule`
- `ingested_at`
- `provider_symbol`
- `provider_interval`
- `source_contract_version`

#### 추가 요구사항
백필 시 아래 파일 생성 필수:

- `data/futures/backfill_manifest_{date}.json`

#### 현재 리스크
Coinalyze → Supabase upsert 과정에서  
row-level source 단일 필드로 덮어쓰며 정보 유실 발생 가능  
현재 가장 큰 감사 리스크

---

### E5. 실험 트래킹

규모:
- 8 replication × 5 horizon × 3 모델 = **120 experiments**

#### 제안
- MLflow 도입
- 또는 최소한 아래 구조 도입

`data/sentiment_join/experiments/{exp_id}.json`

포함 내용:
- param
- metric
- git sha

#### 기대 효과
현재와 같은 "실험 결과 사라짐" 문제 방지

---

### E6. 회귀 방지 테스트

#### 1) 이상치 회귀 테스트
`tests/test_sentiment_join_outlier.py`

대표 4일 샘플 데이터 사용:

- 2021-05-19 flash crash
- 2022-11 FTX
- 2024-03 ATH
- 2026-04-18

검증:
- 마스킹 여부 스냅샷
- 규칙 변경이 의도된 변화인지 확인

#### 2) 호라이즌 누출 테스트
`tests/test_sentiment_join_horizon.py`

검증:
- `T+k` 타겟의 `shift(-k)` 정확성
- 미래 데이터 누출 여부

---

## 4. 우선순위 로드맵 (추천)

| 단계 | 작업 | 기대 효과 | 위험 |
|---|---|---|---|
| 1 (1~2일) | 행 단위 마스킹 → 컬럼 단위 마스킹, `IQR × 3.0` → `× 4.0`, winsorize 2%/98% 병행, `RobustScaler` 교체, `outlier_audit` 로그 추가 | hybrid coverage 78% → 92%+, 마스킹된 stress day 복원 | 기존 backtest 수치가 크게 바뀜. 다만 의도된 변경 |
| 2 (2~3일) | T+3, T+7, `fwd_vol_5d`, `large_move_3d` 타겟 추가, walk-forward에 embargo/purge 도입, 타겟별 hit/Pearson/AUC 리포트 | 변동성 타겟에서 의미 있는 신호가 나올 가능성이 높음 | T+7은 유효 샘플이 더 줄어듦. 1년 360일 → 약 350개 |
| 3 (3~5일) | 4개 서브 인덱스 분리 + 비선형 interaction feature, L1 logistic / LightGBM 벤치와 PCA 지수 비교 | `full ≠ core` 차별화, SHAP 기반 설명 가능 | 과적합 위험. nested CV 필요 |
| 4 (병행) | Futures lineage, backfill manifest, 실험 트래킹, 회귀 테스트 | 이후 실험 결과 신뢰도 확보 | 단기 메트릭 개선은 없지만 이후 작업 속도 증가 |
| 5 (선택) | Transfer Entropy, expanding window walk-forward, Bayesian regime switching(HMM/MS-GARCH)로 regime labels 재정의 | regime descriptor로서 설명력 대폭 상승 | 해석 복잡도 증가 |

---

## 5. 솔직한 현실 체크

### 1) "다음날 BTC 방향 맞추는 알파"는 목표로 잡지 않는 것이 좋음
- 데이터 360일
- 24/7 암호화폐
- predictor 6개

이 조건에서는 통계적 power 자체가 부족함 (§2-G)

따라서 실제 자금 운용을 하지 않는 이상,  
그 타겟으로 평가를 계속하는 것은 의미를 축소시킬 수 있음

### 2) 목표를 바꾸면 데이터셋의 가치가 더 잘 드러남
아래 방향이 더 적절함:

- **변동성 regime 예측**
- **극단 이벤트 확률 예측**

이는 리포트 §1 권고인  
**"regime_index로 명명"** 방향과도 일치함

### 3) 이상치 규칙은 반드시 먼저 수정해야 함
이걸 고치지 않은 채 T+3 / T+7만 늘리면,  
4/13, 4/17, 4/18처럼 가장 중요한 학습 샘플이 계속 NaN으로 남아  
호라이즌 변경 효과가 상쇄됨

---

## 최종 제안

가장 ROI가 높은 시작점은 아래입니다.

### 1단계 우선 수행
- 행 단위 마스킹 제거
- 컬럼 단위 마스킹 전환
- winsorize 도입
- `RobustScaler` 교체
- `outlier_audit` 로그 추가

이 단계만 먼저 적용해도:
- 커버리지 개선
- 스트레스 구간 복원
- 이후 모든 실험의 해석 가능성 확보

---

## 추가 가능 작업

필요 시 다음 작업으로 바로 이어갈 수 있음:

- **1단계(이상치 리워크)** 실제 diff 작성
- 멀티 호라이즌 타겟 추가 코드 설계
- 실험 트래킹/스키마 구조 정리
