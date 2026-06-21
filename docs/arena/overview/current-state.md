# Arena Current State

작성일: 2026-06-21

## 한 줄 요약

BTC Signal Arena는 EC2 상시 프로세스로 4H spot long/flat 페이퍼트레이딩을 수행하고, 1분 실시간 feature/risk state와 4H decision diagnostics를 함께 저장하는 단계까지 왔다. 아직 전략 성능을 판단하거나 파라미터 튜닝할 단계는 아니다.

## 현재 운영 상태

| 항목 | 상태 |
| --- | --- |
| 운영 경로 | EC2 `src/arena` |
| 서버 | Seoul EC2, `arena.service` |
| 거래 모드 | paper trading, spot long/flat semantics |
| 대상 | `BTCUSDT`, `4h` |
| 실행 주기 | 4H candle close 이후 `:05` |
| 실시간 감시 | Binance WebSocket 1m kline stop-loss 감지 + realtime execution feature 수집 |
| DB | Supabase |
| 최신 서비스 확인 | 2026-06-21 14:04 UTC `arena.service = active`, `SubState=running`, `ExecMainStatus=0`, `NRestarts=0` |
| 최신 live run | `06a8ae1f-83c4-4b21-96be-34967df9c0df` |
| 최신 live run 상태 | `completed`, `capture_status=ok`, `capture_error_count=0` |
| 최신 live version | code 기준 `strategy_version=arena-spot-v4`, `params_version=arena-params-v18`, `feature_set_version=arena-features-v8`, `risk_model_version=portfolio-risk-v1` |
| 최신 validation | 기존 baseline 기준 `pass=8`, `warn=3`, `fail=0`, `na=1` |
| 최신 diagnostics | latest 5 decisions 모두 `stored_reason_diagnostics` 저장 확인 |
| 대시보드 | `arena/index.html`에 latest decision diagnostics 패널 추가 |

## 지금까지 완료한 것

### 1. 금융 모델링 결함 수정

초기 결함:

| 계층 | 결함 | 처리 |
| --- | --- | --- |
| 수집 | OHLC에서 close만 추출해 ATR 계산 불가 | OHLCV 수집으로 변경 |
| 수집 | R2 macro 신선도 검증 없음 | `macro_stale_hours` 초과 시 macro 비활성화 |
| 판단 | MACD hist 미세값에도 신호 발생 | ATR 대비 MACD threshold 추가 |
| 판단 | `multi_factor` raw 롱/숏 비대칭 | raw short/risk-off에도 MACD 필터 적용 |
| 거래 | 최소 보유 기간 없음 | 알고리즘별 `MIN_HOLD_HOURS` 추가 |
| 리스크 | 고정 5% 손절 | ATR 기반 동적 stop-loss 추가 |
| 리스크 | `stop_loss_price` DB 미저장 | 포지션 원장에 저장 |

### 2. 파라미터 인벤토리와 상수화

- 거래/지표/스케줄/리스크 파라미터를 `src/arena/parameters.py` 중심으로 정리.
- env override가 필요한 값은 `src/arena/config.py`에서 기본값을 `parameters.py`와 맞춤.
- 파라미터 문서: [../reference/parameter-inventory.md](../reference/parameter-inventory.md)

### 3. 포지션 재현성 보강

`paper_positions`에 아래 재현 필드를 추가하고 open 시점에 저장한다.

- `strategy_version`
- `params_version`
- `params_snapshot`
- `indicator_snapshot`
- `macro_snapshot`
- `market_snapshot`
- `signal_reason`
- `risk_snapshot`
- `data_timestamp`
- `stop_loss_price`
- `runtime`

목적은 나중에 “왜 특정 시점에 이 알고리즘이 raw long/short/flat을 냈고, spot 실행 정책이 어떤 executable action으로 바꿨는가”를 복원하는 것이다.

### 3A. Spot Long/Flat 실행 정책

실거래 승격 전제는 현물이다. 따라서 live/paper 실행 계층은 현물 계정에서 불가능한 short position을 열지 않는다.

- raw `short` + long 보유: long 청산, `close_spot_risk_off`
- raw `short` + 미보유: 신규 진입 없음, `spot_short_no_trade`
- raw `long` + 미보유: long open
- raw `long` + long 보유: hold
- legacy short: 신규 spot 원장과 분리해 `legacy_perp_sim`으로 archive

raw short 신호 자체는 연구/리스크오프 정보로 보존한다. derivatives/perp-style long/short 연구는 backtest/shadow에서만 유지한다.

### 4. 데이터 수집 계층 분리

라이브 거래 판단과 별개로 분석용 데이터레이크를 만들었다.

| 레이어 | 테이블 |
| --- | --- |
| run | `arena_runs` |
| raw market | `arena_ohlcv_bars`, `arena_run_ohlcv_bars` |
| raw macro | `arena_macro_snapshots` |
| derived indicators | `arena_indicator_snapshots` |
| decisions | `arena_decisions` |

capture hardening도 추가했다.

- `capture_status`
- `capture_error_count`
- `capture_warnings`

문서: [../architecture/data-lake-v0.md](../architecture/data-lake-v0.md)

### 5. Strategy/Feature Mart

추가 객체:

- `arena_strategy_versions`
- `arena_feature_registry`
- `arena_decision_mart_v1`

현재 feature registry는 8개 피처를 추적한다.

- `rsi`
- `macd_hist`
- `bb_pos`
- `atr`
- `regime_state`
- `fng`
- `vix_now`
- `vix_q40`

문서: [../research/research-mart-v1.md](../research/research-mart-v1.md)

### 6. Trading Rule Parity Layer

라이브와 백테스트가 같은 규칙을 쓰도록 순수 모듈을 추가했다.

파일:

- `src/arena/execution_rules.py`

공통화된 규칙:

- UTC timestamp parsing/formatting
- hold hours
- min hold 판정
- ATR stop-loss price
- stop-loss trigger
- fee/slippage adjusted return
- params/market/signal snapshot 생성

### 7. Backtest / Walk-forward Framework v1

추가 객체:

- `arena_backtest_runs`
- `arena_backtest_trades`
- `arena_backtest_equity_curve`
- `arena_walk_forward_splits`
- `arena_backtest_run_summary_v1`

백테스트 CLI:

```bash
PYTHONPATH=src .venv/bin/python -m arena.backtest --limit 300 --save
```

저장된 baseline:

| 항목 | 값 |
| --- | --- |
| `backtest_run_id` | `4ce27c17-a6be-4aba-b872-88d5d7763abd` |
| 기간 | 2026-05-31 07:59:59 UTC ~ 2026-06-19 11:59:59 UTC |
| bar_count | 116 |
| trade_count | 8 |
| fee_bps | 5 |
| slippage_bps | 0 |

주의: 현재 baseline은 framework 검증용이지 전략 성능 판단용이 아니다.

문서: [../research/backtest-framework-v1.md](../research/backtest-framework-v1.md)

### 8. Backtest Validation Rubric

추가 객체:

- `arena_backtest_validation_runs`
- `arena_backtest_validation_checks`
- `arena_backtest_validation_summary_v1`

검증 CLI:

```bash
PYTHONPATH=src .venv/bin/python -m arena.backtest_validation --latest --save
```

최신 검증:

| status | pass | warn | fail | na |
| --- | ---: | ---: | ---: | ---: |
| `warn` | 8 | 3 | 0 | 1 |

warn 3개:

- `macro_fetched_at_recorded`: 기존 run은 fetched_at 보강 전 생성되어 macro snapshot 감사력이 약함.
- `end_of_data_exit_impact`: 강제 종료 PnL은 성과 해석에서 분리해야 함.
- `research_sample_size`: 표본 부족.

na 1개:

- `stop_loss_fill_policy`: 이번 baseline에는 stop-loss trade가 없어 검증 대상 없음.

### 9. Portfolio Risk Layer v1

라이브와 백테스트 모두 알고리즘별 독립 포지션을 열기 전에 portfolio risk gate를 통과한다.

추가 코드:

- `src/arena/risk.py`

기본 정책:

| 항목 | 값 |
| --- | ---: |
| max open positions total | 3 |
| max long positions | 2 |
| max short positions | live/paper spot effective `0`, research/perp replay 호환용 config 보존 |
| max net long exposure | 2.0 |
| max net short exposure | live/paper spot effective `0.0`, research/perp replay 호환용 config 보존 |
| daily loss limit | 5% |
| algo max drawdown kill | 10% |
| cooldown after kill | 24h |

추가 객체:

- `arena_risk_events`
- `arena_risk_state`
- `arena_backtest_risk_events`

마이그레이션:

```sql
supabase/migrations/20260619_arena_portfolio_risk_layer.sql
```

적용 상태:

- Supabase check `arena_portfolio_risk_layer_ready`: all true.
- EC2 재배포 완료.
- 최신 확인 run `06a8ae1f-83c4-4b21-96be-34967df9c0df`는 `arena-params-v18`, `portfolio-risk-v1`로 기록됐다.
- 최신 run은 `fng_contrarian` long 보유, 나머지 알고리즘 flat/skip 상태다.
- 신규 spot 포지션은 `risk_snapshot`과 spot semantics를 기준으로 판단한다. legacy synthetic short는 archive mart에서 분리해서 본다.

### 10. Walk-forward / Report Mart

- `src/arena/walk_forward.py` 구현 완료.
- `arena_backtest_report_mart_v1`, `arena_backtest_algo_summary_v1` SQL 구현 완료.
- 다음에는 생성/저장 상태를 SQL로 확인하고, 표본 부족이면 `research_only`로 해석한다.

### 11. vNext Shadow Research

추가 코드:

- `src/arena/market_structure.py`
- `src/arena/regime.py`
- `src/arena/sleeves.py`
- `src/arena/allocator.py`

추가 SQL:

```sql
supabase/migrations/20260620_arena_market_structure_v1.sql
```

역할:

- Binance derivatives funding/OI/basis/mark price raw capture. 이 데이터는 현재 현물 거래 실행이 아니라 market-structure research/shadow feature다.
- 4H 판단 시점 market feature snapshot.
- `regime_gate_v1`과 `regime_trend` shadow sleeve decision 저장.
- 기존 `paper_positions`는 변경하지 않음.

### 12. Frequency Research v1

기존 4H paper trading은 그대로 두고, 1H/15m는 research/backtest/shadow 전용 profile로 분리했다.

추가 코드:

- `src/arena/frequency.py`
- `scripts/backfill_arena_ohlcv.py`의 `--symbol --interval --days --dry-run`
- `src/arena/backtest.py`의 `--profile --indicator-profile --cost-scenario`
- `src/arena/walk_forward.py`의 profile 기반 train/test/embargo 환산

추가 SQL:

```sql
supabase/migrations/20260620_arena_frequency_research_v1.sql
```

현재 smoke 결과:

- `BTCUSDT 1h 180d` 저장: 4,319 complete bars.
- `BTCUSDT 15m 180d` 저장: 17,279 complete bars.
- `research_1h` walk-forward: 3 splits 생성.
- `live_4h` backtest: 신규 baseline은 `arena-spot-v4`, `arena-params-v18`, `arena-features-v8` 기준으로 다시 저장해야 한다.
- `live_4h` walk-forward: 3 splits 생성.

주의: `ENABLE_ARENA_FREQUENCY_SHADOW=false`가 기본값이다. 활성화해도 `research_1h` shadow decision만 기록하고 `paper_positions`는 만들지 않는다.

### 13. Realtime Execution Gate v1

실시간 시장 데이터는 계속 관측하고, 거래는 체결 품질 조건을 통과할 때만 실행하는 방향으로 shadow execution gate를 추가했다.

추가 코드:

- `src/arena/realtime_market.py`
- `src/arena/execution_gate.py`
- `src/arena/scheduler.py`의 `arena_execution_gates` shadow 기록

추가 SQL:

```sql
supabase/migrations/20260620_arena_realtime_execution_v1.sql
```

기본값:

- `ENABLE_ARENA_REALTIME_COLLECTOR=true`
- `ENABLE_ARENA_EXECUTION_GATE_SHADOW=true`
- `ENABLE_ARENA_EXECUTION_GATE_LIVE=false`

즉, 기본 배포에서는 기존 4H paper open/close를 막지 않고 no-trade/gate 판단만 기록한다.

### 14. Shadow TCA v1

실제 주문 없이 parent order intent와 visible depth 기반 체결 품질 추정치를 남긴다.

추가 코드:

- `src/arena/tca_shadow.py`
- `src/arena/scheduler.py`의 decision-time depth snapshot 수집과 shadow parent order 기록
- `src/arena/data_lake.py`의 `arena_parent_orders`, `arena_execution_quality` write

추가 SQL:

```sql
supabase/migrations/20260620_arena_tca_shadow_v1.sql
```

변경된 기본값:

- `ARENA_SHADOW_ORDER_NOTIONAL_USD=1000`
- `ARENA_SHADOW_ORDER_TIMEOUT_SEC=30`
- `ARENA_SHADOW_ARRIVAL_BENCHMARK_SEC=1`

주의: `ENABLE_ARENA_EXECUTION_GATE_LIVE=false`는 유지한다. shadow TCA는 기존 paper open/close를 차단하지 않는다.

### 15. Realtime Risk Trigger v1

1분 realtime feature를 이용해 현물 신규 매수 위험 상태를 shadow로 기록한다. 기존 4H paper trading은 유지하고, 최신 risk state는 4H execution gate snapshot에 첨부한다.

추가 코드:

- `src/arena/realtime_risk.py`
- `src/arena/realtime_market.py`의 5분 변동성, spread widening, depth collapse, aggressive sell ratio 계산
- `src/arena/data_lake.py`의 `arena_realtime_risk_states`, `arena_realtime_risk_events` write/read
- `src/arena/scheduler.py`의 최신 risk state snapshot 연결

추가 SQL:

```sql
supabase/migrations/20260621_arena_realtime_risk_v1.sql
```

기본값:

- `ENABLE_ARENA_REALTIME_RISK=true`
- `ENABLE_ARENA_REALTIME_RISK_LIVE=false`
- `REALTIME_RISK_HISTORY_WINDOWS=60`
- `REALTIME_RISK_FRESHNESS_SECONDS=180`

주의: live flag가 false이면 `BLOCK_ENTRY`, `EXIT_CANDIDATE`, `FORCE_EXIT_CANDIDATE`도 실제 open/close를 바꾸지 않고 shadow 원장에만 남긴다.

### 16. Roster Diagnostics / Close Validation / Parity v1

2026-06-21에 로스터 진단과 검증 갭을 보강했다.

추가 코드:

- `src/arena/algorithms.py`의 `explain_signal()`, `primary_flat_skip_reason()`
- `src/arena/roster_diagnostics.py`
- `src/arena/backtest.py`의 `--regime-variant`, `--replay-execution-gate-blocks`, `--replay-realtime-risk-blocks`
- `tests/test_arena_slack_notify.py`

확인 결과:

- P1: latest live decisions 5개 모두 stored diagnostics로 집계.
- P0: 테스트 spot long position 강제 청산으로 `ret_pct=0.0483`, `hit=true`, `hold_hours=6`, spot semantics 확인. 테스트 row 삭제 완료.
- P2: `relaxed_2of3_v1` regime variant는 거래 수를 늘렸지만 현재 표본에서 strict보다 성과가 나빠 live 승격 금지.
- P3: execution gate / realtime risk block을 backtest replay에 반영하는 옵션 추가.

문서: [../research/roster-diagnostics-and-parity-v1.md](../research/roster-diagnostics-and-parity-v1.md)

## 주요 결정

| 결정 | 이유 |
| --- | --- |
| EC2를 primary 운영 경로로 사용 | 실시간 WebSocket stop-loss 감지가 필요하고 Lambda는 상시 스트림에 부적합 |
| Lambda arena는 신규 개선 대상에서 제외 | EC2와 중복 거래/중복 로직/운영 혼선 위험 |
| raw와 derived를 분리 | 지표 로직이 바뀌어도 raw OHLCV로 재계산 가능 |
| 모든 판단 run을 저장 | 포지션이 없어도 알고리즘이 왜 skip/hold 했는지 분석해야 함 |
| `strategy_version`과 snapshot 저장 | 나중에 특정 판단을 재현하기 위함 |
| live/paper 실행은 spot long/flat으로 제한 | 초기 실거래는 현물 제약과 수수료 구조를 먼저 맞추기 위함 |
| 백테스트 전 rule parity layer를 먼저 구축 | 라이브와 다른 규칙으로 백테스트하면 결과가 무의미함 |
| 로스터 diagnostics를 decision 원장에 저장 | trade가 없어도 어떤 veto가 신호를 막았는지 분석하기 위함 |
| relaxed regime은 research-only | unknown은 줄지만 현재 표본에서 성과가 악화됐으므로 live 승격 금지 |
| 파라미터 튜닝 보류 | 짧은 표본과 shadow 미검증 상태에서는 과최적화 위험이 높음 |
| walk-forward 전 portfolio risk layer를 먼저 적용 | 리스크 gate 없이 split을 만들면 실제 운영보다 과대평가될 수 있음 |
| EC2 운영 배포는 rsync 방식으로 수행 | 현재 `/home/ubuntu/news`는 Git checkout이 아니라 경량 배포 디렉터리다 |
| vNext는 shadow로만 시작 | 신규 전략이 기존 paper 포지션을 즉시 열면 성과 원장이 섞임 |

## 현재 고민과 리스크

| 리스크 | 현재 상태 | 대응 |
| --- | --- | --- |
| 표본 부족 | 아직 튜닝/우열 판단 불가 | 최소 수개월 포워드 데이터 필요 |
| macro 과거 이력 부족 | `arena_macro_snapshots`는 최근부터 쌓이는 중 | 시간이 해결. 과거 R2 snapshot이 없다면 macro 전략 백테스트 제한 |
| stop-loss 체결 검증 부족 | baseline에 stop-loss trade 없음 | 향후 stop-loss 발생 run에서 자동 검증 |
| forced end-of-data 왜곡 | baseline에 2건 있음 | 성과 리포트에서 별도 분리 |
| Lambda 중복 경로 | 코드가 남아 있음 | 운영 비활성 유지, 추후 legacy archive/삭제 검토 |
| Supabase SQL Editor fetch 오류 | Dashboard 문제였고 API 조회는 정상 | 복잡한 view는 필요한 컬럼만 조회 |
| realtime/TCA SQL 적용 완료 | realtime feature/gate/order 원장과 shadow TCA mart 적용 확인 | `arena_tca_shadow_v1_ready` 모두 true |
| realtime risk는 shadow-first | 1분 risk state를 저장하지만 live open/close를 바꾸지 않음 | `ENABLE_ARENA_REALTIME_RISK_LIVE=false` 유지 |
| 알고리즘 절반 비활성처럼 보이는 문제 | `skipped_reason`과 diagnostics로 veto별 탈락 카운트 분석 가능 | `arena.roster_diagnostics`와 대시보드 diagnostics 패널 사용 |
| 청산/수수료 경로 미검증 | 테스트 포지션으로 close path와 Slack payload 경로 검증 완료 | 자연 closed trade 발생 시 동일 값 재확인 |
| 레짐 unknown 과다 | relaxed 2-of-3 variant 구현 후 A/B 완료 | 현재 결과 악화. strict 유지 |
| live/backtest parity gap | execution gate/realtime risk replay 옵션 추가 | baseline과 gate replay 결과를 분리 비교 |
| shadow TCA는 추정치 | 실제 fill이 아니라 depth snapshot 기반 visible sweep | live 승격 전 최소 14일 shadow TCA 관찰 |
| shadow capture degraded | Binance fapi 또는 SQL 미적용 시 발생 가능 | 기존 paper trading 실패로 보지 않고 capture warning으로 해석 |
| 중복 방향 노출 | portfolio risk gate 추가 | 신규 open 또는 risk block 발생 시 snapshot/event 확인 |
| 원격 배포 방식 혼선 | `deploy/deploy.sh`는 git pull 전제이나 현재 EC2는 Git repo가 아님 | rsync 배포 명령을 runbook에 기록 |
| legacy short paper position | 과거 derivatives/perp-style synthetic paper simulation | `arena_legacy_perp_sim_position_mart_v1`로 분리 완료. spot mart에서는 제외 |

## 아직 하면 안 되는 것

- 파라미터 튜닝
- 승률/수익률을 근거로 알고리즘 우열 판단
- `macd_momentum` baseline 수익률을 홍보/제품화 근거로 사용
- `end_of_data` 포함 성과를 정상 청산 성과처럼 해석
- Lambda와 EC2를 동시에 활성화
- spot live/paper에서 short position open 허용
- funding/OI/basis 같은 derivatives feature를 곧바로 derivatives/perp 실거래 신호로 해석

## 다음 작업

우선순위 순서:

1. **Step 5A: roster diagnostics 누적 분석**
   - `arena.roster_diagnostics --source live --limit 200` 실행.
   - `above_ma200_or_missing`, `bullish_regime`, `adx_trending`, `factor_score_at_least_4` 등 veto별 탈락률 확인.
   - 완화는 반드시 backtest/replay 후 결정한다.

2. **Step 5B: spot semantics 운영 검증**
   - `arena_spot_semantics_v1_ready` 확인.
   - `arena_spot_position_mart_v1`에는 현물 long만 보이는지 확인.
   - `arena_legacy_perp_sim_position_mart_v1`은 과거 synthetic short archive로만 해석한다.

3. **Step 5C: shadow vNext live capture 확인**
   - `arena_market_feature_snapshots` 최신 row 확인.
   - `arena_shadow_decisions` 최신 row 확인.
   - 기존 `paper_positions` 신규 open 여부와 분리 확인.

4. **Step 5D: risk layer live verification**
   - 신규 open 또는 `risk_blocked` 발생 후 `risk_decision`, `risk_snapshot`, `arena_risk_events` 확인.
   - 기존 legacy open position은 snapshot이 비어 있으므로 신규 포지션 기준으로 판단한다.

5. **Step 5E: realtime execution shadow 검증**
   - `arena_execution_gates` 최신 row 확인.
   - `arena_realtime_feature_bars` 최신 row 확인.
   - 최소 2주 이상 shadow 로그 전에는 `ENABLE_ARENA_EXECUTION_GATE_LIVE=true` 금지.
   - `arena.walk_forward --profile research_1h --save` 실행.
   - `arena.backtest --profile research_1h --cost-scenario base` 실행.

6. **Step 5F: Shadow TCA 검증**
   - `/Users/giwon/code/news/supabase/migrations/20260620_arena_tca_shadow_v1.sql` 실행.
   - `arena_tca_shadow_v1_ready` 확인.
   - `arena_shadow_tca_daily_v1`의 `quality_ok_ratio`, `avg_cost_to_edge_ratio`를 최소 14일 관찰.

7. **Step 5G: Realtime Risk Trigger 검증**
   - `/Users/giwon/code/news/supabase/migrations/20260621_arena_realtime_risk_v1.sql` 실행.
   - `arena_realtime_risk_v1_ready` 확인.
   - `arena_realtime_risk_states`가 1분 단위로 쌓이는지 확인.
   - 최소 7일 이상 shadow 기록 전에는 `ENABLE_ARENA_REALTIME_RISK_LIVE=true` 금지.

8. **Longer data accumulation**
   - live forward test 누적.
   - macro snapshot 장기 이력 확보.
   - market-structure raw coverage 확보.

9. **Rule parity gap tests**
   - stop-loss trade가 발생하면 `stop_loss_fill_policy`가 pass/fail로 실제 검증되는지 확인.
   - funding 포함 backtest에서 `ret_pct = gross - cost + funding` 검증.
   - `--replay-execution-gate-blocks`, `--replay-realtime-risk-blocks` 결과를 baseline과 분리 비교.

10. **운영 정리**
   - `deploy/deploy.sh`를 현재 EC2 경량 배포 구조에 맞게 고치거나 Git checkout 방식으로 원격 구조를 통일한다.
   - Lambda legacy 처리 방침 결정.

11. **ML/RL Overlay는 나중**
   - walk-forward split 최소 3개.
   - validation critical/high fail 0.
   - shadow 30일 이상.
   - funding/OI/mark data coverage 90% 이상.

12. **제품/리더보드는 나중**
   - 최소 수개월, 가능하면 1,000개 이상의 live decision/position 기록 확보 후 공개 판단.

## 검증 명령

로컬 테스트:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_arena_parameters.py \
  tests/test_arena_data_lake.py \
  tests/test_arena_execution_rules.py \
  tests/test_arena_backtest.py \
  tests/test_arena_backtest_validation.py \
  tests/test_arena_risk.py -q
```

lint:

```bash
.venv/bin/python -m ruff check src/arena \
  tests/test_arena_parameters.py \
  tests/test_arena_data_lake.py \
  tests/test_arena_execution_rules.py \
  tests/test_arena_backtest.py \
  tests/test_arena_backtest_validation.py \
  tests/test_arena_risk.py \
  scripts/verify_arena_data_lake.py
```

서비스 상태:

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 'systemctl is-active arena.service'
```
