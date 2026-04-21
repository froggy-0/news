# Implementation Plan: Sentiment Insight Visualization

## Overview

Python 추출 모듈 → pipeline 연결 → 프론트 타입·lib → 페이지·컴포넌트 → QA 순서로 진행한다.
각 단계는 독립적으로 검증 가능하며, 백엔드와 프론트는 JSON 아티팩트 스키마 계약을 경계로 분리된다.
기존 파이프라인 통계 로직과 브리핑 프론트는 **일절 수정하지 않는다**.

---

## Tasks

- [x] 1. Python: `frontend_artifact.py` 신규 모듈 작성
  - [x] 1.1 `build_frontend_artifact(stats_metadata_bytes, reference_date)` 구현
    - `sentiment_join_stats` bytes를 JSON 파싱
    - `granger_results` 필터링: `predictor`, `target`, `lag`, `pvalue`, `pvalue_adjusted`, `significant` 추출
    - `direction` 계산: `statistical_tests.GRANGER_PAIRS_REVERSE` import 후 `(predictor, target)` 매칭 → `"forward"` / `"reverse"`
    - `optimalLag` 계산: 같은 `(predictor, target, direction)` 그룹에서 `pvalue_adjusted` 최솟값 lag에만 `true`, 동률 시 작은 lag 우선
    - `pca.full` / `pca.core` 필터링: `status`, `selectedFeatures`, `nComponents`, `explainedVariance`, `loadings`, `excludedFeatures`, `coverageRatio`, `qualityStatus`, `qualityReasons` 추출
    - snake_case → camelCase 변환
    - `granger_correction` → `granger.correction` 재구조
    - 불허 키(walk_forward, correlations, backtest, adf, structured_sources 등) 포함 금지
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 `should_skip_artifact(artifact)` 구현
    - `pca.full.qualityStatus == "critical"` AND `pca.core.qualityStatus == "critical"` 일 때만 `True`
    - _Requirements: 1.4_
  - [x] 1.3 `write_frontend_artifact(output_dir, artifact, run_date)` 구현
    - `latest.json`과 `{run_date}.json` 두 파일 생성
    - 반환: `tuple[Path, Path]`
    - _Requirements: 1.1_
  - [x] 1.4 테스트: `tests/analysis/test_frontend_artifact.py` 작성
    - `direction` 매핑 정확성 (forward/reverse 각 1케이스)
    - `optimalLag` 선정 (3 lag 중 최소 q-value, 동률 tie-break)
    - 화이트리스트 검증: 불허 키가 결과에 없음
    - `should_skip_artifact`: (둘 다 critical → True), (하나만 critical → False), (둘 다 ok → False)
    - `loadings` 키 집합 == `selectedFeatures` 키 집합
    - _Requirements: 1.2, 1.3_

- [x] 2. Checkpoint — `make test` 통과 확인
  ```bash
  pytest tests/analysis/ -v
  make lint
  make typecheck
  ```

- [x] 3. Python: `pipeline.py` 연결 지점 삽입
  - [x] 3.1 `save_parquet(...)` 직후에 artifact 생성·저장·업로드 블록 추가
    - `build_frontend_artifact` 호출 → `should_skip_artifact` 분기 → `write_frontend_artifact` → `upload_to_r2` × 2
    - R2 key: `analytics/sentiment/latest.json`, `analytics/sentiment/{run_date}.json`
    - `upload_to_r2` 기존 함수 재사용 (실패 시 WARNING, 파이프라인 미중단)
    - _Requirements: 1.1, 1.4, 1.5_
  - [ ] 3.2 테스트: `tests/analysis/test_frontend_artifact_pipeline.py` 작성
    - skip 조건(둘 다 critical): `write_frontend_artifact` 미호출 검증
    - 정상 조건: 두 파일 경로 반환 + `upload_to_r2` 두 번 호출 검증
    - _Requirements: 1.4_

- [x] 4. Checkpoint — 통합 검증
  ```bash
  pytest tests/analysis/ -v
  make check
  ```

- [x] 5. Frontend: 타입 및 라이브러리 레이어
  - [x] 5.1 `schema/analysis.types.ts` 신규 파일 작성
    - `GrangerDirection`, `GrangerResult`, `PcaIndex`, `SentimentInsightArtifact` 타입 정의
    - 기존 `brief.types.ts` 불변
    - _Requirements: 5.5_
  - [x] 5.2 `frontend/lib/analysis-schema.ts` 작성
    - `parseSentimentInsight(unknown): SentimentInsightArtifact` 수기 파서 + 타입가드
    - 필수 필드 누락 시 `Error` throw
    - _Requirements: 4.3_
  - [x] 5.3 `frontend/lib/analysis.ts` 작성
    - `fetchSentimentInsight()`: R2 `analytics/sentiment/latest.json` fetch
    - fixture 모드: `BRIEF_DATA_SOURCE=fixture` 시 `fixtures/sentiment-insight.json` 로컬 파일 읽기
    - 실패 시 throw (페이지가 catch)
    - `isStaleReferenceDate(referenceDate, now)`: KST 기준 2일 이상 경과 시 true
    - _Requirements: 1.5, 4.1, 4.2, 4.3_
  - [x] 5.4 `frontend/fixtures/sentiment-insight.json` fixture 파일 작성
    - 스키마 예시값: granger 5개 결과(유의 3개·비유의 2개·역방향 1개 포함), pca full/core 각각 loadings 4개 포함
    - _Requirements: 없음 (개발 편의)_
  - [x] 5.5 테스트: `frontend/tests/analysis-schema.test.ts`
    - 유효한 payload → `SentimentInsightArtifact` 반환
    - 필수 필드 누락 payload → throw
    - _Requirements: 4.3_
  - [x] 5.6 테스트: `frontend/tests/analysis-stale.test.ts`
    - `isStaleReferenceDate` 경계값: 1일 23h 59m → false, 2일 0h 0m → true, 2일 0h 1m → true
    - _Requirements: 4.2_

- [x] 6. Checkpoint — 프론트 타입·lib 검증
  ```bash
  cd frontend && npm run lint && npm test
  ```

- [x] 7. Frontend: 컴포넌트 구현
  - [x] 7.1 `frontend/components/analysis/AnalysisMasthead.tsx`
    - 좌: Instrument Serif italic 페이지 제목
    - 우: JetBrains Mono 모노 블록 (referenceDate / generatedAt / nTests / FDR)
    - `staleWarning` prop → 상단 띠 배너 표시
    - _Requirements: 4.1, 4.2_
  - [x] 7.2 `frontend/components/analysis/GrangerSymmetric.tsx`
    - 중앙축 수직선 + 좌(forward)·우(reverse) 대칭 막대 레이아웃
    - 막대 길이 = `-log10(pvalueAdjusted)` 기반, 전체 95 percentile로 정규화
    - `significant` 인코딩: true → 진한 색·불투명 1, false → 18% 불투명도
    - 기본 표시 = `optimalLag === true` lag 1개. hover/click → 같은 페어의 lag 1/2/3 수직 스택 공개
    - 다른 행 디밍 (`opacity: 0.35`, 0.2s transition)
    - `executed === false` → "Granger 검정 미수행" 안내 렌더
    - "Granger causality ≠ causation" 안내 문구 우상단 (JetBrains Mono, 0.7rem)
    - CSS 모션: `axisDraw` (중앙축 scaleY 0→1, 0.6s), 막대 staggered reveal (`--row-index` 기반)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_
  - [x] 7.3 `frontend/components/analysis/PcaTabs.tsx`
    - 탭 2개: FULL(기본) / CORE (JetBrains Mono 대문자, underline 애니메이션)
    - 수평 막대 차트: Y=변수명, X=loading (중앙 0 기준 좌우 대칭)
    - 양수 → 밝은 포그라운드, 음수 → 반대편 연한 색
    - 메타 스트립: explainedVariance·nComponents·coverageRatio·qualityStatus 4개 pill
    - `qualityStatus === "degraded"` → pill 강조 + qualityReasons expand 토글
    - `excludedFeatures` 비어있지 않으면 하단 VIF 제거 변수 테이블
    - `status !== "ok"` → `<EmptyState>` 렌더, 막대 차트 억제
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_
  - [x] 7.4 `frontend/components/analysis/AnalysisUnavailable.tsx`
    - fetch 실패 시 빈 상태 UI
    - 짧은 안내 문구 + `reason` 1줄 (JetBrains Mono, 0.8rem)
    - _Requirements: 4.3_

- [x] 8. Frontend: 페이지 조립
  - [x] 8.1 `frontend/app/analysis/page.tsx` 작성
    - `export const dynamic = "force-static"`
    - `fetchSentimentInsight()` try/catch → 실패 시 `<AnalysisUnavailable>` 렌더
    - `isStaleReferenceDate` 서버에서 계산 후 `staleWarning` prop 전달
    - `SiteHeader` 포함 (`historyEntries=[]`)
    - `BottomTabBar`·기존 `SiteHeader` 수정 없음
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1_

- [x] 9. Checkpoint — 로컬 브라우저 확인
  ```bash
  cd frontend
  npm run dev:fixture    # fixture 데이터로 /analysis 렌더 확인
  npm run lint
  ```
  확인 항목:
  - `/analysis` 페이지 정상 로드
  - Granger 중앙축 대칭 레이아웃 렌더
  - PCA 탭 전환 (FULL → CORE)
  - `staleWarning` 배너 (fixture에서 날짜를 과거로 설정해 확인)
  - `GrangerSymmetric`에서 유의/비유의 색상 구분

- [x] 10. QA: Playwright
  - [x] 10.1 `frontend/qa/analysis.spec.ts` 작성
    - fixture 기반 `/analysis` 페이지 렌더 스냅샷
    - PCA 탭 전환: CORE 클릭 후 FULL 탭 내용 사라짐, CORE 내용 표시
    - Granger 막대 hover: lag 상세 3개 노출
    - stale 배너: referenceDate를 3일 전으로 설정한 fixture에서 배너 표시 확인
    - `executed === false` fixture에서 "Granger 검정 미수행" 안내 표시
    - _Requirements: 2.4, 2.5, 3.1, 4.2, 4.3_
  - [x] 10.2 QA 실행
    ```bash
    cd frontend && npm run qa:playwright
    ```

- [x] 11. Checkpoint — 전체 최종 검증
  ```bash
  make check                           # Python lint + test + typecheck
  cd frontend && npm run lint && npm test && npm run build:fixture
  ```
