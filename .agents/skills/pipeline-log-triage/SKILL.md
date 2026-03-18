---
name: pipeline-log-triage
description: Analyze Morning Market Brief pipeline failures or degraded runs. Use when the task involves GitHub Actions logs, observability JSON, provider errors, cache misses, fallback behavior, or phase regressions.
---

1. 시작은 항상 실패 단계와 이벤트 이름부터 좁힙니다.
2. 가능하면 `gh run view --log-failed`, `outputs/observability/pipeline-run-*.json`, `outputs/observability/perplexity-audit-*.json`을 우선 봅니다.
3. 원인을 아래 4가지로 분리해서 판단합니다.
   - provider 요청 실패
   - parser/filter 실패
   - ranking/fallback 실패
   - brief/review/fallback 구조 실패
4. 로그 이벤트를 실제 코드 경로와 연결하고, 가장 작은 수정안을 먼저 제안하거나 구현합니다.
5. `src/morning_brief/data/`를 바꾸면 관련 pytest를 같이 수정합니다.
6. 외부 계약이 개입되면 공식 문서를 먼저 확인하고, 그 뒤에 코드 수정과 파이프라인 재실행 순으로 진행합니다.
