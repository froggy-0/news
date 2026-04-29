# Sentiment Join P0 개선 결과 보고서

**작성일**: 2026-04-30  
**PR**: [#95 feat(sentiment-join): P0 개선](https://github.com/froggy-0/news/pull/95)  
**기준 실행**: `SENTIMENT_JOIN_LOOKBACK_DAYS=540 python scripts/build_sentiment_join.py`

---

## 1. 개요

이번 P0 개선은 다음 4가지 항목을 목표로 진행했다.

| # | 항목 | 목표 | 결과 |
|---|---|---|---|
| 1 | Lookback 확장 | 365d → 540d | ✅ 완료 |
| 2 | 거래비용 현실화 | 왕복 0.2% (편도 10bps) 반영 | ✅ 완료 |
| 3 | 이상치 정책 리팩터링 | 유효 신호 손실 방지 | ✅ 완료 |
| 4 | 신규 파생 피처 | ETF log1p, usdkrw gap flag | ✅ 등록 완료 |

---

## 2. 데이터 확장: 540d Lookback + 로컬 백필

### 배경

기존 Lookback 365일 → 540일로 확장 시, R2에 보관된 데이터가 2025-01-01부터 시작해 갭 발생.  
540일 기준 필요 최초 날짜: **2024-11-05** → 실제로는 2024-10-01부터 안전하게 백필.

### 해결

로컬 `dataset/data/processed/{YYYY}/{MM}/{YYYY-MM-DD}.jsonl` 파일을 직접 읽는 백필 소스 추가.

```
scripts/backfill/sources/local_dataset.py  (신규)
scripts/backfill_news_sentiment.py         --source {api,local} 옵션 추가
```

**백필 결과**: 2024-10-01 ~ 2024-12-31 (92일, 약 87분 소요)

### 데이터 통계 (540일 기준)

| 항목 | 값 |
|---|---|
| 전체 rows | 540 |
| 이상치 필터 후 | 540 (셀 단위 71개 마스크, 13.2%) |
| Granger 검정 대상 | 540 rows |
| Granger 유의미 쌍 | 28 / 72 (38.9%) |

---

## 3. 거래비용 현실화: 왕복 0.2% = 편도 10bps

### 변경 전 문제

- 기존 코드: 포지션 전환 1회당 **20bps** 일괄 차감
- 문제 1: long→short 플립 시 실제로는 청산 + 진입 = 2 legs인데 1회만 차감 (과소 부과)
- 문제 2: 왕복 0.4%에 해당하는 수수료로, 실제 Binance 기준 대비 과도하게 보수적

### 변경 후

**편도 10bps** 기준으로 거래 구조에 따라 정확한 leg 수 적용:

| 전환 유형 | Leg 수 | 차감 비용 |
|---|---|---|
| flat → long / flat → short (신규 진입) | 1 leg | 10bps |
| long → flat / short → flat (청산) | 1 leg | 10bps |
| long → short / short → long (직접 플립) | 2 legs | 20bps |

**Baselines 구현 개선**: `aligned` 전체 배열 기준으로 legs 계산 후, 청산(→0) 비용을 이전 active 날짜에 귀속. flat 기간이 Sharpe 계산에서 제외될 때 exit 비용이 누락되는 문제 방지.

### 변경 적용 범위

| 위치 | 함수 | 변경 |
|---|---|---|
| `baselines.py` | `evaluate_baseline()` | `transaction_cost_bps=20` → `fee_per_leg_bps=10`, legs 계산 로직 신규 |
| `statistical_tests.py` | walk-forward `compute_backtest` | `20.0` → `10.0` |
| `statistical_tests.py` | alpha predictor `compute_backtest` × 3 | `20.0` → `10.0` |
| `statistical_tests.py` | `_payoff_diagnostics` | `20.0` → `10.0` |

---

## 4. 이상치 정책 컬럼별 분리

### 배경 및 문제

기존 정책: rolling 30일 IQR×3.0 초과 셀 → NaN 처리 (regime_stress 조건 충족 시 면제)

**실제 손실 사례**:

| 날짜 | 컬럼 | 실제 값 | 왜 문제인가 |
|---|---|---|---|
| 2026-03-12 | `etf_net_inflow_usd` | +$1.8B | BTC는 조용한데 기관 대규모 매수 → 선행 신호 |
| 2025-10-06~08 | `etf_net_inflow_usd` | +$8~9억×3일 | 기관 누적 매수 패턴 → 전부 NaN |
| 2026-02-05 | `btc_return` | -14% | 급락인데 regime_stress 미충족(volume 보통) → NaN |
| 2025-04-11 | `usdkrw_return` | -2.4% | 관세 쇼크 원화 급락, btc +4.8% → 역상관 신호 |

### 해결: 컬럼별 정책 분리

```
① usdkrw_return       — ColumnMaskPolicy 유지 (rolling IQR×3, regime_stress 면제)
② volume_change_pct   — WinsorizePolicy (q01/q99 clip, 방향 정보 보존)
   oi_change_pct      — WinsorizePolicy (동일)
③ btc_return          — 마스킹 제외 (타겟 직결 변수, NaN=학습 구멍)
④ etf_net_inflow_usd  — 마스킹 제외 + log1p 파생 피처 (fat-tail 안정화)
⑤ funding_rate        — 마스킹 제외 (DATA_ERROR_RULES abs>0.05 로만 오류 제거)
```

### 신규 파생 피처

#### `etf_net_inflow_usd_log1p`

ETF 순유입액의 fat-tail 분포를 안정화하는 부호 보존 log1p 변환:

```python
sign(x) * log1p(|x|)
```

- 원본 척도: 수억~수십억 달러 → IQR 기반 마스킹에 취약
- 변환 후: 연속적이고 압축된 분포, 방향성(+/-)은 보존
- `etf_net_inflow_usd_log1p_lag1`: T+7 BTC 방향 예측 alpha predictor로 등록

#### `usdkrw_gap_flag`

날짜 갭 > 1일 (공휴일·주말 재개장) 여부 플래그:

```python
gap_days = dates.diff().dt.days.fillna(1)
usdkrw_gap_flag = (gap_days > 1).astype(float)
```

- 공휴일 이후 환율 급락은 실제 쇼크가 아닌 갭 재개장일 가능성
- `usdkrw_gap_flag_lag1`: 전날 갭 여부를 보조 피처로 활용

---

## 5. 최종 백테스트 결과

### Walk-Forward 검증 (core, 편도 10bps, embargo 7일)

| 지표 | 값 |
|---|---|
| 기간 | 2025-03-12 ~ 2026-04-05 (13 folds) |
| avg_alpha | **+0.074** |
| avg_hit_rate | **51.2%** |
| stability | **0.661** |
| positive alpha folds | **6 / 13 (46.2%)** |
| train_days | 120 |
| test_days | 30 |

### Baselines (편도 10bps)

| 전략 | Sharpe | 95% CI | Hit Rate | Coverage |
|---|---|---|---|---|
| `vol_regime` | **+2.448** | [-0.86, +5.67] | 54.9% | 98.1% |
| `btc_momo_20d` | +0.698 | [-2.43, +4.06] | 49.3% | 95.0% |
| `always_up` | -0.034 | [-3.92, +4.07] | 52.5% | 98.7% |
| `fng_contrarian` | -2.763 | [-8.18, +2.42] | 47.6% | 38.9% |

> `fng_contrarian` Sharpe가 낮은 이유: long↔short 직접 플립이 많아 2 legs 비용이 더 많이 적용됨 (이전 방식 -2.674 → 현재 -2.763, 정확한 계산).

### 개별 피처 백테스트 전체 (편도 10bps)

| 피처 | Sharpe | 95% CI | Alpha | 거래 수 | 누적 수익 |
|---|---|---|---|---|---|
| `vix_regime_score_lag1` | **+0.813** | [-0.52, +2.21] | +0.450 | 46 | +0.266 |
| `fng_value_lag1` | **+0.794** | [-0.91, +2.33] | +0.239 | 35 | +0.310 |
| `btc_bear_regime_lag1` | +0.232 | [-1.32, +1.84] | +0.042 | 17 | +0.113 |
| `fng_change_1d_x_bear_lag1` | +0.217 | [-1.75, +1.70] | +0.082 | 136 | +0.067 |
| `full_hybrid_index_score_lag1` | +0.011 | [-1.67, +1.68] | -0.169 | 30 | +0.003 |
| `core_hybrid_index_score_lag1` | -0.012 | [-1.79, +1.55] | +0.015 | 39 | -0.004 |
| `sentiment_momentum_lag1` | -0.028 | [-1.80, +1.72] | +0.013 | 173 | -0.014 |
| `news_sentiment_mean_lag1` | -0.079 | [-1.86, +1.56] | -0.108 | 93 | -0.037 |
| `vix_lag1` | -0.195 | [-1.56, +1.35] | -0.170 | 22 | -0.124 |
| `funding_rate_x_bear_lag1` | -0.236 | [-1.63, +1.30] | -0.176 | 50 | -0.105 |
| `sentiment_accel_lag1` | -0.318 | [-1.72, +1.04] | -0.133 | 305 | -0.148 |
| `sentiment_momentum_x_bear_lag1` | -0.329 | [-2.17, +1.86] | -0.090 | 82 | -0.117 |
| `fng_change_1d_lag1` | -0.413 | [-1.88, +1.00] | -0.181 | 312 | -0.195 |
| `fng_change_5d_lag1` | -0.430 | [-2.04, +1.10] | -0.103 | 150 | -0.180 |
| `usdkrw_gap_flag_lag1` | -0.878 | [-1.52, -0.82] | -0.086 | 2 | -0.015 |
| `etf_net_inflow_usd_log1p_lag1` | -1.994 | [-3.38, -0.37] | -0.787 | 184 | -0.802 |

---

## 6. 신규 피처 평가 및 다음 단계

### `etf_net_inflow_usd_log1p_lag1` — 현재 형태로 미채택

- Sharpe -1.994, 거래 수 184회 → 과도한 진입 빈도
- 원인: threshold=0 기준으로 log1p(inflow) > 0 = long 판정 → 유입이 조금이라도 있으면 전부 진입
- **개선 방향**: threshold를 높이거나 (예: 상위 25th percentile 초과), 방향 반전 여부 검토, 기간 필터 추가

### `usdkrw_gap_flag_lag1` — 샘플 부족

- 거래 2회, 유의미한 통계 불가
- 공휴일 갭 이벤트가 540일 내 희소 → 보조 컨텍스트 피처로는 유효하나 독립 신호로는 한계

### 상위 신호 요약

`vix_regime_score_lag1`과 `fng_value_lag1`이 Sharpe +0.8 수준으로 가장 유효한 T+7 선행 신호.  
두 피처 모두 CI 하단이 음수라 통계적 유의성은 아직 약하나, alpha > 0 방향성은 일관적.

---

## 7. 변경 파일 목록

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `scripts/backfill/sources/local_dataset.py` | 신규 | 로컬 JSONL 백필 소스 |
| `scripts/backfill_news_sentiment.py` | 수정 | `--source {api,local}` 옵션, 로컬 최대 3650일 |
| `src/morning_brief/analysis/sentiment_join/pipeline.py` | 수정 | 이상치 정책 컬럼별 분리, log1p·gap_flag 파생 피처 |
| `src/morning_brief/analysis/sentiment_join/baselines.py` | 수정 | `fee_per_leg_bps=10`, 플립 2 legs, exit 비용 귀속 로직 |
| `src/morning_brief/analysis/sentiment_join/statistical_tests.py` | 수정 | 10bps 통일, 신규 피처 등록 (predictor/ADF/source 매핑) |
| `tests/analysis/test_sentiment_join/test_statistical_tests.py` | 수정 | Granger pair 수 업데이트 (TARGET 10→11, 총 23→24) |
