# Implementation Plan: News Analysis Prompt & Grok Optimization

## Overview

변경 A(프롬프트·reasoning)와 변경 B(Grok 그룹·config)를 독립적으로 진행한다. 변경 A는 프롬프트 파일 재작성 + 1줄 코드 변경으로 완결된다. 변경 B는 `grok_x_keyword.py` 내에서 코드 레벨로 그룹을 통합하고(registry JSON 불변), config 기본값을 줄인다. 두 변경 모두 파이프라인 인터페이스와 기존 테스트를 깨지 않는다.

**변경 파일 목록:**
- `src/morning_brief/prompts/public_news_analysis_instructions.j2`
- `src/morning_brief/public_news_analysis.py` (1줄)
- `src/morning_brief/data/sources/grok_x_keyword.py`
- `src/morning_brief/config.py` (2줄)
- `tests/test_public_news_analysis.py` (테스트 추가)
- `tests/test_grok_x_keyword.py` (신규 생성)
- `tests/test_config.py` (테스트 추가)

**변경하지 않는 파일:**
- `official_signal_registry.json` — `grok_official_signals.py`가 동일 registry를 읽으므로 불변
- `grok_official_signals.py` — 공식 신호 경로 유지
- `test_official_signal_registry.py` — registry 변경 없으므로 회귀 없음

---

## Tasks

### 변경 A: 프롬프트 품질 + reasoning

- [x] 1. `public_news_analysis_instructions.j2` 재작성
  - [x] 1.1 프롬프트를 세 블록 구조로 재작성한다
    - 파일: `src/morning_brief/prompts/public_news_analysis_instructions.j2`
    - **블록 1 (역할 + 세계 지식 허용):** 기존 1행 역할 문장을 확장. "입력이 얇더라도 배경 지식으로 보강 가능, 단 입력에 없는 구체적 수치·날짜·기업명 지어내기 금지" 명시
    - **블록 2 (토픽별 분석 지침):** `topic` 값별 `interpretation_ko` 초점 지침 5줄:
      - `"ai_bigtech"`: AI 인프라·반도체 공급망·모델 발표·설비투자 맥락
      - `"macro"`: 연준 정책·금리 기대·인플레이션·성장 전망과의 연결
      - `"bitcoin"`: ETF 자금 흐름·규제 동향·기관 수요와의 연결
      - `"us_equity"`: 섹터 영향·지수 영향·투자 심리와의 연결
      - `(기타)`: 해당 자산군에 미치는 시장 가격 영향 중심
    - **블록 3 (생성 규칙):** 기존 규칙 1·2·3·4·6·7·8 유지. 규칙 5만 역전: "부족하면 빈 문자열" → "title과 topic만으로도 최소 1문장 한국어 해설 생성, 빈 문자열 반환 금지"
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 2. `public_news_analysis.py` reasoning effort 변경
  - [x] 2.1 reasoning effort를 `"low"`로 변경한다
    - 파일: `src/morning_brief/public_news_analysis.py`
    - 변경 위치: `enrich_public_news_packet()` 내 `client.responses.create()` 호출
    - 변경: `reasoning={"effort": "minimal"}` → `reasoning={"effort": "low"}`
    - `max_output_tokens` 공식(`min(3200, max(900, 320 * len(batch)))`) 변경 없음
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 3. 변경 A 테스트 추가
  - [x] 3.1 얇은 입력 테스트 추가
    - 파일: `tests/test_public_news_analysis.py`
    - **Property 1: 얇은 입력에서도 비어 있지 않은 해설 생성**
    - `summary=None`, `why_it_matters=None`인 항목에서 LLM mock이 유효한 한국어 응답을 반환할 때 `enrich_public_news_packet()`이 해당 결과를 패킷에 병합하는지 검증
    - 기존 `FakeOpenAI.create(**kwargs)` 패턴 그대로 사용, `why_it_matters` 없는 입력 항목 전달
    - _Requirements: 1.7, 1.8_
  - [x] 3.2 reasoning effort "low" 전달 검증 테스트 추가
    - 파일: `tests/test_public_news_analysis.py`
    - **Property 2: reasoning effort가 "low"로 설정됨**
    - `FakeOpenAI.create(**kwargs)`의 `create` 메서드 내부에서 `assert kwargs.get("reasoning") == {"effort": "low"}` 추가
    - _Requirements: 2.1_

- [x] 4. Checkpoint A — 변경 A 테스트 통과 확인
  - `uv run pytest tests/test_public_news_analysis.py -v`
  - 통과 기준: 신규 테스트 2개 포함 전체 통과
  - _Requirements: 7.2, 7.3_

---

### 변경 B: Grok 그룹 통합 + config

- [x] 5. `grok_x_keyword.py` — 그룹 통합 및 핸들 union
  - [x] 5.1 `BITCOIN_CRYPTO_GROUP` 상수를 추가하고 구 그룹 상수 2개를 제거한다
    - 파일: `src/morning_brief/data/sources/grok_x_keyword.py`
    - 추가: `BITCOIN_CRYPTO_GROUP = "bitcoin_crypto"`
    - 삭제: `CRYPTO_ETF_GROUP = "crypto_and_etf"`, `BTC_ETF_GROUP = "btc_etf_primary"`
    - _Requirements: 3.1, 3.3_
  - [x] 5.2 `BITCOIN_CRYPTO_PROMPT`을 작성하고 `GROUP_PROMPTS`를 3개 항목으로 갱신한다
    - 기존 `CRYPTO_ETF_PROMPT`·`BTC_ETF_PRIMARY_PROMPT` 두 프롬프트의 포커스를 병합:
      - IBIT·BITB·GBTC·FBTC·ARKB ETF 자금 흐름·AUM
      - BTC 가격 동향·시장 심리
      - 크립토 규제(SEC·CFTC 결정·집행)
      - 기관 수요·신규 ETF 신청·수수료 변경·운용사 공식 코멘트
    - `GROUP_PROMPTS`: 구 두 항목 제거, `BITCOIN_CRYPTO_GROUP: BITCOIN_CRYPTO_PROMPT` 추가
    - 구 상수(`CRYPTO_ETF_PROMPT`, `BTC_ETF_PRIMARY_PROMPT`) 제거
    - _Requirements: 3.2_
  - [x] 5.3 `GROUP_TOPIC_MAP`과 `search_groups`를 3개 그룹으로 업데이트한다
    - `GROUP_TOPIC_MAP`: 구 두 항목 제거, `BITCOIN_CRYPTO_GROUP: "bitcoin"` 추가
    - `search_groups = [MACRO_EQUITY_GROUP, AI_BIGTECH_GROUP, BITCOIN_CRYPTO_GROUP]`
    - _Requirements: 3.3, 3.5_
  - [x] 5.4 `BITCOIN_CRYPTO_GROUP` 핸들을 두 구 그룹에서 union하는 로직을 추가한다
    - `fetch_x_keyword_signals()` 내부에서 `all_handles = grouped_verified_x_handles()` 호출 후:
      - `MACRO_EQUITY_GROUP`, `AI_BIGTECH_GROUP`: 기존대로 `all_handles.get(group, [])` 사용
      - `BITCOIN_CRYPTO_GROUP`: `all_handles.get("crypto_and_etf", [])` + `all_handles.get("btc_etf_primary", [])` 두 리스트를 중복 없이 병합하여 사용
    - registry JSON 변경 없음 — `grok_official_signals.py`의 공식 신호 경로가 `"btc_etf_primary"` 그룹을 그대로 사용해야 하기 때문
    - _Requirements: 3.4_

- [x] 6. Grok 그룹 통합 테스트 추가 (신규 파일)
  - [x] 6.1 `tests/test_grok_x_keyword.py` 신규 생성
    - **Property 3: search_groups가 정확히 3개이고 BITCOIN_CRYPTO_GROUP 포함**
    - `len(search_groups) == 3` 및 `BITCOIN_CRYPTO_GROUP in search_groups` assert
    - **Property 4: BITCOIN_CRYPTO_GROUP의 topic 매핑이 "bitcoin"**
    - `GROUP_TOPIC_MAP[BITCOIN_CRYPTO_GROUP] == "bitcoin"` assert
    - **Property 5: 구 그룹 상수 2개가 모듈에 없음**
    - `hasattr(module, "CRYPTO_ETF_GROUP")` → `False` assert
    - `hasattr(module, "BTC_ETF_GROUP")` → `False` assert
    - **Property 6: BITCOIN_CRYPTO_GROUP 프롬프트에 필수 키워드 포함**
    - `BITCOIN_CRYPTO_PROMPT`에 `"ETF"`, `"BTC"`, `"SEC"` 문자열 포함 assert
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 6.1, 6.2_

- [x] 7. Checkpoint B — Grok 그룹 통합 테스트 통과 확인
  - `uv run pytest tests/test_grok_x_keyword.py -v`
  - 통과 기준: 6개 assert 모두 통과
  - 부가 확인: `uv run pytest tests/test_official_signal_registry.py -v` → 변경 없이 전체 통과 (registry 불변 검증)
  - _Requirements: 7.1, 7.3_

- [x] 8. `config.py` max_items 기본값·상한 수정
  - [x] 8.1 `grok_x_search_max_items` 기본값·상한을 낮춘다
    - 파일: `src/morning_brief/config.py`
    - 변경: `default=6, maximum=10` → `default=4, maximum=8`
    - _Requirements: 4.1, 4.2_
  - [x] 8.2 `official_x_max_items` 기본값·상한을 낮춘다
    - 파일: `src/morning_brief/config.py`
    - 변경: `default=4, maximum=6` → `default=3, maximum=5`
    - _Requirements: 5.1, 5.2_

- [x] 9. config 변경 테스트 추가
  - [x] 9.1 새 기본값과 클램프 동작 검증 테스트를 `tests/test_config.py`에 추가한다
    - **Property 7: grok_x_search_max_items 기본값이 4**
    - 환경변수 미설정 시 `settings.grok_x_search_max_items == 4` assert
    - **Property 8: official_x_max_items 기본값이 3**
    - 환경변수 미설정 시 `settings.official_x_max_items == 3` assert
    - **Property 9: grok_x_search_max_items 상한 클램프 동작**
    - `GROK_X_SEARCH_MAX_ITEMS=20` 설정 시 `settings.grok_x_search_max_items == 8` assert
    - 기존 `test_perplexity_settings_loaded` 참고: `OFFICIAL_X_MAX_ITEMS=2` 테스트가 이미 존재하므로, 기존 2 → 새 default 3으로 바뀐 경우 그 테스트가 여전히 유효한지 확인 (해당 테스트는 env를 2로 명시 설정하므로 영향 없음)
    - _Requirements: 4.1, 4.2, 4.4, 5.1, 5.2_

- [x] 10. Checkpoint C — config 테스트 통과 확인
  - `uv run pytest tests/test_config.py -v`
  - 통과 기준: 신규 기본값·클램프 테스트 포함 전체 통과 (기존 `OFFICIAL_X_MAX_ITEMS=2` 테스트 회귀 없음)
  - _Requirements: 4.3, 5.3, 7.3_

---

### 최종 검증

- [x] 11. 파이프라인 인터페이스 계약 유지 확인
  - [x] 11.1 `fetch_x_keyword_signals()` 반환 타입 회귀 테스트 추가
    - 파일: `tests/test_grok_x_keyword.py`
    - **Property 10: fetch_x_keyword_signals 반환 구조 유지**
    - mock 호출 결과가 `(list, list, dict)` 3-tuple 형태임을 assert
    - _Requirements: 6.1, 6.2_
  - [x] 11.2 기존 `test_public_news_analysis.py` 전체 회귀 확인
    - 기존 4개 테스트(merged, placeholder, disabled, invalid_json)가 모두 통과하는지 확인
    - _Requirements: 6.3, 6.4, 6.5_
  - [x] 11.3 `test_official_signal_registry.py` 전체 회귀 확인
    - registry JSON 불변이므로 `test_new_entities_verified_enabled_and_group`, `test_grouped_handle_counts` 등 전체 통과 확인
    - _Requirements: 6.5_

- [x] 12. Checkpoint D — 전체 통합 테스트
  - `uv run pytest tests/test_public_news_analysis.py tests/test_grok_x_keyword.py tests/test_config.py tests/test_official_signal_registry.py -v`
  - 통과 기준: 4개 파일 전체 통과

- [x] 13. 전체 스위트 최종 검증
  - `make check` (lint + type + test 통합)
  - 통과 기준: ruff lint 0 error, mypy strict 0 error, pytest 전체 통과
  - _Requirements: 7.3_
