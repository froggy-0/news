# Signal Pipeline 현황 — 2026-05-03

다음 세션에서 컨텍스트 없이 바로 이어서 작업할 수 있도록 현재 상태를 기록합니다.

---

## 현재 상태 한 줄 요약

`vol_regime_v2_vix_realized_vol_2of2`는 **overlay gate 통과(decision=promote)** 상태.
`decision_strict=research_only` (CI 분리 미달)로 운영 적용 여부 판단 보류 중.
신규 feature 추가를 위한 사전 작업 완료.

---

## 데이터 현황

| 항목 | 값 |
|---|---|
| 최신 parquet | `data/sentiment_join/sentiment_join_master_20260502.parquet` |
| parquet 날짜 범위 | 2024-11-08 ~ 2026-05-01 (539행, 82컬럼) |
| 최신 artifact | `data/sentiment_join/latest.json` (referenceDate: 2026-05-01) |
| drift JSONL | `data/sentiment_join/vol_regime_v2_drift.jsonl` (21일치) |

---

## vol_regime_v2 게이트 현황

```
evaluate_regime_overlay_gate() 결과 (2026-05-03 실행):
  decision          : promote
  n_records         : 21
  rolling_hit_rate  : 0.6147  (기준: ≥ 0.55)  ✅
  rolling_coverage  : 0.5621  (기준: 0.45~0.70) ✅
  rolling_p_median  : 0.0137  (기준: < 0.10)   ✅
```

```
latest.json promotionGate:
  vol_regime_v2_vix_realized_vol_2of2  → decision=promote, promoted_from_research_rule=True
  decision_strict                      → research_only  (CI 미분리, fdr_q=1.0)
```

**판단 보류 이유**: `decision_strict` 실패. 원인은 통계 구조적 문제 (BH 보정 m=26, 현 샘플로 불가).

---

## 분석 결과 (20260502 parquet 기준)

### Cost Sensitivity
| baseline | breakeven fee | 실거래 edge (taker 7bps) |
|---|---|---|
| vol_regime | ~96.1 bps/leg | ✅ 충분 |
| **vol_regime_v2** | **~53.5 bps/leg** | ✅ 충분 |
| fng_contrarian | ~0.2 bps | ⚠ 없음 |

### Voting Rules (horizon=7d, latest.json 기준)
| predictor | HR | uplift | coverage |
|---|---|---|---|
| vote_vol_vix_sent_fng5_3of4 | 56.7% | +1.9% | 33.4% ⚠ |
| vix_low_long_only | 56.4% | +1.6% | 43.4% |
| vote_vol_sent_fng5_2of3 | 56.2% | +1.4% | 34.3% ⚠ |
| ~~vol_regime_v3~~ | 제거됨 | ~~-0.1%~~ | — |
| ~~vote_vix_fng_2of2~~ | 제거됨 | ~~-1.5%~~ | — |

### ACF Block Length (20260502 기준)
- `vix_regime_score_lag1`: first_insignificant=5 → block_length=14 유지
- `fng_value_lag1`: first_insignificant=6 → block_length=14 유지
- `etf_net_inflow_usd_log1p_lag1`: first_insignificant=2 → block_length=14 유지

---

## 이번 세션에서 완료한 사전 작업

### 1. 가설 집합 축소 (BH 보정 완화)

**`statistical_tests.py` — `_SPARSE_RESEARCH_RULE_CONFIGS`**:
- 제거: `vol_regime_v3_vix_realized_vol_ma200_2of3` (HR delta -0.1%, 검정력 5%)
- 제거: `vote_vix_fng_2of2` (HR delta -1.5%, 검정력 2%)
- 효과: BH 보정 threshold 0.10/6 → 0.10/4 (25% 완화)

**`scripts/analysis/eval_voting_rules.py` — `_VOTING_LABELS`**:
- 동일하게 2개 제거

**`_sparse_research_rule` 신호 함수**:
- 제거된 rule 분기 삭제

### 2. 1d/3d 보조 horizon 추가 (다음 replay부터 자동 수집)

**`scripts/analysis/replay_vol_regime_v2_history.py`**:
- `_AUX_HORIZONS = {1: "btc_fwd_ret_1d", 3: "btc_fwd_ret_3d"}` 추가
- `_extract_drift_record()` — 보조 horizon 지표를 JSONL 레코드에 포함
  - `vol_regime_v2_hit_rate_1d`, `vol_regime_v2_hit_rate_3d`
  - `vol_regime_v2_coverage_1d`, `vol_regime_v2_coverage_3d`
  - `sparse_hit_rate_1d`, `sparse_hit_rate_3d`

**`scripts/analysis/eval_voting_rules.py`**:
- `--multi-horizon` 플래그 추가 — artifact의 1d/3d 데이터가 있으면 표 출력
- 현재 latest.json은 7d만 있어 "재생성 필요" 메시지 출력됨

### 3. Exchange Net Outflow 스캐폴딩

**신규 파일**: `src/morning_brief/analysis/sentiment_join/sources/exchange_outflow.py`
- 3개 제공자 skeleton: CryptoQuant, Glassnode, CoinMetrics
- `EXCHANGE_OUTFLOW_PROVIDER` 환경변수로 제공자 선택
- 파이프라인 연결 방법 + 구현 체크리스트 문서화

**`src/morning_brief/analysis/sentiment_join/join.py`**:
- `merge_sources()` 안에 TODO 블록 주석 추가 (해제하면 바로 연결됨)

---

## 다음 세션 작업 목록

### 우선순위 1: Exchange Net Outflow 구현

```
결정 필요: 어떤 API 제공자를 쓸 것인가?
  - CryptoQuant (권장, 가장 풍부한 데이터): 유료 API 키 필요
  - CoinMetrics Community: 무료이나 rate limit 있음
  - Glassnode: 무료 tier는 주별만, 일별은 유료
```

구현 순서:
1. `exchange_outflow.py` — `_fetch_cryptoquant()` 또는 `_fetch_coinmetrics()` 구현
2. `join.py` — TODO 주석 해제 + `merge_sources()` 시그니처 업데이트
3. `join.py` — `_add_futures_lag_columns()` 또는 별도 함수에 lag1 생성
4. `statistical_tests.py` — `_PREDICTORS_RAW`에 `"btc_exchange_net_outflow_usd"` 추가
5. `baselines.py` — `exchange_outflow_long()` 신호 함수 추가
6. `check_acf_block_length.py` — predictor 목록에 추가
7. parquet 재생성 + replay 실행 (1d/3d 보조 horizon 포함)

### 우선순위 2: 통계 파워 분석 재확인 (rule 제거 후)

```bash
# 가설 4개로 줄인 뒤 BH 보정 threshold 확인
python scripts/analysis/eval_voting_rules.py \
    --horizon 7 --all-rules --multi-horizon
```

새 replay로 latest.json을 20260502 기준으로 재생성하면 fdr_q가 개선되는지 확인.

### 우선순위 3: Overlay Gate 소프트 런치 판단

현재 모든 rolling 기준 충족 (21일). 이번 주 안에:
- `decision_strict` 보조 지표화 → PR 검토
- 실제 포트폴리오에 소프트 적용 여부 결정 (포지션 사이즈 축소 → 점진 확대)

---

## 통계 파워 문제 배경 (다음 세션 참고)

**fdr_q = 1.000 원인**: BH 보정 m=26 predictor에서 2% HR delta를 감지하려면 ~15,000 샘플 필요. 현재 180~340 샘플 → 검정력 8~10%.

**가설 축소 후 효과**:
- m=6 → m=4: BH threshold 0.10/6=0.017 → 0.10/4=0.025 (47% 완화)
- 2% HR delta + n=234 → power 여전히 낮음 (~12%)
- 실질적 해결: exchange outflow 피쳐 (예상 HR delta 5~10%)

**현실적 목표**: fdr_q 통과보다는 overlay gate 21일 → 60일 지속 확인 후 운영 결정.

---

## 주요 파일 경로

| 역할 | 경로 |
|---|---|
| 주 분석 로직 | `src/morning_brief/analysis/sentiment_join/statistical_tests.py` |
| 게이트 평가 | `src/morning_brief/analysis/sentiment_join/variance.py` |
| 데이터 합산 | `src/morning_brief/analysis/sentiment_join/join.py` |
| Exchange outflow | `src/morning_brief/analysis/sentiment_join/sources/exchange_outflow.py` |
| Drift 분석 | `scripts/analysis/check_vol_regime_v2_drift.py` |
| Voting 평가 | `scripts/analysis/eval_voting_rules.py` |
| Replay | `scripts/analysis/replay_vol_regime_v2_history.py` |
| 통합 모니터링 | `scripts/monitor_r2.py` |
| 최신 artifact | `data/sentiment_join/latest.json` |
| Drift JSONL | `data/sentiment_join/vol_regime_v2_drift.jsonl` |
