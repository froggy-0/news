# Requirements Document

## Introduction

Sovereign Brief의 sentiment_join 분석 파이프라인은 Granger 인과성 검정과 PCA 기반 하이브리드 지수를 이미 계산해 Parquet 메타데이터에 저장하고 있으나, 프론트엔드에 노출되지 않아 사용자가 "뉴스 감성이 시장 지표를 선행하는가"와 "하이브리드 지수에서 각 변수의 기여도"를 확인할 수 없다. 본 작업의 목적은 이미 계산되는 두 분석 결과(Granger, PCA)만을 대상으로 **새로운 분석 페이지**를 신설해 시각화를 제공하는 것이다. 신규 통계 로직 추가, ablation, horizon별 hit rate 등은 범위에서 제외한다.

## Glossary

- **sentiment_join 파이프라인**: `make sentiment-join`으로 실행되는 감성-시계열 결합 분석 배치.
- **Master Parquet**: `data/sentiment_join/master_{YYYYMMDD}.parquet`. 48개 컬럼과 `sentiment_join_stats` JSON 메타데이터를 포함.
- **분석 아티팩트(Analysis Artifact)**: 본 작업에서 신설하는, 프론트 전용으로 추려진 JSON 파일. Master Parquet 메타에서 Granger·PCA 결과만 추출해 구성.
- **Granger 선행관계**: 한 시계열이 다른 시계열을 통계적으로 선행해 설명하는 관계. 인과성과 구별.
- **순방향 / 역방향 페어**: 순방향 = 뉴스·지표 → BTC 또는 뉴스 → 지표(16쌍). 역방향 = BTC → 지표(5쌍).
- **PCA Loadings**: 하이브리드 지수의 첫 주성분(PC1)에 각 입력 변수가 기여한 가중치.
- **Full / Core 지수**: 전체 피처 세트로 만든 지수(full)와 소수 핵심 피처로 만든 견고성 버전(core).
- **BH-FDR 보정**: 다중 검정 false discovery rate 통제를 위한 Benjamini-Hochberg 보정. 본 파이프라인의 63개 Granger 검정에 이미 적용.

## Requirements

### Requirement 1: 프론트 전용 분석 아티팩트 발행

**카테고리**: 출력/리포트/UI, 데이터 모델

**User Story:**
As a 프론트엔드 개발자·사용자,
I want 매일 생성되는 Granger·PCA 분석 결과를 프론트 소비에 필요한 필드만 추려진 단일 정적 JSON으로 받기를,
so that Parquet 메타를 해석할 필요 없이 바로 렌더링할 수 있다.

#### Acceptance Criteria

1. WHEN sentiment_join 파이프라인이 정상 완료되면, THE 시스템 SHALL 프론트 소비용 단일 JSON 아티팩트를 생성한다.
2. WHEN 해당 아티팩트가 생성되면, THE 아티팩트 SHALL 다음 필드만을 포함한다:
   - `generated_at_utc`(ISO 8601), `reference_date`(분석 기준일 YYYY-MM-DD)
   - `granger`: 각 페어별 `predictor`, `target`, `direction`(forward/reverse), `lag`, `pvalue`, `pvalue_adjusted`, `significant`, `optimal_lag` 여부
   - `granger_correction`: `correction_method`, `n_tests`
   - `pca.full` 및 `pca.core` 각각: `status`, `selected_features`, `n_components`, `explained_variance`, `loadings`(변수명→값), `excluded_features`(변수명→사유), `coverage_ratio`, `quality_status`, `quality_reasons`
3. WHEN 아티팩트가 생성될 때, THE 아티팩트 SHALL Master Parquet 메타에 존재하지만 프론트에서 사용하지 않는 필드(예: walk_forward, correlations, backtest, adf, structured_sources 등)를 포함하지 않는다.
4. IF sentiment_join 파이프라인이 실패하거나 품질 상태가 `critical`이면, THEN THE 시스템 SHALL 기존 아티팩트를 덮어쓰지 않는다.
5. WHEN 프론트엔드가 아티팩트에 접근하면, THE 시스템 SHALL 기존 브리핑 정적 자산과 동일한 R2 공개 경로 체계를 통해 제공한다.

---

### Requirement 2: Granger 선행관계 시각화

**카테고리**: 출력/리포트/UI

**User Story:**
As a 분석 결과를 보는 사용자,
I want 뉴스·지표가 시장을 선행하는 경로와 시장이 지표를 선행하는 경로를 하나의 화면에서 비교할 수 있기를,
so that "뉴스가 시장을 움직이는가, 시장이 뉴스를 만드는가"를 직접 판단할 수 있다.

#### Acceptance Criteria

1. WHEN 사용자가 해당 페이지에 진입하면, THE UI SHALL 파이프라인이 검정하는 모든 Granger 페어(순방향 16쌍 + 역방향 5쌍)를 동일 화면에 표시한다.
2. WHEN 각 페어가 표시될 때, THE UI SHALL predictor, target, direction, lag, BH-FDR 보정 후 유의성, p-value(또는 q-value) 정보를 반드시 포함한다.
3. WHEN 순방향과 역방향을 표시할 때, THE UI SHALL 동일 지표(예: fng_value, etf_net_inflow_usd)를 중심으로 좌우 또는 상하 대칭 배치하여 양방향을 동시에 비교할 수 있게 구성한다.
4. WHEN 순방향과 역방향을 표시할 때, THE UI SHALL 탭·토글·별도 페이지로 두 방향을 분리하지 않는다.
5. WHEN 디폴트 뷰에서 각 페어가 표시될 때, THE UI SHALL 페어당 가장 유의한 lag 하나의 결과를 기본으로 표시하고, lag 1/2/3 전체 세부 결과는 사용자 인터랙션(클릭/호버 등)을 통해 드러낸다.
6. WHEN 유의성 상태가 표시될 때, THE UI SHALL BH-FDR 통과 여부를 색상 강도 또는 시각적 두께로 인코딩하여, 페어를 숨기지 않고도 유의한 페어가 자연스럽게 인지되도록 한다.
7. WHEN 페어가 BH-FDR 보정 후 유의하지 않으면, THE UI SHALL 해당 페어를 화면에서 제거하지 않고 시각적으로 구분해 표시한다.
8. IF 특정 페어에 대해 Granger 검정이 실행되지 않았거나 샘플 수 부족으로 결과가 누락되면, THEN THE UI SHALL 해당 페어를 숨기지 않고 "검정 미수행" 사유를 함께 표시한다.
9. WHEN 시각화가 표시될 때, THE UI SHALL "Granger 선행관계는 통계적 인과관계가 아님"을 명시하는 안내 문구를 동일 화면에 함께 보여준다.

---

### Requirement 3: PCA Loadings 시각화

**카테고리**: 출력/리포트/UI

**User Story:**
As a 분석 결과를 보는 사용자,
I want 하이브리드 지수가 어떤 변수에 의해 어느 방향으로 구성되는지 보고 싶기를,
so that 지수 값의 상승/하락을 해석할 수 있다.

#### Acceptance Criteria

1. WHEN 사용자가 해당 섹션에 진입하면, THE UI SHALL `full` 지수와 `core` 지수의 loadings를 탭 전환 방식으로 제공한다.
2. WHEN 사용자가 페이지에 처음 진입하면, THE UI SHALL `full` 탭을 기본 선택 상태로 표시한다.
3. WHEN 특정 탭이 활성화되면, THE UI SHALL 해당 지수의 변수명, loading 값(부호 포함), 양/음 방향을 시각적으로 구별해 표시한다.
4. WHEN 특정 탭이 활성화되면, THE UI SHALL 해당 지수의 설명 분산(explained variance), 사용된 n_components, 데이터 커버리지 비율을 함께 보여준다.
5. WHEN VIF 단계에서 제거된 변수(`excluded_features`)가 존재하면, THE UI SHALL 제거된 변수 이름과 사유를 해당 탭 내 별도 영역에 표시한다.
6. WHEN 지수 품질 상태(`quality_status`)가 `degraded`이면, THE UI SHALL 해당 탭에 경고를 노출한다.
7. IF 특정 지수가 피처 부족 등 사유로 계산되지 않았으면(`status != "ok"`), THEN THE UI SHALL 해당 탭에 계산 불가 사유를 표시하고 빈 그래프를 억제한다.

---

### Requirement 4: 데이터 신선도 및 오류 표시

**카테고리**: 오류 처리/복원, 출력

**User Story:**
As a 운영자·사용자,
I want 화면에 표시된 분석이 언제 생성된 것인지 확인하기를,
so that 오래된 결과를 최신으로 오해하지 않는다.

#### Acceptance Criteria

1. WHEN 페이지가 렌더링되면, THE UI SHALL 아티팩트의 기준일과 생성 시각(UTC)을 사용자에게 표시한다.
2. WHEN 아티팩트의 기준일이 오늘(KST) 기준 2일 이상 경과했으면, THE UI SHALL "데이터가 최신이 아님"을 사용자에게 경고한다.
3. IF 프론트가 아티팩트를 불러오지 못하면, THEN THE UI SHALL 빈 그래프 대신 명시적 오류 메시지를 표시한다.
4. WHEN 아티팩트 내 Granger 결과 또는 PCA 결과 중 한 쪽만 누락되면, THE UI SHALL 존재하는 쪽은 정상 표시하고 누락된 쪽만 "데이터 없음" 상태로 표시한다.

---

### Requirement 5: 페이지 배치 및 범위 제한

**카테고리**: 설정/환경, 출력/리포트/UI

#### Acceptance Criteria

1. WHEN 본 작업이 구현될 때, THE 프론트엔드 SHALL 기존 페이지에 섹션을 추가하지 않고 새로운 전용 페이지를 신설한다.
2. WHEN 본 작업이 구현될 때, THE 범위 SHALL Granger 시각화와 PCA Loadings 시각화 두 가지에만 한정된다.
3. WHEN 본 작업이 구현될 때, THE 시스템 SHALL 기존 sentiment_join 파이프라인의 통계 계산 로직을 수정하지 않는다.
4. WHEN 본 작업이 구현될 때, THE 시스템 SHALL horizon별 hit rate, ablation, variance decomposition, walk-forward, correlations, backtest 결과는 범위에서 제외한다.
5. WHEN 본 작업이 구현될 때, THE 시스템 SHALL 기존 `schema/brief.types.ts`의 기존 필드를 변경하거나 제거하지 않는다(신규 타입 추가만 허용).
