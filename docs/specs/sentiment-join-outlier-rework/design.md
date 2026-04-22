# Design — Sentiment-Join Outlier Rework & Ablation Platform

## Overview

`docs/analysis/sentiment-join/post-backfill-review-20260419.md`에서 확인된 두 가지 구조적 약점을 해결한다.

1. **행 단위 IQR×3.0 마스킹이 20.56%를 폐기** — 그중 상당수는 market-stress 이벤트이며, full/core hybrid index 커버리지를 78%까지 끌어내려 PCA가 평시 regime에 과적합된다.
2. **타겟이 T+1 단일** — 센티먼트·펀딩·ETF 유입처럼 누적형 feature의 강점이 발현되는 T+3/T+7 horizon과 변동성 타겟이 평가 루프에 없다.

이 spec은 **이상치 규칙과 스케일러를 팩토리얼로 교차한 8-treatment × 4-horizon × 2-index ablation 플랫폼**을 구축하고, 2-way ANOVA + variance decomposition으로 driver 기여도를 분해해 프로덕션 교체 여부를 결정한다.

승격 기준(사전 등록):

> `hit_rate Δ ≥ +2pp` **AND** `Sharpe Δ ≥ +0.10` **AND** `masked_ratio ≤ 10%` **AND** `FDR q < 0.10` **AND** `fold stability ≥ 0.5`

하나라도 미충족 시 `research_only` 태깅, 현 파이프라인 유지.

## Requirements 요약 (대화 확립분)

| # | 요구사항 | EARS |
|---|---|---|
| R1 | 이상치 마스킹을 행→열 단위로 전환 가능해야 한다 | WHEN `mask_mode="column"` THEN `is_outlier` 플래그는 셀 단위로 기록되고 해당 셀만 NaN화된다 |
| R2 | 이상치 규칙을 `data_error` vs `market_regime`으로 분리해야 한다 | WHERE 부호 불가능값·provider 404 THEN `data_error_outlier=True`이고 반드시 마스크된다; WHERE 3σ 초과 + 다수 변화율 공동 점프 THEN `market_regime_outlier=True`이고 기본 마스크되지 않는다 |
| R3 | Winsorize(q01/q99) 옵션을 제공해야 한다 | WHEN `mask_mode="winsorize"` THEN 분포 꼬리만 clip되고 행은 보존된다 |
| R4 | 스케일러를 Standard/Robust로 교체 가능해야 한다 | WHEN `scaler_kind="robust"` THEN `RobustScaler`가 PCA 전처리에 주입된다 |
| R5 | 멀티 호라이즌 타겟을 지원해야 한다 | WHEN horizon ∈ {1,3,7,vol5} THEN walk-forward는 각 타겟을 독립 평가한다 |
| R6 | 64 cell ablation을 재현 가능하게 실행해야 한다 | WHEN `run_outlier_ablation.py` 실행 THEN 모든 replication의 fold-level metric이 parquet로 저장된다 |
| R7 | Variance decomposition + 2-way ANOVA 리포트를 생성해야 한다 | WHEN ablation 완료 후 `variance_report.py` 실행 THEN scaler/mask/horizon effect와 interaction η², FDR q-value가 담긴 `report.md`와 waterfall이 출력된다 |
| R8 | 승격 게이트가 자동 평가되어야 한다 | WHEN 리포트 생성 시 THEN 5개 AND 조건이 코드로 검증되고 `decision: promote|research_only`가 기록된다 |
| R9 | 기존 파이프라인 회귀를 막아야 한다 | `scaler_kind="standard"` + `mask_mode="row"` 조합은 기존 출력과 수치적으로 동등해야 한다 (tolerance 1e-9) |

## Design Decisions

### D1. Mask 정책을 전략 객체로 추상화

**현재:** `join.py:282-296`에서 `detect_outliers_rolling_iqr` 호출 후 `pipeline.py:408`에서 `analysis_df.loc[is_outlier, _mask_cols] = np.nan` 단일 분기.

**변경:** `OutlierPolicy` 프로토콜 도입.

```python
# src/morning_brief/analysis/sentiment_join/outlier_policy.py (신규)
class OutlierPolicy(Protocol):
    name: Literal["row", "column", "winsorize", "none"]
    def apply(self, df: pd.DataFrame, cols: list[str]) -> OutlierResult: ...

@dataclass
class OutlierResult:
    df: pd.DataFrame                    # 마스킹/윈저라이즈 후
    flags: pd.DataFrame                 # date × col 2D 플래그 (cell-level)
    classification: pd.DataFrame        # data_error / market_regime 분류
    stats: dict[str, float]             # masked_ratio, winsorized_ratio, ...
```

- `RowMaskPolicy` — 기존 동작 그대로. 회귀 테스트 호환성 유지.
- `ColumnMaskPolicy` — 셀 단위 NaN. 행 수 보존.
- `WinsorizePolicy` — `np.clip(x, q01, q99)`. 꼬리 자르지만 부호·순위 보존.
- `NoMaskPolicy` — data_error만 제거하고 regime outlier는 통과.

**이유:** `pipeline.py` 변경 최소화 + 전략 교체가 단일 주입 지점(`OutlierPolicyFactory.create(name)`)으로 수렴. 실험 매트릭스가 config 한 줄로 표현됨.

### D2. data_error vs market_regime 2원 분류

`outlier_policy.py` 내부 공통 전처리:

1. **data_error 규칙 (항상 적용)**
   - `open_interest_usd < 0`
   - `|funding_rate| > 0.05` (5%/8h — 역사적 이상)
   - `btc_log_return` 누락(`NaN`)인데 `funding_rate` 존재 → provider timeline 불일치
   - source == `fallback_empty`
2. **market_regime 규칙 (정책에 따라 선택적 적용)**
   - rolling IQR×k 초과 AND 다음 중 ≥2개 동시 충족:
     - `|btc_return|` 일중 95 퍼센타일 초과
     - `|funding_rate|` 30일 95 퍼센타일 초과
     - `|volume_change_pct|` 30일 95 퍼센타일 초과
   - → regime stress로 분류되고 마스크되지 않음

classification 결과는 `flags` DataFrame에 `reason ∈ {data_error, regime_stress, iqr_single}` 3-way 범주로 저장 → audit 가능.

### D3. Scaler 주입

**현재:** `hybrid_index.py:437, 271`에서 `StandardScaler()` 직접 생성.

**변경:** `make_scaler(kind: Literal["standard", "robust"]) -> TransformerMixin` 팩토리.

- `IndexSpec`(기존 dataclass)에 `scaler_kind: str = "standard"` 필드 추가.
- 주입 지점: full/core 양쪽의 `fit_hybrid_index` 및 walk-forward pre-fitted PCA 경로.
- 기본값은 `"standard"`로 두어 기본 호출 경로는 기존과 동일(R9).

**왜 RobustScaler?** median·IQR 기반이라 극단값에 둔감. Winsorize와 상호작용 효과를 측정해야 하므로 둘은 직교 변수로 유지.

### D4. 멀티 호라이즌 타겟

`join.py`에서 master 생성 시점에 forward-shifted 컬럼을 선계산:

```python
merged["btc_fwd_ret_1d"]  = merged["btc_log_return"].shift(-1)     # 기존 T+1과 동등
merged["btc_fwd_ret_3d"]  = (np.log(price).shift(-3) - np.log(price))  # cumulative
merged["btc_fwd_ret_7d"]  = (np.log(price).shift(-7) - np.log(price))
merged["btc_fwd_vol_5d"]  = merged["btc_log_return"].rolling(5).std().shift(-5) * np.sqrt(5)
merged["btc_large_move_3d"] = (merged["btc_fwd_ret_3d"].abs() > 1.5 * merged["btc_fwd_ret_3d"].rolling(60).std()).astype(int)
```

- 마지막 k개 행은 NaN (leak 방지).
- `walk_forward_validate(return_col=<horizon>)` 에 이미 `return_col` 인자가 존재(`statistical_tests.py:948`) — 시그니처 수정 없이 타겟만 전환 가능.
- embargo: `test_days` 시작 전 `max(horizon, 5)`일 갭 삽입해 forward leak 방지.

### D5. Ablation Runner

`scripts/run_outlier_ablation.py` 신규:

```python
SCALERS   = ["standard", "robust"]
MASKS     = ["row", "column", "winsorize", "none"]
HORIZONS  = ["1d", "3d", "7d", "vol5d"]
INDICES   = ["full", "core"]
# 2 × 4 × 4 × 2 = 64 cell
```

각 cell은 `ExperimentSpec(scaler, mask, horizon, index)` → `ExperimentRunner.run(spec)` → `FoldMetrics(fold_id, hit_rate, pearson, sharpe, cumret, brier_vol, coverage, masked_ratio, stability)` 반환. 결과는 `data/sentiment_join/experiments/{run_id}/folds.parquet` 단일 파일로 누적.

**재현성:** `run_id = {timestamp}-{git_sha}`. `spec.json`에 각 cell의 정확한 config 스냅샷 저장.

### D6. Variance Report

`scripts/variance_report.py` 신규. 입력: `folds.parquet`. 산출:

1. **2-way ANOVA (statsmodels)**  `metric ~ C(scaler) + C(mask) + C(scaler):C(mask) + C(fold_id)`  → η² 및 F p-value.
2. **Horizon effect** — 별도 1-way ANOVA (horizon은 타겟이 바뀌므로 교차 X).
3. **Effect size 표준화** — hit_rate/coverage/masked_ratio는 pp, Pearson은 Fisher-z, Sharpe는 원값.
4. **FDR 보정** — BH q-value (`statistical_tests.py:402` 재사용).
5. **Waterfall** — best treatment vs baseline, scaler/mask/horizon/interaction 4 driver 분해 markdown + 수치.
6. **Promotion gate** — 5 AND 조건 자동 평가. 결과 `decision` 필드.

출력: `data/sentiment_join/experiments/{run_id}/report.md`, `waterfall.md`, `anova.json`.

### D7. Bootstrap power 보강

fold n=8이 얕아 Cohen's d=0.5 감지 power ≈ 0.30. **fold-level bootstrap(n=500)** 으로 각 metric 95% CI 생성. 승격 게이트의 `hit_rate Δ ≥ +2pp`는 **CI 하단이 +2pp를 넘어야** 충족으로 간주(보수적 해석).

### D8. 회귀 방지

- `tests/test_outlier_policies.py`
  - fixture 데이터로 4 policy 스냅샷. standard+row 결과가 현 `master_*.parquet` 하나와 수치 동등(tolerance 1e-9).
  - regime stress 케이스(2026-04-17 sim) — column-mask가 해당 행을 보존하는지.
- `tests/test_multi_horizon_targets.py`
  - T+k shift 방향/크기 검증 (forward leak 차단).
  - 마지막 k rows가 NaN인지.
- `tests/test_variance_decomposition.py`
  - sum(drivers) = total Δ 검증 (tolerance 1e-9).
  - ANOVA sum of squares decomposition 항등식.

## Out of Scope

- 서브 인덱스 분리(sentiment/positioning/flow/vol 4-way) — 별도 spec.
- LightGBM·elastic net 등 supervised 벤치 — 별도 spec.
- Transfer Entropy / CCM — 별도 spec.
- Futures lineage 컬럼(`funding_source` 등) — 별도 spec (리포트 §5 대응용).
- 프론트엔드 표출 변경 — 이번 spec은 백엔드·분석 레이어만.

## Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Column-mask 때문에 dropna 후 Granger 샘플이 더 줄어 이상 결과 | M | flags DataFrame으로 row-valid 계산 유지, Granger는 pairwise dropna 그대로 |
| no-mask에서 PCA 불안정 | M | 기존 VIF 게이트(10.0) 유지, 필요 시 5.0 조정 옵션 |
| Winsorize q01/q99 고정값 한계 | L | 민감도 분석 서브태스크로 q02/q98, q05/q95 비교 포함 |
| 64 cell × 4 horizon 실행 시간 | M | fold 재사용 캐시 (scaler·PCA만 재학습), 예상 30~45분/run |
| Bootstrap CI로 게이트가 너무 엄격 → 모두 research_only | M | 2-tier 게이트: "promote" vs "conditional_promote" (CI 하단 +1pp 이상) 도입 |
