# Arena Backtest Framework v1

작성일: 2026-06-19

## 목적

파라미터 튜닝 전에 라이브 arena 봇과 같은 규칙으로 과거 4H 데이터를 재생하는 baseline 검증 프레임을 만든다.

## 현재 범위

- 입력: `arena_ohlcv_bars` 원본 4H OHLCV, `arena_macro_snapshots` macro 원본 snapshot
- 계산: replay 시점까지의 OHLCV만 사용해 RSI/MACD/BB/ATR 재계산
- 실행 규칙: `src/arena/execution_rules.py` 공통 함수 사용
- 리스크 규칙: `src/arena/risk.py` portfolio gate 공통 함수 사용
- 결과 저장: backtest run, trade, equity curve, walk-forward split 테이블

## Rule Parity

백테스트는 아래 규칙을 라이브와 같은 정책으로 재현한다.

| 항목 | 재현 방식 |
| --- | --- |
| 신호 시점 | 4H closed candle의 close price 기준 |
| 손절 | 다음 bar의 low/high로 intrabar trigger 판정 |
| 손절 체결가 | stop price 우선, gap이면 bar open 기준 보수적 체결 |
| 수수료 | round-trip `fee_bps * 2` |
| 슬리피지 | 기본 0 bps, backtest 옵션으로 추가 |
| funding | `open_time < funding_time <= close_time` 합산 후 long 비용/short 수익으로 반영 |
| 최소 보유 | signal 기반 flat/reverse exit에만 적용 |
| stop-loss | 최소 보유와 무관하게 즉시 exit |
| stale macro | `macro_stale_hours` 초과 시 macro 입력 비활성화 |
| portfolio exposure | max open/long/short/net exposure 초과 시 신규 진입 차단 |
| risk kill switch | 일간 손실 제한, 알고리즘별 MDD kill switch를 replay |
| 파라미터 | `params_snapshot`, `rules_snapshot`, `strategy_version` 저장 |

## 신규 DB 객체

| Object | Grain | Role |
| --- | --- | --- |
| `arena_backtest_runs` | backtest_run_id | 실행 메타, 기간, 버전, rules snapshot, metrics |
| `arena_backtest_trades` | trade | 백테스트 체결/종료 원장 |
| `arena_backtest_equity_curve` | run/algo/data_timestamp | 알고리즘별 equity curve |
| `arena_backtest_risk_events` | run/algo/data_timestamp/event | risk gate 차단 이벤트 |
| `arena_walk_forward_splits` | split_id | train/test/embargo 기간 정의 |
| `arena_backtest_run_summary_v1` | backtest_run_id | run + trade 집계 요약 |
| `arena_funding_rates` | exchange/symbol/funding_time | funding 포함 net backtest 입력 |

## 운영 순서

1. Supabase SQL Editor에서 `/Users/giwon/code/news/supabase/migrations/20260619_arena_backtest_framework.sql` 실행.
2. 결과 row의 `arena_backtest_framework_ready`와 `has_*` 값이 모두 true인지 확인.
3. funding 포함 net backtest 전에는 `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql`도 실행.
4. 로컬 또는 EC2에서 dry-run:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.backtest --limit 300
```

5. 결과 저장:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.backtest --limit 300 --save
```

6. 저장 확인:

```sql
SELECT *
FROM arena_backtest_run_summary_v1
ORDER BY started_at DESC
LIMIT 5;
```

## 주의점

- 지금 단계에서는 파라미터 튜닝을 하지 않는다.
- macro 과거 이력이 충분히 쌓이기 전에는 macro 기반 전략 백테스트 sample size가 작다.
- 4H OHLCV만으로는 intrabar stop-loss의 정확한 tick 순서를 알 수 없으므로, 손절 체결은 보수적 근사다.
- walk-forward split 생성/저장은 구현되어 있다. 최적화 루프는 validation과 shadow coverage가 충분해진 뒤 추가한다.

## 현재 적용 상태

- `arena_backtest_framework_ready`: 적용 완료.
- baseline backtest 저장 완료.
- `arena_backtest_validation_ready`: 적용 완료.
- baseline validation 저장 완료.
- `arena_portfolio_risk_layer_ready`: 적용 완료.
- `arena_market_structure_v1_ready`: SQL 적용 후 확인 필요.
- `arena_frequency_research_v1_ready`: SQL 적용 후 확인 필요.
- funding 데이터가 없으면 `funding_ret_pct=0`으로 처리되어 기존 backtest와 동일하게 동작한다.
- `--profile`, `--indicator-profile`, `--cost-scenario` 옵션으로 4H/1H/15m replay를 분리한다.
- metrics에는 trades/day, turnover/day, cost drag, funding drag, gross/net return, end-of-data 제외 성과를 포함한다.

최신 baseline:

| 항목 | 값 |
| --- | --- |
| `backtest_run_id` | `4ce27c17-a6be-4aba-b872-88d5d7763abd` |
| `bar_count` | 116 |
| `trade_count` | 8 |
| `validation_run_id` | `93005949-4fd9-47db-9407-94d56a272a02` |
| validation status | `warn` |
| validation counts | pass 8 / warn 3 / fail 0 / na 1 |

## 다음 단계

- frequency SQL 적용 후 `arena_frequency_research_v1_ready` 확인.
- `BTCUSDT 1h 180d`, `BTCUSDT 15m 90~180d` raw OHLCV 저장.
- `arena.walk_forward --profile research_1h --save` 실행.
- `arena.backtest --profile research_1h --cost-scenario base --limit 1000` 실행.
- sample size 부족 시 `research_only`로 자동 표시.
- forced `end_of_data` 포함/제외 성과를 분리.
- risk event count와 risk-blocked signal count를 report mart에 포함.
- stop-loss trade가 발생한 run에서 `stop_loss_fill_policy` 실제 pass/fail 확인.
- funding 포함 run에서는 `gross_ret_pct`, `trading_cost_pct`, `funding_ret_pct`, `net_ret_pct`를 같이 본다.

## Step 2B 검증 루브릭

검증 CLI:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.backtest_validation --latest
```

검증 결과 저장:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.backtest_validation --latest --save
```

CI/자동화에서 critical/high fail 발생 시 실패 처리:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.backtest_validation --latest --fail-on-critical
```

저장 전 Supabase SQL Editor에서 `/Users/giwon/code/news/supabase/migrations/20260619_arena_backtest_validation.sql`을 실행한다.

검증 항목:

| Check | Category | Fail/Warn 의미 |
| --- | --- | --- |
| `equity_row_count` | integrity | equity row 수가 `bar_count * algo_count`와 다름 |
| `equity_unique_key` | integrity | run/algo/timestamp 중복 |
| `trade_time_and_price_integrity` | integrity | 시간 역전, 음수 hold, 비정상 가격 |
| `trade_snapshots_present` | integrity | params/indicator/macro snapshot 누락 |
| `fee_adjusted_return_replay` | execution | 저장된 ret_pct가 공통 수수료/슬리피지/funding 규칙과 불일치 |
| `min_hold_signal_exits` | execution | signal 기반 flat/reverse exit가 최소 보유 시간 위반 |
| `stop_loss_fill_policy` | execution | stop-loss가 OHLC로 도달 불가하거나 fill price 불일치 |
| `signal_exit_close_price_policy` | execution | signal/end exit가 bar close price와 불일치 |
| `portfolio_risk_snapshots_present` | risk | portfolio risk policy 또는 trade risk snapshot 누락 |
| `portfolio_exposure_bounds` | risk | equity path가 max exposure 한도를 위반 |
| `risk_event_consistency` | risk | risk event와 blocked risk decision이 불일치 |
| `macro_staleness` | leakage | stale macro가 trade snapshot에 사용됨 |
| `macro_fetched_at_recorded` | leakage | macro snapshot에 fetched_at이 없어 시간 누수 감사력이 약함 |
| `end_of_data_exit_impact` | statistics | 강제 종료 PnL이 성과 해석을 왜곡할 수 있음 |
| `research_sample_size` | statistics | bar/trade sample이 튜닝에 부족함 |

현재 baseline run `4ce27c17-a6be-4aba-b872-88d5d7763abd`의 dry validation 결과:

- `pass=8`
- `warn=3`
- `fail=0`
- `na=1`

경고는 표본 부족, forced `end_of_data` 청산 영향, 기존 run의 macro `fetched_at` 누락이다. 이후 생성되는 run은 macro snapshot에 `fetched_at`이 포함되어 누수 감사력이 더 좋아진다.
