# Implementation Plan: Public News Article Selection

## Overview

이 버그픽스는 공개 브리프의 뉴스/X 경계를 다시 세우는 작업이다. 구현은 `news_selection.py`에 공개 기사형 뉴스 전용 필터를 추가하고, `build_news_packet()`의 공개 뉴스 선택 경로만 그 필터로 교체한 뒤, `public_site.py`의 placeholder 방어선과 회귀 테스트를 정리하는 순서로 진행한다.

완료: 2026-03-29 Asia/Seoul

## Tasks

- [x] 1. 공개 기사형 뉴스 전용 필터를 추가한다
  - [x] 1.1 `/Users/giwon/code/news/src/morning_brief/data/news_selection.py`에 공개 뉴스 전용 helper를 추가한다
    - `@handle` source 여부를 판정하는 helper를 추가한다
    - `x.com/twitter.com` URL 여부를 판정하는 helper를 추가한다
    - `why_it_matters` 또는 `summary`가 비어 있거나 placeholder인지 판정하는 helper를 추가한다
    - _Requirements: Expected Behavior 2, 3_
  - [x] 1.2 `/Users/giwon/code/news/src/morning_brief/data/news_selection.py`에 공개 기사형 뉴스 전용 필터 함수를 구현한다
    - `filter_public_article_news_candidates()`를 추가해 기사형이 아닌 후보를 초기에 제외한다
    - `filter_public_article_news()`를 추가해 기존 품질 규칙을 적용하되, 기본 동작은 축소된 기사형 뉴스 목록을 허용하도록 `min_items=0`으로 둔다
    - dropped reason에 `x_handle_source`, `x_domain_url`, `missing_public_interpretation`, `placeholder_public_interpretation`를 기록한다
    - _Requirements: Expected Behavior 1, 2, 3, 4, 5, 6; Unchanged Behavior 1_
  - [x] 1.3 공개 뉴스 전용 필터 단위 테스트를 추가한다
    - `tests/test_news_quality.py`에 `@handle` source 제외 케이스를 추가한다
    - `tests/test_news_quality.py`에 `x.com/twitter.com` URL 제외 케이스를 추가한다
    - `tests/test_news_quality.py`에 placeholder interpretation 제외 케이스를 추가한다
    - `tests/test_news_quality.py`에 기사형 뉴스가 1~2개만 남아도 결과를 전부 비우지 않는 케이스를 추가한다
    - `tests/test_news_quality.py`에 정상 기사형 뉴스 유지 케이스를 추가한다
    - _Requirements: Expected Behavior 1, 2, 3, 4, 5, 6; Unchanged Behavior 1_

- [x] 2. 공개 뉴스 선택 경로를 새 필터로 교체한다
  - [x] 2.1 `/Users/giwon/code/news/src/morning_brief/data/news.py`의 공개 뉴스 선택 경로를 교체한다
    - `filter_publish_news_candidates()` 대신 `filter_public_article_news_candidates()`를 사용한다
    - `filter_publish_news()` 대신 `filter_public_article_news()`를 사용한다
    - 이메일용 `email_ranked_items`와 X 시그널 선택 경로는 유지한다
    - _Requirements: Expected Behavior 1, 2, 3, 4, 5; Unchanged Behavior 2, 3_
  - [x] 2.2 observer/logging과 source count가 새 공개 뉴스 결과를 반영하게 유지한다
    - `public_publish_news_selection` audit가 새 dropped reason을 기록하는지 확인한다
    - `public_context["source_counts"]`가 필터 적용 후 개수를 반영하는지 확인한다
    - _Requirements: Expected Behavior 1, 2, 3; Unchanged Behavior 3_
  - [x] 2.3 파이프라인 레벨 회귀 테스트를 추가한다
    - `tests/test_news_quality.py` 또는 가장 가까운 테스트에 `x_news`가 후보군에는 있어도 공개 뉴스에는 남지 않는 케이스를 추가한다
    - `featuredXSignals/allXSignals`는 그대로 유지되는 케이스를 함께 검증한다
    - `public_context["all_news"]`가 기사형 뉴스만 포함하고 개수 축소를 허용하는지 검증한다
    - _Requirements: Expected Behavior 2, 4, 5, 6; Unchanged Behavior 2, 3_

- [x] 3. Checkpoint - 공개 뉴스 선택 경계 복원
  - `news_selection.py`의 새 필터가 공개 뉴스에서 X성 항목을 제외하고, `build_news_packet()`이 이를 실제 `public_context["featured_news"]`, `public_context["all_news"]`에 반영해야 한다
  - 권장 검증:
    - `cd /Users/giwon/code/news && pytest /Users/giwon/code/news/tests/test_news_quality.py -q`

- [x] 4. 공개 직렬화 단계의 placeholder 방어선을 정리한다
  - [x] 4.1 `/Users/giwon/code/news/src/morning_brief/public_site.py`의 `_best_korean_text()` placeholder 목록을 유지/정리한다
    - 이미 추가한 `"해당 없음"` 계열이 최종 방어선으로 계속 동작하는지 확인한다
    - 선택 계층에서 걸러지지 않은 placeholder가 있어도 공개 JSON에서 다시 제거되는지 확인한다
    - _Requirements: Expected Behavior 3_
  - [x] 4.2 `/Users/giwon/code/news/src/morning_brief/public_site.py`의 `_filter_public_news_for_display()`가 빈 해설을 다시 노출하지 않도록 검증한다
    - `summaryKo`와 `interpretation`가 모두 무의미하면 featured/public 노출에서 제거되는지 확인한다
    - 기존 한국어 title/summary 정규화 동작은 유지한다
    - _Requirements: Expected Behavior 3; Unchanged Behavior 1, 3_
  - [x] 4.3 공개 사이트 회귀 테스트를 추가한다
    - `tests/test_public_site.py`에 placeholder 해설이 featured/public 뉴스에서 제거되는 케이스를 추가한다
    - `tests/test_public_site.py`에 기사형 뉴스는 여전히 `featuredNews/allNews`에 노출되는 케이스를 유지한다
    - `tests/test_public_site.py`에 `featuredXSignals/allXSignals`가 계속 생성되는 케이스를 추가하거나 보강한다
    - `tests/test_public_site.py`에 `UnifiedOutput` 입력 경로에서도 같은 필터링 결과가 유지되는 케이스를 추가한다
    - _Requirements: Expected Behavior 3, 5, 6; Unchanged Behavior 1, 2, 3_

- [x] 5. 연구/백필 경로 회귀를 확인한다
  - [x] 5.1 공개 뉴스 전용 필터 추가가 연구/백필 경로에 영향을 주지 않게 확인한다
    - `research_backfill.py`가 기존 `filter_publish_news_candidates()` 의미를 계속 사용하도록 유지한다
    - 공개 뉴스 전용 정책이 내부 연구 품질 점검 로직을 바꾸지 않는지 검증한다
    - _Requirements: Unchanged Behavior 1, 2, 3_
  - [x] 5.2 회귀 방지 테스트를 추가한다
    - `tests/test_research_backfill.py` 또는 가장 가까운 테스트에 공개 뉴스 전용 필터 도입 후에도 기존 backfill 판단이 유지되는 케이스를 추가한다
    - _Requirements: Unchanged Behavior 1, 3_

- [x] 6. Checkpoint - 공개 JSON 계약과 X 시그널 경로 보존
  - `featuredNews/allNews`는 기사형 뉴스만 우선 담고, 기사 수가 부족할 때는 개수를 줄여서 유지해야 한다
  - `featuredXSignals/allXSignals`는 기존 구조와 의미를 유지해야 한다
  - 권장 검증:
    - `cd /Users/giwon/code/news && pytest /Users/giwon/code/news/tests/test_public_site.py -q`
    - `cd /Users/giwon/code/news && pytest /Users/giwon/code/news/tests/test_research_backfill.py -q`

- [x] 7. 최종 회귀 검증과 관찰성 정리
  - [x] 7.1 선택/직렬화/공개 출력 전체를 묶어 최종 검증한다
    - `test_news_quality.py`, `test_public_site.py`, `test_research_backfill.py`를 함께 실행한다
    - 가능하면 실제 공개 브리프 fixture 기준으로 `featuredNews`에 `@handle` source가 남지 않는지 확인한다
    - `UnifiedOutput -> build_public_brief()` 경로에서도 `featuredNews`에 `@handle` source가 남지 않는지 확인한다
    - _Requirements: Expected Behavior 1, 2, 3, 4, 5, 6; Unchanged Behavior 1, 2, 3_
  - [x] 7.2 audit reason과 결과 개수를 최종 점검한다
    - dropped reason이 예상대로 기록되는지 확인한다
    - 기사형 뉴스 부족 시 슬롯을 억지로 채우지 않는지 확인한다
    - _Requirements: Expected Behavior 2, 3, 4_

- [x] 8. Checkpoint - 버그픽스 완료 기준 확인
  - 공개 브리프의 `featuredNews/allNews`에는 기사형 뉴스만 우선 노출되고, 기사 수가 부족하면 축소된 개수로 유지되어야 한다
  - X 기반 항목은 `featuredXSignals/allXSignals`에 남아야 한다
  - `"해당 없음"` 계열 placeholder는 공개 뉴스 해설로 다시 노출되지 않아야 한다
  - 공개 JSON 계약과 기존 이메일/연구 백필 경로는 유지되어야 한다
  - 권장 검증:
    - `cd /Users/giwon/code/news && pytest /Users/giwon/code/news/tests/test_news_quality.py -q`
    - `cd /Users/giwon/code/news && pytest /Users/giwon/code/news/tests/test_public_site.py -q`
    - `cd /Users/giwon/code/news && pytest /Users/giwon/code/news/tests/test_research_backfill.py -q`
