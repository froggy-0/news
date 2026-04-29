# Sentiment Join 파이프라인 P0 개선 계획

**작성일:** 2026-04-29  
**기준 parquet:** `master_20260429.parquet` (365행 × 70컬럼, 2025-04-29 ~ 2026-04-29)  
**현재 독립 관측치:** ~49개 (T+7 overlap 기준, N/7)

---

## 개요

현재 파이프라인은 vix_regime_score_lag1 추가로 Sharpe +4.88을 달성했으나, T+7 overlap으로 실효 독립 관측치가 ~49개에 불과해 paired bootstrap CI 하한이 0에 근접해 있다. 운영 승격을 위해서는 아래 4개 항목을 순서대로 완료해야 한다.

---

## 항목 1 — Lookback 540d 확장

### 목표
독립 관측치 49개 → 77개로 확대해 bootstrap CI 하한을 0 초과로 확보

### 현재 상태 (코드 근거)

| 항목 | 값 | 파일:라인 |
|------|-----|-----------|
| 환경변수 | `SENTIMENT_JOIN_LOOKBACK_DAYS` | `config.py:54` |
| 기본값 | `365`일 | `config.py:57` |
| 하드 상한 | `730`일 (초과 시 `ValueError`) | `config.py:61` |
| 날짜 슬라이싱 | `today - timedelta(days=lookback_days)` | `pipeline.py:341-349` |
| 실효 독립 N | `lookback_days / 7` | T+7 overlap 특성 |

```python
# config.py:54-61
lookback_days = _env_bounded_int(
    "SENTIMENT_JOIN_LOOKBACK_DAYS",
    default=365,
    minimum=0,
    maximum=10_000,
)
if lookback_days < 1 or lookback_days > 730:
    raise ValueError("SENTIMENT_JOIN_LOOKBACK_DAYS must be between 1 and 730")
```

540일은 하드 상한(730) 이내이므로 코드 변경 없이 **환경변수 설정만으로 즉시 적용 가능**하다.

### 구현

```bash
SENTIMENT_JOIN_LOOKBACK_DAYS=540
```

### Data Scientist 검토

**타당성**
- 540d → 독립 N ≈ 77개. 양측 검정 power 0.8 달성을 위한 최소 N(effect size 0.3 기준) ≈ 70개를 충족.
- 730d(최대)는 N ≈ 104개이나, 데이터 소스(R2 뉴스, Supabase futures) 실제 커버리지가 먼저 확보되어야 한다.

**리스크**
- **regime shift**: 540일 내 2025 crypto 강세장·약세장이 혼재. 전체 기간 Sharpe가 특정 regime 쏠림을 가릴 수 있다. → fold별 Sharpe 편차가 핵심 진단 지표.
- **look-ahead contamination**: `today - 540d` 기준 슬라이싱이 매일 rolling되므로 가장 오래된 데이터가 매번 교체된다. 과거 기간에 현재 vix_regime 파라미터(warmup 220d)가 소급 적용되는 문제 없는지 확인 필요. (`pipeline.py:349`: `btc_history_days = lookback_days + regime_warmup_days`)

**추가 권장 지표**
- 연도별/분기별 슬라이스 hit rate 분해 → regime 편향 여부 조기 감지
- 데이터 추가 후 fold Sharpe CV(표준편차/평균)가 현재보다 낮아지는지 확인

---

## 항목 2 — 거래비용 20bps/roundtrip net-Sharpe

### 목표
Walk-forward fold payoff에서 실제 거래비용을 반영한 net-Sharpe를 산출해 gross-net 괴리를 진단

### 현재 상태 (코드 근거)

| 함수 | 기본값 | walk-forward override | 파일:라인 |
|------|--------|----------------------|-----------|
| `compute_backtest()` | `transaction_cost_bps=10.0` | `0.0`으로 override | `statistical_tests.py:989, 1331` |
| `evaluate_baseline()` | 없음 (비용 미반영) | — | `baselines.py:93-96` |
| 비용 적용 방식 | 로그공간 편도 차감 | `log(1 - bps/10000)` | `statistical_tests.py:1043` |
| 연환산 | `√365` | BTC 24/7 기준 | `statistical_tests.py:25` |

```python
# statistical_tests.py:1326-1331 — 현재 walk-forward
bt_result = compute_backtest(
    test_eval,
    score_lag1_col,
    threshold=50.0,
    return_col=return_col,
    transaction_cost_bps=0.0,   # ← 비용 미반영
)
```

```python
# baselines.py:93-96 — baseline도 비용 없음
strategy_ret = np.sign(active["signal"].to_numpy()) * active["ret"].to_numpy()
sigma = float(np.std(strategy_ret, ddof=1)) if len(strategy_ret) > 1 else 0.0
sharpe = float(np.mean(strategy_ret)) / sigma * math.sqrt(TRADING_DAYS_PER_YEAR)
```

### 구현

walk-forward 호출부(`statistical_tests.py:1331`)와 baseline(`baselines.py`)에 동일하게 `transaction_cost_bps=20.0` 전달.

비교 구조:
- `gross_sharpe`: 현재값 (bps=0)
- `net_sharpe`: 신규 (bps=20)
- `gross_net_gap = gross_sharpe - net_sharpe` → 이 값이 크면 실제 시그널 약함

### Data Scientist 검토

**타당성**
- 20bps roundtrip = 편도 10bps는 crypto 현물 maker fee 수준으로 현실적.
- 현재 로그공간 비용 적용(`log(1 - bps/10000)`)은 compounding 효과까지 반영한 정확한 방식.

**리스크**
- **baseline 비대칭**: baseline에 비용 미반영 시 signal vs baseline Sharpe 비교가 유리하게 왜곡된다. 반드시 baseline과 signal 모두 동일한 bps로 계산해야 공정한 paired 비교가 된다.
- **포지션 전환 빈도**: T+7 이진 신호 특성상 평균 weekly 전환이면 연간 ~52회. 20bps × 52 = 연 1,040bps = 10.4% 비용. Sharpe 1.0 전략도 net 기준으로 크게 낮아질 수 있다.

**추가 권장 지표**
- `n_trades / lookback_days` (연간화된 거래 빈도)
- `total_cost_bps = n_trades × 20bps` (총 비용 규모)
- 비용 민감도 분석: 10 / 20 / 30bps 시나리오별 net-Sharpe 테이블

---

## 항목 3 — 소스별 이상치 마스크

### 목표
전역 row-level 마스킹이 아닌 소스-컬럼 단위 셀 마스킹으로 데이터 손실 최소화

### 현재 상태 (코드 근거)

**이미 column 정책 사용 중** — 우선순위가 낮지만 구현 상태 정확히 이해 필요.

```python
# pipeline.py:552-564
_OUTLIER_IQR_COLS = [
    c for c in [
        "btc_return",
        "usdkrw_return",
        "funding_rate",
        "oi_change_pct",
        "volume_change_pct",
        "etf_net_inflow_usd",
    ] if c in master_df.columns
]
_outlier_result = OutlierPolicyFactory.create("column").apply(master_df, _OUTLIER_IQR_COLS)
```

```python
# outlier_policy.py:222-278 — ColumnMaskPolicy 핵심
mask_cells = iqr_col & ~regime_rows       # IQR 이상치 ∧ non-stress → 마스킹
stress_cells = iqr_col & regime_rows      # IQR 이상치 ∧ regime_stress → 보존 + 분류
```

IQR 기준:
- 윈도우: 30일 롤링
- 배수: 3.0×IQR (`join.py:30`)
- 기준값: 전일 rolling median (shift(1) — look-ahead 방지)

메트릭 수집:
```python
# pipeline.py:571-581
masked_count = int(_outlier_result.stats.get("masked_cells", 0))
masked_ratio = round(masked_count / max(len(analysis_df), 1), 4)
# regime_stress_rows: 마스킹 제외 이상치 행 수
```

### Data Scientist 검토

**타당성**
- 현재 구현은 이미 소스-컬럼 단위 셀 마스킹이므로 기본 목표는 달성된 상태.
- `regime_stress` 행 보존 처리는 위기 구간 데이터를 신호로 활용하려는 올바른 설계.

**현재 맹점**
1. **`sentiment_score` 계열 컬럼이 `_OUTLIER_IQR_COLS`에 없음**: 뉴스 FinBERT 점수 자체의 이상치(극단적 뉴스 집중일)는 현재 마스킹되지 않는다. 특히 `compound_signal` 생성에 직접 영향.
2. **IQR 윈도우 30일은 짧음**: 540d로 lookback 확장 시 초기 warmup 구간에서 rolling IQR의 신뢰도 낮음 (min_periods=15 설정 — `join.py:37`). 540d 데이터에서는 윈도우를 60~90일로 늘리는 것을 검토.
3. **컬럼별 masked_ratio 모니터링 부재**: 현재 전체 `masked_cells`만 집계. 특정 컬럼(예: `oi_change_pct`)에서 집중 마스킹 발생해도 감지 어려움.

**추가 권장 지표**
- 컬럼별 `masked_ratio` 개별 로깅 (`per_column` 딕셔너리는 이미 `_build_outlier_mask_summary()`에서 계산 중 — `pipeline.py:79-122` — 단지 로그 출력/artifact 미포함)
- `regime_stress_rows / total_rows` 비율 추이 모니터링

---

## 항목 4 — 백필 확인

### 목표
540d 확장에 필요한 소스 커버리지 검증:
- R2 뉴스: 2024-11-06 ~ 현재 (약 540일)
- Supabase `btc_futures_daily`: MIN(date) 확인

### 현재 상태 (코드 근거)

**R2 뉴스 경로**
```python
# r2_sentiment.py:98
url = f"{r2_public_bucket.rstrip('/')}/analytics/btc/{date}.json"
```

**Supabase 테이블**
```python
# futures.py:20
SUPABASE_FUTURES_TABLE = "btc_futures_daily"
```

**OI/LSR API 제약**
```python
# futures.py:455-456
# Binance OI/LSR API는 최근 30일만 보존
# OI_LSR_SIGNAL_WINDOW = 30  (futures.py:434)
```

**백필 스크립트**
```bash
# 뉴스 감성 (CoinDesk + FinBERT → R2)
python scripts/backfill_news_sentiment.py \
    --start 2024-11-06 \
    --end   $(date +%Y-%m-%d) \
    --batch-size 32

# BTC futures (Coinalyze → Supabase btc_futures_daily)
python scripts/backfill_btc_futures.py \
    --provider coinalyze \
    --lookback-days 540
```

### 소스별 커버리지 매트릭스

| 소스 | 필요 기간 | API 제약 | 백필 가능 여부 |
|------|-----------|----------|--------------|
| R2 뉴스 (FinBERT) | 2024-11-06 ~ | 없음 (히스토리 무제한) | ✅ `backfill_news_sentiment.py` |
| `btc_futures_daily` funding rate | 2024-11-06 ~ | Binance 히스토리 무제한 | ✅ `backfill_btc_futures.py` |
| `btc_futures_daily` OI/LSR | 최근 30일만 | **Binance 30일 보존** | ⚠️ 30일 이전 데이터 유실 |
| Supabase btc/usdkrw 가격 | 2024-11-06 ~ | Supabase DB 조회 | ✅ 기존 적재 확인 필요 |

### 백필 전 확인 체크리스트

```bash
# 1. R2 뉴스 커버리지 확인 (2024-11-06 기준)
python scripts/backfill_news_sentiment.py \
    --start 2024-11-06 --end 2024-11-10 --dry-run

# 2. Supabase btc_futures_daily MIN(date) 확인
# SQL: SELECT MIN(date), MAX(date), COUNT(*) FROM btc_futures_daily;

# 3. 파이프라인 dry-run (540d)
SENTIMENT_JOIN_LOOKBACK_DAYS=540 python -m morning_brief.analysis.sentiment_join.pipeline --dry-run
```

### Data Scientist 검토

**타당성**
- 뉴스 + funding rate는 백필 완전 가능.
- **OI/LSR 30일 제약이 핵심 문제**: 540d 기간 중 30일 이전 OI/LSR은 결측. 이 컬럼들의 실제 영향력(feature importance)을 먼저 측정해야 함.

**리스크**
- **데이터 소스 이질성**: 2024-11 ~ 2025-04 기간의 CoinDesk 뉴스 수집 정책이 현재와 달랐을 수 있음. 백필 데이터의 `n_articles` 분포가 현재 데이터와 유사한지 검증 필요.
- **FinBERT 모델 일관성**: 백필 당시와 현재 FinBERT 모델 버전이 동일해야 함. 버전이 다르면 sentiment_score 분포가 이질적.

**추가 권장 지표**
- 백필 전후 `n_articles` / `sentiment_score` 분포 비교 (KS test)
- 기간별 결측률 히트맵 (컬럼 × 월별)

---

## 우선순위 및 실행 순서

```
[1] 백필 확인 (항목 4)
    └─ R2 뉴스 2024-11-06~ 커버리지 체크 → 결측 구간 백필 실행
    └─ Supabase btc_futures_daily MIN(date) 확인
    └─ 예상 소요: 0.5일

[2] Lookback 540d 설정 (항목 1)
    └─ 환경변수 SENTIMENT_JOIN_LOOKBACK_DAYS=540 설정
    └─ 파이프라인 재실행 → master parquet 갱신
    └─ fold Sharpe CV 감소 여부 확인
    └─ 예상 소요: 0.5일

[3] 거래비용 20bps 반영 (항목 2)
    └─ walk-forward + baseline 동시 적용
    └─ gross vs net Sharpe 비교 리포트 생성
    └─ 예상 소요: 1일

[4] 이상치 마스크 보완 (항목 3)
    └─ sentiment_score 계열 컬럼 _OUTLIER_IQR_COLS 추가 검토
    └─ per_column masked_ratio artifact 노출
    └─ 540d 기준 IQR 윈도우 재조정 (30d → 60d)
    └─ 예상 소요: 1일
```

---

## 운영 승격 게이트 기준 (제안)

| 지표 | 현재 | 목표 |
|------|------|------|
| 독립 관측치 N | ~49 | ≥ 70 |
| bootstrap CI 하한 | ≈ 0.000 | > 0 (양측) |
| net-Sharpe (20bps) | 미계산 | > 0 |
| fold Sharpe 최악 fold | -3.76 | > -2.0 |
| 데이터 커버리지 | 365d | ≥ 500d (소스별 검증) |
