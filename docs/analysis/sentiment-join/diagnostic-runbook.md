# Sentiment Join Diagnostic Runbook

이 문서는 sentiment-join 파이프라인을 다시 돌린 뒤 원인을 명확하게 추적하는 운영 절차입니다. 기준 산출물은 `data/sentiment_join/master_YYYYMMDD.parquet`와 Parquet metadata의 `sentiment_join_stats`입니다.

## 1. 재실행 경로

GitHub Actions에서 수동 실행하는 경로를 우선 사용합니다. secret 값을 로컬에서 출력하지 않고, workflow artifact로 master parquet를 받을 수 있기 때문입니다.

```bash
gh workflow run sentiment-join.yml -f lookback_days=540
gh run list --workflow sentiment-join.yml --limit 5
gh run watch <run_id> --exit-status
gh run download <run_id> -n sentiment-join-artifacts -D /tmp/sentiment-join-<run_id>
```

로컬에서 실행할 때는 필요한 환경변수가 이미 준비되어 있다는 전제에서만 실행합니다. `.env` 또는 `.env.*` 내용을 출력하지 않습니다.

```bash
SENTIMENT_JOIN_LOOKBACK_DAYS=540 \
SENTIMENT_JOIN_REGIME_WARMUP_DAYS=220 \
make sentiment-join
```

## 2. 첫 진단 명령

새 master parquet가 생성되면 metadata를 먼저 봅니다. 원인 분석은 본문 DataFrame보다 `sentiment_join_stats`를 먼저 확인하는 순서가 더 빠릅니다.

```bash
export MASTER=data/sentiment_join/master_YYYYMMDD.parquet
.venv/bin/python - <<'PY'
import json
import os
from collections import Counter

import pandas as pd
import pyarrow.parquet as pq

master = os.environ["MASTER"]
df = pd.read_parquet(master)
meta = pq.read_metadata(master).metadata or {}
stats = json.loads(meta[b"sentiment_join_stats"].decode("utf-8"))

print("rows", len(df), df["date"].min(), df["date"].max())
print("sources", {c: sorted(df[c].dropna().unique().tolist()) for c in df if c.endswith("_source")})
print("ffill_breakdown", json.dumps(stats.get("ffill_breakdown", {}), indent=2, ensure_ascii=False))
print("granger_results", len(stats.get("granger_results", [])))
print("granger_skips", len(stats.get("granger_skips", [])))
print("granger_skip_summary", stats.get("granger_skip_summary", {}))
print("skip_by_pair", Counter((s.get("predictor"), s.get("target"), s.get("reason")) for s in stats.get("granger_skips", [])))
print("target_diagnostics", json.dumps(stats.get("target_diagnostics", {}), indent=2, ensure_ascii=False))
print("baseline_horizons", sorted(stats.get("baseline_metrics", {}).keys()))
print("alpha_horizons", sorted(stats.get("horizon_metrics", {}).keys()))
PY
```

## 3. 원인 판정 순서

1. 산출물이 없으면 workflow의 `Upload sentiment join artifacts` 단계와 `Run sentiment time join` 로그를 먼저 확인합니다. `gh run view <run_id> --log`로 실패 지점을 좁힙니다.
2. `etf_source`가 `unknown`이면 ETF lineage가 깨진 상태입니다. master 본문 `etf_source`와 `sentiment_join_stats.structured_sources.btc_etf`를 같이 봅니다.
3. `ffill_days`가 커 보이면 총합만 보지 말고 `ffill_breakdown.btc/usdkrw/vix`로 분해합니다. USDKRW/VIX는 주말과 휴장일 ffill이 정상적으로 발생할 수 있고, BTC ffill이 크면 수집 결측 가능성을 우선 봅니다.
4. Granger가 `0 / 0`처럼 보이면 `len(granger_results) + len(granger_skips)`를 확인합니다. 이제 각 pair는 결과 또는 skip 중 하나에 남아야 합니다.
5. `granger_skip_summary.non_stationary_after_diff`가 많으면 데이터 결측 문제가 아니라 정상성 gate에서 차단된 것입니다. 이 경우 해당 pair의 `pred_conclusion`, `tgt_conclusion`, `diff_conclusion`을 봅니다.
6. `insufficient_pair_rows_pre_stationarity` 또는 `insufficient_pair_rows_post_stationarity`가 많으면 lookback, source coverage, outlier mask 이후 유효 행 수를 확인합니다.
7. Alpha 성능은 `horizon_metrics`만 단독으로 보지 말고 같은 horizon의 `baseline_metrics` 대비 uplift로 봅니다. T일 feature는 T+1/T+3/T+7 target만 예측하는 기준입니다.
8. `btc_ma_200d` 초반 결측이 많으면 `SENTIMENT_JOIN_REGIME_WARMUP_DAYS`를 확인합니다. 기본값 220일이면 540일 lookback에서 초기 NaN 비율이 크게 줄어야 합니다.
9. large move 비율이 과하면 `target_diagnostics.btc_large_move_3d`와 `target_diagnostics.btc_large_move_3d_vol_adj`를 비교합니다. fixed threshold와 volatility-adjusted target을 분리해서 해석합니다.

## 4. 성공 기준

재실행 후 아래 조건을 체크합니다.

- `etf_source`가 `unknown`이 아니라 `gold_history` 등 실제 source mode로 남습니다.
- `sentiment_join_stats.ffill_breakdown`에 `btc`, `usdkrw`, `vix`별 `filled_days`와 `max_periods`가 있습니다.
- Granger 대상 pair는 `granger_results` 또는 `granger_skips` 중 하나에 기록됩니다.
- `baseline_metrics`, `horizon_metrics`, `walk_forward_horizons`가 horizon `1`, `3`, `7` 기준으로 해석 가능합니다.
- `target_diagnostics`에서 fixed large move와 volatility-adjusted large move의 positive rate를 비교할 수 있습니다.

## 5. 실험 승격 절차

신규 regime interaction feature는 gate 통과 전까지 full hybrid 기본 후보로 승격하지 않습니다. 실험은 기존 runner와 variance report로 수행합니다.

```bash
python scripts/run_outlier_ablation.py --master "$MASTER"
make sentiment-variance-report RUN_ID=data/sentiment_join/experiments/<run_id>
```

promotion gate는 아래 5개 조건을 모두 만족할 때만 통과입니다.

- `hit_rate uplift >= +2pp`
- `Sharpe uplift >= +0.10`
- `coverage >= 0.85`
- `stability >= 0.50`
- `masked_ratio <= 0.10`

`report.md`에서 `promote`가 없으면 후보 feature는 연구용으로만 유지합니다.

## 6. CI 추적

PR 또는 push 후에는 GitHub Actions 상태를 끝까지 확인합니다.

```bash
gh pr checks --watch
gh pr checks --json name,state,bucket,link,workflow
```

실패가 뜨면 해당 run log를 먼저 봅니다.

```bash
gh run view <run_id> --json name,workflowName,conclusion,status,url,headBranch,headSha
gh run view <run_id> --log
```

수정은 실패 로그의 직접 원인에만 제한합니다. unrelated 파일이나 기존 untracked 분석 산출물은 stage하지 않습니다.
