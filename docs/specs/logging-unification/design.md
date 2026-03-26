# Logging Unification — Feature Design

## Overview

현재 Morning Market Brief의 실행 로그는 `logging` 텍스트 로그, `PipelineObserver` JSON 이벤트, 종료 시점 summary/audit JSON, 그리고 GitHub Actions shell wrapper 출력이 서로 다른 경로로 흩어져 있다. 이 설계의 목표는 **앱이 생성하는 로그를 하나의 canonical event pipeline으로 통합**하고, 그 위에 **사람이 읽는 콘솔 렌더러**와 **머신이 읽는 JSONL 렌더러**를 얹는 것이다.

핵심 전략 네 가지:
1. **중앙 설정 단일화** — `logging.basicConfig()` 대신 `dictConfig()` 기반 단일 설정 진입점으로 root/app/third-party 정책을 관리
2. **Canonical event 우선** — 텍스트 로그와 observer 이벤트를 따로 다루지 않고, 모든 앱 로그를 하나의 event dict로 정규화
3. **동일 이벤트, 이중 렌더링** — 같은 event를 console formatter와 JSONL formatter로 각각 직렬화
4. **하위 호환 유지** — `outputs/observability/pipeline-run-*.json`와 `perplexity-audit-*.json`는 유지하고, 새 JSONL artifact를 추가

## Glossary

- **Canonical Event**: 앱 내부에서 로그 1건을 표현하는 표준 구조체. `ts`, `level`, `event`, `message`, `attributes`, `run_id`, `component`를 포함한다.
- **Console Renderer**: 개발자와 운영자가 stdout에서 읽는 one-line human-readable 포맷터
- **JSONL Renderer**: artifact 저장과 후처리를 위한 line-delimited structured formatter
- **Log Context**: `run_id`, `phase`, `provider`, `attempt`처럼 현재 실행 문맥을 나타내는 값. `contextvars`로 자동 주입한다.
- **App Log Sink**: 앱이 생성한 canonical event를 실제 출력 채널로 내보내는 계층
- **Observer Summary**: 실행 종료 후 쓰는 `pipeline-run-<run_id>.json` summary. 비용, duration, anomaly, cache 상태를 요약한다.
- **Workflow Wrapper Log**: GitHub Actions shell step이 찍는 `Pipeline attempt 1/2`, `tee run.log`, 환경 변수 export 등의 앱 외부 로그

## Architecture

### 상위 구조

```
┌────────────────────────────────────┐
│            App Code                │
│ logger.info / logger.warning       │
│ observer.log_event / usage records │
└────────────────┬───────────────────┘
                 │
                 ▼
┌────────────────────────────────────┐
│      Canonical Logging Layer       │
│ - contextvars injection            │
│ - event normalization              │
│ - redaction / truncation           │
│ - severity mapping                 │
└───────────────┬───────────────┬────┘
                │               │
                ▼               ▼
┌──────────────────────┐  ┌────────────────────────┐
│ Console Renderer     │  │ JSONL Renderer         │
│ human single-line    │  │ app-events-<run>.jsonl │
└──────────┬───────────┘  └──────────┬─────────────┘
           │                         │
           ▼                         ▼
    stdout / run.log         outputs/observability/
                                     │
                                     ▼
                     pipeline-run-<run>.json summary
                     perplexity-audit-<run>.json
```

### 중앙 설정 구조

로깅 초기화는 `main.py -> setup_logging()` 진입을 유지하되, 내부 구현은 `dictConfig()` 기반으로 교체한다.

설정 계층:
- `root logger`
- `morning_brief.*` app logger
- `third-party logger` (`httpx`, `openai`, `urllib3`, `googleapiclient` 등)
- `QueueHandler` / `QueueListener`
- formatter 2종
  - `HumanConsoleFormatter`
  - `JsonlFormatter`
- filter 2종
  - `ContextInjectionFilter`
  - `RedactionFilter`

정책:
- app logger는 canonical schema를 통과해야 한다
- third-party logger는 default로 plain pass-through가 아니라 동일 renderer를 통과시키되, `event`는 `third_party.log`로 normalize한다
- noisy third-party logger는 level override를 둔다
- `propagate` 정책은 root 단에서 한 번만 출력되도록 정한다

### Queue sink topology

느린 sink와 빠른 sink를 분리하기 위해 queue 기반 토폴로지를 기본 설계로 둔다.

구성:
- producer
  - `morning_brief.*` logger
  - `observer.log_event()` wrapper
  - third-party logger 중 root에 propagate되는 항목
- queue
  - process-local `queue.Queue`
- consumer
  - `QueueListener`
- sinks
  - console stream handler
  - JSONL file handler

소유권:
- `setup_logging()`가 queue 생성, `QueueHandler` 장착, `QueueListener` 시작 책임을 가진다
- 종료 시 `setup_logging()`가 listener stop을 보장한다
- `PipelineObserver.write_outputs()`는 listener stop 이후 summary/audit 파일을 쓰지 않고, listener가 살아 있는 동안 JSONL이 flush되도록 종료 순서를 맞춘다

fallback:
- listener 초기화에 실패하면 console-only direct handler로 안전하게 내려간다
- fallback 경고는 stdout에 한 번만 남기고 반복 출력하지 않는다
- fallback 상태는 final summary와 summary JSON에 같이 남긴다

### 파일 구조

기존 파일을 최대한 활용하면서 역할을 재배치한다.

예상 파일 배치:
- `src/morning_brief/logging_utils.py`
  - `setup_logging()`
  - `build_logging_config()`
  - formatter/filter 등록
- `src/morning_brief/log_context.py` 또는 `logging_utils.py` 내부
  - `set_run_context()`
  - `bind_phase()`
  - `bind_provider()`
  - `reset_context()`
- `src/morning_brief/observability.py`
  - `PipelineObserver`는 summary/audit와 phase metrics 책임 유지
  - `log_event()`는 내부적으로 canonical logger를 사용
- `src/morning_brief/log_schema.py` 또는 `logging_utils.py` 내부
  - `CanonicalEvent` 타입 정의
  - severity mapping
  - truncation helpers

### 출력 산출물 경로

하위 호환을 위해 기존 observability 산출물은 유지하고, 앱 로그 JSONL만 추가한다.

```
outputs/
  observability/
    app-events-<run_id>.jsonl
    pipeline-run-<run_id>.json
    perplexity-audit-<run_id>.json
```

규칙:
- `app-events-<run_id>.jsonl`가 앱 로그의 source of truth
- `pipeline-run-<run_id>.json`는 요약본
- `run.log`는 workflow wrapper와 console renderer가 섞인 triage 보조본

## Canonical Event Schema

### 최소 필드

```json
{
  "ts": "2026-03-27T11:25:10.123Z",
  "level": "INFO",
  "severity_text": "INFO",
  "severity_number": 9,
  "event": "phase.complete",
  "message": "news phase completed",
  "run_id": "20260327-022510-abc123",
  "component": "morning_brief.pipeline",
  "phase": "news",
  "provider": null,
  "attributes": {
    "duration_ms": 14822,
    "candidate_count": 24,
    "kept_count": 12
  }
}
```

### 역할 분리

- `event`
  - 기계 친화적인 고정 이벤트 이름
  - 예: `run.start`, `phase.complete`, `provider.request`, `publish.complete`
- `message`
  - 사람이 읽는 한 줄 설명
  - 예: `news phase completed`
- `attributes`
  - 비교, 집계, 검색이 가능한 세부 수치/텍스트 필드

### severity 매핑

Python logging level을 유지하면서 OpenTelemetry와 충돌하지 않는 수치 매핑을 쓴다.

| Python Level | severity_text | severity_number |
|--------------|---------------|-----------------|
| DEBUG | DEBUG | 5 |
| INFO | INFO | 9 |
| WARNING | WARN | 13 |
| ERROR | ERROR | 17 |
| CRITICAL | FATAL | 21 |

## Context Propagation

### contextvars 기반 바인딩

`run_id`, `phase`, `provider`, `attempt`는 문자열 보간이 아니라 `contextvars`로 관리한다.

예상 흐름:
1. `main.py`가 run 시작 시 `run_id` bind
2. `pipeline.py`가 phase 시작 시 `phase` bind
3. provider adapter가 API 호출 직전 `provider` bind
4. retry loop가 `attempt` bind
5. 로그 호출은 payload 없이도 현재 컨텍스트를 자동 포함

### scope 규칙

- `run_id`: run 전체 범위
- `phase`: `market`, `news`, `backfill`, `brief`, `review`, `email`, `publish`, `deploy`
- `provider`: `openai`, `perplexity`, `grok_keyword`, `grok_official`, `fred`, `gmail` 등
- `attempt`: retry 또는 pipeline attempt

## Renderer Strategy

### Console Renderer

목표:
- 사람이 GitHub Actions와 로컬 터미널에서 빠르게 읽을 수 있어야 한다
- 한 줄당 하나의 사건만 출력한다

형식 예:

```text
2026-03-27 11:25:10 | INFO | run=20260327-022510-abc123 | phase=news | event=selection.complete | kept=12/24 | publish quality gate completed
```

원칙:
- 앞쪽에 시간, level, run, phase, event
- 뒤쪽에 결과 요약
- 큰 payload는 콘솔에 넣지 않음

### JSONL Renderer

목표:
- 기계 파싱과 사후 분석에 안정적이어야 한다
- stdout과 다른 정보를 추가하지 않고, 같은 canonical event를 JSON으로만 표현한다

형식:
- 1 line = 1 event
- UTF-8
- append-only

예:

```json
{"ts":"2026-03-27T02:25:10.123Z","level":"INFO","severity_text":"INFO","severity_number":9,"event":"selection.complete","message":"publish quality gate completed","run_id":"20260327-022510-abc123","component":"morning_brief.data.news","phase":"news","provider":null,"attributes":{"candidate_count":24,"kept_count":12,"dropped":12,"reason":"non_preferred_domain"}}
```

## Event Taxonomy

### Naming Convention

이벤트는 `<domain>.<action>` 또는 `<domain>.<subdomain>.<action>` 규칙으로 고정한다.

예:
- `run.start`
- `run.complete`
- `phase.start`
- `phase.complete`
- `provider.request`
- `provider.response`
- `provider.usage`
- `selection.complete`
- `selection.drop`
- `cache.hit`
- `cache.miss`
- `publish.complete`
- `deploy.complete`
- `error.raised`
- `fallback.used`

### 기존 이벤트 매핑

현재 ad-hoc 이벤트는 아래처럼 정규화한다.

| Current Event | Canonical Event |
|---------------|-----------------|
| `phase_duration` | `phase.complete` |
| `public_publish_news_selection` | `selection.complete` |
| `public_publish_x_selection` | `selection.complete` |
| `provider_usage_summary` | `provider.usage` |
| `pipeline_summary` | `run.complete` |
| `backfill_skipped` | `fallback.used` 또는 `phase.skip` |
| `brief_review_failed` | `error.raised` |

세부 구분은 `attributes.kind`, `attributes.target`, `attributes.reason`로 보완한다.

## Observer Integration

### 역할 재정의

`PipelineObserver`는 폐기하지 않는다. 대신 책임을 줄인다.

유지 책임:
- phase duration 축적
- provider usage 축적
- summary/audit 파일 쓰기
- anomaly, cache status 집계

이동 책임:
- stdout JSON 직접 `print()`
- ad-hoc event 직렬화

새 구조:
- `observer.log_event()`는 canonical logger 호출 래퍼가 된다
- `observer.record_provider_usage()`는 summary 집계와 동시에 `provider.usage` canonical event를 남긴다
- `observer.write_outputs()`는 `app-events-<run_id>.jsonl`와 `pipeline-run-<run_id>.json`의 연결만 보장한다

## Exception, Redaction, Truncation

### 예외 로깅

예외는 하나의 canonical event로 정리한다.

필수 속성:
- `error_type`
- `reason`
- `retryable`
- `attempt`

선택 속성:
- `stacktrace`
- `provider_status`
- `response_code`

콘솔:
- stacktrace 미출력
- `message` 한 줄만 출력

JSONL:
- stacktrace 포함 가능

### Redaction

민감 정보는 formatter 직전 filter에서 마스킹한다.

대상:
- API key
- OAuth token
- bearer token
- Gmail credentials
- account identifier

규칙:
- 값 전체를 쓰지 않고 `***` 또는 일부 suffix만 남긴다
- dict/list/string payload 모두 재귀적으로 적용

### Truncation

payload 제한은 전역 helper에서 처리한다.

초기 기준:
- 긴 문자열: 500자 초과 시 절단
- 리스트: 10개 초과 시 head N + `truncated_count`
- dict: 허용 key 수 초과 시 whitelist 우선 + 나머지 생략

목적:
- `perplexity_items_collected`, `selection` 상세, raw model payload가 콘솔과 artifact를 과도하게 키우지 않게 한다

## CI and Artifact Flow

### GitHub Actions

현재 workflow는 유지하되 앱 로그 artifact를 추가한다.

`Run pipeline` step:
1. shell wrapper 시작
2. wrapper 출력은 `[workflow]` prefix를 고정해 남긴다
3. app console renderer 출력은 canonical console formatter만 사용한다
4. `run.log`에 wrapper + console renderer 동시 저장
5. `outputs/observability/app-events-<run_id>.jsonl` 생성
6. 기존 `pipeline-run-<run_id>.json`, `perplexity-audit-<run_id>.json` 생성
7. final stdout summary(`run.complete`)를 한 번만 출력
8. artifact 업로드

규칙:
- workflow 메타 로그는 shell wrapper가 `[workflow]` prefix로 남긴다
- 앱 로그는 `[workflow]` prefix를 절대 사용하지 않는다
- 운영자는 `run.log` 안에서도 prefix만으로 wrapper/app 경계를 구분할 수 있어야 한다

### Final stdout summary contract

run 종료 시에는 canonical taxonomy의 `run.complete` event를 stdout에 정확히 한 번만 출력한다.

출력 위치:
- 권장 위치는 `observer.write_outputs()`가 summary payload를 확정한 직후다
- 성공/실패 공통으로 같은 경로를 사용한다

필수 내용:
- `run_id`
- `status`
- `phase durations`
- `provider usage`
- `artifact paths`
- queue fallback 여부

일관성 규칙:
- final stdout summary는 `pipeline-run-<run_id>.json` summary와 같은 source payload를 공유한다
- `provider_usage_summary`, `pipeline_summary`, `run.complete`가 서로 다른 값을 계산하지 않는다
- 동일 run에서 final summary line이 2회 이상 출력되면 버그로 간주한다

### 사람이 보는 우선순위

1. `run.log`
   - 장애를 빠르게 읽는 1차 진입점
2. `app-events-<run_id>.jsonl`
   - 구조화 원본
3. `pipeline-run-<run_id>.json`
   - 요약/비용/phase duration 확인
4. `perplexity-audit-<run_id>.json`
   - 특정 provider 감사본

## Migration Plan

### Phase 1: 기반 계층 도입

- `dictConfig()` 기반 setup 도입
- canonical schema 타입 도입
- contextvars 주입
- console/jsonl formatter 추가

이 단계에서는 기존 logger 호출을 최대한 유지하고, observer 출력만 새 경로에 태운다.

### Phase 2: observer/stdlib 통합

- `observer.log_event()`를 canonical event wrapper로 변경
- 주요 `logger.info/warning/error`를 taxonomy에 맞는 event 중심 호출로 정리
- 중복 stdout JSON 출력 제거

### Phase 3: taxonomy와 payload 정리

- ad-hoc event 이름 정규화
- selection/provider/cache/publish 이벤트 payload 정리
- truncation/redaction 정책 고정

### Phase 4: CI와 운영 문서 정리

- artifact 경로 반영
- triage 문서 갱신
- 테스트/fixture/observability 회귀 강화

## Risks and Trade-offs

| Risk | 대응 방안 |
|------|-----------|
| 기존 텍스트 로그와 event 이름이 달라져 운영자가 낯설어함 | migration 단계에서 summary와 대표 메시지 wording은 최대한 유지 |
| third-party logger까지 JSON화하면 noise 증가 | namespace별 level/propagate 정책 분리 |
| truncation이 너무 강하면 디버깅 정보 부족 | 콘솔과 JSONL의 limit를 분리하고, JSONL은 더 완화 |
| observer와 logger를 한 번에 완전 통합하면 회귀 위험 큼 | observer summary 책임은 유지하고 출력 경로만 먼저 통일 |
| OTel을 바로 도입하면 의존성 증가 | 현재는 schema 호환만 목표로 하고 SDK 연동은 보류 |

## Correctness Properties

### Property 1: Single Event Source

_For any_ 앱 로그 사건에서, console 출력과 JSONL artifact는 동일한 canonical event에서 파생되어야 한다 (SHALL). 채널마다 별도의 메시지 생성 로직을 가지지 않아야 한다.

**Validates: Requirements 2.6, 2.9, 5.2**

### Property 2: Context Completeness

_For any_ phase/provider 관련 로그에서, `run_id`와 현재 활성 `phase`, `provider`, `attempt` 컨텍스트는 자동으로 포함되어야 한다 (SHALL). 수동 문자열 조합에 의존하지 않아야 한다.

**Validates: Requirements 0.3, 0.4, 1.3, 1.4**

### Property 3: Human-readable Console

_For any_ stdout 앱 로그에서, 한 줄은 하나의 사건만 표현하고, 사람이 “무엇이 어느 단계에서 어떤 결과로 끝났는지”를 구조화 payload 없이도 읽을 수 있어야 한다 (SHALL).

**Validates: Requirements 2.1, 3.1, 3.2, 3.4**

### Property 4: Backward-compatible Observability

_For any_ run 종료에서, 기존 `pipeline-run-<run_id>.json`와 `perplexity-audit-<run_id>.json`는 계속 생성되어야 하며, 새 `app-events-<run_id>.jsonl`와 같은 `run_id`로 연결되어야 한다 (SHALL).

**Validates: Requirements 2.5, 5.4, 6.2**

### Property 5: Safe Payload Handling

_For any_ 로그 payload에서, 시크릿은 redaction되어야 하고, 과도한 payload는 정해진 truncation 규칙에 따라 잘려야 하며, 잘림 사실은 추적 가능해야 한다 (SHALL).

**Validates: Requirements 3.6, 3.7, 7.1, 7.2**

### Property 6: Distinguishable Workflow and App Logs

_For any_ GitHub Actions `Run pipeline` step에서, wrapper 로그와 앱 로그는 같은 `run.log`에 존재하더라도 prefix 또는 동등한 표식으로 논리적으로 구분 가능해야 한다 (SHALL).

**Validates: Requirements 2.2, 6.1**

### Property 7: Single Final Summary Emission

_For any_ run 종료에서, human-readable final summary는 canonical `run.complete` event로 정확히 한 번만 stdout에 출력되어야 하며, `pipeline-run-<run_id>.json`와 동일한 핵심 값을 가져야 한다 (SHALL).

**Validates: Requirements 4.5, 6.3**
