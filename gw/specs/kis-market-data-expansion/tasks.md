# Implementation Plan: KIS Market Data Expansion

## Overview

phase 1 구현은 검증된 네 항목 `usdkrw`, `dow30`, `kospi`, `kosdaq`만 production 코드에 편입한다. 구현 순서는 `kis.py` 계약 확장 → `market_policy.py`/`market.py` orchestration 반영 → `pipeline.py`와 출력 소비자 연결 → 관련 단위/통합/live 테스트 보강 순으로 진행한다.

## Tasks

- [ ] 1. `kis.py`에 phase 1 KIS 계약을 추가한다
  - [ ] 1.1 chartprice/국내지수 공통 요청 helper를 정리한다
    - `src/morning_brief/data/sources/kis.py`에 토큰·헤더·retry를 재사용하는 공통 GET 경로를 추가한다.
    - `fetch_usdkrw_point()`와 호환되도록 chartprice 계열 공통 파서를 정리하고, `.DJI` direct index 조회를 같은 경로에 얹는다.
    - 국내지수 전용 파서를 추가해 `0001`, `1001` 응답을 `tuple[float, float]`로 정규화한다.
    - `_Requirements: 3.1, 4.1, 4.8, 5.1, 5.2, 7.1, 7.4_`
  - [ ] 1.2 zero payload와 401을 런타임 실패로 표준화한다
    - `rt_cd="0"`이어도 `output1` 가격이 `0`이고 `output2`가 비어 있으면 `HttpFetchError`로 승격해 fallback으로 넘긴다.
    - `401` 또는 토큰 만료 응답은 `_TOKEN` 무효화 후 1회만 재시도하도록 정리한다.
    - 기존 `fetch_close_change_and_volume()`와 `fetch_usdkrw_point()`의 반환 타입과 호출 방식은 유지한다.
    - `_Requirements: 2.3, 3.4, 7.3, 9.3_`

- [ ] 2. `kis.py` phase 1 계약을 검증하는 테스트를 추가한다
  - [ ] 2.1 `tests/test_kis_source.py`를 확장한다
    - `.DJI`, `0001`, `1001` 파싱 경로를 unit test로 추가한다.
    - zero payload가 success가 아니라 예외로 승격되는지 검증한다.
    - `401` 재시도와 `EGW00201` retry 경로가 기존 policy 위에서 동작하는지 검증한다.
    - **Property 1: zero payload는 성공이 아니다**
    - 테스트 파일: `tests/test_kis_source.py`
    - **Validates: Requirements 2.3, 3.4, 5.4, 7.2, 7.3**
  - [ ] 2.2 live contract 범위를 phase 1 기준으로 정리한다
    - `tests/test_kis_live_contract.py`는 `FX@KRW`, `.DJI`, `0001`, `1001` 유지 확인에 집중한다.
    - `scripts/kis_parameter_probe.py`는 `zero_payload`/`unit_unresolved` 후보를 계속 분리 보고하되, production-ready contract와 future-phase 후보를 명확히 구분한다.
    - **Property 2: probe와 live contract 범위는 phase 1 scope와 일치해야 한다**
    - 테스트 파일: `tests/test_kis_live_contract.py`
    - **Validates: Requirements 1.2, 2.2, 3.2, 4.2, 5.3**

- [ ] 3. `market_policy.py`와 `market.py`에 새 canonical key와 orchestration 경로를 반영한다
  - [ ] 3.1 `market_policy.py`를 phase 1 scope에 맞게 확장한다
    - `src/morning_brief/data/market_policy.py`에 `dow30`, `kospi`, `kosdaq` label과 source mapping을 추가한다.
    - `MARKET_VALIDATION_BOUNDS`에 세 항목의 bound를 추가하되 기존 key와 mapping은 그대로 보존한다.
    - 사용되지 않는 `DISPLAY_ONLY_VALIDATION`은 이번 작업 범위에 포함하지 않는다.
    - `_Requirements: 1.2, 3.6, 5.3, 8.3_`
  - [ ] 3.2 `market.py`에 phase 1 orchestration 함수를 추가한다
    - `src/morning_brief/data/market.py`에 `fetch_validated_global_index_points()`와 `fetch_korea_index_points()`를 추가한다.
    - `build_market_packet()`는 기존 `us_indices`를 유지하면서 `validated_indices`를 추가한다.
    - `fetch_newsletter_display_data()`는 기존 `korea_watch`를 유지하면서 `korea_indices`를 추가하고, 필요 시 `observer`를 받아 display-stage provider usage를 기록할 수 있게 한다.
    - 각 항목은 `_safe_with_fallback()`, `_resolve_points_from_cache()`, `_validate_market_points()`를 재사용하고, 같은 자산 의미의 yfinance fallback만 사용한다.
    - `_Requirements: 3.5, 5.6, 8.1, 8.3, 9.1, 9.2, 10.3, 10.4, 11.1, 11.2, 11.3_`

- [ ] 4. `market.py`와 policy 변경을 검증하는 테스트를 추가한다
  - [ ] 4.1 `tests/test_market_reliability.py`를 확장한다
    - `build_market_packet()`에 `validated_indices`가 추가되고, `fetch_newsletter_display_data()`에 `korea_indices`가 추가되는지 검증한다.
    - `dow30`, `kospi`, `kosdaq`의 fallback과 cache restore, anomaly bound 적용을 검증한다.
    - `kis.is_available() == False`일 때 category-level fallback으로 전환되는지 확인한다.
    - **Property 3: 같은 자산 fallback만 사용한다**
    - 테스트 파일: `tests/test_market_reliability.py`
    - **Validates: Requirements 3.5, 5.6, 8.3, 9.1, 9.3, 10.3, 10.4**
  - [ ] 4.2 보존 테스트와 canonical mapping 테스트를 보강한다
    - `tests/test_preservation_properties.py`에 새 canonical key와 validation bound가 기존 key를 깨지 않고 확장되는지 검증을 추가한다.
    - 같은 파일의 `build_market_packet()` expected key 검증을 additive schema 확장에 맞게 갱신한다.
    - 필요 시 `tests/test_bug_condition_exploration.py` 또는 인접 테스트에 `.DJI -> dow30` 매핑 보존 검증을 추가한다.
    - **Property 4: 기존 mapping과 bounds는 보존되면서 phase 1 key만 확장된다**
    - 테스트 파일: `tests/test_preservation_properties.py`
    - **Validates: Requirements 1.2, 3.6, 5.3, 8.3, 10.6**

- [ ] 5. Checkpoint - source/policy/orchestration 단위 테스트 통과 확인
  - `tests/test_kis_source.py`, `tests/test_market_reliability.py`, `tests/test_preservation_properties.py`를 우선 실행한다.
  - 실패 시 구현 추가보다 먼저 contract/consumer 불일치를 원인으로 분류한다.
  - `_Requirements: 2.1, 7.2, 8.4, 11.4_`

- [ ] 6. `pipeline.py`와 출력 소비자에 새 section 전달 경로를 반영한다
  - [ ] 6.1 `pipeline.py` render merge를 갱신한다
    - `src/morning_brief/pipeline.py`에서 `observer`를 `fetch_newsletter_display_data()`로 전달하고, 반환한 `korea_indices`를 `render_packet`에 병합한다.
    - `build_market_packet()`의 `validated_indices`가 publish/public/email 경로까지 전달되도록 유지한다.
    - `_Requirements: 10.3, 10.4, 10.5, 11.3, 11.5_`
  - [ ] 6.2 최소 하나 이상의 downstream consumer를 실제로 연결한다
    - `src/morning_brief/unified_output.py`의 `QuantitativeLayer`와 `packet_to_quantitative()`에 `dow30`, `kospi`, `kosdaq` 소비 슬롯을 추가한다.
    - `tests/test_unified_output.py`의 `MINIMAL_PACKET` fixture와 관련 assertion도 같은 변경에서 갱신한다.
    - `src/morning_brief/briefing.py`, `src/morning_brief/emailer.py`, `src/morning_brief/public_site.py`는 새 section을 즉시 사용할지 여부를 결정하고, 미사용이면 문서와 테스트에 의도적 제외 상태를 남긴다.
    - 기존 `spy`, `qqq`, `soxx` proxy 경로와 canonical 의미를 덮어쓰지 않는다.
    - `_Requirements: 3.6, 10.1, 10.5, 11.5_`

- [ ] 7. downstream consumer 변경을 검증하는 통합 테스트를 추가한다
  - [ ] 7.1 `pipeline.py` merge와 consumer 전달을 검증한다
    - 신규 `tests/test_pipeline_render_packet.py`를 추가해 `validated_indices`, `korea_indices`, `observer` 전달이 `render_packet`으로 반영되는지 확인한다.
    - packet schema 변경이 기존 품질 평가를 깨지 않는지 함께 확인한다.
    - **Property 5: 새 structured field는 dead field가 아니어야 한다**
    - 테스트 파일: `tests/test_pipeline_render_packet.py`
    - **Validates: Requirements 10.5, 11.3, 11.5**
  - [ ] 7.2 unified/email/public 출력 계층을 검증한다
    - `tests/test_unified_output.py`에 `QuantitativeLayer` 새 슬롯을 검증하는 fixture를 추가한다.
    - 필요한 경우 `tests/test_emailer.py` 또는 `tests/test_public_site.py`에 새 항목 표시 또는 의도적 미표시 정책 검증을 추가한다.
    - `tests/test_logging_surface.py`는 새 `observer.record_provider_usage(...)` 호출이 생기는 경우 allowlist를 함께 갱신한다.
    - **Property 6: consumer 추가는 기존 출력 경로를 깨지 않는다**
    - 테스트 파일: `tests/test_unified_output.py`, `tests/test_emailer.py`, `tests/test_public_site.py`
    - **Validates: Requirements 10.4, 10.5, 11.1, 11.2, 11.3, 11.5**

- [ ] 8. Checkpoint - packet/render consumer 통합 검증
  - `tests/test_pipeline_render_packet.py`, `tests/test_unified_output.py`, 관련 `emailer/public_site` 테스트를 실행한다.
  - `validated_indices`와 `korea_indices`가 dead field 없이 실제 소비되거나, 의도적 미사용 상태가 테스트로 고정되었는지 확인한다.
  - `_Requirements: 10.5, 11.5_`

- [ ] 9. 운영 문서와 실행 명령을 정리한다
  - `README.md` 또는 가장 가까운 운영 문서에 새 phase 1 KIS 항목, probe 사용법, live contract 범위를 반영한다.
  - `scripts/kis_parameter_probe.py` 실행 명령과 `pytest -m live_kis` 실행 명령을 문서에 함께 남긴다.
  - phase 1 범위 밖 항목(`sp500`, `nasdaq100`, `jpykrw`, `eurkrw`, `cnykrw`, 국채, 원자재`)은 future phase임을 분명히 적는다.
  - `_Requirements: 1.3, 2.2, 6.2, 11.6_`

- [ ] 10. Final Checkpoint - 전체 검증 명령 통과 확인
  - 최소 검증 순서:
    - `make fmt`
    - `make lint`
    - `python -m pytest -q tests/test_kis_source.py tests/test_market_reliability.py tests/test_preservation_properties.py tests/test_pipeline_render_packet.py tests/test_unified_output.py`
    - 필요 시 `python -m pytest -q -m live_kis tests/test_kis_live_contract.py`
  - phase 1 범위 밖 후보는 probe 결과만 유지되고 production path에 들어가지 않았는지 최종 확인한다.
  - `_Requirements: 1.2, 2.1, 7.2, 8.4, 11.5, 11.7_`
