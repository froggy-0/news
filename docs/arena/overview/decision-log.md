# Arena Decision Log

작성일: 2026-06-21

이 문서는 코드/DB 변경보다 더 오래 남아야 하는 의사결정과 그 이유를 기록한다.

## D001. EC2를 primary arena runtime으로 둔다

- 결정: `src/arena`를 EC2 상시 프로세스로 운영한다.
- 이유: Binance WebSocket으로 실시간 stop-loss를 감지해야 한다. Lambda는 4H 배치에는 가능하지만 상시 스트림에는 맞지 않는다.
- 영향: Lambda arena 로직은 신규 개선 대상에서 제외한다.
- 리스크: Lambda와 EC2가 동시에 거래하면 같은 DB에서 중복/경합 거래가 발생할 수 있다.
- 후속: Lambda EventBridge schedule은 기본 비활성 상태로 유지한다.

## D002. raw market data와 derived indicators를 분리한다

- 결정: `arena_ohlcv_bars`와 `arena_indicator_snapshots`를 분리한다.
- 이유: RSI/MACD/ATR 계산 로직이 바뀌어도 raw OHLCV로 재계산할 수 있어야 한다.
- 영향: backtest는 `arena_ohlcv_bars`에서 indicators를 재계산한다.
- 리스크: raw row가 부족하면 indicator warmup 이후 표본이 줄어든다.

## D003. 모든 4H 판단을 run/decision으로 저장한다

- 결정: 포지션이 열리지 않아도 `arena_runs`와 `arena_decisions`를 저장한다.
- 이유: “왜 거래하지 않았는가”도 전략 품질 판단에 필요하다.
- 영향: `arena_decision_mart_v1`에서 신호와 forward label을 함께 볼 수 있다.
- 리스크: 저장 write 실패가 거래를 막지 않도록 capture health는 degraded로 기록하고 거래는 계속 진행한다.

## D004. strategy_version과 snapshot을 거래 원장에 저장한다

- 결정: `paper_positions`에 version/snapshot 필드를 저장한다.
- 이유: 나중에 특정 포지션을 같은 코드/파라미터/지표/macro 상태로 설명해야 한다.
- 영향: `strategy_version`, `params_snapshot`, `indicator_snapshot`, `macro_snapshot`, `market_snapshot`, `signal_reason`, `data_timestamp`를 open 시점에 저장한다.
- 리스크: 기존 legacy open positions는 snapshot이 비어 있을 수 있다.

## D005. 파라미터 튜닝보다 rule parity를 먼저 한다

- 결정: 백테스트 튜닝 전 `execution_rules.py`를 만들었다.
- 이유: 라이브와 다른 규칙으로 백테스트하면 성과가 좋아도 운영에 재현되지 않는다.
- 영향: live close 수익률, min_hold, stop-loss, snapshot 생성, 백테스트가 같은 pure rule을 쓴다.
- 리스크: 새 execution rule을 바꿀 때 live/backtest 테스트를 함께 갱신해야 한다.

## D006. stop-loss 체결은 4H OHLC 기반 보수적 근사로 둔다

- 결정: stop-loss backtest fill은 `stop_price_or_gap_open` 정책이다.
- long: `low <= stop_loss_price`이면 체결, gap이면 `min(open, stop_loss_price)`.
- research/perp short: `high >= stop_loss_price`이면 체결, gap이면 `max(open, stop_loss_price)`.
- 이유: 4H OHLC만으로는 intrabar tick 순서를 알 수 없다.
- 영향: 실제보다 보수적일 수 있지만 과대평가를 줄인다.
- 리스크: 같은 bar 안에서 stop과 signal이 모두 가능할 때 tick 순서 불확실성이 남는다.

## D007. 현재 성과는 research-only로 해석한다

- 결정: 현 baseline 결과로 전략 우열이나 파라미터를 판단하지 않는다.
- 근거: baseline은 116 bars / 8 trades에 불과하다.
- 영향: `research_sample_size` validation은 warn이다.
- 리스크: 작은 표본에서 우연히 좋아 보이는 전략을 과신할 수 있다.
- 후속: walk-forward split과 report는 만들되, 최적화는 보류한다.

## D008. validation 결과를 DB에 저장한다

- 결정: 백테스트 결과마다 validation run/check를 저장한다.
- 이유: 튜닝/리포트 전에 “이 결과를 믿어도 되는지”를 기계적으로 확인해야 한다.
- 영향: `arena_backtest_validation_runs`, `arena_backtest_validation_checks`, `arena_backtest_validation_summary_v1` 추가.
- 현재 상태: latest validation은 fail 0, warn 3.

## D009. 문서 구조는 Arena와 legacy pipeline을 분리한다

- 결정: Arena 문서는 `docs/arena` 아래에 모은다.
- 이유: 기존 Morning Brief/sentiment-join 문서와 Arena 운영 문서가 섞이면 다음 작업 순서가 흐려진다.
- 영향: 기존 `docs/planning` 문서는 `docs/arena` 하위로 이동했다.
- 삭제: `.DS_Store`만 제거했다. 과거 연구/발표 산출물은 임의 삭제하지 않았다.

## D010. walk-forward 전 portfolio risk layer를 고정한다

- 결정: walk-forward split/최적화 전에 `portfolio-risk-v1`을 라이브와 백테스트 양쪽에 적용한다.
- 이유: 전체 노출 제한 없이 알고리즘별 독립 포지션만 replay하면 실제 운영보다 성과가 과대평가될 수 있다.
- 영향: `src/arena/risk.py`, `arena_risk_events`, `arena_risk_state`, `arena_backtest_risk_events`, `risk_snapshot`을 추가했다.
- 기본 정책: total 3 positions, long 2, daily loss 5%, algo MDD kill 10%. short/net short 한도는 research/perp replay 호환용으로 남지만 live/paper spot 실행에는 사용하지 않는다.
- 현재 상태: Supabase migration 적용 확인 후 EC2 `arena.service`에 재배포 완료.
- 리스크: 기존 legacy open position은 risk snapshot이 비어 있다. 신규 open/risk block부터 snapshot/event가 채워진다.

## D011. live/paper 거래 기준은 현물 spot long/flat으로 고정한다

- 결정: 실거래 승격을 전제로 하는 Arena live/paper 경로는 `spot_long_flat`만 허용한다.
- 이유: 초기 실거래는 현물 제약, 수수료, 체결 가능성을 먼저 정확히 맞춰야 한다. 일반 현물 계정에서는 short position을 열 수 없다.
- 영향: raw `short` 신호는 신규 포지션 진입이 아니라 long 청산(`close_spot_risk_off`) 또는 no-trade(`spot_short_no_trade`)로 변환한다.
- 영향: `paper_positions.direction='short'` 신규 open은 `positions.open_position()`에서 guard한다.
- 영향: derivatives/perp funding/OI/basis/mark price와 long/short replay는 research/shadow/backtest 전용으로 유지한다.
- 리스크: 과거 synthetic short 원장은 성과 해석을 오염시킬 수 있으므로 `legacy_perp_sim`으로 분리한다.

## D012. 알고리즘 skip/veto diagnostics를 decision 원장에 저장한다

- 결정: `arena_decisions.reason.diagnostics`와 `skipped_reason`에 알고리즘별 탈락 조건을 저장한다.
- 이유: trade가 없거나 적은 알고리즘은 성과가 아니라 "왜 거래하지 않았는가"를 먼저 봐야 한다.
- 영향: `regime_trend`, `vix_rsi`, `macd_momentum`, `multi_factor`, `fng_contrarian` 모두 조건별 pass/fail/veto를 집계할 수 있다.
- 영향: `arena.roster_diagnostics` CLI와 대시보드 diagnostics 패널이 같은 원장을 읽는다.
- 리스크: diagnostics는 설명/감사용 정보다. 임계값 완화는 backtest/replay 후에만 한다.

## D013. P0 close path는 강제 테스트 포지션으로 검증한다

- 결정: 자연 청산을 기다리지 않고 테스트 spot long 포지션 1건을 열고 닫아 `close_position` 경로를 검증했다.
- 이유: closed trade가 없는 상태에서는 수수료, 슬리피지, spread, `ret_pct`, `hit`, `hold_hours` 기록을 신뢰하기 어렵다.
- 영향: 테스트 row는 검증 후 삭제했다.
- 영향: Slack close 알림은 실제 채널 발송 대신 `_post()`를 모킹해 payload 조립 경로를 테스트한다.
- 리스크: 실제 Slack API 장애/권한 문제는 별도 운영 알림 테스트가 필요하다.

## D014. relaxed regime은 research-only로 둔다

- 결정: `relaxed_2of3_v1` regime classifier는 live default가 아니라 research variant로만 둔다.
- 이유: unknown을 줄이는 것은 좋지만, 1차 A/B에서 low-quality trades가 늘어 strict 대비 성과가 악화됐다.
- 영향: live/paper 기본값은 `strict_v1`이다.
- 영향: backtest CLI에서 `--regime-variant relaxed_2of3_v1`로만 실험한다.
- 리스크: 표본이 짧으므로 최종 폐기는 아니다. 다만 승격은 금지한다.

## D015. live gate replay는 기본 off인 backtest 옵션으로 둔다

- 결정: execution gate/realtime risk block replay를 `--replay-execution-gate-blocks`, `--replay-realtime-risk-blocks` 옵션으로 추가한다.
- 이유: baseline 성과와 live gate 적용 성과를 분리해서 비교해야 한다.
- 영향: 옵션을 켜면 gate block이 신규 open을 막고 `arena_backtest_risk_events`에 `live_gate_replay` event를 남긴다.
- 리스크: realtime feature coverage가 부족한 과거 구간에서는 gate replay가 보수적으로 해석될 수 있다.
