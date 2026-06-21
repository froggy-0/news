# Realtime Risk Trigger v1

작성일: 2026-06-21

## 목적

BTC 현물 long/flat 전략은 4H candle close에서 방향을 판단한다. 하지만 시장 데이터와 리스크 감시는 1분 단위로 계속 수행한다. 이 문서는 1분 microstructure feature를 이용해 신규 spot buy를 막아야 할 위험 상태를 shadow로 기록하는 realtime risk trigger v1을 정의한다.

v1은 shadow-first다. 기본값에서는 `paper_positions`를 열거나 닫지 않는다.

## 현재 적용 상태

2026-06-21 서버 재배포 후 EC2 로그에서 아래 write가 정상 확인됐다.

- `arena_realtime_feature_bars` 1분 row upsert
- `arena_realtime_risk_states` 1분 row upsert
- risk state 변화 시 `arena_realtime_risk_events` insert
- 4H cycle에서 최신 realtime risk state 조회 후 execution gate snapshot에 연결

latest run `06a8ae1f-83c4-4b21-96be-34967df9c0df`는 `capture_status=ok`, `capture_error_count=0`으로 완료됐다.

## 코드 구성

| 영역 | 파일 | 역할 |
| --- | --- | --- |
| feature 보강 | `/Users/giwon/code/news/src/arena/realtime_market.py` | 1분 feature에 5분 변동성, short drawdown, spread widening, depth collapse, aggressive sell ratio 추가 |
| risk score | `/Users/giwon/code/news/src/arena/realtime_risk.py` | `NORMAL`부터 `FORCE_EXIT_CANDIDATE`까지 상태 분류 |
| 저장 | `/Users/giwon/code/news/src/arena/data_lake.py` | `arena_realtime_risk_states`, `arena_realtime_risk_events` write/read |
| 4H 연결 | `/Users/giwon/code/news/src/arena/scheduler.py` | 최신 risk state를 execution gate snapshot에 첨부 |

## 상태와 액션

| State | 의미 | v1 액션 |
| --- | --- | --- |
| `NORMAL` | 정상 시장 | 4H 신호 허용 후보 |
| `CAUTION` | 비용/체결 품질 악화 초기 | shadow상 size 축소/post-only 후보 |
| `BLOCK_ENTRY` | 신규 매수 보류가 유리한 상태 | shadow상 spot buy 차단 후보 |
| `EXIT_CANDIDATE` | 보유 long 리스크 확대 | shadow상 stop tighten/partial exit 후보 |
| `FORCE_EXIT_CANDIDATE` | 극단적 리스크 | shadow상 강제 청산 후보. live 비활성 |
| `UNKNOWN` | 핵심 feature 품질 부족 | live 판단에 사용 금지 |

## 기본 정책

| 항목 | 기본값 |
| --- | ---: |
| `ENABLE_ARENA_REALTIME_RISK` | `true` |
| `ENABLE_ARENA_REALTIME_RISK_LIVE` | `false` |
| `REALTIME_RISK_HISTORY_WINDOWS` | `60` |
| `REALTIME_RISK_FRESHNESS_SECONDS` | `180` |
| `CAUTION` threshold | `0.35` |
| `BLOCK_ENTRY` threshold | `0.55` |
| `EXIT_CANDIDATE` threshold | `0.70`, 2 windows sustained |
| `FORCE_EXIT_CANDIDATE` threshold | `0.85`, 2 windows sustained |

점수 weight는 보고서 기준을 그대로 둔다: volatility `0.18`, spread `0.18`, depth `0.22`, volume `0.10`, order flow `0.12`, slippage `0.15`, futures auxiliary stress `0.05`.

## SQL 적용

```sql
-- /Users/giwon/code/news/supabase/migrations/20260621_arena_realtime_risk_v1.sql
select * from arena_realtime_risk_v1_ready;
```

## 확인 쿼리

```sql
select
  symbol,
  window_start,
  risk_state,
  risk_score,
  trigger_reasons,
  recommended_action,
  quality_status,
  created_at
from arena_realtime_risk_states
order by window_start desc
limit 30;

select
  event_type,
  previous_state,
  risk_state,
  severity,
  recommended_action,
  risk_score,
  created_at
from arena_realtime_risk_events
order by created_at desc
limit 30;
```

## 승격 조건

`ENABLE_ARENA_REALTIME_RISK_LIVE=true`는 최소 7일 이상 shadow 데이터를 보고 아래 조건을 만족한 뒤에만 검토한다.

- `arena_realtime_risk_v1_ready`의 schema 항목이 모두 true.
- 최근 24시간 feature freshness 정상.
- 1분 feature core null과 duplicate grain 문제가 없음.
- `BLOCK_ENTRY`가 실제 손실 회피에 도움이 되는지 replay로 확인.
- 현물 spot long/flat 원칙이 유지됨. short position 생성 금지.
