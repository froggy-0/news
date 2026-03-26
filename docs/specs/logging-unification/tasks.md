# Implementation Plan

- [ ] 1. 현재 로그 발생 지점과 마이그레이션 범위를 코드 기준으로 동결
  - 현재 `logging.basicConfig()` 진입점과 root/third-party logger 정책을 확인하고, 1차 변경 범위를 `src/morning_brief/logging_utils.py`, `src/morning_brief/observability.py`, `main.py`, `.github/workflows/morning-brief.yml`로 고정한다
  - 프로젝트 전체 스캔 기준 현재 로그 surface를 수치로 동결한다
    - `logger.*` 호출 파일 20개
    - `logging.getLogger(__name__)` 선언 파일 21개
    - `observer.log_event()` 사용 파일 14개
    - `observer.record_provider_usage()` 사용 파일 12개
    - runtime `print(...)` 사용 파일은 `main.py`, `src/morning_brief/observability.py`, `generate_gmail_token.py`로 분류한다
  - 현재 `logger.*` 호출 파일 전체를 목록화하고, 누락 없이 마이그레이션 대상에 포함한다
    - `src/morning_brief/brief_review.py`
    - `src/morning_brief/public_site.py`
    - `src/morning_brief/pipeline.py`
    - `src/morning_brief/data/market.py`
    - `src/morning_brief/research_backfill.py`
    - `src/morning_brief/briefing.py`
    - `src/morning_brief/data/news.py`
    - `src/morning_brief/unified_output.py`
    - `src/morning_brief/emailer.py`
    - `src/morning_brief/scheduler.py`
    - `src/morning_brief/data/sources/http_client.py`
    - `src/morning_brief/data/sources/btc_etf_official.py`
    - `src/morning_brief/data/sources/google_news_rss.py`
    - `src/morning_brief/data/sources/gemini_grounding.py`
    - `src/morning_brief/data/sources/grok_web_search.py`
    - `src/morning_brief/data/sources/perplexity_sonar.py`
    - `src/morning_brief/data/sources/dynamic_registry_updater.py`
    - `src/morning_brief/data/sources/fred.py`
    - `src/morning_brief/data/sources/grok_x_keyword.py`
    - `src/morning_brief/data/sources/grok_official_signals.py`
    - `src/morning_brief/data/sources/perplexity_search.py`
  - 현재 `observer.log_event()`, `observer.record_provider_usage()`, `PipelineObserver._emit()` 호출 지점을 목록화하고, event taxonomy 변환 대상 표를 만든다
  - 현재 artifact 구조(`run.log`, `outputs/observability/*.json`)를 기준선으로 문서화한다
  - `main.py --print-brief`는 의도적인 사용자 출력이므로 app logging 통합 대상이 아니라는 점을 명시한다
  - `generate_gmail_token.py`는 운영용 bootstrap 스크립트로 분리 취급할지, 별도 logging 규칙을 적용할지 scope decision을 문서에 남긴다
  - 신규 파일은 바로 만들지 말고, 1차 구현은 기존 `logging_utils.py`와 `observability.py` 확장을 우선한다. `log_context.py`, `log_schema.py` 분리는 구현 후 파일 크기와 책임이 명확히 갈릴 때만 허용한다
  - _Requirements: 0.1, 5.1, 5.3, 5.4, 10.1_

- [ ] 2. Canonical event schema와 event taxonomy를 실코드 기준 상수/헬퍼로 정의
  - `src/morning_brief/logging_utils.py` 또는 같은 모듈 내부 helper에 canonical event 생성 함수와 severity 매핑을 추가한다
  - 최소 필드 `ts`, `level`, `severity_text`, `severity_number`, `event`, `message`, `attributes`, `run_id`, `component`를 강제한다
  - `event`, `message`, `attributes` 역할을 분리하는 helper를 만든다
  - 현재 ad-hoc event를 canonical taxonomy로 매핑하는 표를 코드 상수로 정의한다
    - 예: `phase_duration -> phase.complete`, `pipeline_summary -> run.complete`
  - `phase.start`, `phase.complete`, `provider.request`, `provider.response`, `provider.usage`, `selection.complete`, `publish.complete`, `error.raised`, `fallback.used`처럼 설계 문서에 정의한 핵심 이벤트를 실제 코드에서 반드시 생성하도록 기준 이벤트 집합을 고정한다
  - selection/filter/provider usage 공통 필드 집합(`candidate_count`, `kept_count`, `dropped`, `reason`, usage metrics)을 helper 수준에서 재사용 가능하게 만든다
  - `error_type`, `reason`, `retryable`, `attempt`, `stacktrace` 예외 필드 규칙을 helper에서 표준화한다
  - _Requirements: 1.1, 1.2, 1.4.1, 1.5, 1.6, 1.7, 1.8, 4.1, 4.2, 4.3, 4.4_

- [ ] 3. 중앙 로깅 설정을 `dictConfig()` 기반으로 교체하되 기존 파일 확장을 우선
  - `src/morning_brief/logging_utils.py:7`의 `setup_logging()`을 `dictConfig()` 기반으로 교체한다
  - root logger, `morning_brief.*`, third-party logger 정책을 한곳에서 선언한다
  - `disable_existing_loggers`, `propagate`, per-namespace level override 정책을 명시적으로 넣는다
  - 기존 third-party quieting 목록(`httpx`, `openai._base_client`, `urllib3.connectionpool`, `googleapiclient.discovery_cache`, `perplexity`, `google.genai`, `google.auth`)을 새 config에 그대로 반영한다
  - 새 설정 도입 후에도 `main.py -> setup_logging() -> run_pipeline()` 진입 구조는 유지한다
  - _Requirements: 0.1, 0.2, 5.5, 5.6, Constraints_

- [ ] 4. run/phase/provider/attempt 컨텍스트를 `contextvars`로 자동 주입
  - `run_id`, `phase`, `provider`, `attempt`용 contextvars helper를 구현한다
  - `main.py`에서 run 시작 직후 `run_id`를 bind하고 종료 시 reset하는 경로를 추가한다
  - `src/morning_brief/pipeline.py`의 phase 경계(`market`, `news`, `backfill`, `brief`, `review`, `email`, `publish`, `deploy`)에서 bind/reset를 넣는다
  - provider adapter 진입점(`openai`, `perplexity`, `grok_*`, `gemini`, `fred`, `gmail`)에서 provider bind/reset를 넣는다
  - retry loop가 있는 곳에서는 `attempt` bind/reset를 넣는다
  - logger 호출부에서 수동 문자열 보간 없이도 context가 자동 포함되는지 확인한다
  - _Requirements: 0.3, 0.4, 1.3, 1.4, 8.1_

- [ ] 5. Queue 기반 sink topology를 실제 코드에 맞게 설계하고 적용
  - 느린 sink를 분리하기 위해 `QueueHandler`/`QueueListener` 구조를 `logging_utils.py`에 추가한다
  - 소유권을 명확히 한다
    - producer: app logger / observer wrapper
    - consumer: QueueListener
    - sinks: console stream, JSONL file
  - 로컬/CI 기본 경로는 queue 기반으로 동작하되, listener 초기화 실패 시 안전한 fallback 정책을 정의한다
    - 최소 fallback: console-only logging
    - fallback 발생 시 경고를 한 번만 남긴다
  - `setup_logging()`에서 listener 시작과 종료 훅을 관리한다
  - queue 사용 여부가 summary/audit 파일 쓰기와 충돌하지 않게 종료 순서를 정의한다
  - _Requirements: 0.5, 2.1, 2.3, 9.1_

- [ ] 6. Console renderer와 JSONL renderer를 같은 event dict 위에 구현
  - `HumanConsoleFormatter`를 구현해 one-line human-readable 형식을 고정한다
  - `JsonlFormatter`를 구현해 line-delimited JSON을 출력한다
  - 같은 canonical event dict를 두 formatter가 공유하도록 구현한다
  - console용 message와 JSONL용 payload를 별도 생성하지 않고, 하나의 canonical event dict를 renderer별로만 직렬화하도록 강제한다
  - 콘솔에는 핵심 필드만, JSONL에는 전체 구조화 필드를 남긴다
  - `attributes` payload가 커질 때 console과 JSONL의 표시량 차이를 둘 수 있도록 limit 정책을 분리한다
  - UTF-8과 append-only 쓰기 조건을 보장한다
  - _Requirements: 2.4, 2.6, 2.7, 2.8, 2.9, 3.1, 3.3_

- [ ] 7. 민감정보 redaction과 payload truncation을 공통 filter/helper로 구현
  - API key, OAuth token, bearer token, Gmail credentials, account identifier를 mask하는 redaction filter를 구현한다
  - dict/list/string payload에 재귀적으로 적용되도록 만든다
  - 긴 문자열, 긴 리스트, 큰 dict에 대한 truncation 규칙을 helper로 구현한다
    - 문자열 길이 제한
    - 리스트 샘플 수 제한
    - dict key 수 제한
  - 잘림 여부와 `truncated_count` 같은 추적 가능 필드를 JSONL에 남긴다
  - `--print-brief`가 있어도 기본 로그 경로에 브리프 본문 전체가 기록되지 않도록 검증한다
  - _Requirements: 3.6, 3.7, 7.1, 7.2, 7.3, 9.2_

- [ ] 8. `PipelineObserver`를 summary/audit 중심으로 재정의하고 stdout 직접 출력 제거 순서를 고정
  - `src/morning_brief/observability.py:138`의 `_emit()` 직접 `print(json.dumps(...))` 경로를 제거하는 단계를 설계한다
  - 1차 단계에서는 `_emit()`이 canonical logger를 호출하도록 바꾸고, `self.events` 적재는 유지한다
  - `log_event()`와 `record_provider_usage()`가 canonical schema를 통과하도록 바꾼다
  - `write_outputs()`는 계속 `pipeline-run-<run_id>.json`와 `perplexity-audit-<run_id>.json`를 생성하되, 새 `app-events-<run_id>.jsonl`와 같은 `run_id`를 공유하게 한다
  - observer summary 책임(phase duration, provider usage, anomaly, cache 상태)은 유지하고, 출력 책임만 canonical logging layer로 이동한다
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.2_

- [ ] 9. GitHub Actions wrapper와 app 로그를 `Run pipeline` step에서 논리적으로 분리
  - `.github/workflows/morning-brief.yml:116`의 `tee run.log` 구조는 유지하되, wrapper와 app 로그를 구분하는 규칙을 정의한다
  - 최소한 다음 중 하나를 구현한다
    - wrapper line prefix (`[workflow]`, `[app]`)
    - app 전용 group marker
    - app JSONL artifact를 triage 기준으로 명시하고 `run.log` 안에서는 console formatter prefix를 고정
  - `Pipeline attempt 1/2`, shell echo, env 복원 로그는 wrapper 로그로 남기고, 앱이 찍는 로그는 console renderer 규칙만 따르게 한다
  - artifact 업로드 경로에 `app-events-*.jsonl`를 추가한다
  - `run.log`와 app JSONL을 같이 봤을 때 wrapper/app 로그 경계가 명확히 드러나게 한다
  - _Requirements: 2.2, 2.3, 6.1, Constraints_

- [ ] 10. 최종 stdout summary 계약을 단일 event로 명시하고 중복 없이 한 번만 출력
  - `run.complete` 또는 동등한 final summary event를 canonical taxonomy에 추가한다
  - 이 이벤트는 파이프라인 성공/실패 모두에서 정확히 1회만 stdout에 출력되게 한다
  - 출력 위치를 하나로 고정한다
    - 권장: `observer.write_outputs()` 직전 또는 직후 단일 경로
  - stdout summary, `pipeline-run-<run_id>.json` summary, `provider_usage_summary`/`pipeline_summary` 값의 일관성을 검증한다
  - `run.log`에서 사람이 마지막 한 블록만 읽어도 `status`, `run_id`, `phase durations`, `provider usage`, `artifact path`를 알 수 있게 한다
  - _Requirements: 4.5, 6.3_

- [ ] 11. 모든 `logger` 레벨 호출을 canonical logging layer 위에 올리도록 모듈별로 마이그레이션

  - [ ] 11.1 핵심 파이프라인 모듈
    - `src/morning_brief/pipeline.py`
    - `src/morning_brief/briefing.py`
    - `src/morning_brief/brief_review.py`
    - `src/morning_brief/public_site.py`
    - `src/morning_brief/research_backfill.py`
    - 현재 `debug/info/warning/error/exception` 호출을 event taxonomy에 맞게 정리한다
    - observer event와 같은 사실을 두 번 말하는 메시지는 canonical event 하나로 합친다
    - _Requirements: 3.4, 3.5, 4.1, 5.2_

  - [ ] 11.2 뉴스/시장 집계 모듈
    - `src/morning_brief/data/news.py`
    - `src/morning_brief/data/market.py`
    - selection/filter/fallback/cache 관련 로그를 공통 필드 집합으로 통일한다
    - `candidate_count`, `kept_count`, `dropped`, `reason`, `provider breakdown`를 비교 가능한 구조로 만든다
    - _Requirements: 4.3, 5.2, 8.1_

  - [ ] 11.3 provider adapter 전 모듈
    - `src/morning_brief/data/sources/perplexity_search.py`
    - `src/morning_brief/data/sources/perplexity_sonar.py`
    - `src/morning_brief/data/sources/grok_x_keyword.py`
    - `src/morning_brief/data/sources/grok_official_signals.py`
    - `src/morning_brief/data/sources/grok_web_search.py`
    - `src/morning_brief/data/sources/gemini_grounding.py`
    - `src/morning_brief/data/sources/btc_etf_official.py`
    - `src/morning_brief/data/sources/google_news_rss.py`
    - `src/morning_brief/data/sources/http_client.py`
    - `src/morning_brief/data/sources/dynamic_registry_updater.py`
    - `src/morning_brief/data/sources/fred.py`
    - provider request/response/retry/failure/usage 로그를 동일 schema와 severity 규칙으로 맞춘다
    - 현재 로그 호출이 없는 adapter도 logger namespace, context injection, future-safe formatter 경로를 공유하도록 포함한다
    - 모든 `warning/error/exception`이 `error_type`, `reason`, `retryable`, `attempt`를 채우게 한다
    - _Requirements: 1.6, 4.4, 5.5, 5.6_

  - [ ] 11.4 이메일/출력/스케줄러 모듈
    - `src/morning_brief/emailer.py`
    - `src/morning_brief/unified_output.py`
    - `src/morning_brief/scheduler.py`
    - 메일 발송, 스케줄러 실행, narrative 파싱 실패의 `warning/info/exception`을 taxonomy에 맞게 정리한다
    - 본문/메일 전문이 로그에 남지 않도록 redaction/truncation 규칙을 적용한다
    - _Requirements: 1.6, 7.3, 8.1_

  - [ ] 11.5 레벨별 회귀 보장
    - `debug`, `info`, `warning`, `error`, `exception`, `critical` 전 레벨이 모두 canonical layer를 통과하는지 테스트로 고정한다
    - 현재 프로젝트에는 `logger.critical()` 호출이 0건이므로, 억지 callsite를 추가하지 말고 infrastructure와 테스트에서 `critical` 지원만 보장한다
    - `logger.exception()`은 stacktrace를 JSONL에만 남기고 console은 한 줄 요약을 유지하는지 확인한다
    - _Requirements: 1.7, 8.1, 10.2_

- [ ] 12. JSONL artifact와 observability summary를 연결하고 source of truth 전환 단계를 문서화
  - `outputs/observability/app-events-<run_id>.jsonl`를 생성하고 artifact 업로드에 포함한다
  - `pipeline-run-<run_id>.json` summary 안에 새 JSONL path 또는 run_id linkage를 넣는다
  - 운영 문서에는 source of truth를 단계별로 적는다
    - 현재 단계: `run.log` + summary 병행
    - 전환 단계: `app-events-*.jsonl` 우선, `run.log` 보조
  - `run.log`가 완전히 대체되기 전까지 운영자 triage 순서를 문서화한다
  - _Requirements: 2.5, 6.2, 10.3_

- [ ] 13. 테스트 작성

  - [ ] 13.1 logging setup / config 단위 테스트
    - `dictConfig()` 기반 설정이 root/app/third-party 정책을 올바르게 구성하는지 검증
    - `propagate`, `disable_existing_loggers`, level override가 의도대로 적용되는지 확인
    - _Requirements: 0.1, 0.2, 5.5, 5.6_

  - [ ] 13.2 contextvars 주입 테스트
    - `run_id`, `phase`, `provider`, `attempt`가 logger payload 없이 자동 포함되는지 검증
    - phase/provider 전환 후 reset이 누락되지 않는지 확인
    - _Requirements: 0.3, 0.4, 1.3, 1.4_

  - [ ] 13.3 formatter / schema 테스트
    - console formatter가 one-line human-readable 형식을 유지하는지 확인
    - JSONL formatter가 필수 필드를 모두 포함하는지 확인
    - severity_text / severity_number 매핑 검증
    - 같은 입력 canonical event에서 console formatter와 JSONL formatter가 같은 핵심 필드 값을 공유하는지 확인
    - _Requirements: 1.2, 1.8, 2.7, 2.8, 3.1, 3.2_

  - [ ] 13.4 redaction / truncation 테스트
    - 시크릿 값이 마스킹되는지 확인
    - 긴 문자열, 리스트, dict가 규칙대로 잘리고 `truncated_count` 등이 남는지 확인
    - `--print-brief` 경로에서도 기본 로그에 본문 전체가 남지 않는지 확인
    - _Requirements: 3.6, 3.7, 7.1, 7.2, 7.3_

  - [ ] 13.5 observer 통합 테스트
    - `observer.log_event()`가 canonical logger를 통과하는지 확인
    - `observer.record_provider_usage()`와 summary 집계가 같은 값으로 맞는지 확인
    - 기존 `pipeline-run-*.json`, `perplexity-audit-*.json` 하위 호환 유지 확인
    - _Requirements: 4.4, 5.2, 5.3, 5.4_

  - [ ] 13.6 final summary 단일 출력 테스트
    - 성공/실패 각각에서 final stdout summary가 정확히 한 번만 나오는지 확인
    - stdout summary와 `pipeline-run-*.json` summary의 값이 동일한지 확인
    - _Requirements: 4.5, 6.3_

  - [ ] 13.7 GitHub Actions artifact / wrapper 구분 테스트
    - `run.log`와 `app-events-*.jsonl`가 함께 생성되는지 확인
    - wrapper 로그와 app 로그를 논리적으로 구분할 수 있는지 확인
    - _Requirements: 2.2, 2.3, 6.1_

  - [ ] 13.8 전체 회귀 테스트
    - 최소한 `make lint`, `make test`, `make typecheck`를 통과한다
    - observability 관련 기존 테스트가 새 구조에서도 깨지지 않는지 확인
    - _Requirements: 10.2, Constraints_

  - [ ] 13.9 로컬/CI 구조 동등성 테스트
    - 로컬 실행에서 생성한 console/JSONL/summary 구조와 GitHub Actions `Run pipeline` step에서 생성한 구조가 같은 필드 체계를 갖는지 확인
    - 최소한 `run_id`, `phase`, `provider`, `event`, `severity`, `message`, `attributes` 필드가 로컬/CI 모두 동일한 규칙으로 직렬화되는지 fixture 또는 통합 테스트로 고정한다
    - _Requirements: 8.2_

  - [ ] 13.10 프로젝트 전체 로그 surface 스캔 테스트
    - 저장소 전체를 스캔해 `logger.*`, `logging.getLogger(__name__)`, `observer.*`, runtime `print(...)` 사용 파일 목록을 만든다
    - in-scope 파일과 out-of-scope 파일(`generate_gmail_token.py`, test fixtures, `main.py --print-brief`)을 명시적으로 분리한다
    - 새 runtime 모듈이 로깅 표면을 추가하면 allowlist/denylist 검증이 실패하도록 고정해, 이후 로깅 통합 대상 누락이 생기지 않게 한다
    - _Requirements: 5.1, 8.1, 10.2_

- [ ] 14. 운영 문서 작성 및 마이그레이션 가이드 정리
  - 로그를 어디서 봐야 하는지 source of truth 우선순위를 문서화한다
  - `run.log`, `app-events-*.jsonl`, `pipeline-run-*.json`, `perplexity-audit-*.json`의 역할을 구분해 적는다
  - wrapper/app 구분 규칙, final summary 읽는 방법, provider usage 확인 방법을 문서화한다
  - OpenTelemetry 연동은 즉시 구현이 아니라 future-compatible 목표임을 명시한다
  - _Requirements: 6.2, 8.3, 10.3_
