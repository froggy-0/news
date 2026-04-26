# Master Parquet 데이터 품질 분석 리포트

**파일**: `master_20260426.parquet`  
**분석일**: 2026-04-26  
**기간**: 2025-04-26 ~ 2026-04-26 (366 calendar days)  
**관점**: Data Engineer — 파이프라인 신뢰성 · 피처 품질 · ML 투입 가능성

---

## 1. 개요 (Executive Summary)

| 항목 | 값 | 평가 |
|---|---|---|
| 유효 행 수 | 363 / 366 | ✅ 99.2% 커버리지 |
| 컬럼 수 | 62 | — Tier 1 신규 12컬럼 포함 |
| 이상치 행 | 48 (13.2%) | ⚠️ 개선 필요 |
| Granger 유의 쌍 | **0 / 23쌍** | 🔴 전체 skip |
| 방향 라벨 균형 | up 49.3% / down+flat 50.7% | ✅ 랜덤워크에 가깝게 균형 |
| ETF 소스 기록 | `unknown` | 🔴 lineage 버그 |
| ffill 적용 일수 | 225 | ⚠️ 점검 필요 |

---

## 2. 데이터 커버리지

### 2.1 날짜 갭

달력 갭 2건 — 모두 최근 데이터:

```
2026-04-19 → 2026-04-21  (gap: 2일)
2026-04-21 → 2026-04-24  (gap: 3일)
```

4월 마지막 3주에 집중된 갭. 해당 구간이 forward target(`btc_fwd_ret_7d`) 계산에 영향을 줄 수 있다. 주말 + 공휴일 조합 가능성이 있으나, 뉴스 수집 실패 여부와 별도로 확인 필요.

### 2.2 소스별 커버리지

| 소스 | null% | 비고 |
|---|---|---|
| `news_sentiment_mean` | 0% | ✅ 완전 |
| `fng_value` | 0% | ✅ 완전 |
| `btc_log_return` | 0% | ✅ Binance |
| `usdkrw_log_return` | **2.8%** | ⚠️ 한국 공휴일 10일 (5월 어린이날·개천절 등) |
| `funding_rate` | 0% | ✅ Supabase |
| `open_interest_usd` | 0% | ✅ Supabase |
| `etf_total_btc` | 0.6% | ✅ gold_history 모드 |
| `etf_net_inflow_usd` | 0.8% | ✅ |
| `vix` | 0.6% | ✅ FRED |

`usdkrw` null은 KRX 휴장일로 구조적이며, ML 투입 전 휴장일 마스킹 또는 ffill 처리 정책 명시 필요.

### 2.3 Regime 피처 초기 NaN

```
btc_ma_200d / btc_above_ma200   : 27.0% null  ← 처음 98일 (min_periods=100 미달)
btc_drawdown_90d                : 7.7% null   ← 처음 28일 (min_periods=90 미달)
```

lookback=365일 기준에서 MA200은 처음 **98행(2025-04-26 ~ 2025-08-01)** 이 NaN. 이 기간은 레짐 컨디셔닝 불가 — Tier 2에서 warm-up window 확장 또는 대안 피처 검토 필요.

---

## 3. Granger 인과성 검정 — 전체 skip 문제 🔴

### 3.1 현황

```
granger_executed   : True
granger_eligible_rows : 363
유의 엔트리 (BH adj.) : 0 / 0  ← 결과 자체가 비어 있음
```

363행으로 검정은 트리거됐지만 **모든 23쌍에서 `_run_granger_all_lags`가 None을 반환**했다.

### 3.2 원인 분석

파이프라인의 정상성 게이트(ADF + KPSS 합동 검정) 결과:

| 컬럼 | 결론 | Granger 가능 여부 |
|---|---|---|
| `btc_log_return` | **stationary** | ✅ target 가능 |
| `fng_change_1d` | **stationary** | ✅ predictor 가능 |
| `sentiment_momentum` | **stationary** | ✅ predictor 가능 |
| `oi_change_pct` | **stationary** | ✅ predictor 가능 |
| `usdkrw_log_return` | **stationary** | ✅ predictor 가능 |
| `volume_change_pct` | **stationary** | ✅ predictor 가능 |
| `fng_value` | non_stationary | ❌ 게이트 탈락 |
| `news_sentiment_mean` | non_stationary | ❌ 게이트 탈락 |
| `funding_rate` | **trend_stationary** | ❌ stationary=False → 탈락 |
| `btc_long_short_ratio` | **trend_stationary** | ❌ 탈락 |
| `etf_net_inflow_usd` | **trend_stationary** | ❌ 탈락 |

**문제**: `sentiment_momentum`, `fng_change_1d`, `oi_change_pct`, `usdkrw_log_return`, `volume_change_pct`는 모두 stationary로 확인됐음에도 0 엔트리. 이는 `_ensure_stationary`가 **쌍별 dropna 서브셋**에 대해 재검정하는 과정에서 KPSS 결과가 달라졌을 가능성이 높다.

### 3.3 권장 조치

1. `_run_granger_all_lags` 내부에서 stationary predictor/target 쌍이 None을 반환할 때 `skip_reason`을 로깅하도록 추가
2. `trend_stationary` 시리즈는 현재 `stationary=False`로 처리 → 차분 후 재시도 로직을 `_ensure_stationary`에 명시적으로 추가하거나 `trend_stationary`도 조건부 통과 허용 검토
3. 단기적으로는 Pearson/Spearman 상관을 Granger 대체 지표로 사용

---

## 4. 피처 품질 분석

### 4.1 Tier 1 신규 피처 (delta + regime)

#### Level → Delta 변환

| 피처 | mean | std | null% | 평가 |
|---|---|---|---|---|
| `fng_change_1d` | -0.089 | 5.96 | 0.3% | ✅ 정규분포에 가까움 |
| `fng_change_5d` | -0.372 | 10.76 | 1.4% | ✅ |
| `sentiment_momentum` | -0.001 | 0.112 | 0.8% | ✅ zero-mean, AR 구조 제거됨 |
| `sentiment_accel` | -0.001 | 0.115 | 0.3% | ✅ |

`sentiment_momentum`이 `news_sentiment_mean`(r=0.2423)보다 `btc_log_return`과 **더 높은 동시 상관**(r=0.3222, p≈0)을 보임 → delta 변환 효과 확인.

단, **lag1 → forward return** 예측력은 아직 유의미하지 않음:

```
sentiment_momentum_lag1 vs btc_fwd_ret_1d : r=-0.086, p=0.103
sentiment_momentum_lag1 vs btc_fwd_ret_3d : r=-0.015, p=0.786
fng_change_1d_lag1      vs btc_fwd_ret_1d : r=-0.058, p=0.270
```

→ 동시 상관은 강하지만 **선행 신호로서의 예측력은 아직 미검증**. 이 갭은 Granger skip 문제 해결 후 재평가 필요.

#### BTC 레짐 피처

| 기간 | 레짐 | 일수 | 비중 |
|---|---|---|---|
| 2025-08-02 ~ | **bear** (below MA200) | 191일 | 52.6% |
| 2025-08-02 ~ | **bull** (above MA200) | 74일 | 20.4% |
| 2025-04-26 ~ 2025-08-01 | unknown (warm-up NaN) | 98일 | 27.0% |

레짐별 다음날 up_rate:

```
bull regime  : 54.1%  (+4.8pp vs 전체)
bear regime  : 46.1%  (-3.2pp vs 전체)
regime gap   : 8.0pp
```

8pp의 레짐 스프레드는 단독으로 의미있는 조건 변수. **bear 구간에서 down 방향 bias**가 확인됨. 이를 모델에서 상호작용 항으로 활용할 경우 hit-rate 개선 가능성 있음.

### 4.2 감성 지표

```
news_sentiment_mean : mean=0.018, std=0.187, range=[-0.503, +0.439]
n_articles          : mean=237, median=247  ← 충분한 기사 수
fng_value           : mean=39.9, std=22.7, range=[5, 79]
```

**월별 추세** (주요 구간):

| 월 | 감성 | FnG | BTC 월 수익률 | up_rate |
|---|---|---|---|---|
| 2025-05 ~ 07 | +0.15 ~ +0.22 | 60 ~ 71 | +0.3 ~ +0.4% | 52 ~ 57% |
| 2025-11 ~ 2026-02 | -0.26 ~ -0.10 | 10 ~ 21 | -0.4 ~ -0.6% | 36 ~ 48% |
| 2026-04 (현재) | -0.007 | 19.3 | +0.35% | 60.9% |

bear 구간(2025-11 ~ 2026-02)에서 감성·FnG가 일관되게 하락 → 후행 지표임은 분명하나, **레짐 전환 신호**로서의 활용 가능성은 있음.

**lag1 기반 이진 예측**은 아직 변별력 부족:

```
lag1 감성 상위 50% : up_rate 48.1%
lag1 감성 하위 50% : up_rate 50.8%  ← 오히려 역전

lag1 FnG > 50 (탐욕) : up_rate 49.3%
lag1 FnG ≤ 50 (공포)  : up_rate 49.6%
```

단변량 threshold로는 예측력 없음. **레짐과의 교호작용 모델** 또는 앙상블 필요.

### 4.3 선물 시장 피처

| 피처 | mean | 비고 |
|---|---|---|
| `funding_rate` | 0.0001 | 정상 범위 (8h 기준) |
| `open_interest_usd` | 84억 USD | — |
| `btc_long_short_ratio` | 1.477 | long 우위 지속 |

소스: Supabase 캐시 (coverage 100%). `lsr_api_capped: True`, `oi_api_capped: True` → API 상한선으로 일부 데이터가 잘렸을 가능성. 수집 로직에서 페이지네이션/재조합 확인 필요.

### 4.4 Hybrid Index

```
full_hybrid_index_score : mean=50.0, std=20.2, range=[0, 100]  ✅ 정규화 정상
core_hybrid_index_score : mean=53.4, std=21.5, range=[0, 100]  ✅
```

null 1.4% / 0.6% — warm-up NaN과 동일한 패턴.  
`features_used`, `excluded_features` 필드가 stats 메타데이터에서 None으로 기록됨 → hybrid index 계산 메타 로깅 버그 확인 필요.

---

## 5. 이상치 분석

```
is_outlier=True : 48 / 363 (13.2%)
```

월별 분포:

| 월 | 이상치 수 | 비고 |
|---|---|---|
| 2026-01 | 10 | bear 본격 시작 |
| 2026-02 | 9 | FnG=10 (극도 공포) 구간 |
| 2026-03 | 7 | — |
| 2025-09 | 5 | — |
| 2025-10 | 4 | — |

이상치의 **40% 이상이 2026-01~02**에 집중. 이 구간은 BTC -16 ~ -19% 하락 월이어서 **구조적 변동성 확대 기간**으로 볼 수 있다. rolling IQR window=60 적용 이후에도 13.2%는 여전히 높은 수준.

현재 이상치 감지 대상 컬럼: `btc_return`, `usdkrw_return`, `funding_rate`, `oi_change_pct`, `volume_change_pct`

**고려 사항**: 이상치 마스킹 행은 ML 학습에서 제외되는데, bear 구간 38%가 이상치라면 해당 구간의 학습 데이터가 극도로 부족해질 수 있음. 마스킹 대신 **이상치 플래그를 피처로 포함**하는 전략도 검토 필요.

---

## 6. Forward Target 분포

| 타겟 | 유효 행 | mean | 비고 |
|---|---|---|---|
| `btc_fwd_ret_1d` | 362 (99.7%) | -0.07% | ✅ 충분 |
| `btc_fwd_ret_3d` | 360 (99.2%) | -0.21% | ✅ |
| `btc_fwd_ret_7d` | 356 (98.1%) | -0.48% | ✅ |
| `btc_fwd_vol_5d` | 358 (98.6%) | 1.96% | ✅ |
| `btc_large_move_3d` | 360 (99.2%) | — | ✅ |

**btc_large_move_3d 분포**:
```
0 (소폭 이동) : 222 (61.7%)
1 (대폭 이동) : 138 (38.3%)
```

large_move 비율 38.3%는 예상보다 높음. 3일 누적 기준 임계값 정의 확인 필요. 클래스 불균형은 낮아 SMOTE 등 처리 불필요.

---

## 7. 파이프라인 데이터 품질 이슈 요약

### 🔴 Critical

| 이슈 | 위치 | 영향 |
|---|---|---|
| Granger 전체 skip | `statistical_tests.py` | 인과성 근거 없이 피처 선택 |
| `etf_source = "unknown"` | `join.py` 소스 lineage | ETF 데이터 출처 추적 불가 |

### ⚠️ Warning

| 이슈 | 위치 | 영향 |
|---|---|---|
| `btc_ma_200d` 초기 27% NaN | lookback 부족 | 레짐 피처 불완전 (warm-up 98일) |
| 이상치율 13.2% | outlier detection | bear 구간 학습 데이터 손실 |
| `ffill_days: 225` | transform pipeline | 실제 갭 규모 확인 필요 |
| `usdkrw_log_return` 2.8% null | 한국 공휴일 | 처리 정책 미문서화 |
| `lsr_api_capped: True` | binance API | LSR 데이터 completeness 불확실 |

### ✅ Confirmed Good

| 항목 | 상태 |
|---|---|
| MASTER_SCHEMA pandera 검증 통과 | ✅ |
| 감성 데이터 100% ok 상태 | ✅ |
| Futures coverage 100% | ✅ |
| ETF gold_history 99.5% | ✅ |
| VIX FRED 99.4% | ✅ |
| Tier 1 delta / regime 피처 정상 생성 | ✅ |
| BH-FDR 다중검정 보정 로직 | ✅ |

---

## 8. Tier 2 우선순위 권고

현재 데이터 기준으로 hit-rate 개선을 위한 다음 단계:

### 8.1 즉시 (파이프라인 버그 수정)

1. **Granger skip 원인 로깅**: `_run_granger_all_lags`에서 None 반환 시 skip_reason 기록 → 어떤 쌍이 왜 탈락하는지 명시
2. **`etf_source = "unknown"` 수정**: join.py에서 ETF attrs 접근 경로 점검
3. **regime warm-up 단축**: lookback을 500일+ 또는 BTC 가격 초기 fetch 기간 확장

### 8.2 단기 (신호 품질)

4. **레짐 × 감성 교호작용 피처**: `btc_above_ma200 × sentiment_momentum` 조합 → regime-conditioned 예측
5. **이상치 전략 재검토**: 마스킹 대신 `is_outlier` 피처화 또는 regime-aware 이상치 임계값 분리
6. **usdkrw 공휴일 처리 정책 명시**: ffill 또는 제외 처리를 validate.py 데이터 컨트랙트에 문서화

### 8.3 중기 (피처 보강)

7. **BTC 온체인 지표 추가**: 고래 이동, 거래소 잔고 변화 → funding rate 대비 더 선행하는 신호
8. **뉴스 텍스트 임베딩 유사도**: 현재 감성 점수는 단일 스칼라 — 토픽 분류(규제/ETF/반감기) 구분 시 신호 개선 가능
9. **Cross-asset signal**: 금, S&P500, DXY와의 상관 구조 변화 → regime 전환 조기 감지

---

## 9. 데이터 계보 (Lineage)

```
Binance Klines ──── btc_log_return, btc_return, btc_quote_volume
                └── btc_ma_200d, btc_drawdown_90d, btc_above_ma200 (pipeline compute)

R2 Sentiment ─────── news_sentiment_mean, n_articles, ...
                  └── sentiment_momentum, fng_change_* (pipeline compute)

CoinGlass / Supabase ─ funding_rate, open_interest_usd, btc_long_short_ratio

Alternative.me ─────── fng_value

ETF (gold_history) ─── etf_total_btc, etf_total_aum_usd, etf_net_inflow_usd
                        ⚠️ source = "unknown" (lineage bug)

FRED ────────────────── vix

KRX / Supabase ──────── usdkrw_log_return, usdkrw_return
                        ⚠️ 10일 null (공휴일)
```

---

*분석 기준 파일: `master_20260426.parquet` (295KB, 363 rows × 62 cols)*  
*생성일: 2026-04-26*
