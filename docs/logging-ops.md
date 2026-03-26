# Logging Ops

## Source Of Truth

현재 앱 로그의 기준 산출물은 아래 순서로 봅니다.

1. `outputs/observability/app-events-<run_id>.jsonl`
2. `outputs/observability/pipeline-run-<run_id>.json`
3. `outputs/observability/perplexity-audit-<run_id>.json`
4. `run.log`

`run.log`는 GitHub Actions wrapper 출력과 사람이 읽는 콘솔 렌더러가 함께 섞인 보조 로그입니다. 앱 구조화 로그의 기준은 `app-events-<run_id>.jsonl`입니다.

## GitHub Actions

`Morning Market Brief`의 `Run pipeline` step에서는 wrapper 출력이 `[workflow]` prefix로 시작합니다.

- `[workflow] ...`
  - shell wrapper, retry, failure banner
- prefix 없음
  - 앱 console renderer 출력

운영자는 `run.log`에서 먼저 wrapper/app 경계를 확인하고, 실제 세부 내용은 JSONL artifact로 내려가 확인합니다.

## Final Summary

run 종료 시 final summary는 canonical `run.complete` event로 stdout에 한 번만 출력됩니다.

필수 확인 항목:
- `run_id`
- `status`
- `total_duration_ms`
- `provider_usage_line`
- `app_events_path`
- `pipeline_run_path`
- `perplexity_audit_path`

`pipeline-run-<run_id>.json`의 `summary`와 final stdout summary는 같은 핵심 값을 공유해야 합니다.

## Backward Compatibility

기존 산출물은 유지합니다.

- `pipeline-run-<run_id>.json`
- `perplexity-audit-<run_id>.json`

새 구조는 위 산출물 위에 `app-events-<run_id>.jsonl`를 추가하는 방식입니다.
