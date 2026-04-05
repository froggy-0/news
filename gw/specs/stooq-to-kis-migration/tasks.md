# Implementation Plan: Stooq → KIS Migration

## Overview

1차 범위는 `usdkrw`만 KIS로 전환하고 `nq_futures`는 기존 yfinance 경로를 유지한다. 구현 전 먼저 `USD/KRW`의 concrete `FID_INPUT_ISCD`를 spec에 고정하고, 이후에는 `kis.py` → `market.py` → 사용자 노출 문구/문서 순으로 진행한다. 각 구현 블록 바로 뒤에 해당 테스트를 배치하고, 3~5개 태스크마다 Checkpoint를 둔다.

완료 일시: 2026-04-05 전체 마이그레이션 완료

---

## Tasks

- [x] 1. Spec gate — USD/KRW 종목코드 확정
  - [x] 1.1 실전 KIS 기준으로 `USD/KRW`의 concrete `FID_INPUT_ISCD` 값을 확인한다
    - 공식 문서, 실전 테스트베드, 기존 탐색 스크립트 중 검증 가능한 근거로 값을 확정한다
    - 확정값: `FX@KRW`
    - placeholder, 추측, 런타임 계산은 허용하지 않는다
    - _Requirements: 3.1, 3.6_
  - [x] 1.2 확정한 `FID_INPUT_ISCD`를 `requirements.md`, `design.md`, `tasks.md`에 반영한다
    - 구현 시작 전에 세 문서의 note/placeholder를 concrete value로 교체한다
    - _Requirements: 3.6_

- [x] 2. 설정 및 provider runtime 기반을 추가한다
  - [x] 2.1 `config.py`에 `kis_app_key`, `kis_app_secret` 필드를 추가한다
    - `Settings` dataclass와 `load_settings()`에 `KIS_APP_KEY`, `KIS_APP_SECRET`를 연결한다
    - _Requirements: 7.1, 7.2_
  - [x] 2.2 `.github/workflows/generate-briefing.yml`에 KIS 시크릿 주입을 추가한다
    - `KIS_APP_KEY`, `KIS_APP_SECRET`을 workflow env에 연결한다
    - _Requirements: 7.3, 7.4_
  - [x] 2.3 `provider_runtime.py`에서 `"stooq"` 정책을 `"kis"`로 교체한다
    - `min_interval_seconds=0.4`, `base_backoff_seconds=1.0`, `max_attempts=5`, `max_backoff_seconds=8.0`
    - `retryable_statuses=frozenset({408, 429, 500, 502, 503, 504})`
    - _Requirements: 4.4, 6.6_
  - [x] 2.4 설정/runtime 관련 테스트를 갱신한다
    - `tests/test_config.py`: KIS env load, 빈 값 처리 검증
    - `tests/test_provider_runtime.py`, `tests/test_providers.py`: `"kis"` 정책과 backoff 설정 검증
    - _Requirements: 7.1, 7.2, 7.4, 4.4, 6.6_

- [x] 3. Checkpoint — 설정/runtime 관련 검증 통과 확인
  - [x] 3.1 `pytest tests/test_config.py tests/test_provider_runtime.py tests/test_providers.py`를 통과시킨다

- [x] 4. `kis.py`에 해외주식 KIS adapter를 구현한다
  - [x] 4.1 `src/morning_brief/data/sources/kis.py`의 공통 기반을 구현한다
    - `KIS_BASE_URL`, `_QUOTE_PATH`, `_TOKEN_PATH`, `_QUOTE_TR_ID`, `_EXCD_MAP`
    - `is_available()`, `_get_token()`, `_ensure_token()`, `_build_headers()`
    - `_KisRateLimitError`, `_kis_get()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.2, 4.1, 4.5, 6.1, 6.2_
  - [x] 4.2 `fetch_close_change_and_volume(ticker)`를 구현한다
    - `execute_with_provider_retry`를 사용하고 `last/base/tvol` 기준으로 값을 계산한다
    - `rt_cd != "0"`, `last == ""`, `last == "0"`은 `HttpFetchError`로 처리한다
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 4.2, 4.3_
  - [x] 4.3 `tests/test_kis_source.py`에 해외주식 경로 테스트를 추가한다
    - 정상 응답 파싱
    - `rt_cd != "0"`
    - `last == ""` 또는 `"0"`
    - EGW00201 재시도 후 성공 / 재시도 소진
    - `is_available()` true/false
    - EXCD 미매핑 ticker
    - _Requirements: 1.4, 2.1, 2.3, 2.4, 2.5, 4.1, 4.2, 4.3_

- [x] 5. `kis.py`에 USD/KRW 전용 API를 구현한다
  - [x] 5.1 공개 인터페이스를 `fetch_usdkrw_point() -> tuple[float, float]`로 확정한다
    - 기존 generic `fetch_rate_point(canonical_key)`는 만들지 않는다
    - _Requirements: 6.2_
  - [x] 5.2 `fetch_usdkrw_point()`를 구현한다
    - `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice`
    - `FID_COND_MRKT_DIV_CODE="X"`
    - 1단계에서 확정한 concrete `FID_INPUT_ISCD`
    - 런타임 추측/검색 없이 spec에 기록된 값만 사용
    - _Requirements: 3.1, 3.4, 3.6, 6.2_
  - [x] 5.3 `tests/test_kis_source.py`에 USD/KRW 테스트를 추가한다
    - KIS 성공 케이스
    - KIS 실패 케이스
    - 최신 가용 값 선택 규칙
    - _Requirements: 3.1, 3.3, 3.4_

- [x] 6. Checkpoint — `kis.py` 단위 테스트 통과 확인
  - [x] 6.1 `pytest tests/test_kis_source.py`를 통과시킨다

- [x] 7. `market.py`의 해외주식 Stooq 경로를 KIS로 교체한다
  - [x] 7.1 import와 상수 구조를 교체한다
    - `stooq` import 제거
    - `fetch_close_change_and_volume as kis_fetch_close_change_and_volume`
    - `US_INDEX_TARGETS` 3-tuple → 2-tuple
    - _Requirements: 6.1, 6.3, 6.4_
  - [x] 7.2 `_point_from_stooq`, `_point_and_volume_from_stooq`, `_safe_stooq_point`, `_safe_stooq_point_and_volume`를 KIS helper로 교체한다
    - `warning_key`: `stooq_fallback_*` → `kis_fallback_*`
    - log message/provider를 `"kis"` 기준으로 정리한다
    - _Requirements: 5.1, 5.4, 6.4_
  - [x] 7.3 해외주식 경로 회귀 테스트를 갱신한다
    - `tests/test_market_btc_official_flow.py`
    - `tests/test_preservation_properties.py`
    - 필요 시 `tests/test_stooq.py` 대체 범위를 `tests/test_kis_source.py`로 연결한다
    - _Requirements: 5.1, 5.4, 6.4, 8.1, 8.2, 8.3_

- [x] 8. `market.py`의 korea_watch를 mixed primary로 바꾼다
  - [x] 8.1 `fetch_usdkrw_point as kis_fetch_usdkrw_point` import를 연결한다
    - _Requirements: 6.2, 6.5_
  - [x] 8.2 `_point_from_kis_usdkrw()`와 `_safe_kis_usdkrw_point()`를 구현한다
    - KIS primary 포인트는 `ticker="USDKRW"`를 사용한다
    - yfinance fallback은 기존 `ticker="KRW=X"`를 유지한다
    - _Requirements: 3.2, 3.3, 5.2, 6.5, 9.3, 9.4_
  - [x] 8.3 `fetch_korea_investor_points()`를 mixed primary로 교체한다
    - `usdkrw`만 `_safe_kis_usdkrw_point()` 사용
    - `nq_futures`는 기존 `_safe_yfinance_point("NQ=F")` 유지
    - _Requirements: 3.2, 3.3, 3.5, 5.2, 5.5, 6.5_
  - [x] 8.4 `tests/test_market_reliability.py`를 mixed primary 기준으로 갱신한다
    - `usdkrw`는 KIS mock
    - `nq_futures`는 yfinance mock
    - KIS 실패 fallback / KIS unavailable 시나리오 포함
    - _Requirements: 3.2, 3.3, 3.5, 5.5, 8.4_

- [x] 9. Checkpoint — `market.py` 교체 후 핵심 회귀 테스트 통과 확인
  - [x] 9.1 `pytest tests/test_kis_source.py tests/test_market_reliability.py tests/test_market_btc_official_flow.py tests/test_preservation_properties.py`를 통과시킨다

- [x] 10. 사용자 노출 출처 문구와 운영 문서를 실제 source에 맞춘다
  - [x] 10.1 `briefing.py`의 source attribution을 수정한다
    - `_market_source_label()`이 `usdkrw`의 `ticker="USDKRW"`를 `KIS`로 식별하도록 수정
    - `usdkrw` 라인은 고정 `[출처: yfinance]` 대신 `_market_source_label(usdkrw)`를 사용
    - `nq_futures`는 기존 `[출처: yfinance]` 동작 유지
    - _Requirements: 9.3, 9.4, 9.5_
  - [x] 10.2 운영 문서를 갱신한다
    - `docs/data-sources.md`: `usdkrw` primary/fallback를 KIS/yfinance로 수정
    - `docs/data-flow.md`: `korea_watch`의 mixed primary 반영
    - _Requirements: 9.1, 9.2_
  - [x] 10.3 사용자 노출 텍스트 검증 테스트를 갱신한다
    - `tests/test_brief_quality.py`
    - `tests/test_briefing_quality.py`
    - `usdkrw` KIS source label / yfinance fallback label 검증
    - _Requirements: 9.3, 9.4, 9.5_

- [x] 11. 레거시 Stooq 잔여물을 정리한다
  - [x] 11.1 `src/morning_brief/data/sources/stooq.py`를 삭제한다
    - _Requirements: 6.3_
  - [x] 11.2 `tests/test_stooq.py`를 삭제하고 탐색용 스크립트를 pytest 수집 대상에서 제외한다
    - `tests/test_kis.py`, `tests/test_twelvedata.py`는 `gw/explorations/` 또는 `tests/exploratory/`로 이동하거나 삭제한다
    - _Requirements: 8.1_

- [x] 12. 최종 Checkpoint — 전체 검증 통과 확인
  - [x] 12.1 `make check`를 통과시킨다
    - _Requirements: 8.5_
