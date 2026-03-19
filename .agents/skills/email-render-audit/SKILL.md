---
name: email-render-audit
description: Compare generated markdown, email context assembly, templates, and raw MIME output. Use when the task is about truncation, duplicate rendering, source formatting, localization drift, or HTML/plain-text mismatch.
---

1. MIME는 raw text가 아니라 디코딩 후 판단합니다.
2. 브리핑 생성 문제와 이메일 렌더링 문제를 분리합니다.
3. `brief markdown -> email context -> html/txt template -> sent mail` 순서로 비교합니다.
4. missing content가 저장 전인지 렌더링 후인지 먼저 확인합니다.
5. 사용자 노출 텍스트는 한국어 기준으로 보고, 원시 URL 노출은 의도된 섹션에서만 허용합니다.
