# Arena Frequency Research v1

작성일: 2026-06-20

## 목적

거래 빈도를 높이면 신호 수는 늘지만, 수수료/슬리피지/스프레드와 노이즈가 함께 커진다. 이 문서는 기존 4H 현물 long/flat paper trading을 유지하면서 1H/15m를 research/backtest/shadow 전용으로 검증하기 위한 구현 상태와 실행 절차를 기록한다. funding buffer는 derivatives/perp-style 연구 비용 시나리오로만 둔다.

## 현재 원칙

- `live_4h`만 기존 paper position 생성 경로를 유지하되, 실행은 현물 long/flat만 허용한다.
- `research_1h`는 raw/backtest/shadow 후보지만 기본 scheduler는 꺼져 있다.
- `research_15m`는 raw/backtest 전용이다. readiness 전에는 scheduler에 연결하지 않는다.
- `time_normalized_v1`이 기본 indicator profile이다. 4H RSI 14 bars의 56시간 의미를 1H 56 bars, 15m 224 bars로 환산한다.
- `intraday_native_v1`은 비교용 후보이며 기본값이 아니다.
- cost-aware filter는 `regime_trend` shadow sleeve 경로에만 적용한다.

## 코드 위치

| 영역 | 파일 |
| --- | --- |
| profile/cost registry | `/Users/giwon/code/news/src/arena/frequency.py` |
| 상수/기본 env | `/Users/giwon/code/news/src/arena/parameters.py`, `/Users/giwon/code/news/src/arena/config.py` |
| OHLCV parser/record | `/Users/giwon/code/news/src/arena/data_lake.py` |
| backfill CLI | `/Users/giwon/code/news/scripts/backfill_arena_ohlcv.py` |
| indicator profile 적용 | `/Users/giwon/code/news/src/arena/indicators.py` |
| walk-forward 기간 환산 | `/Users/giwon/code/news/src/arena/walk_forward.py` |
| backtest profile/cost metrics | `/Users/giwon/code/news/src/arena/backtest.py` |
| shadow scheduler | `/Users/giwon/code/news/src/arena/scheduler.py` |
| SQL migration | `/Users/giwon/code/news/supabase/migrations/20260620_arena_frequency_research_v1.sql` |

## Profiles

| profile | interval | mode | train/test/embargo | ECR | max trades/day/algo | 기본 상태 |
| --- | --- | --- | --- | ---: | ---: | --- |
| `live_4h` | `4h` | spot paper + research | 84d / 20d / 24h | 1.3 | 3 | live 유지 |
| `research_1h` | `1h` | research + shadow 후보 | 90d / 21d / 24h | 1.5 | 6 | raw 저장 후 검증 |
| `research_15m` | `15m` | raw + backtest | 60d / 14d / 12h | 1.7 | 12 | scheduler 미연결 |

## Cost Scenarios

| profile | scenario | fee | slippage | spread RT | funding buffer | all-in RT |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `live_4h` | `base` | 5bps/leg | 0bps/leg | 0bps | 0bps/8h | 10bps |
| `research_1h` | `base` | 5bps/leg | 2bps/leg | 3bps | 0.5bps/8h | 17.5bps |
| `research_15m` | `base` | 5bps/leg | 4bps/leg | 5bps | 1bps/8h | 24bps |

## DB Objects

신규 migration 적용 후 필요한 객체:

- `arena_frequency_profiles`
- `arena_indicator_feature_bars`
- `arena_frequency_backtest_mart_v1`
- `arena_frequency_research_v1_ready`
- `arena_runs.frequency_profile_id`
- `arena_backtest_runs.frequency_profile_id`
- `arena_backtest_runs.indicator_profile_id`
- `arena_backtest_runs.cost_model_version`
- `arena_backtest_runs.cost_scenario_id`

Readiness:

```sql
select * from arena_frequency_research_v1_ready;
```

## 실행 절차

SQL 적용:

```sql
-- Supabase SQL Editor
-- /Users/giwon/code/news/supabase/migrations/20260620_arena_frequency_research_v1.sql
select * from arena_frequency_research_v1_ready;
```

1H/15m raw 저장:

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python scripts/backfill_arena_ohlcv.py --symbol BTCUSDT --interval 1h --days 180
PYTHONPATH=src .venv/bin/python scripts/backfill_arena_ohlcv.py --symbol BTCUSDT --interval 15m --days 180
```

dry-run smoke:

```bash
PYTHONPATH=src .venv/bin/python scripts/backfill_arena_ohlcv.py --symbol BTCUSDT --interval 1h --days 180 --dry-run
```

walk-forward:

```bash
PYTHONPATH=src .venv/bin/python -m arena.walk_forward --profile live_4h --save
PYTHONPATH=src .venv/bin/python -m arena.walk_forward --profile research_1h --save
```

backtest:

```bash
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile live_4h --cost-scenario base --limit 300
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile research_1h --indicator-profile time_normalized_v1 --cost-scenario base --limit 1000
```

derivatives/perp-style long/short 연구 replay가 필요할 때만 아래처럼 명시한다.

```bash
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile research_1h --cost-scenario base --product usdm_perp_paper --limit 1000
```

frequency shadow 활성화는 1H raw/backtest가 정상화된 뒤에만 한다.

```bash
ENABLE_ARENA_FREQUENCY_SHADOW=true
ARENA_FREQUENCY_SHADOW_PROFILES=research_1h
```

## 현재 Smoke 결과

- `pytest tests/test_arena_*.py -q`: 통과.
- `ruff check src/arena tests/test_arena_*.py scripts/backfill_arena_ohlcv.py`: 통과.
- `BTCUSDT 1h 180d --dry-run`: 4,319 complete bars 파싱.
- `arena.walk_forward --profile research_1h`: DB에 1H raw 저장 전이라 `insufficient_data`.
- `arena.backtest --profile research_1h`: DB에 1H raw 저장 전이라 프레임 없음.
- `arena.backtest --profile live_4h --limit 300`: 정상 완료.
- `arena.walk_forward --profile live_4h`: 3 splits 생성.

## 다음 판단 기준

빈도 비교는 아래 mart가 채워진 뒤에만 한다.

- trades per day
- average hold hours
- turnover per day
- gross return
- trading cost drag
- funding drag (derivatives/perp-style research replay에서만)
- cost-to-gross ratio
- end-of-data 제외 성과

`research_1h`가 비용 바닥을 못 넘으면 15m는 승격하지 않는다. `research_15m`는 raw coverage와 backtest mart 안정화 이후 별도 shadow 승격 여부를 판단한다.
