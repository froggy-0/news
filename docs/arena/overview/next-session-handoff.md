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
7. `docs/arena/overview/decision-log.md`

## 현재 한 줄 상태

Arena는 EC2 상시 프로세스에서 `BTCUSDT` 4H paper trading을 돌고 있다. 데이터레이크, snapshot, backtest, validation, portfolio risk layer v1, walk-forward generator, report mart SQL까지 구현됐다. 다음 구현/운영 순서는 market-structure SQL 적용과 vNext shadow run 검증이다.

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
| latest params | code 기준 `arena-params-v6` |
| latest risk model | `portfolio-risk-v1` |
| latest feature set | code 기준 `arena-features-v3` |
| open positions | `fng_contrarian long`, `macd_momentum short` |
| open position caveat | 둘 다 hardening 전 생성된 `legacy` position |

## 현재 완료된 단계

1. 금융 모델링 결함 수정
   - OHLCV 수집, ATR, macro stale check, MACD threshold, min hold, ATR stop-loss, stop_loss_price 저장.

2. 파라미터 인벤토리와 상수화
   - `src/arena/parameters.py` 중심.
   - 현재 코드 기준은 `arena-ec2-v5`, `arena-params-v6`, `arena-features-v3`, `portfolio-risk-v1`.

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
.venv/bin/ruff check src/arena tests/test_arena_*.py
```

백테스트 dry-run:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.backtest --limit 100
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
  action,
  skipped_reason,
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

Walk-forward/report mart readiness:

```sql
select * from arena_walk_forward_enhancements_ready;
```

Market-structure/shadow readiness:

```sql
select * from arena_market_structure_v1_ready;
select * from arena_shadow_vnext_ready;
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

먼저 `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql`을 Supabase SQL Editor에서 실행한다.

확인:

```sql
select * from arena_market_structure_v1_ready;
select * from arena_shadow_vnext_ready;
```

### 1. Walk-forward 적용 상태 검증

목표:

- `arena_walk_forward_splits` 테이블을 실제로 채우는 generator가 동작하는지 확인한다.
- 현재 표본 부족이면 실패가 아니라 `insufficient_data` 또는 `research_only`로 명시한다.
- split은 최적화가 아니라 리포트 골격을 위한 것이다.

CLI:

```bash
PYTHONPATH=src .venv/bin/python -m arena.walk_forward --symbol BTCUSDT --interval 4h --save
```

필수 규칙:

- train/test/embargo 기간이 겹치지 않아야 한다.
- 최소 bar 수 미달이면 split을 만들지 않고 이유를 출력한다.
- `strategy_version`, `params_version`, `risk_model_version`을 저장한다.
- 향후 튜닝이 들어와도 leakage가 생기지 않도록 test window는 완전히 미래여야 한다.

### 2. Backtest Report Mart 적용 상태 검증

목표:

- run, trade, equity, validation, risk event를 한 번에 볼 수 있는 summary view를 만든다.
- `end_of_data` 포함/제외 성과를 분리한다.
- risk-blocked signal count를 같이 보여준다.

객체:

- `arena_backtest_report_mart_v1`
- `arena_backtest_algo_summary_v1`

필수 컬럼:

- `backtest_run_id`
- `algo_id`
- `trade_count`
- `normal_exit_trade_count`
- `end_of_data_trade_count`
- `stop_loss_trade_count`
- `risk_event_count`
- `win_rate`
- `total_return_pct`
- `total_return_ex_end_of_data_pct`
- `max_drawdown_pct`
- `validation_status`
- `fail_count`
- `warn_count`
- `research_only`

### 3. Risk Layer Live Verification

목표:

- 신규 open position이 생기거나 risk block이 생겼을 때 실제 DB snapshot이 채워지는지 확인한다.

확인 기준:

- 신규 `paper_positions.risk_snapshot`이 `{}`가 아님.
- `arena_decisions.risk_decision`이 `{}`가 아님.
- `risk_blocked` 발생 시 `arena_risk_events`에 row가 생김.

주의:

- 현재 open position 2개는 legacy라 risk snapshot이 비어 있다.
- 다음 신규 진입부터 봐야 한다.

### 4. vNext Shadow Run Verification

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

“다음은 walk-forward인가?”에 대한 현재 답은 **아니오, 코드상 walk-forward generator와 report mart SQL은 이미 있다**다. 다음은 market-structure SQL 적용, shadow vNext capture 검증, 그 후 shadow 데이터가 쌓였을 때 전략 승격 여부 판단이다.
