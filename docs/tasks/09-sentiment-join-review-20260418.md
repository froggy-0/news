# Sentiment-Join Review (2026-04-18)

## 실행 기준

- 실행 명령:

```bash
PYTHONPATH=src ./.venv/bin/python -m morning_brief.analysis.sentiment_join.inspect "$(ls -t data/sentiment_join/master_*.parquet | head -n 1)"
```

- 리뷰 대상 파일: `data/sentiment_join/master_20260418.parquet`
- 리뷰 관점: Senior Data Engineer

## 한줄 평가

- **종합 점수: 72/100**
- **판정:** 저장/스키마 관점에서는 합격, 분석/운영 관점에서는 아직 보완 필요

## 현재 상태 요약

| 항목 | 값 | 메모 |
|---|---:|---|
| date range | `2025-10-20 ~ 2026-04-17` | 180일 window |
| rows | `180` | schema validation 통과 |
| columns | `33` | strict schema 유지 |
| outlier rows | `32` | 17.78% |
| `hybrid_index` non-null | `25` | 13.9%만 실제 값 |
| `open_interest_usd` non-null | `30` | feature sparsity 높음 |
| `btc_long_short_ratio` non-null | `30` | feature sparsity 높음 |
| `etf_total_aum_usd` non-null | `38` | feature sparsity 높음 |
| `granger_executed` | `true` | 그러나 `granger_results=[]` |

## Findings

### 1. `lookback_days` 기본값 180이 백필 범위와 parquet 범위를 분리해 운영자가 쉽게 오해할 수 있습니다

- 심각도: High
- 근거:
  - `src/morning_brief/analysis/sentiment_join/config.py:47-54`
  - `src/morning_brief/analysis/sentiment_join/pipeline.py:124-128`
- 관찰:
  - 뉴스 백필은 2025-07-01부터 준비되어 있어도, 현재 sentiment-join 실행은 기본 `SENTIMENT_JOIN_LOOKBACK_DAYS=180`이라 parquet가 `2025-10-20`부터만 생성됩니다.
  - 운영자는 "백필을 7월부터 했는데 parquet 왜 10월부터지?" 같은 혼선을 겪게 됩니다.
- 권고:
  - parquet 메타데이터에 `requested_start_date`, `effective_start_date`, `lookback_days`를 명시적으로 저장합니다.
  - inspect 출력에도 이 3개 값을 함께 보여줍니다.
  - 운영 문서/명령 예시에 `SENTIMENT_JOIN_LOOKBACK_DAYS=290` 같은 실사용 값을 명시합니다.

### 2. `granger_executed=true`는 현재 semantics상 misleading 합니다

- 심각도: High
- 근거:
  - `src/morning_brief/analysis/sentiment_join/pipeline.py:279-302`
  - `src/morning_brief/analysis/sentiment_join/statistical_tests.py:205-210`
  - `src/morning_brief/analysis/sentiment_join/statistical_tests.py:427-429`
- 관찰:
  - 메타데이터에는 `granger_eligible_rows=180`, `granger_executed=true`가 기록됐지만 실제 `granger_results`는 0건입니다.
  - 이유는 outlier 32행을 NaN 마스킹한 뒤 페어별 `dropna()`를 하면 대표 페어도 144~148행 수준으로 줄어들기 때문입니다.
  - 즉 "파이프라인이 Granger 단계에 진입했다"와 "실제 pairwise test가 실행됐다"가 혼재되어 있습니다.
- 권고:
  - `granger_executed`를 `any_pair_executed` 의미로 바꾸거나, 새 필드 `granger_candidate_rows`, `granger_pairs_attempted`, `granger_pairs_executed`, `granger_pairs_skipped`를 추가합니다.
  - 페어별 `effective_rows`와 `skip_reason`를 메타에 저장해 후속 디버깅 비용을 줄입니다.

### 3. `hybrid_index`는 현재 너무 sparse 해서 시계열 신호로 쓰기 어렵습니다

- 심각도: High
- 근거:
  - `src/morning_brief/analysis/sentiment_join/hybrid_index.py:120-126`
  - `src/morning_brief/analysis/sentiment_join/hybrid_index.py:141-205`
- 관찰:
  - `hybrid_index` non-null이 25/180행뿐입니다.
  - 주요 입력 feature인 `open_interest_usd`, `btc_long_short_ratio`, `etf_total_aum_usd`가 각각 30, 30, 38행만 채워져 있어 PCA 입력이 지나치게 희소합니다.
  - 현재 구조는 "모든 selected feature가 있는 날만 지수 산출" 방식이라 운영 신호 연속성이 약합니다.
- 권고:
  - 최소 feature 세트별 tier를 나눠 `full_hybrid_index`, `reduced_hybrid_index` 같은 degradation path를 둡니다.
  - 또는 feature availability가 임계치 미만이면 `hybrid_index`를 계산하되 metadata에 `feature_coverage_ratio`를 남겨 신뢰도를 분리 표시합니다.
  - 최소한 inspect/report에 `hybrid_index_coverage=25/180`를 요약값으로 노출해야 합니다.

### 4. 리포트 추출 스크립트가 현재 parquet 메타 키와 어긋나 있습니다

- 심각도: Medium
- 근거:
  - `scripts/extract_report_data.py:105-110`
- 관찰:
  - 현재 스크립트는 `res["statistic"]`, `res["pvalue"]`를 기대하지만 parquet 메타는 `adf_statistic`, `adf_pvalue`를 저장합니다.
  - 결과적으로 parquet는 좋아졌는데 리포트 추출은 중간에 `KeyError`로 끊깁니다.
- 권고:
  - extractor를 최신 metadata contract에 맞추고, metadata key rename 시 회귀 테스트를 추가합니다.

### 5. inspect는 보기 좋아졌지만 품질 scorecard 역할은 아직 부족합니다

- 심각도: Medium
- 근거:
  - 현재 inspect 출력에는 `run_id`, outlier 수, PCA 상태는 보이지만 coverage/실행 의미가 부족합니다.
- 권고:
  - 아래 요약 항목을 추가합니다:
    - `effective_granger_rows_max`
    - `hybrid_index_coverage_ratio`
    - `feature_non_null_counts`
    - `pairwise_granger_skip_summary`
    - `requested_start_date vs effective_start_date`

## 우선순위 제안

### P0

1. `granger_executed` semantics 정리 및 pairwise skip reason 저장
2. `extract_report_data.py`를 최신 metadata contract에 맞게 수정

### P1

1. `lookback_days`와 실제 parquet 시작일 차이를 메타/inspect/UI에 명시
2. `hybrid_index` coverage 지표 추가 및 sparse feature degradation path 설계

### P2

1. inspect에 데이터 품질 scorecard 추가
2. parquet 품질 기준을 CI 또는 배치 검증에 연결

## 추천 후속 실행

```bash
# 2025-07-01 ~ 2026-04-17를 parquet에 반영하려면
SENTIMENT_JOIN_LOOKBACK_DAYS=290 make sentiment-join

# 최신 parquet 확인
PYTHONPATH=src ./.venv/bin/python -m morning_brief.analysis.sentiment_join.inspect "$(ls -t data/sentiment_join/master_*.parquet | head -n 1)"
```

## 최종 코멘트

현재 산출물은 "데이터 파이프라인이 무너지지 않고 결과물을 만든다"는 점에서는 충분히 진전됐습니다. 다만 Senior Data Engineer 관점에서는 **운영자가 기대한 분석 window와 실제 parquet window가 어긋나는 문제**, **Granger 실행 여부 semantics의 모호함**, **희소 feature에 의존한 hybrid_index 연속성 부족**이 아직 남아 있습니다. 이 3가지를 정리하면 지금 파이프라인은 연구용을 넘어서 운영용 분석 자산에 더 가까워질 수 있습니다.
