# Sprint Review — 2026-05

이번 스프린트에서 개선된 내용과 앞으로 주의해야 할 포인트를 정리합니다.

---

## 무엇이 바뀌었나

### P1 · 데이터 정합성

| 항목 | 변경 내용 |
|---|---|
| `_baseline_hits_series` 인덱스 정렬 | `reindex` + `fillna(0)` 순서 버그 수정 — 기존에는 aligned 이전 인덱스로 hits 계산 시 날짜 어긋남 발생 가능 |
| `validate_latest_artifact.py` | 배포 전 latest.json 필드 존재·범위 검증 스크립트 추가 (`scripts/validate_latest_artifact.py`) |

### P2 · 통계 신뢰구간 & 드리프트 추적

| 항목 | 변경 내용 |
|---|---|
| Block bootstrap CI | `bootstrap.py` — circular block, B=1000, L=14, BH-FDR q≤0.10 적용 |
| `decision` vs `decision_strict` 갭 | 파이프라인 실행 시 갭 비율(`gapRatio`) 자동 계산 후 artifact에 기록 |
| vol_regime_v2 드리프트 추적 | `storage.py` — JSONL 파일에 매 실행마다 hit_rate·coverage·p-value 누적 |
| 드리프트 확인 스크립트 | `scripts/analysis/check_vol_regime_v2_drift.py` — 최근 14일 롤링 요약 + 14일 트렌드 출력 |

### P3 · 신호 확장

| 항목 | 변경 내용 |
|---|---|
| ETF 유입 threshold 3-variant | `etf_net_inflow_usd_log1p_lag1_inverted`, `_q75`, `_q80` — 고정 threshold 대신 롤링 분위수 사용 |
| Voting rule 군 평가 | `vote_vol_sent_fng5_2of3`, `vote_vix_fng_2of2` 등 6개 rule 추가 + `eval_voting_rules.py` |
| `vote_vix_fng_2of2` 신호 | VIX q40 + FNG 중립(50) 기준 2/2 동의 시에만 진입하는 sparse 연구 신호 |

### P4 · 비용·리스크 분석 & 승격 게이트

| 항목 | 변경 내용 |
|---|---|
| Transaction cost sensitivity | `baselines.py` — `fee_per_leg_bps` 파라미터 추가, 진입/청산/플립 leg 수 계산 |
| MDD (Max Drawdown) | `evaluate_baseline()` 반환값에 `max_drawdown` 추가 |
| 비용 민감도 스크립트 | `scripts/analysis/vol_regime_v2_cost_sensitivity.py` — 0·2·7·15·25 bps 시나리오별 Sharpe/MDD/hit_rate 출력 + 손익분기 수수료 binary search |
| vol_regime_v2 승격 게이트 | `variance.py` — `evaluate_regime_overlay_gate()`: 롤링 14일 JSONL 기록 기준, 3개 기준 동시 충족 시 "promote" 판정 |

**승격 기준 (모두 충족해야 promote):**

```
hit_rate_rolling_mean  ≥ 0.55
coverage_rolling_mean  0.45 ~ 0.70
p_value_rolling_median ≤ 0.10
최소 기록 수           ≥ 14일
```

### P5 · Frontend & Artifact

| 항목 | 변경 내용 |
|---|---|
| CI 에러 바 시각화 | `AnalysisDashboardPanels.tsx` — hit_rate 바 위에 95% CI 마커(세로선+범위 밴드) 오버레이 |
| `decision_strict` 배지 | promote→hold 갭이 있는 신호에 "strict" 라벨 표시 |
| Research rule 구분 | 알파 보드 하단에 "Research rules · not in production gate" 섹션 분리 |
| Gate stats 패널 | decision vs strict 승격 수 + gapRatio 표시 |
| Sharpe 기준 변경 공지 | `meta.sharpeBasisChangeDate` 존재 시 알파 보드 상단에 황색 배너 표시 (`sqrt(252) → sqrt(365)`) |
| `meta` 필드 | `SentimentInsightArtifact`에 `meta?: JsonObject` 추가, artifact JSON에서 파싱 |

---

## 앞으로 주의해야 할 포인트

### 1. vol_regime_v2 승격 게이트 — 데이터 쌓임 대기

`evaluate_regime_overlay_gate()`는 **최소 14일 JSONL 기록**이 필요합니다.  
현재는 파이프라인 실행이 쌓일수록 정확도가 높아지는 구조입니다.

```
확인 방법:
python scripts/analysis/check_vol_regime_v2_drift.py \
    --jsonl data/sentiment_join/vol_regime_v2_drift.jsonl
```

- `decision: insufficient_data` 가 14일 이상 지속되면 파이프라인이 정상 실행되고 있는지 점검
- 14일 후 `monitor` 상태가 계속되면 hit_rate·coverage·p 중 어느 기준이 미달인지 `message` 필드 확인

### 2. ETF 유입 variant q75/q80 — 통계 검증 필요

`etf_net_inflow_usd_log1p_lag1_q75`, `_q80`은 롤링 분위수 threshold를 사용합니다.  
현재 연구 신호(`research_rule=True`)로 분류되어 있으며, **실제 데이터로 alpha 검증 후** 프로덕션 게이트 진입 여부를 판단해야 합니다.

- decision이 "promote"여도 CI 하한이 best_baseline 이하면 `decision_strict="hold"` — 이 경우 조심
- bootstrap B=1000, L=14는 T+7 horizon 기준으로 튜닝된 값. 다른 horizon 사용 시 재검토 필요

### 3. Transaction cost — 실거래 수수료 검증

현재 `fee_per_leg_bps` 기본값은 `10.0 bps`입니다.  
BTC 현물 실거래 환경 기준:

| 거래 유형 | 예상 비용 |
|---|---|
| Maker | ~2 bps |
| Taker | ~5–7 bps |
| 현물 + 슬리피지 | ~15 bps |
| 보수적 추정 | ~25 bps |

`vol_regime_v2`의 **breakeven fee**가 어느 시나리오까지 버티는지 확인:

```
python scripts/analysis/vol_regime_v2_cost_sensitivity.py \
    --parquet data/sentiment_join/master_latest.parquet
```

breakeven이 7 bps 미만이라면 실거래에서 edge가 없을 가능성이 높습니다.

### 4. Voting rule — coverage 함정

`vote_vix_fng_2of2`, `vote_vol_vix_sent_fng5_3of4` 등 다중 조건 신호는 **abstain(포지션 없음) 구간이 길수록 coverage가 낮아집니다.**  
hit_rate가 높아 보여도 coverage가 30% 이하면 실용성이 낮습니다.

`eval_voting_rules.py` 실행 시 `coverage` 컬럼을 반드시 확인하세요:

```
python scripts/analysis/eval_voting_rules.py \
    --artifact data/sentiment_join/latest.json
```

### 5. Sharpe 비교 시 날짜 경계 주의

**2026-04-30 이전** 산출물은 `sqrt(252)` 기준 Sharpe입니다.  
**2026-04-30 이후**는 `sqrt(365)` 기준입니다.  
두 시기 Sharpe를 직접 비교하면 약 **+20% 과대 평가** 오류가 발생합니다.

```
sqrt(365) / sqrt(252) ≈ 1.204
```

artifact의 `meta.sharpeBasisChangeDate` 필드가 있으면 프론트엔드 알파 보드에 경고 배너가 표시됩니다. 이 배너가 없는 구형 artifact를 참고할 때 주의하세요.

### 6. Bootstrap CI 해석 기준

| 지표 | 기준 |
|---|---|
| `decision = "promote"` | hit_rate_ci_lower > best_baseline |
| `decision_strict = "promote"` | 위 + BH-FDR q ≤ 0.10 |
| `gapRatio > 0.3` | CI 미달 신호 다수 — 전략 신뢰도 재검토 필요 |

`gapRatio`가 30% 초과 시 프론트엔드에 경고 문구가 표시됩니다. 이 경우 block length L 재조정(ACF lag 확인) 또는 신호 필터링 강화를 고려하세요.

---

## 확인 커맨드 체크리스트

```bash
# 1. 파이프라인 실행 후 artifact 검증
python scripts/validate_latest_artifact.py \
    --path data/sentiment_join/latest.json

# 2. vol_regime_v2 드리프트 모니터링
python scripts/analysis/check_vol_regime_v2_drift.py \
    --jsonl data/sentiment_join/vol_regime_v2_drift.jsonl

# 3. voting rule 평가
python scripts/analysis/eval_voting_rules.py \
    --artifact data/sentiment_join/latest.json

# 4. 거래비용 민감도 확인
python scripts/analysis/vol_regime_v2_cost_sensitivity.py \
    --parquet data/sentiment_join/master_latest.parquet

# 5. bootstrap block length ACF 검증 (데이터 업데이트 시마다)
python scripts/analysis/check_acf_block_length.py \
    --parquet data/sentiment_join/master_latest.parquet

# 6. 테스트 전체 실행
.venv/bin/python -m pytest tests/ -q
cd frontend && npm test
```

---

## 파일 맵 (주요 변경 파일)

```
src/morning_brief/analysis/sentiment_join/
├── baselines.py          # fee_per_leg_bps, max_drawdown 추가
├── bootstrap.py          # circular block bootstrap, BH-FDR
├── frontend_artifact.py  # meta.sharpeBasisChangeDate, gateStats 포함
├── pipeline.py           # overlay gate 평가 호출, 드리프트 append
├── statistical_tests.py  # threshold_fn, predictor_name, ETF variant, voting rules
├── storage.py            # JSONL drift 기록 (append_drift_record)
└── variance.py           # OverlayGateResult, evaluate_regime_overlay_gate

scripts/
├── validate_latest_artifact.py
└── analysis/
    ├── check_bootstrap_block_length.py
    ├── check_vol_regime_v2_drift.py
    ├── eval_voting_rules.py
    └── vol_regime_v2_cost_sensitivity.py

frontend/
├── app/analysis/page.tsx                        # meta prop 전달
├── components/analysis/AnalysisDashboardPanels.tsx  # CI 바, 배너, gate 패널
├── lib/analysis-schema.ts                       # meta, gateStats 파싱
└── schema/analysis.types.ts                     # gateStats, meta 타입 추가
```
