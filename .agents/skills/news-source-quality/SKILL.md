---
name: news-source-quality
description: Audit Perplexity, Sonar, Grok, RSS, and ranking quality before changing prompts or email rendering. Use when the task is about domain drift, language filtering, file-like titles, topic coverage, or news fallback quality.
---

1. query 품질, provider 응답, post-filter, ranking, fallback을 분리해서 봅니다.
2. URL, title, domain, language, file-like path(`.htm`, `.pdf`)를 먼저 점검합니다.
3. user-facing 뉴스는 citation 파일명보다 실제 기사 제목과 도메인을 우선합니다.
4. `src/morning_brief/data/` 필터를 바꾸면 관련 pytest를 같이 갱신합니다.
5. 토픽별로 무엇이 살아남았고 무엇이 버려졌는지 이유를 남깁니다.
