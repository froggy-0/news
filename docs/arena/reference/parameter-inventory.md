# Parameter Inventory

작성일: 2026-06-20

목표는 거래 결과를 재현할 수 있도록 코드/env/DB/docs에 흩어진 파라미터를 한 곳에서 추적하는 것이다. 운영 판단 경로는 EC2 `src/arena`를 단일 truth로 두고, Lambda arena 로직은 신규 운영 경로로 확장하지 않는다.

## 운영 원칙

- `src/arena`는 라이브 페이퍼트레이딩 판단 경로다.
- `lambda/arena`는 동일 전략 로직을 복제하고 있으므로 신규 개선 대상에서 제외한다.
- 거래 로직 변경 전에는 `paper_positions.params_snapshot`으로 진입 시점 파라미터를 저장한다.
- `.env` / `.env.*` 값은 문서화하지 않고, env var 이름과 기본값만 기록한다.
- 파라미터 변경 가능성은 `code_only`, `env_restart`, `db_versioned`, `yaml_policy` 중 하나로 분류한다.

## Arena Trading

| Key | Default | Unit | Mutable | Risk | Used at | Notes |
| --- | ---: | --- | --- | --- | --- | --- |
| `arena.version.strategy` | `arena-ec2-v6` | version | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:13` | live paper 전략 버전 |
| `arena.version.params` | `arena-params-v7` | version | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:14` | params snapshot schema 기준 |
| `arena.version.features` | `arena-features-v4` | version | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:15` | feature registry 기준 |
| `arena.runtime` | `ec2` | text | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:17` | Lambda와 EC2 성과 구분 |
| `arena.market.symbol` | `BTCUSDT` | symbol | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:19` | 거래/수집 대상 |
| `arena.market.kline_interval` | `4h` | candle | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:20` | 지표와 스케줄의 시간축 |
| `arena.market.klines_limit` | `150` | candles | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:21` | 지표 warmup 길이 |
| `arena.shadow_vnext.enabled` | `true` | bool | env_restart | Medium | `/Users/giwon/code/news/src/arena/config.py:29` | shadow decision 기록 on/off |
| `arena.frequency_shadow.enabled` | `false` | bool | env_restart | Medium | `/Users/giwon/code/news/src/arena/config.py:33` | 1H frequency shadow scheduler on/off |
| `arena.frequency_shadow.profiles` | `research_1h` | csv | env_restart | Medium | `/Users/giwon/code/news/src/arena/config.py:89` | 활성화 시 자동 shadow profile 목록 |
| `arena.net.http_timeout` | `30` | seconds | code_only | Low | `/Users/giwon/code/news/src/arena/parameters.py:24` | Binance/R2 fetch timeout |
| `arena.schedule.hour` | `*/4` | cron | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:27` | 4H 판단 cadence |
| `arena.schedule.minute` | `5` | minute | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:28` | candle close 직후 지연 실행 |
| `arena.stream.ping_interval` | `20` | seconds | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:25` | WebSocket 유지 |
| `arena.stream.reconnect_delay` | `5` | seconds | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:26` | 장애 시 stop-loss 감지 공백 |
| `arena.risk.stop_loss_fallback_pct` | `0.05` | pct | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:34` | 저장된 stop_loss_price 없을 때만 사용 |
| `arena.risk.fee_bps` | `5.0` | bps per leg | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:37` | ret_pct 계산 직접 영향 |
| `arena.risk.atr_multiple` | `2.5` | ATR x | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:41` | 손절 거리 핵심 |
| `arena.risk.stop_loss_min_pct` | `0.02` | pct | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:42` | 과소 손절 방지 |
| `arena.risk.stop_loss_max_pct` | `0.08` | pct | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:45` | 과대 손실 방지 |
| `arena.macro.stale_hours` | `36` | hours | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:50` | 오래된 macro 신호 차단 |
| `arena.risk.position_unit` | `1.0` | unit | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:54` | 알고리즘별 포지션 노출 단위 |
| `arena.risk.max_open_positions_total` | `3` | positions | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:55` | 전체 동시 포지션 수 제한 |
| `arena.risk.max_long_positions` | `2` | positions | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:58` | 같은 방향 long 중복 제한 |
| `arena.risk.max_short_positions` | `2` | positions | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:61` | 같은 방향 short 중복 제한 |
| `arena.risk.max_net_long_exposure` | `2.0` | unit | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:64` | net long exposure 상한 |
| `arena.risk.max_net_short_exposure` | `2.0` | unit | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:67` | net short exposure 상한 |
| `arena.risk.daily_loss_limit_pct` | `0.05` | pct | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:70` | 일간 실현 손실 제한 |
| `arena.risk.algo_max_drawdown_kill_pct` | `0.10` | pct | env_restart | High | `/Users/giwon/code/news/src/arena/config.py:73` | 알고리즘별 MDD kill switch |
| `arena.risk.cooldown_after_kill_hours` | `24` | hours | env_restart | Medium | `/Users/giwon/code/news/src/arena/config.py:76` | kill 이후 재가동 대기 정책 |

## Arena Frequency Research

| Key | Default | Unit | Mutable | Risk | Used at | Notes |
| --- | ---: | --- | --- | --- | --- | --- |
| `arena.frequency.live_4h.interval` | `4h` | candle | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:164` | 기존 live paper cadence 유지 |
| `arena.frequency.live_4h.train_days` | `84` | days | code_only | Medium | `/Users/giwon/code/news/src/arena/frequency.py:171` | WF train window, 4H 기준 504 bars |
| `arena.frequency.live_4h.test_days` | `20` | days | code_only | Medium | `/Users/giwon/code/news/src/arena/frequency.py:172` | WF test window, 4H 기준 120 bars |
| `arena.frequency.live_4h.ecr` | `1.3` | multiple | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:174` | 비용 대비 edge cushion |
| `arena.frequency.research_1h.interval` | `1h` | candle | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:179` | research/shadow 후보, paper position 미생성 |
| `arena.frequency.research_1h.train_days` | `90` | days | code_only | Medium | `/Users/giwon/code/news/src/arena/frequency.py:186` | WF train window, 1H 기준 2160 bars |
| `arena.frequency.research_1h.test_days` | `21` | days | code_only | Medium | `/Users/giwon/code/news/src/arena/frequency.py:187` | WF test window, 1H 기준 504 bars |
| `arena.frequency.research_1h.embargo_hours` | `24` | hours | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:188` | train/test leakage 완충 |
| `arena.frequency.research_1h.max_trades_per_day_per_algo` | `6` | trades/day | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:190` | 고빈도 과매매 상한 |
| `arena.frequency.research_15m.interval` | `15m` | candle | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:194` | raw/backtest 전용, scheduler 미연결 |
| `arena.frequency.research_15m.train_days` | `60` | days | code_only | Medium | `/Users/giwon/code/news/src/arena/frequency.py:201` | WF train window, 15m 기준 5760 bars |
| `arena.frequency.research_15m.test_days` | `14` | days | code_only | Medium | `/Users/giwon/code/news/src/arena/frequency.py:202` | WF test window, 15m 기준 1344 bars |
| `arena.frequency.research_15m.ecr` | `1.7` | multiple | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:204` | 더 높은 비용/노이즈 cushion |
| `arena.indicator_profile.time_normalized_v1` | `4H time equivalent` | profile | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:277` | 4H RSI14=56h 의미를 1H/15m로 환산 |
| `arena.indicator_profile.intraday_native_v1` | `bar native` | profile | code_only | Medium | `/Users/giwon/code/news/src/arena/frequency.py:286` | RSI14/MACD12-26-9를 intraday bar 기준으로 사용, 기본값 아님 |
| `arena.cost.research_1h.base` | `17.5` | bps round-trip incl buffer | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:237` | fee 5bps/leg, slippage 2bps/leg, spread 3bps RT, funding buffer 0.5bps/8h |
| `arena.cost.research_15m.base` | `24.0` | bps round-trip incl buffer | code_only | High | `/Users/giwon/code/news/src/arena/frequency.py:245` | fee 5bps/leg, slippage 4bps/leg, spread 5bps RT, funding buffer 1bps/8h |

## Arena Indicators

| Key | Default | Unit | Mutable | Risk | Used at | Notes |
| --- | ---: | --- | --- | --- | --- | --- |
| `arena.indicator.rsi_period` | `14` | candles | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:48` | RSI 기본 기간 |
| `arena.indicator.rsi_neutral` | `50` | index | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:49` | 데이터 부족 fallback |
| `arena.indicator.rsi_recent_multiple` | `3` | period x | code_only | Low | `/Users/giwon/code/news/src/arena/parameters.py:50` | Wilder smoothing 입력 길이 |
| `arena.indicator.macd_fast` | `12` | candles | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:51` | MACD 신호 직접 영향 |
| `arena.indicator.macd_slow` | `26` | candles | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:52` | MACD 신호 직접 영향 |
| `arena.indicator.macd_signal` | `9` | candles | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:53` | MACD histogram 직접 영향 |
| `arena.indicator.bb_period` | `20` | candles | code_only | Low | `/Users/giwon/code/news/src/arena/parameters.py:55` | 현재는 기록 중심 |
| `arena.indicator.bb_stddev` | `2` | sigma | code_only | Low | `/Users/giwon/code/news/src/arena/parameters.py:56` | 현재는 기록 중심 |
| `arena.indicator.atr_period` | `14` | candles | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:58` | 손절 거리 직접 영향 |
| `arena.indicator.atr_fallback_pct` | `0.01` | pct | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:59` | OHLCV 부족 시 손절 거리 |
| `arena.indicator.trend_ema_fast` | `12` | candles | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:73` | trend_core_v1 fast EMA |
| `arena.indicator.trend_ema_slow` | `26` | candles | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:74` | trend_core_v1 slow EMA |
| `arena.indicator.return_24h_bars` | `6` | 4H bars | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:75` | regime_gate_v1 24h return |
| `arena.indicator.return_72h_bars` | `18` | 4H bars | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:76` | regime_gate_v1 72h return |

## Arena Strategy Thresholds

| Key | Default | Unit | Mutable | Risk | Used at | Notes |
| --- | ---: | --- | --- | --- | --- | --- |
| `arena.strategy.regime_long_state` | `BullQuiet` | label | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:61` | regime_v2 long |
| `arena.strategy.regime_short_state` | `BearPanic` | label | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:62` | regime_v2 short |
| `arena.strategy.fng_long_below` | `30` | index | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:63` | 공포 매수 |
| `arena.strategy.fng_short_above` | `70` | index | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:64` | 탐욕 매도 |
| `arena.strategy.vix_rsi_long_max` | `50` | RSI | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:65` | vix_rsi long filter |
| `arena.strategy.macd_atr_threshold_multiple` | `0.10` | ATR x | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:66` | MACD noise filter |
| `arena.strategy.multi_factor_long_rsi_max` | `50` | RSI | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:70` | multi_factor long |
| `arena.strategy.multi_factor_short_rsi_min` | `55` | RSI | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:71` | multi_factor short |
| `arena.strategy.trend_core_rsi_long_max` | `70` | RSI | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:78` | shadow trend_core_v1 long 과열 차단 |
| `arena.strategy.trend_core_rsi_short_min` | `30` | RSI | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:79` | shadow trend_core_v1 short 과매도 차단 |
| `arena.strategy.regime_stress_return_atr_multiple` | `3` | ATR pct x | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:81` | regime_gate_v1 stress 판정 |
| `arena.strategy.allocator_trend_core_budget` | `0.60` | weight | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:87` | shadow trend sleeve risk budget |
| `arena.strategy.allocator_legacy_rule_budget` | `0.40` | weight | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:88` | 기존 rule sleeve reserved budget |
| `arena.strategy.allocator_carry_budget` | `0.00` | weight | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:89` | carry는 v1 데이터 수집만 |

## Arena Holding Periods

| Key | Default | Unit | Mutable | Risk | Used at | Notes |
| --- | ---: | --- | --- | --- | --- | --- |
| `arena.hold.regime_v2` | `24` | hours | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:92` | macro 전략 잦은 반전 방지 |
| `arena.hold.fng_contrarian` | `24` | hours | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:93` | FNG 저빈도 특성 반영 |
| `arena.hold.vix_rsi` | `8` | hours | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:94` | macro + RSI 혼합 |
| `arena.hold.macd_momentum` | `8` | hours | code_only | High | `/Users/giwon/code/news/src/arena/parameters.py:95` | 4H 단일바 노이즈 제거 |
| `arena.hold.multi_factor` | `8` | hours | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:96` | 복합 신호 최소 보유 |
| `arena.hold.trend_core_v1` | `12` | hours | code_only | Medium | `/Users/giwon/code/news/src/arena/parameters.py:97` | shadow trend_core_v1 최소 보유 기준 |

## Position Ledger Snapshots

| Column | Type | Mutable | Risk | Used at | Notes |
| --- | --- | --- | --- | --- | --- |
| `strategy_version` | text | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:6` | 전략 버전 |
| `data_timestamp` | timestamptz | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_data_timestamp.sql:7` | 판단에 사용한 마지막 4H closed candle 시각 |
| `params_version` | text | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:7` | 파라미터 schema 버전 |
| `params_snapshot` | jsonb | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:8` | 진입 시점 파라미터 |
| `indicator_snapshot` | jsonb | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:9` | 진입 시점 RSI/MACD/BB/ATR |
| `macro_snapshot` | jsonb | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:10` | 진입 시점 regime/FNG/VIX |
| `market_snapshot` | jsonb | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:11` | 진입 시점 가격/수집 상태 |
| `signal_reason` | jsonb | db_versioned | Medium | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:12` | 신호 설명용 입력 묶음 |
| `risk_snapshot` | jsonb | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260619_arena_portfolio_risk_layer.sql:8` | 진입 시점 portfolio risk gate 결과 |
| `runtime` | text | db_versioned | Medium | `/Users/giwon/code/news/supabase/migrations/20260619_arena_position_snapshots.sql:13` | EC2/Lambda 구분 |

## Shadow / Market Structure Ledger

| Table or Column | Type | Mutable | Risk | Used at | Notes |
| --- | --- | --- | --- | --- | --- |
| `arena_funding_rates` | table | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql:10` | 8H funding raw events |
| `arena_open_interest_snapshots` | table | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql:25` | OI raw snapshots |
| `arena_basis_snapshots` | table | db_versioned | Medium | `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql:43` | futures basis raw snapshots |
| `arena_mark_price_bars` | table | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql:61` | mark price and premium index bars |
| `arena_market_feature_snapshots` | table | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql:90` | 4H decision-aligned market features |
| `arena_shadow_decisions` | table | db_versioned | High | `/Users/giwon/code/news/supabase/migrations/20260620_arena_market_structure_v1.sql:110` | vNext sleeve/allocator shadow results |

## News Collection / Provider Runtime

| Key | Default | Unit | Mutable | Risk | Used at | Notes |
| --- | ---: | --- | --- | --- | --- | --- |
| `news.thenewsapi.max_items` | `6` | items | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/config.py:210` | 무료 플랜/품질 영향 |
| `news.thenewsapi.lookback_hours` | `36` | hours | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/config.py:213` | 신선도/누락 trade-off |
| `news.marketaux.max_items` | `3` | items | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/config.py:229` | provider quota 영향 |
| `news.marketaux.lookback_hours` | `36` | hours | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/config.py:232` | 신선도/누락 trade-off |
| `news.coindesk.lookback_hours` | `36` | hours | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/config.py:247` | weekday lookback |
| `news.coindesk.weekend_lookback_hours` | `72` | hours | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/config.py:250` | weekend coverage |
| `news.coindesk.max_items` | `18` | items | env_restart | Low | `/Users/giwon/code/news/src/morning_brief/config.py:253` | public packet 규모 |
| `provider.default.max_attempts` | `3` | attempts | code_only | Medium | `/Users/giwon/code/news/src/morning_brief/data/sources/provider_runtime.py:15` | retry budget |
| `provider.default.base_backoff` | `1.2` | seconds | code_only | Medium | `/Users/giwon/code/news/src/morning_brief/data/sources/provider_runtime.py:16` | retry pressure |
| `provider.default.max_backoff` | `12` | seconds | code_only | Medium | `/Users/giwon/code/news/src/morning_brief/data/sources/provider_runtime.py:17` | retry latency cap |
| `provider.default.jitter` | `0.2` | ratio | code_only | Low | `/Users/giwon/code/news/src/morning_brief/data/sources/provider_runtime.py:18` | burst 완화 |

## Analysis / Sentiment Join

| Key | Default | Unit | Mutable | Risk | Used at | Notes |
| --- | ---: | --- | --- | --- | --- | --- |
| `sentiment_join.lookback_days` | `540` | days | env_restart | High | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/config.py:54` | 학습/분석 표본 수 |
| `sentiment_join.r2_max_concurrency` | `10` | workers | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/config.py:60` | R2 부하 |
| `sentiment_join.retain_days` | `90` | days | env_restart | Medium | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/config.py:61` | 저장 비용/롤백 가능성 |
| `sentiment_join.regime_warmup_days` | `220` | days | env_restart | High | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/config.py:62` | regime 안정성 |
| `risk_overlay.vix_window` | `90` | days | code_only | High | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/risk_overlay.py:21` | regime 분류 |
| `risk_overlay.rv_window` | `45` | days | code_only | High | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/risk_overlay.py:25` | realized vol 분류 |
| `risk_overlay.funding_heat` | `1.5` | z-score | code_only | Medium | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/risk_overlay.py:28` | leverage risk |
| `risk_overlay.fng_extreme_fear` | `20` | index | code_only | Medium | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/risk_overlay.py:33` | sentiment regime |
| `stat_tests.min_rows_adf` | `30` | rows | code_only | Medium | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/statistical_tests.py:22` | 통계 검정 안정성 |
| `stat_tests.min_rows_granger` | `180` | rows | code_only | High | `/Users/giwon/code/news/src/morning_brief/analysis/sentiment_join/statistical_tests.py:23` | causal claim 안정성 |

## Known Drifts

- `/Users/giwon/code/news/lambda/arena/deploy.sh:118` Lambda schedule은 정각이고, `/Users/giwon/code/news/src/arena/scheduler.py:220` EC2 schedule은 `:05`다. Lambda는 신규 운영 경로에서 제외한다.
- `/Users/giwon/code/news/lambda/arena/handler.py:29` 이후 거래/지표/전략 로직이 EC2와 중복되어 있다. 향후 삭제 또는 legacy archive 대상이다.
- sentiment join spec 문서의 lookback/retain 기본값은 코드와 다르다. 별도 문서 정합성 작업이 필요하다.

## Next Steps

완료:

1. `paper_positions` snapshot 계층 적용.
2. `data_timestamp` 적용.
3. `paper_positions` hardening 적용.
4. EC2 `src/arena` primary 운영 확인.
5. backtest/validation에도 동일 파라미터 snapshot 저장.
6. portfolio risk layer v1 적용.
7. walk-forward generator와 report mart SQL 구현.
8. market-structure/shadow vNext 코드와 migration 작성.
9. frequency profile registry, 1H/15m OHLCV 수집 일반화, frequency backtest mart migration 작성.

남은 작업:

1. Lambda EventBridge rule `arena-trader-4h`가 켜져 있으면 비활성화 상태를 주기적으로 확인한다.
2. news/provider/risk overlay 파라미터를 별도 policy registry로 분리할지 결정한다.
3. `20260620_arena_market_structure_v1.sql`과 `20260620_arena_frequency_research_v1.sql`을 Supabase에 적용하고 readiness view를 확인한다.
4. `BTCUSDT 1h 180d`, `BTCUSDT 15m 90~180d` raw OHLCV를 저장한다.
5. shadow 30일 이상, validation critical/high fail 0 전까지 `trend_core_v1`은 live paper로 승격하지 않는다.
