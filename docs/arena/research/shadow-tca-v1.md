# Shadow TCA v1

작성일: 2026-06-20

## 목적

기존 4H paper trading은 유지하면서, 실제 주문 없이 parent order intent와 체결 품질 추정치를 남긴다. 목표는 새 전략을 빨리 켜는 것이 아니라 spread, depth, slippage, latency가 나쁜 구간을 식별해 손실과 비용 drag를 줄이는 것이다.

## 코드 구성

| 영역 | 파일 | 역할 |
| --- | --- | --- |
| Shadow TCA 계산 | `/Users/giwon/code/news/src/arena/tca_shadow.py` | arrival mid, depth sweep slippage, fill ratio, estimated cost 계산 |
| 저장 | `/Users/giwon/code/news/src/arena/data_lake.py` | `arena_parent_orders`, `arena_execution_quality` write |
| 연결 | `/Users/giwon/code/news/src/arena/scheduler.py` | 4H decision-time book/depth snapshot과 gate decision 기반 shadow parent order 기록 |
| Mart SQL | `/Users/giwon/code/news/supabase/migrations/20260620_arena_tca_shadow_v1.sql` | shadow TCA mart, daily/by-algo view, readiness view |

## 기본 정책

| 항목 | 기본값 | 의미 |
| --- | ---: | --- |
| `ENABLE_ARENA_REALTIME_COLLECTOR` | `true` | 1분 microstructure feature를 수집 |
| `ENABLE_ARENA_EXECUTION_GATE_SHADOW` | `true` | gate 판단과 no-trade reason을 저장 |
| `ENABLE_ARENA_EXECUTION_GATE_LIVE` | `false` | 기존 paper open 차단은 아직 비활성 |
| `ARENA_SHADOW_ORDER_NOTIONAL_USD` | `1000` | shadow sweep 추정용 주문 크기 |
| `ARENA_SHADOW_ORDER_TIMEOUT_SEC` | `30` | 향후 order lifecycle 시뮬레이션용 timeout |
| `ARENA_SHADOW_ARRIVAL_BENCHMARK_SEC` | `1` | arrival benchmark 정의 |

## 운영 원칙

1. `arena_execution_gates`는 모든 알고리즘 gate 판단을 남긴다.
2. `arena_parent_orders`는 실제 주문이 아니라 shadow parent intent다.
3. `arena_execution_quality`의 비용은 실제 fill이 아닌 visible depth 기반 추정치다.
4. depth snapshot이 없으면 `quality_status=degraded`로 남기고 기존 paper cycle은 계속 진행한다.
5. 최소 14일 이상 shadow TCA를 모으기 전에는 `ENABLE_ARENA_EXECUTION_GATE_LIVE=true`로 승격하지 않는다.

## 확인 쿼리

```sql
select * from arena_tca_shadow_v1_ready;

select
  day,
  signal_count,
  trade_allowed_count,
  no_trade_count,
  avg_expected_return_bps,
  avg_expected_cost_bps,
  avg_arrival_slippage_bps,
  avg_cost_to_edge_ratio,
  quality_ok_ratio,
  reject_reason_distribution
from arena_shadow_tca_daily_v1
order by day desc
limit 14;

select
  algo_id,
  signal_count,
  trade_allowed_count,
  no_trade_count,
  avg_cost_to_edge_ratio,
  quality_ok_ratio
from arena_shadow_tca_by_algo_v1
order by signal_count desc;
```

## Live 승격 조건

- realtime feature coverage 14일 이상.
- `arena_execution_gates` reject reason 100건 이상.
- `arena_shadow_tca_daily_v1.quality_ok_ratio >= 0.90`.
- backtest validation critical/high fail 0.
- no-trade shadow가 paper 손익을 과도하게 놓치지 않는지 검토 완료.
