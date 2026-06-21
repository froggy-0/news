# Arena Strategy Taxonomy and Sleeve Contract

작성일: 2026-06-20

## 목적

Arena vNext는 기존 paper trading 알고리즘을 즉시 교체하지 않는다. 기존 `ALGORITHMS`는 현물 long/flat live paper 원장(`paper_positions`)에 계속 사용하고, 새 전략은 shadow sleeve로 평가해 `arena_shadow_decisions`에만 저장한다.

## Taxonomy

| Layer | 역할 | v1 상태 |
| --- | --- | --- |
| live rule algorithms | 기존 5개 paper trading 알고리즘 | 현물 long/flat으로 유지 |
| regime gate | 내부 가격/변동성/시장구조 기반 레짐 판정 | `regime_gate_v1` |
| trend sleeve | trend-following core signal | `regime_trend`, shadow only |
| carry sleeve | funding/basis carry | 데이터 수집만 |
| allocator | sleeve target weight와 risk budget 산출 | shadow only |
| risk engine | live/backtest portfolio gate | 기존 `portfolio-risk-v1` 유지 |

## Sleeve Signal Contract

`SleeveSignal`은 아래 필드를 가진다.

| Field | 의미 |
| --- | --- |
| `sleeve_id` | 예: `trend_core` |
| `algo_id` | 예: `regime_trend` |
| `direction` | `long`, `null` |
| `confidence` | 0~1 confidence |
| `raw_score` | 방향성을 포함한 score |
| `target_weight` | allocator 전 요청 weight |
| `reason` | 신호 규칙 설명 |
| `feature_snapshot` | 신호 입력 feature snapshot |

## Allocation Contract

`AllocationDecision`은 아래 필드를 가진다.

| Field | 의미 |
| --- | --- |
| `allowed` | shadow allocation 허용 여부 |
| `target_weight` | budget cap 이후 weight |
| `risk_budget` | sleeve별 risk budget |
| `reason` | allocation rule 결과 |
| `regime_snapshot` | regime gate 결과 |
| `risk_snapshot` | live portfolio risk state snapshot |

## v1 운영 규칙

- `regime_trend`는 live/paper `ALGORITHMS`에 포함되어 있지만 실행은 spot long/flat으로 제한된다. vNext sleeve 평가는 같은 신호를 shadow allocation 원장에 별도로 기록한다.
- shadow decision은 포지션을 열지 않는다.
- live/paper 실행은 `spot_long_flat` 기준이다. 신규 숏 진입은 만들지 않는다.
- `ENABLE_ARENA_SHADOW_VNEXT=true`가 기본값이다.
- SQL 미적용 또는 Binance fapi 실패는 capture degraded로 남기고 기존 paper cycle은 계속한다.

## ML/RL Gate

ML/RL overlay는 아래 조건 전까지 구현하지 않는다.

- walk-forward split 최소 3개.
- backtest validation critical/high fail 0.
- shadow decision 30일 이상.
- funding/OI/mark data coverage 90% 이상.
