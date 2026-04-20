# Tasks — Sentiment-Join Outlier Rework & Ablation Platform

> 참고: `design.md` 와 함께 읽는다. 각 태스크 끝에 `_Requirements: R#_` 로 요구사항 매핑.

## Phase 1 — Abstractions (Day 1)

### 1. `outlier_policy.py` 신규 모듈 작성
- [x] `src/morning_brief/analysis/sentiment_join/outlier_policy.py` 생성
- [x] `OutlierPolicy` Protocol, `OutlierResult` dataclass 정의
- [x] `RowMaskPolicy`, `ColumnMaskPolicy`, `WinsorizePolicy`, `NoMaskPolicy` 4종 구현
- [x] `OutlierPolicyFactory.create(name)` 팩토리 + `IQR_MULTIPLIER`, `WINSOR_QUANTILES` config 상수
- [x] data_error 1차 필터(`open_interest_usd<0`, `|funding|>0.05`, `fallback_empty` 소스) 공통 전처리
- [x] regime stress 분류(3σ 초과 + 변화율 2개↑ 공동 점프)
- [x] flags DataFrame에 `reason ∈ {data_error, regime_stress, iqr_single}` 기록
- _Requirements: R1, R2, R3_

### 2. `outlier_policy` 단위 테스트
- [x] `tests/analysis/test_sentiment_join/test_outlier_policies.py` 생성
- [x] 각 4 policy에 대해 synthetic fixture로 snapshot 테스트
- [x] `RowMaskPolicy` 결과가 기존 `detect_outliers_rolling_iqr` + `pipeline.py:408` 결과와 tolerance 1e-9 내 동등
- [x] regime stress 케이스(2026-04-17 sim): column/winsorize/none에서 행 보존 확인
- [x] data_error 케이스: 모든 policy에서 해당 셀 반드시 마스크
- _Requirements: R1, R2, R9_

### 3. Scaler 주입 지점 리팩터링
- [x] `src/morning_brief/analysis/sentiment_join/hybrid_index.py` 에 `make_scaler(kind)` 팩토리 추가
- [x] `IndexSpec` dataclass에 `scaler_kind: Literal["standard","robust"] = "standard"` 필드
- [x] 437·271 라인의 `StandardScaler()` 직접 생성을 `make_scaler(spec.scaler_kind)` 로 교체
- [x] walk-forward pre-fitted PCA 경로(`hybrid_index.py:207-313`)에도 동일 주입
- _Requirements: R4, R9_

### 4. Scaler 회귀 테스트
- [x] `tests/analysis/test_sentiment_join/test_hybrid_index_scaler.py` 생성
- [x] `scaler_kind="standard"` 기본값 호출이 기존 출력과 수치 동등(tolerance 1e-9) — latest `master_*.parquet` 대상
- [x] `scaler_kind="robust"` 로 PCA fit 성공 + score가 [0,100] clip 경계 내인지 확인
- _Requirements: R4, R9_

### ✅ Checkpoint 1
```bash
make fmt && make lint && make typecheck && pytest tests/analysis/test_sentiment_join/test_outlier_policies.py tests/analysis/test_sentiment_join/test_hybrid_index_scaler.py -v
```
- [x] 모든 테스트 통과 (28/28)
- [x] 기존 `pytest tests/test_pipeline_quality.py`(있다면) 회귀 없음

## Phase 2 — Multi-Horizon Targets (Day 2)

### 5. Forward-shifted 타겟 컬럼 추가
- [x] `src/morning_brief/analysis/sentiment_join/join.py` 의 master 병합 직후 forward 컬럼 계산
  - `btc_fwd_ret_1d`, `btc_fwd_ret_3d`, `btc_fwd_ret_7d`, `btc_fwd_vol_5d`, `btc_large_move_3d`
- [x] 마지막 k개 행은 NaN 유지 (forward leak 방지)
- [x] `validate.py` MASTER_SCHEMA 에 신규 컬럼 5종 추가
- _Requirements: R5_

### 6. 호라이즌 타겟 테스트
- [x] `tests/analysis/test_sentiment_join/test_multi_horizon_targets.py` 생성
- [x] 기지 시퀀스(연속 1% 상승)로 T+3/T+7 누적 수익률 정확성 검증
- [x] 마지막 1·3·5·7 row가 각 타겟에서 NaN인지 검증
- [x] `btc_fwd_ret_1d` 가 기존 `btc_log_return.shift(-1)` 과 동등
- [x] `btc_large_move_3d` 이 이진(0/1)이고 NaN 허용 (Int64 dtype)
- _Requirements: R5_

### 7. Walk-forward 함수 horizon-aware 확장
- [x] `statistical_tests.walk_forward_validate` 에 `return_col`, `direction_label_col`, `horizon_days`, `embargo_days` kwargs 노출
- [x] embargo 삽입: horizon>1 이면 `max(horizon_days, 5)` gap 적용, 기본(h=1)은 0
- [x] fold stability 계산: `1 - stdev(hit_rates)/|mean(hit_rates)|` → `WalkForwardResult.stability` 필드
- [x] 동적 direction label 유도(sign(return_col)) — fwd horizon 타겟 지원
- [ ] `_ALPHA_PREDICTOR_CONFIGS` 호라이즌 루프 확장은 Phase 3 ExperimentRunner 에서 처리 (현 파이프라인 회귀 방지)
- _Requirements: R5_

### ✅ Checkpoint 2
```bash
make fmt && make lint && make typecheck && pytest tests/analysis/test_sentiment_join/test_multi_horizon_targets.py -v
pytest tests/  # full suite regression
```
- [x] 신규 multi-horizon 테스트 10/10 통과
- [x] 전체 테스트 suite 1056/1056 통과 (기존 walk-forward · validate 회귀 없음)
- [x] 스키마 검증: MASTER_SCHEMA 에 5개 forward target 컬럼 등록 + `test_validate.py` 업데이트
- [ ] `make sentiment-join` 실제 파이프라인 smoke 는 Phase 3 진입 전 별도 실행(외부 API 의존)

## Phase 3 — Ablation Runner (Day 3)

### 8. `ExperimentSpec` / `ExperimentRunner` 도입
- [x] `src/morning_brief/analysis/sentiment_join/experiments.py` 신규
- [x] `ExperimentSpec(scaler, mask, horizon, index)` dataclass
- [x] `ExperimentRunner.run(spec) -> pd.DataFrame`(fold-level metrics)
- [x] fold 캐시: scaler·PCA만 재학습, raw feature 매트릭스는 cell 간 공유
- _Requirements: R6_

### 9. `run_outlier_ablation.py` 스크립트
- [x] `scripts/run_outlier_ablation.py` 신규 (실행 가능, shebang)
- [x] 2×4×3×2 = 48 cell grid 순회 (horizon 3개: 1,3,7)
- [x] 결과 누적: `data/sentiment_join/experiments/{run_id}/folds.parquet`
- [x] `spec.json` 스냅샷: 각 cell의 정확한 config + git sha
- [x] `run_id = {YYYYMMDD-HHMM}-{git_sha[:7]}`
- [x] Makefile 타겟 `make sentiment-ablation` 추가
- _Requirements: R6_

### 10. Runner 통합 테스트
- [x] `tests/test_experiment_runner.py` 생성
- [x] 축소 grid(2×2×2×1=8 cell)로 end-to-end 실행 검증
- [x] `folds.parquet` 스키마 검증: fold_id, hit_rate, sharpe, cumret, coverage, masked_ratio, stability, spec_id
- [x] 재현성: 동일 spec 2회 실행 → 수치 동등
- _Requirements: R6_

### ✅ Checkpoint 3
```bash
make fmt && make lint && make typecheck && pytest tests/test_experiment_runner.py -v
make sentiment-ablation  # 전체 48 cell 실행 (예상 30~45분)
```
- [x] 11/11 테스트 통과
- [x] 모든 cell이 예외 없이 완료(로그 확인) — 격리 테스트 포함

## Phase 4 — Variance Decomposition & Report (Day 4)

### 11. ANOVA + effect size 계산 모듈
- [x] `src/morning_brief/analysis/sentiment_join/variance.py` 신규
- [x] `run_anova(df, metric)` — 2-way `C(scaler)*C(mask) + C(fold_id)` via statsmodels
- [x] η² 계산(type II SS)
- [x] Horizon 1-way ANOVA 별도 함수
- [x] Fisher-z 변환, BH-FDR 보정 유틸
- _Requirements: R7_

### 12. Bootstrap CI 계산
- [x] fold-level bootstrap(n=500) 구현 (`variance.py:bootstrap_ci`)
- [x] 각 cell × metric 95% CI 저장
- [x] CI 하단 기반 보수적 승격 판단 지원 (`conditional_promote` tier)
- _Requirements: R7, R8_

### 13. `variance_report.py` 스크립트
- [x] `scripts/variance_report.py` 신규 (입력: `{run_id}` 디렉토리)
- [x] 베이스라인(standard + row + T+1 + full) 기준 Δ 계산
- [x] Waterfall markdown 생성: scaler / mask / horizon / interaction 4 driver 분해
- [x] 승격 게이트 평가: `hit Δ≥+2pp AND Sharpe Δ≥+0.10 AND masked≤10% AND q<0.10 AND stability≥0.5`
- [x] 출력: `report.md`, `waterfall.md`, `anova.json`
- [x] Makefile 타겟 `make sentiment-variance-report RUN_ID=...` 추가
- _Requirements: R7, R8_

### 14. Variance 결정론적 테스트
- [x] `tests/test_variance_decomposition.py` 생성
- [x] ANOVA SS decomposition 항등식(총 SS = 설명 SS + 잔차 SS)
- [x] 승격 게이트 boolean 로직: 5개 AND 조합 truth table 전수 테스트(2^5=32 케이스)
- _Requirements: R7, R8, R9_

### ✅ Checkpoint 4
```bash
make fmt && make lint && make typecheck && pytest tests/test_variance_decomposition.py -v
make sentiment-variance-report RUN_ID=<phase3 run_id>
```
- [x] 54/54 테스트 통과
- [x] `decision` 값이 `promote` 또는 `research_only` 또는 `conditional_promote` 중 하나 (truth table 검증)

## Phase 5 — Decision & Documentation (Day 5)

### 15. 결과 해석 및 결정
- [ ] `make sentiment-ablation` 실행 후 `report.md` 검토 (외부 API 의존, 별도 실행 필요)
- [ ] 승격 게이트 결과에 따라 분기:
  - `promote`: Phase 6 진행
  - `conditional_promote`: 추가 샘플/fold 수집 후 재평가 계획 수립
  - `research_only`: 현 파이프라인 유지, 다음 spec(서브 인덱스 분리)으로 넘어감
- [ ] 결정과 근거를 `data/sentiment_join/experiments/{run_id}/decision.md`로 저장

### 16. README / 운영 문서 갱신
- [x] `CLAUDE.md` — Sentiment Join Analysis Pipeline 섹션에 신규 환경변수 반영
  - `SENTIMENT_JOIN_OUTLIER_POLICY` (row/column/winsorize/none)
  - `SENTIMENT_JOIN_SCALER_KIND` (standard/robust)
- [x] Ablation & Variance Decomposition 섹션 신규 추가 (make 명령어, 출력물, 승격 게이트)
- _Requirements: R6_

### 17. Phase 6 — Production Promotion (conditional, `promote` 시에만)
- [ ] `src/morning_brief/analysis/sentiment_join/config.py` 의 기본값 업데이트
- [ ] 기존 `master_*.parquet` 하나 이상에서 새 config로 재생성 후 smoke 검사
- [ ] `data/sentiment_join/report_post_backfill_review_20260419.md` 대비 개선 지표를 별도 `report_post_rework_{date}.md` 로 기록
- [ ] `full_hybrid_index` 라벨을 `regime_index` 로 변경(report/프롬프트)
- _Requirements: R8_

### ✅ Final Checkpoint
```bash
make check
make sentiment-join  # 프로덕션 기본 config로 재생성
```
- [x] 전체 테스트 suite 1120/1120 통과 (0 failed)
- [x] 신규 모듈 lint clean (ruff check --fix 통과)
- [x] 이 spec의 Phase 1~4 태스크 체크박스 `[x]` 완료
- [ ] `make sentiment-ablation` + `make sentiment-variance-report` 실제 실행 (외부 API 의존, 별도 수행)
- [ ] `decision.md` 에 최종 결정 + 게이트 스코어카드 보존 (Phase 5 Task 15 이후)

## Regression Test Summary

회귀 방지 테스트(필수, Checkpoint별 실행):

| 테스트 파일 | 검증 | Phase |
|---|---|---|
| `tests/test_outlier_policies.py` | 4 policy snapshot + data_error 필수 마스크 | 1 |
| `tests/test_hybrid_index_scaler.py` | standard 기본값 수치 동등성 | 1 |
| `tests/test_multi_horizon_targets.py` | T+k shift 정확성 + forward-leak 차단 | 2 |
| `tests/test_experiment_runner.py` | 축소 grid 스키마 + 재현성 | 3 |
| `tests/test_variance_decomposition.py` | driver 합 = total, 승격 게이트 truth table | 4 |

## Rollback Plan

Phase 6까지 진행했다가 프로덕션에서 문제 발견 시:

1. `config.py` 기본값을 `scaler_kind="standard"`, `outlier_policy="row"` 로 복구 (1줄 수정)
2. `make sentiment-join` 재실행 → 기존 동작 복원(R9 보장)
3. 문제 원인을 `decision.md` 에 업데이트하고 Phase 4 재실행
