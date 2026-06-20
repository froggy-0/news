# Real-time Execution Gate v1

작성일: 2026-06-20

## 목적

데이터는 가능한 한 실시간으로 관측하되, 거래는 4H/1H 전략 신호와 체결 품질 조건이 동시에 충족될 때만 실행한다.

이번 단계는 shadow-only다. 기본값에서 `paper_positions` 생성 로직은 변경하지 않는다.

## 코드 구성

| 영역 | 파일 | 역할 |
| --- | --- | --- |
| 실시간 수집 | `/Users/giwon/code/news/src/arena/realtime_market.py` | trade, bookTicker, depth, 1m kline을 1분 feature로 집계 |
| 체결 gate | `/Users/giwon/code/news/src/arena/execution_gate.py` | expected return, cost, spread, slippage, depth, latency, risk 조건 평가 |
| 저장 | `/Users/giwon/code/news/src/arena/data_lake.py` | `arena_realtime_feature_bars`, `arena_execution_gates` write |
| 연결 | `/Users/giwon/code/news/src/arena/scheduler.py` | 4H live decision과 vNext shadow decision에 gate snapshot 기록 |
| 서버 | `/Users/giwon/code/news/src/arena/server.py` | env 활성화 시 realtime collector task 실행 |

## 기본 정책

| 항목 | 기본값 | 의미 |
| --- | ---: | --- |
| `ENABLE_ARENA_REALTIME_COLLECTOR` | `false` | SQL 적용 전 noisy write 방지 |
| `ENABLE_ARENA_EXECUTION_GATE_SHADOW` | `true` | gate 판단은 shadow ledger에 저장 |
| `ENABLE_ARENA_EXECUTION_GATE_LIVE` | `false` | 기존 paper open 차단하지 않음 |
| `EXEC_GATE_ECR_MULTIPLE` | `3.0` | expected return이 비용의 3배 이상일 때만 통과 |
| `EXEC_GATE_MAX_SPREAD_BPS` | `5.0` | spread 초과 시 no-trade |
| `EXEC_GATE_MAX_SLIPPAGE_BPS` | `8.0` | 예상 slippage 초과 시 no-trade |
| `EXEC_GATE_MIN_DEPTH_SCORE` | `0.5` | depth 부족 시 no-trade |
| `EXEC_GATE_MAX_LATENCY_MS` | `750` | API latency 초과 시 no-trade |

## SQL 적용

```sql
-- /Users/giwon/code/news/supabase/migrations/20260620_arena_realtime_execution_v1.sql
select * from arena_realtime_execution_v1_ready;
select * from arena_execution_gate_shadow_ready;
```

## 운영 순서

1. SQL migration을 Supabase SQL Editor에서 실행한다.
2. 로컬 테스트를 통과시킨다.
3. EC2에 코드 배포 후, 우선 기본값으로 재시작한다.
4. `arena_execution_gates`에 4H decision gate snapshot이 쌓이는지 확인한다.
5. realtime feature를 쌓을 준비가 되면 systemd env에 `ENABLE_ARENA_REALTIME_COLLECTOR=true`를 추가하고 재시작한다.
6. 최소 2주 이상 reject reason과 missed opportunity를 검토하기 전에는 `ENABLE_ARENA_EXECUTION_GATE_LIVE=true`로 승격하지 않는다.

## 확인 쿼리

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

select
  symbol,
  window_start,
  spread_bps_avg,
  depth_10bp_bid_usd,
  depth_10bp_ask_usd,
  taker_buy_sell_ratio,
  expected_slippage_bps,
  api_latency_ms_p95,
  quality_status
from arena_realtime_feature_bars
order by window_start desc
limit 20;
```
