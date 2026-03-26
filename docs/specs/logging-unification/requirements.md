# Requirements Document

## Introduction

현재 프로젝트의 실행 로그는 세 갈래로 분산돼 있다.

- stdlib `logging` 기반 텍스트 로그
- `PipelineObserver`가 stdout에 직접 출력하는 JSON 이벤트
- 실행 종료 후 `outputs/observability/`에 저장되는 summary/audit JSON

여기에 GitHub Actions의 shell wrapper 출력과 환경 변수 dump가 같은 step 로그에 섞이면서, 사람이 `Run pipeline` 로그를 읽을 때 앱 로그와 workflow 메타 로그를 분리해 해석해야 한다. 또한 같은 사실이 텍스트 로그와 JSON 이벤트에 중복 기록되거나, 반대로 중요한 상태가 한쪽에만 남는 문제도 있다.

이번 작업의 목표는 **앱이 생성하는 로그를 하나의 표준 구조로 통일**하고, **사람이 읽기 쉬운 콘솔 출력**과 **머신이 파싱하기 쉬운 구조화 산출물**을 동시에 제공하는 것이다. 대상 범위는 `main.py`, `logging_utils.py`, `PipelineObserver`, 파이프라인/수집/번역/메일/공개 게시 경로, 그리고 GitHub Actions의 `Run pipeline` 로그 캡처 흐름까지 포함한다.

## Functional Requirements

### 설정 중앙화와 컨텍스트 전파

0.1 WHEN 애플리케이션이 로깅을 초기화할 때 THEN `logging.basicConfig()`에 의존하지 않고 하나의 중앙 설정 진입점에서 전체 로깅 구성을 선언해야 한다

0.2 WHEN 중앙 로깅 구성을 선언할 때 THEN `logger`, `handler`, `formatter`, `filter`, `root`, `propagate`, `disable_existing_loggers` 정책을 한 곳에서 관리할 수 있어야 한다

0.3 WHEN 하나의 run 안에서 phase, provider, attempt, run_id가 바뀔 수 있을 때 THEN 이 컨텍스트는 수동 문자열 조합이 아니라 `contextvars` 또는 동등한 메커니즘으로 자동 주입되어야 한다

0.4 WHEN 앱 코드가 직접 payload를 넘기지 않더라도 THEN 현재 활성화된 `run_id`, `phase`, `provider`, `attempt` 컨텍스트는 모든 로그에 누락 없이 포함되어야 한다

0.5 WHEN 향후 원격 export 또는 파일 기반 수집이 추가될 때 THEN 느린 로그 sink는 `QueueHandler`/`QueueListener` 또는 동등한 비차단 구조로 분리 가능해야 한다

### 표준 로그 스키마

1.1 WHEN 애플리케이션이 로그를 생성할 때 THEN 모든 앱 로그는 하나의 canonical event schema를 따라야 한다

1.2 WHEN canonical event schema가 적용될 때 THEN 모든 로그는 최소한 다음 공통 필드를 가져야 한다:
- `ts`
- `level`
- `severity_text`
- `severity_number`
- `event`
- `message`
- `attributes`
- `run_id`
- `component`

1.3 WHEN 로그가 특정 단계와 연관될 때 THEN `phase` 필드를 일관되게 포함해야 한다

1.4 WHEN 로그가 공급자 호출과 연관될 때 THEN `provider` 필드를 일관되게 포함해야 한다

1.4.1 WHEN canonical event schema가 적용될 때 THEN `event`, `message`, `attributes`는 서로 다른 역할을 가져야 한다:
- `event`: 기계적으로 식별 가능한 이벤트 이름
- `message`: 사람이 읽는 한 줄 요약
- `attributes`: 구조화된 세부 필드

1.5 WHEN 로그가 요약/카운트/비용 정보를 포함할 때 THEN 자유 텍스트가 아니라 구조화된 숫자 필드로 기록해야 한다

1.6 WHEN 예외 또는 실패가 발생할 때 THEN `error_type`, `reason`, `retryable`, `attempt` 같은 오류 컨텍스트 필드를 표준화해 포함해야 한다

1.7 WHEN 예외를 기록할 때 THEN stacktrace는 선택 가능한 구조화 필드로 남기되, 콘솔 기본 출력은 한 줄 요약을 유지해야 한다

1.8 WHEN severity를 기록할 때 THEN Python logging level은 유지하되, 미래 호환성을 위해 `severity_text`와 `severity_number`를 안정적으로 매핑해야 한다

### 출력 채널 통일

2.1 WHEN 로컬 실행 또는 CI 실행에서 앱 로그가 stdout으로 출력될 때 THEN 앱이 생성한 모든 로그는 동일한 포맷 규칙을 사용해야 한다

2.2 WHEN GitHub Actions `Run pipeline` step이 실행될 때 THEN workflow shell wrapper 출력과 앱 로그를 논리적으로 구분할 수 있어야 한다

2.3 WHEN CI가 run artifact를 저장할 때 THEN 사람이 읽는 콘솔 로그와 별도로 앱 로그 전용 산출물을 저장해야 한다

2.4 WHEN 앱 로그 전용 산출물을 저장할 때 THEN line-delimited structured format(JSONL 또는 동등한 형태)으로 저장되어야 한다

2.5 WHEN 실행 종료 후 summary를 쓸 때 THEN 기존 `outputs/observability/pipeline-run-*.json` summary와 새 앱 로그 산출물이 같은 `run_id`로 연결되어야 한다

2.6 WHEN 같은 canonical event를 여러 채널에 출력할 때 THEN 콘솔 출력과 구조화 산출물은 같은 event dict를 서로 다른 renderer로 직렬화해야 한다

2.7 WHEN 로컬 개발자가 콘솔을 읽을 때 THEN 기본 renderer는 사람이 읽기 쉬운 single-line console formatter여야 한다

2.8 WHEN artifact 또는 후처리용 로그를 저장할 때 THEN 기본 renderer는 machine-friendly JSONL formatter여야 한다

2.9 WHEN structured artifact와 console 출력이 공존할 때 THEN 두 채널의 핵심 필드 집합은 같고, 표현 형식만 달라야 한다

### 사람 중심 가독성

3.1 WHEN 콘솔에서 로그를 읽을 때 THEN 기본 출력은 한 줄당 하나의 사건만 보여주고, 필드 순서와 시각적 리듬이 모든 모듈에서 일관되어야 한다

3.2 WHEN 사람이 콘솔 로그를 읽을 때 THEN 기본 출력은 다음 우선순위를 따르는 human-readable message를 포함해야 한다:
1. 무엇이 일어났는가
2. 어느 단계/공급자에서 일어났는가
3. 결과가 무엇인가

3.3 WHEN 상세 payload가 큰 경우 THEN 기본 콘솔 출력에는 핵심 필드만 노출하고, 큰 payload는 구조화 산출물에만 남겨야 한다

3.4 WHEN 진행 상황 로그를 출력할 때 THEN phase 시작/종료, provider 호출, selection 결과, 번역 결과, 게시 결과가 읽기 순서대로 보이도록 해야 한다

3.5 WHEN 같은 사실을 여러 방식으로 기록하려 할 때 THEN 콘솔용 메시지와 구조화 payload는 같은 event를 공유해야 하며, 중복된 별도 로그를 만들지 않아야 한다

3.6 WHEN 속성이나 payload가 큰 경우 THEN 로그 시스템은 attribute 개수, 문자열 길이, 배열 샘플 수에 대한 제한과 truncation 규칙을 명시적으로 가져야 한다

3.7 WHEN 큰 payload가 잘려야 할 때 THEN 잘렸다는 사실과 원본 위치 또는 샘플링 규칙이 사람이 추적 가능하게 기록되어야 한다

### 이벤트 taxonomy 정리

4.1 WHEN 로그 이벤트 이름을 정의할 때 THEN 이벤트는 다음 카테고리 중 하나로 분류되어야 한다:
- run lifecycle
- phase lifecycle
- provider request/response
- selection/filter decision
- cache
- publish/deploy
- error/fallback

4.2 WHEN 이벤트를 카테고리화할 때 THEN 이벤트 이름은 현재처럼 ad-hoc하게 늘어나는 대신 일정한 접두 규칙 또는 명시적 분류 필드를 가져야 한다

4.3 WHEN selection/filter 관련 로그를 남길 때 THEN `candidate_count`, `kept_count`, `dropped`, `reason` 등 비교 가능한 필드 집합을 공통으로 가져야 한다

4.4 WHEN provider usage를 기록할 때 THEN 요청 수, 입력/출력 토큰, cached input, reasoning, sources, parse failures, cost가 모든 provider에 대해 같은 필드 집합으로 노출되어야 한다

4.5 WHEN run 종료 summary를 기록할 때 THEN `provider_usage_summary`와 `pipeline_summary`가 stdout, JSON 산출물, artifact 간에 동일한 핵심 값을 가져야 한다

### observability와 stdlib logging 역할 정리

5.1 WHEN 애플리케이션이 로그를 남길 때 THEN `logging`과 `PipelineObserver`의 역할 경계가 명확해야 한다

5.2 WHEN 구조화된 앱 로그가 도입될 때 THEN `PipelineObserver`와 모듈별 `logger.*` 호출은 최종적으로 같은 canonical schema를 통과해야 한다

5.3 WHEN 기존 `observer.log_event()`가 남아 있을 때 THEN 새 로그 시스템 아래에서 동일 스키마로 직렬화되어야 하며, 별도 예외 포맷을 가지면 안 된다

5.4 WHEN 기존 `outputs/observability/pipeline-run-*.json`와 `perplexity-audit-*.json`을 유지할 필요가 있을 때 THEN 하위 호환을 깨지 않는 범위에서 유지되어야 한다

5.5 WHEN app logger와 third-party logger가 함께 존재할 때 THEN `morning_brief.*` 네임스페이스와 외부 라이브러리 로거의 처리 정책을 명시적으로 구분해야 한다

5.6 WHEN third-party logger를 루트 로거에 연결할 때 THEN `propagate` 여부, level override, JSON 재직렬화 여부를 일관된 정책으로 통제해야 한다

### CI와 운영 절차

6.1 WHEN GitHub Actions가 파이프라인을 실행할 때 THEN `run.log`는 workflow wrapper 출력과 앱 로그를 함께 담더라도, 앱 로그만 별도로 재사용 가능한 artifact가 존재해야 한다

6.2 WHEN 사람이 GitHub Actions에서 장애를 triage할 때 THEN 다음 3가지를 한 번에 비교할 수 있어야 한다:
- step 콘솔 로그
- 앱 구조화 로그 산출물
- 최종 observability summary JSON

6.3 WHEN 파이프라인이 성공 또는 실패로 종료될 때 THEN 마지막에 사람이 바로 읽을 수 있는 run summary가 stdout에 항상 한 번 나타나야 한다

### 보안 및 민감 정보

7.1 WHEN 로그가 환경 변수, 요청, 응답을 포함할 때 THEN API 키, OAuth 토큰, 이메일 자격증명, 계정 식별자 등 비밀값은 절대 평문으로 기록되면 안 된다

7.2 WHEN payload 일부가 민감할 수 있을 때 THEN 민감 필드는 redaction 규칙에 따라 마스킹되어야 한다

7.3 WHEN `--print-brief`처럼 본문 노출 가능 옵션이 있는 경우 THEN 기본 로그 경로에서는 브리프 본문이나 메일 본문 전체가 기록되지 않아야 한다

## Non-Functional Requirements

### 일관성

8.1 WHEN 어느 모듈에서 로그를 남기더라도 THEN timestamp, level, component, event, message 순서와 의미가 동일해야 한다

8.2 WHEN 로컬 실행과 GitHub Actions 실행을 비교할 때 THEN 앱 로그 구조는 동일해야 한다

8.3 WHEN 미래에 OpenTelemetry export를 붙일 경우 THEN 현재 canonical schema는 OpenTelemetry Logs Data Model과 충돌하지 않는 필드명과 확장 지점을 가져야 한다

### 성능

9.1 WHEN 구조화 로그를 추가하더라도 THEN 파이프라인 전체 실행 시간에 눈에 띄는 영향을 주지 않아야 한다

9.2 WHEN 큰 payload를 기록할 때 THEN 콘솔 출력은 최소화하고 파일 산출물에만 저장해 stdout noise를 줄여야 한다

### 유지보수성

10.1 WHEN 새 모듈이나 새 provider가 추가될 때 THEN 동일 스키마와 helper를 통해 최소한의 코드로 로그를 남길 수 있어야 한다

10.2 WHEN 테스트를 작성할 때 THEN 이벤트 이름, 필수 필드, summary 필드를 안정적으로 검증할 수 있어야 한다

10.3 WHEN 운영 문서를 읽는 작업자가 있을 때 THEN 로그를 어디서 봐야 하는지, 어떤 파일이 source of truth인지 즉시 알 수 있어야 한다

## Constraints

- 현재 `main.py` → `setup_logging()` → `run_pipeline()` 진입 구조는 유지한다
- 현재 `outputs/observability/pipeline-run-*.json`, `outputs/observability/perplexity-audit-*.json` 산출물은 하위 호환을 가능한 한 유지한다
- GitHub Actions `Morning Market Brief` workflow의 artifact 업로드 구조는 크게 깨지 않도록 한다
- `.env*`, OAuth 파일, 시크릿은 로그에 포함되면 안 된다
- 구조화 로그 통합은 앱 로그 범위를 우선 대상으로 하며, GitHub Actions 자체 메타 로그(`##[group]`, shell echo)는 앱 로그 체계 밖으로 본다
