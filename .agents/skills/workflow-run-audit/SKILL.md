---
name: workflow-run-audit
description: Compare GitHub Actions runs, observability JSON, saved briefs, and raw mail sources. Use when the task is about finding where a mismatch first appeared between pipeline logs, downloaded artifacts, markdown briefs, and sent email output.
---

1. run id, observability JSON, 저장 브리핑, 메일 원문을 같은 실행인지 먼저 맞춥니다.
2. `generation -> review -> fallback -> save -> email` 순서로 첫 번째 분기 지점을 찾습니다.
3. copied snippet보다 `gh run download`, `outputs/observability`, `.eml` 원문을 우선 봅니다.
4. markdown 본문 문제와 이메일 템플릿 문제를 섞지 않습니다.
5. 원인 보고는 `어디서 처음 깨졌는지`를 파일과 이벤트 기준으로 적습니다.
