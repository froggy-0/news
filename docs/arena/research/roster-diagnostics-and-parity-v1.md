# Roster Diagnostics and Parity v1

작성일: 2026-06-21

## 목적

이 문서는 2026-06-21에 진행한 P0~P3 검증과 코드 반영 상태를 기록한다. 목표는 전략 수익률을 바로 판단하는 것이 아니라, **트랙레코드가 믿을 수 있는지**, **어떤 알고리즘이 왜 거래하지 않는지**, **live와 backtest 규칙이 같은지**를 먼저 고정하는 것이다.

## 결론

- P1 로스터 진단은 구현 및 배포 완료.
- P0 청산 경로는 테스트 포지션으로 검증 완료. 테스트 row는 삭제했다.
- P2 레짐 완화안은 research-only로 구현했지만, 현재 표본에서는 strict 대비 성과가 나빠 live 승격하지 않는다.
- P3 live/backtest 패리티 리플레이 옵션은 구현 완료.
- 최신 EC2 run은 `arena-spot-v4`, `arena-params-v18`, `arena-features-v8`, `portfolio-risk-v1`로 정상 완료됐다.

## P1. Algorithm Roster Diagnostics

### 문제

기존에는 `arena_decisions.action='flat_skip'`만 보면 왜 신호가 죽었는지 알기 어려웠다. 특히 `vix_rsi`, `multi_factor`, `regime_trend`는 trade count가 낮거나 0이라, 과도한 gating인지 정당한 방어인지 구분이 필요했다.

### 구현

| 파일 | 변경 |
| --- | --- |
| `/Users/giwon/code/news/src/arena/algorithms.py` | `explain_signal()`, `primary_flat_skip_reason()` 추가 |
| `/Users/giwon/code/news/src/arena/scheduler.py` | decision reason에 diagnostics 저장, flat skip 시 primary veto 저장 |
| `/Users/giwon/code/news/src/arena/execution_rules.py` | signal reason 입력 snapshot 확장 |
| `/Users/giwon/code/news/src/arena/roster_diagnostics.py` | live/backtest decision diagnostics CLI 추가 |
| `/Users/giwon/code/news/tests/test_arena_algorithm_diagnostics.py` | diagnostics 단위 테스트 |

### 최신 live 확인

서버 배포 후 `arena.roster_diagnostics --source live --limit 5`에서 최신 decision 5개가 `stored_reason_diagnostics`로 집계됐다.

최신 분포:

| algo | action | primary skip |
| --- | --- | --- |
| `multi_factor` | `flat_skip` | `veto:above_ma200_or_missing` |
| `macd_momentum` | `flat_skip` | `veto:above_ma200_or_missing` |
| `vix_rsi` | `flat_skip` | `veto:above_ma200_or_missing` |
| `fng_contrarian` | `hold` | 없음 |
| `regime_trend` | `flat_skip` | `veto:bullish_regime` |

해석: 최신 run 기준으로 대부분의 신규 매수 차단은 BTC가 200MA 기준 강세 확인을 통과하지 못했기 때문이다. 이것은 현재 spot long-only 정책에서는 공격적 진입을 막는 방어 역할을 한다.

### 운영 명령

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m arena.roster_diagnostics --source live --limit 50
PYTHONPATH=src .venv/bin/python -m arena.roster_diagnostics --source backtest --profile live_4h --limit 300
```

## P0. Close Path Validation

### 문제

closed 거래가 없으면 `positions.close_position()`, fee/slippage/spread 반영, `ret_pct`, `hit`, `hold_hours`, Slack close 알림 경로가 실제로 신뢰 가능한지 확인하기 어렵다.

### 검증 방식

테스트용 spot long position을 1건 생성한 뒤, 같은 코드 경로로 청산했다.

검증 입력:

- open price: `100`
- close price: `105`
- fee: `5bps` per leg
- slippage: `2bps` per leg
- spread: `3bps` round trip
- hold: `6h`

검증 결과:

| 항목 | 결과 |
| --- | --- |
| `status` | `closed` |
| `ret_pct` | `0.0483` |
| `hit` | `true` |
| `hold_hours` | `6` |
| `product_type` | `spot` |
| `position_semantics` | `spot_long_flat` |
| cleanup | 테스트 row 삭제 완료 |

실제 Slack 메시지 발송은 운영 채널 노이즈를 막기 위해 수행하지 않았다. 대신 네트워크 없이 `notify_close()` payload가 조립되고 `_post()` 호출까지 도달하는 테스트를 추가했다.

관련 테스트:

- `/Users/giwon/code/news/tests/test_arena_slack_notify.py`

## P2. Regime Classifier A/B

### 문제

기존 strict regime classifier는 `unknown` 비율이 높아 trend sleeve와 `regime_trend` 신호를 과도하게 막을 가능성이 있었다.

### 구현

`/Users/giwon/code/news/src/arena/regime.py`에 research-only variant를 추가했다.

| variant | 설명 |
| --- | --- |
| `strict_v1` | 기존 기본값. live default |
| `relaxed_2of3_v1` | 24h return, 72h return, EMA alignment 중 2개 동의 시 bull/bear 허용. trend `bb_width` gate 제거 |

Backtest CLI:

```bash
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile live_4h --limit 300 --regime-variant strict_v1
PYTHONPATH=src .venv/bin/python -m arena.backtest --profile live_4h --limit 300 --regime-variant relaxed_2of3_v1
```

### 1차 결과

| variant | 핵심 결과 |
| --- | --- |
| `strict_v1` | `regime_trend` 1 trade, total return 약 `+1.94%`; `macd_momentum` 7 trades, 약 `+0.35%` |
| `relaxed_2of3_v1` | 거래 수는 늘었지만 `regime_trend`, `macd_momentum`, `multi_factor` 성과가 악화 |

판정: relaxed variant는 unknown을 줄이지만 현재 표본에서는 low-quality trades를 늘렸다. live/paper 승격 금지.

## P3. Live / Backtest Parity Replay

### 문제

live 경로에는 execution gate와 realtime risk snapshot이 붙고, backtest 경로가 이를 무시하면 live와 replay 성과가 갈라질 수 있다.

### 구현

`/Users/giwon/code/news/src/arena/backtest.py`에 아래 옵션을 추가했다.

```bash
PYTHONPATH=src .venv/bin/python -m arena.backtest \
  --profile live_4h \
  --limit 300 \
  --replay-execution-gate-blocks \
  --replay-realtime-risk-blocks
```

동작:

- `execution_gate_allowed=false`이면 신규 open을 막고 `arena_backtest_risk_events`에 `live_gate_replay` event를 남긴다.
- 최신 realtime risk가 fresh이고 `BLOCK_ENTRY`, `EXIT_CANDIDATE`, `FORCE_EXIT_CANDIDATE`이면 신규 open을 막는다.
- 기본값은 둘 다 false다. 기존 baseline과 비교가 가능해야 하기 때문이다.

## Frontend 반영

`/Users/giwon/code/news/arena/index.html`에 최신 decision diagnostics 패널을 추가했다.

표시 항목:

- algo별 latest `action`
- raw signal -> executable signal
- `skipped_reason`
- diagnostics veto/failed condition 요약
- decision timestamp

카드에는 최신 skip hint를 표시한다. 예: `대기: above_ma200_or_missing`.

## 최신 배포 확인

2026-06-21 14:04 UTC 기준 EC2 상태:

| 항목 | 값 |
| --- | --- |
| service | `arena.service` |
| state | `active`, `running` |
| latest run | `06a8ae1f-83c4-4b21-96be-34967df9c0df` |
| run status | `completed` |
| data timestamp | `2026-06-21T11:59:59+00:00` |
| strategy | `arena-spot-v4` |
| params | `arena-params-v18` |
| features | `arena-features-v8` |
| risk model | `portfolio-risk-v1` |
| capture | `ok`, error count `0`, warnings `[]` |

## 검증 명령

```bash
cd /Users/giwon/code/news
PYTHONPATH=src .venv/bin/python -m pytest tests/test_arena_*.py -q
.venv/bin/ruff check src/arena tests/test_arena_*.py
node - <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('arena/index.html', 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
  .map(m => m[1])
  .filter(s => s.includes('const SUPABASE_URL'));
new Function(scripts[0]);
console.log('arena inline js ok');
NODE
```

## 다음 판단

다음 개선은 “새 전략 추가”가 아니라 `arena_decisions.skipped_reason`과 diagnostics 누적치를 보고 진행한다.

우선순위:

1. `above_ma200_or_missing` veto가 너무 보수적인지 90일 이상 live/backtest로 분해.
2. `regime_trend` strict/relaxed 외 2/3 vote + cost-aware 조합을 별도 research variant로 실험.
3. realtime risk gate가 실제 손실 회피에 도움이 되는지 `--replay-realtime-risk-blocks`로 비교.
4. closed trade가 자연 발생하면 P0에서 검증한 청산 경로와 동일한 값이 기록되는지 재확인.
