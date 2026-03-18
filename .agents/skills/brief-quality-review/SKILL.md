---
name: brief-quality-review
description: Review or improve the generated market brief, validator, rewrite loop, and email rendering. Use when the task is about prompt quality, structure mismatches, readability, or brief_fallback behavior.
---

1. `prompt -> generation -> review -> rewrite -> final structure check -> email render` 순서로 흐름을 봅니다.
2. 생성 품질 문제와 구조 파서 문제를 분리해서 판단합니다.
3. review 통과 기준과 final fallback 기준이 다르면 계약부터 맞춥니다.
4. 읽기 품질, 숫자-해석 일치, 한국어 구조, fallback 조건을 테스트로 고정합니다.
5. 코드 리뷰 답변은 findings 우선으로 작성합니다.
