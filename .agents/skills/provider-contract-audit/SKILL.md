---
name: provider-contract-audit
description: Audit provider adapters and external data contracts. Use when changing or debugging fallback, retry, ranking, parser, or structured-response behavior under src/morning_brief/data/.
---

1. `src/morning_brief/data/AGENTS.md`와 관련 테스트를 먼저 읽습니다.
2. 공급자 문제를 아래 경계로 나눕니다.
   - 요청 계약
   - 재시도/쿼터/회로 차단
   - 응답 파싱
   - 랭킹/품질 평가
   - fallback 병합
3. warning 로그는 운영자가 후속 조치를 할 수 있게 남깁니다.
4. 전체 실패보다 부분 성공을 우선하는 현재 설계를 유지합니다.
5. provider 정책을 바꿀 때는 테스트와 문서를 함께 갱신합니다.
