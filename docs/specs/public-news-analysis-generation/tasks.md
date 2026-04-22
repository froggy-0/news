# Implementation Plan: Public News Analysis Generation

## Overview

구현은 `공개 기사형 뉴스 선택 -> 기사 해설 생성 -> public_context 반영 -> public_site 직렬화 보정` 순서로 진행한다. 먼저 생성 모듈과 프롬프트/설정을 추가하고, 그 다음 `build_news_packet()`에 통합한 뒤, 마지막으로 `build_public_brief()`가 생성 결과를 일관되게 소비하도록 정리한다.

완료: 2026-03-29 Asia/Seoul

## Tasks

- [x] 1. 공개 뉴스 해설 생성 기반 추가
  - [x] 1.1 `Settings`와 프롬프트 렌더링 경로를 추가한다
    - `src/morning_brief/config.py`에 `openai_public_news_analysis_enabled`, `openai_public_news_analysis_model`을 추가한다.
    - `src/morning_brief/prompting.py`에 `render_public_news_analysis_prompts()`를 추가한다.
    - `src/morning_brief/prompts/public_news_analysis_instructions.j2`, `src/morning_brief/prompts/public_news_analysis_input.j2`를 추가한다.
    - _Requirements: 2, 8, 9_
  - [x] 1.2 `src/morning_brief/public_news_analysis.py`를 추가한다
    - `PublicNewsAnalysisInput`, `PublicNewsAnalysisOutput`, `PublicNewsAnalysisAudit`를 정의한다.
    - `enrich_public_news_packet()`에서 packet dict를 입력으로 받아 OpenAI Responses API 배치 호출, JSON schema 파싱, placeholder 필터링, audit 집계를 구현한다.
    - `build_prompt_cache_key()`와 `usage_snapshot()`을 재사용해 provider usage와 캐시 키 구성을 맞춘다.
    - _Requirements: 1, 2, 3, 4, 5, 9, 10_
  - [x] 1.3 생성 모듈 단위 테스트를 작성한다
    - **Property 1: 유효한 생성 결과만 packet에 병합된다**
    - 테스트 파일: `tests/test_public_news_analysis.py`
    - 정상 응답, partial failure, invalid JSON, placeholder 출력, disabled/no_api_key skip 케이스를 검증한다.
    - **Validates: Requirements 1, 3, 4, 5, 9, 10**

- [x] 2. 공개 뉴스 선택 경로에 해설 생성 단계를 통합한다
  - [x] 2.1 `build_news_packet()`에 공개 기사형 뉴스 enrich 단계를 삽입한다
    - `src/morning_brief/data/news.py`에서 `filter_public_article_news()` 이후 `_news_items_to_packet(publish_news_items)` 결과를 `enrich_public_news_packet()`으로 넘긴다.
    - enrich된 packet을 `public_context["featured_news"]`, `public_context["all_news"]`에 사용한다.
    - _Requirements: 1, 6, 7, 8, 9_
  - [x] 2.2 공개 news packet 내부 확장 필드를 허용한다
    - `src/morning_brief/data/news_packet.py`에서 `news_items_to_packet()` 결과에 `summary_ko`, `interpretation_ko` 선택 필드를 실을 수 있도록 정리한다.
    - `packet_item_to_news_item()`은 새 내부 필드를 무시해 기존 공용 경로와 호환되도록 유지한다.
    - _Requirements: 6, 8_
  - [x] 2.3 공개 뉴스 selection 통합 테스트를 작성한다
    - **Property 2: 공개 기사형 뉴스만 enrich되고 email 경로는 유지된다**
    - 테스트 파일: `tests/test_news_quality.py`
    - `build_news_packet()` 결과의 `public_context["all_news"]`에만 생성 필드가 반영되고, `email_ranked_items` 및 X 시그널 경로는 유지되는지 검증한다.
    - **Validates: Requirements 1, 6, 7, 8, 9**

- [x] 3. public_site 직렬화와 최종 필터를 보정한다
  - [x] 3.1 `_news_items()`와 `_news_items_v2()`가 생성 필드를 우선 사용하도록 수정한다
    - `src/morning_brief/public_site.py`에서 `summary_ko`, `interpretation_ko`를 우선 읽고, 기존 `summary`, `why_it_matters`는 fallback으로만 사용한다.
    - `summaryKo`와 `interpretation`이 동일 값으로 내려가던 현재 경로를 분리한다.
    - _Requirements: 3, 4, 6_
  - [x] 3.2 `featuredNews`와 `allNews`에 동일한 최종 display filter를 적용한다
    - `build_public_brief()`에서 최종 `all_news`를 먼저 `_filter_public_news_for_display()`로 정제한 뒤 `featuredNews`, `allNews` 둘 다 같은 정제 결과를 사용하게 한다.
    - placeholder 또는 비어 있는 해설이 공개 JSON에 남지 않도록 한다.
    - _Requirements: 5, 6, 7, 10_
  - [x] 3.3 public JSON 직렬화 테스트를 작성한다
    - **Property 3: UnifiedOutput 경로와 direct public_context 경로가 같은 해설 결과를 직렬화한다**
    - 테스트 파일: `tests/test_public_site.py`
    - `summary_ko`, `interpretation_ko` 우선 적용, `allNews`/`featuredNews` 동시 필터링, 축소 유지, unified 경로 반영을 검증한다.
    - **Validates: Requirements 4, 5, 6, 7, 10**

- [x] 4. Checkpoint - 공개 뉴스 생성/직렬화 경로 검증
  - [x] 4.1 좁은 범위 테스트를 먼저 실행한다
    - `uv run pytest tests/test_public_news_analysis.py tests/test_news_quality.py tests/test_public_site.py -q`
    - 실패 시 생성 모듈, selection 통합, 직렬화 보정 중 어느 단계에서 깨졌는지 먼저 분리한다.
    - _Requirements: 10_

- [x] 5. 기존 경로 회귀 방지와 운영 문서를 정리한다
  - [x] 5.1 `research_backfill`과 일반 publish filter 비의존성을 검증한다
    - `tests/test_research_backfill.py`에 공개 뉴스 해설 생성 단계가 연구 백필 경로를 건드리지 않는 회귀 테스트를 추가한다.
    - 필요 시 `filter_publish_news()` 일반 경로가 새 public-only 생성 단계에 의존하지 않는 것도 함께 검증한다.
    - _Requirements: 8, 10_
  - [x] 5.2 새 설정과 운영 영향 범위를 문서에 반영한다
    - 동작/설정 변경이므로 `README.md` 또는 가장 가까운 문서에 새 설정(`openai_public_news_analysis_enabled`, `openai_public_news_analysis_model`)과 공개 뉴스 해설 생성 단계의 목적을 간단히 기록한다.
    - _Requirements: 8, 9, 10_
  - [x] 5.3 최종 회귀 테스트를 실행한다
    - `uv run pytest tests/test_public_news_analysis.py tests/test_news_quality.py tests/test_public_site.py tests/test_research_backfill.py -q`
    - `uv run ruff check src/morning_brief/public_news_analysis.py src/morning_brief/data/news.py src/morning_brief/public_site.py src/morning_brief/prompting.py src/morning_brief/config.py tests/test_public_news_analysis.py tests/test_news_quality.py tests/test_public_site.py tests/test_research_backfill.py`
    - **Validates: Requirements 1, 2, 3, 4, 5, 6, 7, 8, 9, 10**

- [x] 6. Checkpoint - 전체 완료 상태 기록
  - [x] 6.1 모든 태스크 완료 후 상태를 문서에 반영한다
    - 완료한 체크박스를 `[x]`로 갱신한다.
    - 구현 중 조정된 범위가 있으면 `design.md`와 정합성만 다시 확인한다.
    - 최종 완료 시점은 tasks 문서 Overview 또는 하단 메모에 기록한다.
    - _Requirements: 10_
