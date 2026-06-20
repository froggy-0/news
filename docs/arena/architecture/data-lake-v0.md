# Arena Data Lake v0

작성일: 2026-06-19

## 목적

아레나 봇이 4H마다 어떤 데이터를 보고, 어떤 지표를 계산하고, 각 알고리즘이 왜 open/hold/close/skip을 선택했는지 재현 가능하게 저장한다.

기존 `paper_positions`는 포지션 원장이다. 이 문서의 v0 데이터 레이크는 포지션이 열리지 않은 4H 판단까지 저장하는 분석 원장이다.

## 확장성 원칙

- symbol/interval을 모든 핵심 테이블에 둔다. BTCUSDT 4H에서 ETHUSDT 1H/1D로 확장 가능해야 한다.
- raw와 derived를 분리한다. OHLCV 원본이 있으면 RSI/MACD/ATR 로직이 바뀌어도 재계산할 수 있다.
- run grain을 둔다. 한 번의 4H 판단은 `arena_runs.run_id`로 묶인다.
- decision grain을 둔다. 포지션이 안 열려도 알고리즘별 판단 5건을 저장한다.
- params_version/strategy_version을 저장한다. 피처와 알고리즘이 늘어나도 버전별 비교가 가능해야 한다.
- JSONB는 빠른 v0 확장용으로 쓰되, 자주 조회되는 축은 별도 컬럼으로 둔다.

## 테이블

| Table | Grain | Role |
| --- | --- | --- |
| `arena_runs` | one 4H cycle | 실행 단위, 상태, 버전, data_timestamp |
| `arena_ohlcv_bars` | exchange/symbol/interval/open_time | Binance raw OHLCV |
| `arena_run_ohlcv_bars` | run_id/exchange/symbol/interval/open_time | run별 입력 OHLCV candle set |
| `arena_macro_snapshots` | run_id | R2 latest.json 원본과 riskOverlay |
| `arena_indicator_snapshots` | run_id | RSI/MACD/BB/ATR derived features |
| `arena_decisions` | run_id/algo_id | 알고리즘별 signal/action/reason |
| `paper_positions` | position | 체결/보유/청산 원장 |

## Action Taxonomy

| Action | Meaning |
| --- | --- |
| `open` | 신규 포지션 진입 |
| `close_flat` | signal이 flat으로 바뀌어 기존 포지션 청산 |
| `reverse` | 반대 방향 signal로 기존 포지션 청산 후 신규 진입 |
| `hold` | 기존 포지션과 같은 방향 signal 유지 |
| `flat_skip` | signal이 없고 보유 포지션도 없음 |
| `min_hold_skip` | signal은 바뀌었지만 최소 보유 시간 미충족 |
| `error` | 해당 알고리즘 판단/거래 처리 중 예외 |

## 운영 순서

1. Supabase SQL Editor에서 `/Users/giwon/code/news/supabase/migrations/20260619_arena_data_lake_v0.sql` 실행.
2. 실행 결과 `arena_data_lake_v0_ready`의 모든 `has_*` 값이 true인지 확인.
3. Supabase SQL Editor에서 `/Users/giwon/code/news/supabase/migrations/20260619_arena_data_lake_capture_hardening.sql` 실행.
4. 실행 결과 `arena_data_lake_capture_hardening_ready`의 모든 `has_*` 값이 true인지 확인.
5. EC2에 최신 `src/arena` 배포.
6. `arena.service` 재시작.
7. 다음 cycle 후 아래 row 수 확인:
   - `arena_runs`: cycle마다 1건
   - `arena_ohlcv_bars`: 최초 실행 시 최대 150건, 이후 upsert
   - `arena_run_ohlcv_bars`: cycle마다 해당 run이 본 closed candle 수
   - `arena_macro_snapshots`: cycle마다 1건
   - `arena_indicator_snapshots`: cycle마다 1건
   - `arena_decisions`: cycle마다 알고리즘 수만큼 5건

## 적용 후 검증

SQL 적용 직후 기대 결과:

```sql
SELECT
    'arena_data_lake_v0_ready' AS check_name,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_runs') AS has_arena_runs,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_ohlcv_bars') AS has_arena_ohlcv_bars,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_macro_snapshots') AS has_arena_macro_snapshots,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_indicator_snapshots') AS has_arena_indicator_snapshots,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_decisions') AS has_arena_decisions;
```

배포와 재시작 후 기대 결과:

```sql
SELECT 'arena_runs' AS table_name, COUNT(*) AS rows FROM arena_runs
UNION ALL
SELECT 'arena_ohlcv_bars', COUNT(*) FROM arena_ohlcv_bars
UNION ALL
SELECT 'arena_run_ohlcv_bars', COUNT(*) FROM arena_run_ohlcv_bars
UNION ALL
SELECT 'arena_macro_snapshots', COUNT(*) FROM arena_macro_snapshots
UNION ALL
SELECT 'arena_indicator_snapshots', COUNT(*) FROM arena_indicator_snapshots
UNION ALL
SELECT 'arena_decisions', COUNT(*) FROM arena_decisions;
```

정상 범위:

- `arena_runs`: 재시작 즉시 실행되므로 1건 이상
- `arena_ohlcv_bars`: 최초 실행 기준 최대 `BINANCE_KLINES_LIMIT`건
- `arena_run_ohlcv_bars`: run별 입력 candle set 보존. 같은 raw bar가 다음 run에 upsert되어도 과거 run의 입력 목록은 유지
- `arena_macro_snapshots`: `arena_runs` completed/data_failed run 중 macro fetch 성공 run 수
- `arena_indicator_snapshots`: OHLCV 수집 성공 run 수
- `arena_decisions`: OHLCV/indicator 계산 성공 run마다 알고리즘 수만큼

capture health:

- `arena_runs.capture_status = ok`: 모든 capture write 성공
- `arena_runs.capture_status = degraded`: 거래 로직은 진행됐지만 하나 이상의 분석용 write 실패
- `arena_runs.capture_warnings`: 실패 label/error 요약

로컬/EC2 셸에서 REST 스키마 캐시까지 확인:

```bash
source ~/.zshrc
python3 /Users/giwon/code/news/scripts/verify_arena_data_lake.py
```

## 다음 확장

- `arena_strategy_versions`, `arena_feature_registry`, `arena_decision_mart_v1`은 적용 완료.
- `arena_backtest_*`, `arena_walk_forward_splits`, `arena_backtest_validation_*`은 적용 완료.
- baseline report mart와 walk-forward split 생성기는 구현 완료다.
- market-structure raw capture와 vNext shadow decision ledger는 코드/migration 작성 완료, SQL 적용 후 readiness 확인이 필요하다.
- frequency research v1은 `live_4h`, `research_1h`, `research_15m` profile로 분리했다. 1H/15m raw OHLCV는 `arena_ohlcv_bars`의 기존 `symbol, interval` 키를 그대로 사용한다.
- `arena_indicator_feature_bars`는 interval/profile별 derived indicator snapshot을 저장한다.
- `feature_name/value` long-form feature table은 피처 수가 크게 늘어날 때 도입한다.
