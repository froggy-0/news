---
name: brief-ops-app
description: Plan or scaffold a ChatGPT Apps SDK operator console for Morning Market Brief. Use with openai-docs and chatgpt-apps when exposing run summaries, provider health, audit logs, or mail previews in an internal UI.
---

1. 이 프로젝트의 Apps SDK UI는 read-only 운영 콘솔을 기본으로 잡습니다.
2. 툴은 `latest_run`, `run_summary`, `provider_usage`, `perplexity_audit`, `brief_preview`, `mail_preview`처럼 intent별로 나눕니다.
3. 저장 구조는 `apps/brief-ops/server`와 `apps/brief-ops/web`를 기본으로 봅니다.
4. model에 보일 작은 요약은 `structuredContent`, 큰 run artifact는 `_meta`로 분리합니다.
5. 기존 observability JSON과 브리핑 산출물을 재사용하고 UI 쪽에 비즈니스 규칙을 복제하지 않습니다.
6. 구현 전에는 global `openai-docs`, `chatgpt-apps` skill을 먼저 사용합니다.
