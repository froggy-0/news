# Implementation Plan: data-ingestion-quality-improvement

## Overview

P0(R1, R2) → P1(R3, R4) → P2(R5, R6, R7) → P3(R8) 우선순위 순으로 진행한다. R1은 이후 모든 작업의 전제 조건이므로 가장 먼저 완료한다. 각 태스크는 구현 직후 테스트로 검증하며, `make check`(lint + test + typecheck) 통과를 Checkpoint 기준으로 삼는다.

완료 일시: 2026-04-04

---

## Tasks

### P0 — 데이터 모델 기반 작업

- [ ] 1. `providers.py` 신규 생성 — Provider 상수 단일 출처화
  - [ ] 1.1 `src/morning_brief/data/providers.py` 파일 생성
    - Data provenance 상수: `PERPLEXITY_SEARCH`, `PERPLEXITY_SONAR`, `GROK_OFFICIAL_X`, `GROK_X_KEYWORD`, `GROK_WEB_SEARCH`
    - Runtime circuit breaker 상수: `RUNTIME_GROK_KEYWORD = "grok_keyword"`
    - 집합 상수: `PERPLEXITY_PROVIDERS`, `GROK_PROVIDERS` (frozenset)
    - **stdlib/typing 전용** — 내부 모듈 임포트 금지 (circular import 방지)
    - _Requirements: 1.1, 1.2_
  - [ ] 1.2 기존 파일에서 provider 상수 제거 후 `providers` 임포트로 교체
    - `news_packet.py`: `OFFICIAL_SIGNAL_PROVIDER`, `GROK_PROVIDERS` 제거 → `providers.GROK_OFFICIAL_X`, `providers.GROK_PROVIDERS`
    - `news_selection.py`: `PERPLEXITY_PROVIDER`, `PERPLEXITY_SONAR_PROVIDER`, `GROK_KEYWORD_PROVIDER`, `GROK_WEB_PROVIDER`, `OFFICIAL_SIGNAL_PROVIDER` 제거 → `providers.*`
    - `data_quality.py`: `PERPLEXITY_PROVIDER`, `PERPLEXITY_SONAR_PROVIDER`, `GROK_X_KEYWORD_PROVIDER`, `OFFICIAL_SIGNAL_PROVIDER` 제거 → `providers.*`
    - `grok_x_keyword.py:32`: `GROK_KEYWORD_PROVIDER = "grok_keyword"` 제거 → `providers.RUNTIME_GROK_KEYWORD`
    - `prompting.py:92`: `"grok_official_x"` 리터럴 → `providers.GROK_OFFICIAL_X`
    - _Requirements: 1.1, 1.2_
  - [ ] 1.3 `tests/test_providers.py` 신규 작성
    - `providers.GROK_X_KEYWORD == "grok_x_keyword"` (grok_x_keyword.py:298 실제 값과 일치)
    - `providers.RUNTIME_GROK_KEYWORD == "grok_keyword"` (provider_runtime.py ProviderPolicy.name과 일치)
    - `providers.GROK_OFFICIAL_X == "grok_official_x"` (grok_official_signals.py:477 실제 값과 일치)
    - `import morning_brief.data.providers` 단독 실행 시 ImportError 없음 (circular import 없음)
    - _Requirements: 1.4_

- [ ] 2. Checkpoint 1 — `make check` 통과 확인
  - lint: provider 상수 리터럴이 `data/` 내부 파일에 남아있지 않음
  - test: 기존 provider 관련 테스트 회귀 없음
  - typecheck: `data_quality.py`, `market.py` mypy 통과

- [ ] 3. `NewsPacketItem` TypedDict 도입 — 뉴스 패킷 타입 경계 보존
  - [ ] 3.1 `news_packet.py`에 `NewsPacketItem(TypedDict)` 정의 추가
    - 필드: `title`, `url`, `source`, `published_at`, `domain`, `source_tier`, `preferred_source`, `age_hours`, `topic`, `provider`, `summary`, `why_it_matters`, `citations`, `official_source`
    - 타입: design.md Data Models 섹션 스키마 그대로 적용
    - _Requirements: 2.1_
  - [ ] 3.2 `news_items_to_packet` 반환 타입을 `list[NewsPacketItem]`으로 변경
    - 구현 로직 변경 없음, 반환 타입 어노테이션만 변경
    - _Requirements: 2.1_
  - [ ] 3.3 `data_quality.py`에서 typed access로 전환
    - `item.get("age_hours")` → `item["age_hours"]`
    - `item.get("domain")` → `item["domain"]`
    - `item.get("official_source")` → `item["official_source"]`
    - 기타 raw dict 접근 전체 점검
    - _Requirements: 2.2_
  - [ ] 3.4 `pyproject.toml` mypy `files` 목록에 추가
    - `src/morning_brief/data/providers.py` 추가
    - `src/morning_brief/data/news_packet.py` 추가
    - _Requirements: 2.2, 2.3_
  - [ ] 3.5 `tests/test_news_packet.py` 신규 또는 확장
    - `news_items_to_packet` 반환값이 `NewsPacketItem`의 모든 14개 키를 포함함을 검증
    - `published_at=None`인 `NewsItem` 변환 시 `age_hours`가 `None`임을 검증
    - `briefing.py`, `emailer.py`의 기존 `.get("key")` 접근 패턴이 런타임에 정상 동작함을 검증 (하위 호환)
    - _Requirements: 2.4_

- [ ] 4. Checkpoint 2 — `make check` 통과 확인
  - typecheck: `news_packet.py`, `providers.py` mypy strict 통과 (신규 추가 파일)
  - test: 기존 뉴스 패킷 소비 테스트 회귀 없음

---

### P1 — 관측성 강화 작업

- [ ] 5. 시장 포인트 캐시 TTL 및 staleness 경고
  - [ ] 5.1 `_save_market_point_cache`에 `_meta.cached_at` 추가
    - JSON 최상위에 `"_meta": {"cached_at": datetime.now(timezone.utc).isoformat()}` 삽입
    - 기존 per-point 직렬화 로직 변경 없음
    - _Requirements: 3.1_
  - [ ] 5.2 `_load_market_point_cache` 시그니처에 `max_age_hours` 파라미터 추가
    - `def _load_market_point_cache(cache_file: Path, *, max_age_hours: int = MARKET_POINT_CACHE_MAX_AGE_HOURS)`
    - `payload.pop("_meta", {})` 처리 후 staleness 체크
    - `age > max_age_hours` 시 `WARNING` 로그 (`event="cache.stale"`)
    - `_meta` 없는 기존 캐시는 staleness 판정 없이 기존대로 로드
    - _Requirements: 3.2, 3.3_
  - [ ] 5.3 `config.py` `Settings`에 `market_point_cache_max_age_hours: int` 필드 추가
    - `load_settings()`에 `_env_bounded_int("MARKET_POINT_CACHE_MAX_AGE_HOURS", default=26, minimum=4, maximum=72)` 추가
    - _Requirements: 3.5_
  - [ ] 5.4 `build_market_packet` 호출 경로에 `max_age_hours` 전달
    - `_load_market_point_cache(cache_file, max_age_hours=settings.market_point_cache_max_age_hours)`
    - `fetch_newsletter_display_data`는 settings 없으므로 기본값(`26`) 사용 — 이번 범위에서 변경 없음
    - _Requirements: 3.2_
  - [ ] 5.5 `tests/test_market_reliability.py` 확장
    - `_meta.cached_at`이 포함된 캐시 파일 저장 후 재로드 시 staleness 경고 발생 검증 (age > threshold)
    - `_meta` 없는 기존 포맷 캐시 파일 로드 시 WARNING 없이 정상 로드 검증 (하위 호환)
    - live fetch 성공 경로에서 staleness 경고 없음 검증
    - _Requirements: 3.2, 3.3, 3.4_

- [ ] 6. 시장 데이터 품질 지표 카테고리별 분리
  - [ ] 6.1 `_zero_ratio_by_category(packet: dict) -> dict[str, float]` 함수 신규 추가
    - 카테고리: `macro`(packet["macro"]), `indices`(packet["us_indices"]), `tech`(packet["tech_stocks"]), `bitcoin`([spot] + etf_points)
    - 빈 카테고리 → `0.0` (분모 0 방지)
    - docstring에 bitcoin etf_points 항상 `[]` 사실 명시 (build_market_packet 경로)
    - _Requirements: 4.1, 4.5_
  - [ ] 6.2 `_zero_ratio(packet: dict) -> float` 를 카테고리 최댓값 방식으로 변경
    - `return max(_zero_ratio_by_category(packet).values(), default=1.0)`
    - critical 임계값(`>= 0.8`) 유지
    - _Requirements: 4.2, 4.3_
  - [ ] 6.3 `assess_data_quality` 반환값에 `"zero_ratio_by_category"` 필드 추가
    - 기존 `"zero_price_ratio"` 키 유지 (하위 호환)
    - _Requirements: 4.1, 4.4_
  - [ ] 6.4 `tests/test_pipeline_quality.py` 확장
    - macro 전부 price=None, indices 정상인 패킷 → `zero_ratio_by_category["macro"] == 1.0`, `["indices"] == 0.0`
    - `zero_price_ratio == max(zero_ratio_by_category.values())` 검증
    - `assess_data_quality` 반환값에 `"zero_ratio_by_category"` 키 존재 검증
    - 기존 `"critical"` 판정 케이스가 변경 후에도 동일하게 판정됨을 검증 (회귀)
    - _Requirements: 4.1, 4.2, 4.3_

- [ ] 7. Checkpoint 3 — `make check` 통과 확인
  - test: `test_market_reliability.py`, `test_pipeline_quality.py` 신규 케이스 통과
  - typecheck: `market.py`, `data_quality.py` mypy strict 통과

---

### P2 — 데이터 품질 강화 작업

- [ ] 8. 뉴스 아이템 제목 기반 보조 dedup
  - [ ] 8.1 `_title_dedup_key(title: str) -> str` 헬퍼 함수 추가 (`news_selection.py`)
    - 소문자·공백 정규화 후 앞 40자 반환
    - 10자 미만이면 빈 문자열 반환 (보조 dedup 비활성화)
    - _Requirements: 5.1, 5.3_
  - [ ] 8.2 `_dedup_and_rank`에 `by_title` 보조 dedup 맵 추가
    - `by_url: dict[str, NewsItem]`, `by_title: dict[str, str]` (title_key → url_key) 두 맵 유지
    - 충돌 시 `_item_score` 높은 것 유지
    - `del by_url[existing_url_key]` 직후 반드시 `by_title[title_key] = url_key` 갱신 (동기화 불변식)
    - URL dedup은 기존대로 우선 적용
    - _Requirements: 5.1, 5.2, 5.4_
  - [ ] 8.3 `tests/test_news_quality.py` 확장
    - 동일 title[:40] + 다른 URL 2개 입력 → 1개만 반환, score 높은 것 유지
    - 다른 title + 동일 URL 입력 → 기존 URL dedup 동작 유지 (회귀)
    - title 9자 아이템은 보조 dedup 미적용 검증
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 9. XSignal 중복 제거
  - [ ] 9.1 `_dedup_x_signals(signals: list[XSignal]) -> list[XSignal]` 함수 추가 (`news.py`)
    - 복합 키: `f"{source_handle.lower()}:{headline[:30].lower().strip()}"`
    - 동일 키 충돌 시 `posted_at` 최신 것 유지, 동일하거나 None이면 기존 유지
    - `removed = len(signals) - len(seen)` 방식으로 카운트
    - removed > 0 이면 `DEBUG` 로그 (`event="dedup.applied"`, `provider="x_signal"`, `removed_count=N`)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ] 9.2 `build_news_packet`에서 `_cap_signals_by_topic` 호출 전에 `_dedup_x_signals` 적용
    - `_cap_signals_by_topic(_dedup_x_signals(x_signals), ...)` 로 래핑
    - _Requirements: 6.1_
  - [ ] 9.3 `tests/test_grok_x_keyword.py` 확장
    - 동일 handle + headline[:30] XSignal 2개 → posted_at 최신 것 1개 반환
    - 빈 입력 → 빈 출력, 예외 없음
    - removed 카운트 = `len(입력) - len(출력)` 정확도 검증
    - _Requirements: 6.1, 6.2, 6.4_

- [ ] 10. 다국어 meaningless interpretation 탐지 확장
  - [ ] 10.1 `_PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS` frozenset에 영어 패턴 추가 (`news_selection.py`)
    - 추가 패턴: `"n/a"`, `"na"`, `"none"`, `"null"`, `"unknown"`, `"no information"`, `"no comment"`, `"not available"`, `"no information available"`, `"no details available"`, `"–"`, `"-"`, `"..."`
    - _Requirements: 7.1, 7.4_
  - [ ] 10.2 `_has_meaningful_public_interpretation` 로직에 30자 미만 부분 매칭 추가
    - `len(normalized) < 30` 조건에서 `normalized.rstrip(".,;:")` 후 frozenset 재체크
    - _Requirements: 7.2_
  - [ ] 10.3 `tests/test_news_quality.py` 확장
    - `why_it_matters="N/A"` → `False`
    - `why_it_matters="none"` → `False`
    - `why_it_matters="no information"` → `False`
    - `why_it_matters="N/A."` → `False` (rstrip 후 매칭)
    - `why_it_matters="The Fed raised rates by 25bps"` → `True`
    - 기존 한국어 패턴 (`"없음"`, `"해당없음"`) → `False` (회귀)
    - _Requirements: 7.1, 7.2, 7.3_

- [ ] 11. Checkpoint 4 — `make check` 통과 확인
  - test: `test_news_quality.py`, `test_grok_x_keyword.py` 신규 케이스 통과
  - 기존 dedup, filter 관련 테스트 회귀 없음

---

### P3 — 설정 외부화 작업

- [ ] 12. 도메인 정책 YAML 외부화
  - [ ] 12.1 `requirements.txt`에 `PyYAML>=6.0` 추가
    - 현재 transitive dependency로만 존재 → 명시적 의존성으로 승격
    - _Requirements: 8.6_
  - [ ] 12.2 `config/domain_policy.yaml` 신규 생성
    - 기존 `news_policy.py`의 `PREFERRED_DOMAINS`, `DOMAIN_SCORES`, `SOURCE_TIERS` 전체 이전
    - 각 도메인에 `score_rationale` 필드 추가 (문서화 용도)
    - `version: "1"` 헤더 포함
    - _Requirements: 8.1, 8.3_
  - [ ] 12.3 `news_policy.py`에 YAML 로더 구현
    - `_resolve_domain_policy_path()`: `Path(__file__)` 기준 절대 경로 계산 (CWD 무관)
    - `_parse_domain_policy(raw: dict) -> tuple[dict, dict, set]`: 스키마 검증 포함
    - `_load_domain_policy()`: YAML 없음 → WARNING+fallback, 파싱 오류 → WARNING+fallback
    - 기존 하드코딩 상수를 `_HARDCODED_*` 접두사로 유지 (fallback용)
    - 모듈 임포트 시 자동 초기화: `DOMAIN_SCORES, SOURCE_TIERS, PREFERRED_DOMAINS = _load_domain_policy()`
    - _Requirements: 8.1, 8.2, 8.4_
  - [ ] 12.4 `tests/test_config.py` 확장
    - 기존 하드코딩과 동일한 내용의 YAML 로드 시 `domain_score("reuters.com") == 5.0` 검증
    - YAML 미존재 시 WARNING 로그 + fallback 동작 검증
    - 스키마 오류 YAML (score 음수, 필수 필드 누락) 시 WARNING 로그 + fallback 동작 검증 (예외 없음)
    - `_resolve_domain_policy_path()` 가 CWD 변경 후에도 동일 절대 경로 반환 검증
    - _Requirements: 8.2, 8.4, 8.5_

- [ ] 13. Checkpoint 5 (최종) — `make check` 통과 확인
  - lint: ruff 포매팅 위반 없음
  - test: 전체 pytest 통과, 신규 케이스 포함
  - typecheck: mypy strict — `providers.py`, `news_packet.py`, `data_quality.py`, `market.py` 통과

---

## 파일별 변경 요약

| 파일 | 작업 | 태스크 |
|------|------|--------|
| `src/morning_brief/data/providers.py` | **신규** | 1.1 |
| `src/morning_brief/data/news_packet.py` | TypedDict 추가, 임포트 교체 | 1.2, 3.1, 3.2 |
| `src/morning_brief/data/news_selection.py` | 임포트 교체, dedup 강화, 패턴 확장 | 1.2, 8.1, 8.2, 10.1, 10.2 |
| `src/morning_brief/data/data_quality.py` | 임포트 교체, typed access, 카테고리 zero_ratio | 1.2, 3.3, 6.1, 6.2, 6.3 |
| `src/morning_brief/data/sources/grok_x_keyword.py` | 임포트 교체 | 1.2 |
| `src/morning_brief/prompting.py` | 리터럴 → 상수 | 1.2 |
| `src/morning_brief/data/market.py` | 캐시 TTL | 5.1, 5.2, 5.4 |
| `src/morning_brief/config.py` | Settings 필드 추가 | 5.3 |
| `src/morning_brief/data/news.py` | XSignal dedup 추가 | 9.1, 9.2 |
| `src/morning_brief/data/news_policy.py` | YAML 로더 추가 | 12.3 |
| `config/domain_policy.yaml` | **신규** | 12.2 |
| `requirements.txt` | PyYAML 추가 | 12.1 |
| `pyproject.toml` | mypy files 목록 확장 | 3.4 |
| `tests/test_providers.py` | **신규** | 1.3 |
| `tests/test_news_packet.py` | 신규 또는 확장 | 3.5 |
| `tests/test_market_reliability.py` | 확장 | 5.5 |
| `tests/test_pipeline_quality.py` | 확장 | 6.4 |
| `tests/test_news_quality.py` | 확장 | 8.3, 10.3 |
| `tests/test_grok_x_keyword.py` | 확장 | 9.3 |
| `tests/test_config.py` | 확장 | 12.4 |
