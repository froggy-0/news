# Arena System Map

작성일: 2026-06-19

## Runtime

| Layer | Path / Object | Role |
| --- | --- | --- |
| service entry | `src/arena/server.py` | positions init, open positions refresh, scheduler/stream 동시 실행 |
| scheduler | `src/arena/scheduler.py` | 4H OHLCV/macro 수집, indicators 계산, 알고리즘 실행, position open/close |
| stream | `src/arena/stream.py` | Binance WebSocket 현재가 수신, stop-loss 감지 |
| realtime market | `src/arena/realtime_market.py` | Binance trade/book/depth/kline stream을 1분 execution feature로 집계 |
| positions | `src/arena/positions.py` | Supabase `paper_positions` CRUD |
| algorithms | `src/arena/algorithms.py` | 5개 전략 신호 함수 |
| indicators | `src/arena/indicators.py` | RSI, MACD hist, Bollinger position, ATR 계산 |
| parameters | `src/arena/parameters.py` | 거래/지표/스케줄 기본 파라미터 |
| config | `src/arena/config.py` | env 기반 runtime config. secret 값은 문서화하지 않음 |
| rule parity | `src/arena/execution_rules.py` | live/backtest 공통 실행 규칙 |
| portfolio risk | `src/arena/risk.py` | max exposure, daily loss limit, algo MDD kill switch |
| execution gate | `src/arena/execution_gate.py` | expected return, cost, spread, slippage, depth, latency 기반 trade/no-trade 판단 |
| data lake writer | `src/arena/data_lake.py` | arena research table write |
| feature registry | `src/arena/feature_registry.py` | strategy/feature metadata row 생성 |
| backtest | `src/arena/backtest.py` | OHLCV/macro replay, 결과 저장 CLI |
| validation | `src/arena/backtest_validation.py` | backtest 결과 무결성/누수/체결 검증 CLI |

## Live Data Flow

```text
Binance 4H OHLCV + R2 latest.json
  -> scheduler
  -> indicators.compute
  -> algorithms
  -> execution_rules
  -> execution_gate shadow ledger
  -> positions.open/close_position
  -> paper_positions
  -> arena_runs / ohlcv / macro / indicators / decisions
```

Stop-loss path:

```text
Binance WebSocket 1m kline
  -> stream._check_stop_loss
  -> execution_rules.stop_loss_triggered
  -> positions.close_position(is_stop_loss=True)
```

Execution observation path:

```text
Binance trade/bookTicker/depth20/kline_1m streams
  -> realtime_market.RealtimeFeatureAggregator
  -> arena_realtime_feature_bars
  -> scheduler/execution_gate shadow decisions
  -> arena_execution_gates
```

## Research Data Flow

```text
arena_ohlcv_bars + arena_macro_snapshots
  -> arena.backtest
  -> arena_backtest_runs / trades / equity_curve
  -> arena.backtest_validation
  -> arena_backtest_validation_runs / checks
```

## Core Tables

| Table / View | Grain | Purpose |
| --- | --- | --- |
| `paper_positions` | position | live paper trading ledger |
| `arena_runs` | 4H run | one scheduler cycle |
| `arena_ohlcv_bars` | exchange/symbol/interval/open_time | raw market candles |
| `arena_run_ohlcv_bars` | run/candle | run별 입력 candle lineage |
| `arena_macro_snapshots` | run | raw macro payload snapshot |
| `arena_indicator_snapshots` | run | derived indicators |
| `arena_decisions` | run/algo | signal/action/reason |
| `arena_realtime_feature_bars` | symbol/window | spread/depth/imbalance/slippage/latency 1m feature |
| `arena_execution_gates` | run/algo | shadow trade/no-trade gate decision |
| `arena_parent_orders` | parent intent | future order intent ledger |
| `arena_child_orders` | submitted order | future exchange order ledger |
| `arena_executions` | fill | future execution/fill ledger |
| `arena_execution_quality` | order/run | TCA and realized execution quality |
| `arena_risk_events` | risk event | live portfolio risk gate block/kill events |
| `arena_risk_state` | algo/risk_model | risk kill/cooldown state registry |
| `arena_strategy_versions` | strategy_version | strategy release registry |
| `arena_feature_registry` | feature_set/feature | feature contract registry |
| `arena_decision_mart_v1` | run/algo | decision + feature + forward label mart |
| `arena_backtest_runs` | backtest_run_id | backtest metadata and metrics |
| `arena_backtest_trades` | trade | replayed trade ledger |
| `arena_backtest_equity_curve` | run/algo/timestamp | equity path |
| `arena_backtest_risk_events` | run/algo/timestamp/event | replayed risk gate events |
| `arena_walk_forward_splits` | split | train/test split registry |
| `arena_backtest_run_summary_v1` | backtest_run_id | backtest summary |
| `arena_backtest_validation_runs` | validation_run_id | validation metadata |
| `arena_backtest_validation_checks` | validation/check | validation check result |
| `arena_backtest_validation_summary_v1` | validation_run_id | validation summary |

## Migration Order

작성/적용 순서:

1. `supabase/migrations/20260619_paper_positions.sql`
2. `supabase/migrations/20260619_arena_data_timestamp.sql`
3. `supabase/migrations/20260619_arena_position_snapshots.sql`
4. `supabase/migrations/20260619_arena_paper_positions_hardening.sql`
5. `supabase/migrations/20260619_arena_data_lake_v0.sql`
6. `supabase/migrations/20260619_arena_data_lake_capture_hardening.sql`
7. `supabase/migrations/20260619_arena_strategy_feature_mart.sql`
8. `supabase/migrations/20260619_arena_backtest_framework.sql`
9. `supabase/migrations/20260619_arena_backtest_validation.sql`
10. `supabase/migrations/20260619_arena_portfolio_risk_layer.sql`
11. `supabase/migrations/20260620_arena_market_structure_v1.sql`
12. `supabase/migrations/20260620_arena_frequency_research_v1.sql`
13. `supabase/migrations/20260620_arena_realtime_execution_v1.sql`

## Current Known Warnings

- Current baseline validation has no fail.
- `macro_fetched_at_recorded` warns for older backtest run because it was generated before `macro_snapshot.fetched_at` was added to backtest trade snapshots.
- `research_sample_size` warns because 116 bars / 8 trades is too small for tuning.
- `stop_loss_fill_policy` is `na` until a backtest run contains stop-loss trades.
