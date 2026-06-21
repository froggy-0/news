# Arena Next Session Handoff

작성일: 2026-06-19

이 문서는 새 세션에서 BTC Signal Arena 현황을 빠르게 복원하기 위한 시작점이다. 먼저 이 문서를 읽고, 필요한 세부 문서로 내려간다.

## 먼저 읽을 문서 순서

1. `docs/arena/overview/next-session-handoff.md`
2. `docs/arena/overview/current-state.md`
3. `docs/arena/operations/access-runbook.md`
4. `docs/arena/architecture/system-map.md`
5. `docs/arena/reference/parameter-inventory.md`
6. `docs/arena/research/backtest-framework-v1.md`
7. `docs/arena/research/frequency-research-v1.md`
8. `docs/arena/research/realtime-execution-gate-v1.md`
9. `docs/arena/research/realtime-risk-trigger-v1.md`
10. `docs/arena/overview/decision-log.md`

## 현재 한 줄 상태

Arena는 EC2 상시 프로세스에서 `BTCUSDT` 4H **현물 spot long/flat** paper trading을 돌도록 설계되어 있다. 데이터레이크, snapshot, backtest, validation, portfolio risk layer v1, walk-forward/report mart, market-structure shadow, frequency research v1, realtime execution gate v1, realtime risk trigger v1, spot semantics v1 코드까지 구현됐다. 선물 데이터는 시장 구조 피처로 수집하지만 실거래/모의거래 실행은 현물 long/flat만 허용한다.

## 최신 운영 확인값

| 항목 | 값 |
| --- | --- |
| EC2 | `3.39.201.112` |
| service | `arena.service` |
| remote dir | `/home/ubuntu/news` |
| deployment shape | Git checkout 아님. `src/arena` rsync 배포 |
| latest checked service | `active`, `SubState=running`, `ExecMainStatus=0` |
| latest live run | `89c6ca1d-a62b-4c1e-97ae-c5b3d5a563cf` |
| latest run status | `completed` |
| latest capture | `capture_status=ok`, `capture_error_count=0`, `capture_warnings=[]` |
| latest params | code 기준 `arena-params-v14` |
| latest risk model | `portfolio-risk-v1` |
| latest feature set | code 기준 `arena-features-v5` |
| open positions | spot mart 기준 long만 허용. legacy synthetic short는 archive mart로 분리 |
| open position caveat | spot 전환 이후 신규 `paper_positions.direction='short'`는 생성되면 안 됨 |
| trading product | 현물 spot only |
| executable directions | `long` / `flat` only |

## 현재 완료된 단계

1. 금융 모델링 결함 수정
   - OHLCV 수집, ATR, macro stale check, MACD threshold, min hold, ATR stop-loss, stop_loss_price 저장.

2. 파라미터 인벤토리와 상수화
   - `src/arena/parameters.py` 중심.
   - 현재 코드 기준은 `arena-spot-v3`, `arena-params-v14`, `arena-features-v5`, `portfolio-risk-v1`.

3. 재현성 snapshot
   - `paper_positions`에 strategy/params/indicator/macro/market/signal/data timestamp 계층 추가.
   - portfolio risk 이후에는 `risk_snapshot`도 추가.

4. 데이터 수집 계층 분리
   - `arena_runs`
   - `arena_ohlcv_bars`
   - `arena_run_ohlcv_bars`
   - `arena_macro_snapshots`
   - `arena_indicator_snapshots`
   - `arena_decisions`

5. Strategy/Feature Mart
   - `arena_strategy_versions`
   - `arena_feature_registry`
   - `arena_decision_mart_v1`

6. Backtest/Validation Framework
   - `arena_backtest_runs`
   - `arena_backtest_trades`
   - `arena_backtest_equity_curve`
   - `arena_walk_forward_splits`
   - `arena_backtest_validation_*`

7. Portfolio Risk Layer v1
   - `src/arena/risk.py`
   - `arena_risk_events`
   - `arena_risk_state`
   - `arena_backtest_risk_events`
   - `risk_snapshot`, `risk_decision`

8. Walk-forward / Report Mart
   - `src/arena/walk_forward.py`
   - `arena_backtest_report_mart_v1`
   - `arena_backtest_algo_summary_v1`

9. vNext Shadow Research
   - `src/arena/market_structure.py`
   - `src/arena/regime.py`
   - `src/arena/sleeves.py`
   - `src/arena/allocator.py`
   - `arena_shadow_decisions`

10. Frequency Research v1
   - `src/arena/frequency.py`
   - `arena_frequency_profiles`
   - `arena_indicator_feature_bars`
   - `arena_frequency_backtest_mart_v1`
   - `live_4h`, `research_1h`, `research_15m` profile 분리

11. Realtime Execution Gate v1
   - `src/arena/realtime_market.py`
   - `src/arena/execution_gate.py`
   - `arena_realtime_feature_bars`
   - `arena_execution_gates`
   - 기본은 shadow-only, live paper 차단 없음

12. Spot Semantics v1
   - `src/arena/spot_policy.py`
   - `paper_positions.product_type`, `position_semantics`, `close_reason`
   - `arena_decisions.raw_signal`, `executable_signal`, `product_policy_snapshot`
   - raw short는 long 청산 또는 no-trade로 기록

## 다음 세션 시작 시 확인 명령

서비스 상태:

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'systemctl is-active arena.service && systemctl show arena.service -p ActiveState -p SubState -p ExecMainStatus -p NRestarts --no-pager'
```

최근 로그:

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'journalctl -u arena.service -n 120 --no-pager --output=short-iso'
```

로컬 검증:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m pytest tests/test_arena_*.py -q
.venv/bin/ruff check src/arena tests/test_arena_*.py scripts/backfill_arena_ohlcv.py
```

백테스트 dry-run:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.backtest --limit 100
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile live_4h --limit 300
PYTHONPATH=src .venv/bin/python -m arena.walk_forward --profile live_4h
```

## Supabase에서 먼저 볼 쿼리

최신 run:

```sql
select
  run_id,
  started_at,
  completed_at,
  status,
  runtime,
  symbol,
  interval,
  data_timestamp,
  strategy_version,
  params_version,
  risk_model_version,
  capture_status,
  capture_error_count,
  capture_warnings
from arena_runs
order by started_at desc
limit 5;
```

최신 decision:

```sql
select
  algo_id,
  signal,
  raw_signal,
  executable_signal,
  action,
  skipped_reason,
  product_policy_snapshot,
  current_position_id,
  resulting_position_id,
  risk_decision,
  risk_snapshot
from arena_decisions
where run_id = '<LATEST_RUN_ID>'
order by algo_id;
```

최근 position:

```sql
select
  id,
  algo_id,
  direction,
  status,
  product_type,
  position_semantics,
  close_reason,
  open_time,
  close_time,
  strategy_version,
  params_version,
  risk_snapshot,
  data_timestamp
from paper_positions
order by id desc
limit 10;
```

Risk layer readiness:

```sql
select * from arena_portfolio_risk_layer_ready_v1;
```

Spot semantics readiness:

```sql
select * from arena_spot_semantics_v1_ready;
```

Walk-forward/report mart readiness:

```sql
select * from arena_walk_forward_enhancements_ready;
```

Market-structure/shadow readiness:

```sql
select * from arena_market_structure_v1_ready;
select * from arena_shadow_vnext_ready;
```

Frequency research readiness:

```sql
select * from arena_frequency_research_v1_ready;
```

Realtime execution readiness:

```sql
select * from arena_realtime_execution_v1_ready;
select * from arena_execution_gate_shadow_ready;
select * from arena_realtime_risk_v1_ready;
```

최근 risk event:

```sql
select
  algo_id,
  event_type,
  created_at,
  risk_decision
from arena_risk_events
order by created_at desc
limit 10;
```

## 다음 구현 우선순위

### 0. Supabase SQL 적용

먼저 아래 migration을 Supabase SQL Editor에서 실행한다.

- `/Users/giwon/code/news/supabase/migrations/20260620_arena_realtime_execution_v1.sql`
- `/Users/giwon/code/news/supabase/migrations/20260621_arena_realtime_risk_v1.sql`

확인:

```sql
select * from arena_market_structure_v1_ready;
select * from arena_shadow_vnext_ready;
select * from arena_frequency_research_v1_ready;
select * from arena_realtime_execution_v1_ready;
select * from arena_execution_gate_shadow_ready;
select * from arena_realtime_risk_v1_ready;
```

### 1. Realtime Execution Gate Shadow 확인

목표:

- 4H live paper trading은 유지한다.
- 전략 신호별 gate decision과 no-trade reason을 저장한다.
- realtime collector는 SQL 적용 후 별도 env로 켠다.

확인:

```sql
select
  algo_id,
  signal,
  timeframe,
  decision,
  reject_reason,
  expected_return_bps,
  expected_cost_bps,
  spread_bps,
  expected_slippage_bps,
  created_at
from arena_execution_gates
order by created_at desc
limit 20;
```

주의: `ENABLE_ARENA_EXECUTION_GATE_LIVE=false` 기본값을 유지한다.

### 2. Realtime Risk Trigger Shadow 확인

목표:

- 1분 realtime risk state를 저장한다.
- 4H 신호에는 최신 risk state snapshot만 붙인다.
- live flag가 false인 동안 기존 `paper_positions` open/close는 바꾸지 않는다.

확인:

```sql
select
  symbol,
  window_start,
  risk_state,
  risk_score,
  recommended_action,
  quality_status
from arena_realtime_risk_states
order by window_start desc
limit 30;
```

주의: `ENABLE_ARENA_REALTIME_RISK_LIVE=false` 기본값을 유지한다.

### 3. Walk-forward 적용 상태 검증

CLI:

```bash
PYTHONPATH=src .venv/bin/python -m arena.walk_forward --profile live_4h --save
PYTHONPATH=src .venv/bin/python -m arena.walk_forward --profile research_1h --save
```

현재 로컬 smoke 기준:

- `live_4h`: 3 splits 생성.
- `research_1h`: DB에 1H raw 저장 전이라 `insufficient_data`.

### 4. Backtest / Frequency Mart 적용 상태 검증

목표:

- run, trade, equity, validation, risk event를 한 번에 볼 수 있는 summary view를 유지한다.
- `end_of_data` 포함/제외 성과를 분리한다.
- `trades_per_day`, `turnover_per_day`, `trading_cost_drag_pct`, `funding_drag_pct`, `cost_to_gross_ratio`를 같이 본다.

객체:

- `arena_backtest_report_mart_v1`
- `arena_backtest_algo_summary_v1`
- `arena_frequency_backtest_mart_v1`

CLI:

```bash
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile live_4h --cost-scenario base --limit 300
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile research_1h --indicator-profile time_normalized_v1 --cost-scenario base --limit 1000
```

### 4. Risk Layer Live Verification

목표:

- 신규 open position이 생기거나 risk block이 생겼을 때 실제 DB snapshot이 채워지는지 확인한다.

확인 기준:

- 신규 `paper_positions.risk_snapshot`이 `{}`가 아님.
- `arena_decisions.risk_decision`이 `{}`가 아님.
- `risk_blocked` 발생 시 `arena_risk_events`에 row가 생김.

주의:

- 현재 open position 2개는 legacy라 risk snapshot이 비어 있다.
- 다음 신규 진입부터 봐야 한다.

### 5. vNext / Frequency Shadow Run Verification

목표:

- `ENABLE_ARENA_SHADOW_VNEXT=true` 기준으로 기존 paper trading은 유지하고 shadow decision만 기록한다.
- `arena_market_feature_snapshots`와 `arena_shadow_decisions`가 최신 run에 생성되는지 확인한다.
- market-structure fetch 실패가 기존 paper run 실패로 전파되지 않는지 확인한다.

확인:

```sql
select run_id, quality_status, quality_errors, features
from arena_market_feature_snapshots
order by created_at desc
limit 5;

select run_id, sleeve_id, algo_id, signal, action, target_weight, allocation_snapshot
from arena_shadow_decisions
order by created_at desc
limit 10;
```

frequency shadow는 기본 비활성화다. 1H raw/backtest가 정상화된 뒤 `.env` 또는 systemd env에 `ENABLE_ARENA_FREQUENCY_SHADOW=true`를 넣고 재시작한다. 활성화되어도 `paper_positions`는 변경하지 않는다.

## 아직 하면 안 되는 것

- 파라미터 튜닝.
- baseline 수익률로 전략 우열 판단.
- `macd_momentum`의 짧은 구간 수익률을 제품/홍보 근거로 사용.
- Lambda와 EC2 동시 활성화.
- risk limit 값을 데이터 없이 완화.

## 운영 주의점

- EC2 `/home/ubuntu/news`는 Git repo가 아니다.
- `deploy/deploy.sh`는 원격 `git pull`을 전제하므로 현재 서버에는 맞지 않는다.
- 현재 검증된 배포 방식은 `src/arena`와 `requirements.txt`를 `rsync`하고 원격 compile 후 service restart하는 방식이다.
- `.env`와 service role key 값은 읽거나 문서화하지 않는다.

## 현재 검증된 배포 명령

```bash
cd /Users/giwon/code/news
rsync -az --delete --exclude='__pycache__/' --exclude='*.pyc' \
  -e 'ssh -i ~/.ssh/arena_ed25519' \
  src/arena/ ubuntu@3.39.201.112:/home/ubuntu/news/src/arena/

rsync -az -e 'ssh -i ~/.ssh/arena_ed25519' \
  requirements.txt ubuntu@3.39.201.112:/home/ubuntu/news/requirements.txt

ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'cd /home/ubuntu/news && .venv/bin/python -m compileall -q src/arena && sudo systemctl restart arena.service && systemctl is-active arena.service'
```

## 다음 세션의 첫 질문에 대한 답

“다음은 walk-forward인가?”에 대한 현재 답은 **부분적으로만 예**다. live 4H walk-forward는 이미 동작한다. 다음은 frequency SQL 적용과 1H/15m raw 저장 후 `research_1h` walk-forward/backtest를 돌려 빈도별 비용 민감도를 보는 것이다.
