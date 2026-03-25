# Implementation Plan

---

## Phase 1 — 공통 레이어 신규 모듈

- [x] 1. `unified_output.py` 신규 모듈 생성
  - **GOAL:** 정량·서사·메타 세 레이어를 단일 컨테이너로 묶는 공통 데이터 계약을 확립한다
  - **IMPORTANT:** 이 모듈은 이메일/대시보드 양쪽이 동일하게 소비하는 단일 진실 공급원(SSOT)이 된다
  - **DO NOT** 기존 `packet`, `briefing` 변수명을 이 모듈 내에서 재정의하지 말 것 — 소비 측 코드와 혼동 방지
  - 파일 위치: `src/morning_brief/unified_output.py`
  - [x] 1.1 `QuantitativeLayer` dataclass 정의
    - 필드: 주요 ticker 항목 (macro, us_indices, tech_stocks, bitcoin), `sparkline_data: dict`
    - 포맷 표준 FC-1~FC-4 적용 기준을 docstring에 명시 (소수점 자리수, 부호 형식)
    - `_Requirements: FC-1, FC-2, FC-3, FC-4`
  - [x] 1.2 `NarrativeLayer` dataclass 정의
    - 공통 필드: `news: list`, `x_signals: list`, `topic_summaries: dict`, `headline: str`, `summary_lead: str`, `summary_support: str`
    - 이메일 전용 optional 5개: `sector_mapping`, `event_calendar`, `issue_briefings`, `weekly_context`, `sonar_analyses`
    - optional 필드 기본값 `None` — 대시보드 소비 시 absent 처리 명시
  - [x] 1.3 `MetaLayer` dataclass 정의
    - 필드: `run_at: str`, `pipeline_version: str`, `source_counts: dict`, `translation_status: str`
    - `translation_status` 허용값: `"ok"`, `"partial"`, `"failed"`, `"skipped"`
  - [x] 1.4 `UnifiedOutput` 최상위 컨테이너 정의
    - 필드: `quantitative: QuantitativeLayer`, `narrative: NarrativeLayer`, `meta: MetaLayer`
    - `to_dict()` 직렬화 메서드 포함 (R2 persist용)

- [x] 2. `packet` → `QuantitativeLayer` 변환 함수 구현
  - **GOAL:** LLM 텍스트를 경유하지 않고 packet raw 값을 직접 `QuantitativeLayer`로 매핑하여 수치 신뢰성을 확보한다
  - **DO NOT** LLM 텍스트에서 regex로 수치를 역추출하는 로직을 이 함수에 포함하지 말 것
  - 함수명: `packet_to_quantitative(packet: dict) -> QuantitativeLayer`
  - 파일 위치: `src/morning_brief/unified_output.py` (또는 `unified_converters.py`)
  - [x] 2.1 수치 추출 로직 구현
    - `packet["macro"]`, `packet["us_indices"]`, `packet["tech_stocks"]`, `packet["bitcoin"]` raw 값 직접 추출
    - 키 누락 시 `None` 처리 — 강제 KeyError 금지
  - [x] 2.2 포맷 표준 적용
    - FC-1: `change_pct` → `f"{v:+.2f}%"` (소수 2자리 고정)
    - FC-2: `total_btc` → `f"{v:,.2f}"` (소수 2자리 고정)
    - FC-3: BTC 가격 → `f"${v:,.0f}"` 형식
    - FC-4: `change_bps` → `f"{v:+.0f}bp"` 부호 포함 정수
  - [x] 2.3 `_synthetic_history()` sparkline 로직 통합
    - 기존 `public_site.py` 내 분산된 sparkline 생성 로직을 이 함수로 이전
    - `sparkline_data` 필드에 결과 저장
    - _Rollback: 기존 public_site.py sparkline 코드는 이전 완료 후 제거_

- [x] 3. `briefing` + `brief_review` output → `NarrativeLayer` 변환 함수 구현
  - **GOAL:** B3 검수 / B4 재작성 결과를 NarrativeLayer에 매핑하여 이메일·대시보드가 동일한 서사 데이터를 소비하게 한다
  - **DO NOT** LLM 텍스트에서 regex로 수치를 역추출하는 로직을 포함하지 말 것 — 수치는 QuantitativeLayer 전용 경로 사용
  - 함수명: `briefing_to_narrative(briefing: str, packet: dict) -> NarrativeLayer`
  - [x] 3.1 B3/B4 결과 매핑
    - `extract_sections(briefing)` 결과를 NarrativeLayer 공통 필드에 매핑
    - `news`, `x_signals`, `topic_summaries`, `headline`, `summary_lead`, `summary_support` 추출
  - [x] 3.2 이메일 전용 optional 필드 파싱
    - `sector_mapping`, `event_calendar`, `issue_briefings`, `weekly_context`, `sonar_analyses` 파싱 로직
    - 파싱 실패 시 해당 필드 `None` — 예외 전파 금지
    - **NOTE:** optional 필드는 이메일 렌더러만 소비하며 대시보드는 absent 처리

- [x] 4. `pipeline.py` 수정 — 공통 레이어 생성 지점 삽입
  - **GOAL:** `build_market_packet()` + `generate_briefing()` 완료 직후 `UnifiedOutput`을 생성하여 이후 채널 분기 전에 단일 진실 공급원을 확립한다
  - **IMPORTANT:** 기존 `packet`, `briefing` 변수를 제거하지 말 것 — `UnifiedOutput` 생성 후에도 하위 호환 참조로 유지
  - _Depends: 1, 2, 3_
  - [x] 4.1 `UnifiedOutput` 생성 지점 추가
    - `generate_briefing()` 반환 직후 `pipeline.py:213` 부근에 삽입
    - `unified = UnifiedOutput(quantitative=packet_to_quantitative(packet), narrative=briefing_to_narrative(briefing, packet), meta=build_meta_layer(...))`
  - [x] 4.2 R2에 `unified/{date}.json` persist
    - `unified.to_dict()`를 `unified/{date}.json` 키로 R2 업로드
    - 업로드 실패 시 채널 발행 중단 없이 경고 로그만 기록
    - _Rollback: persist 실패 시 기존 briefs/{date}.json 업로드 경로 유지_
  - [x] 4.3 `observer` 이벤트 추가
    - `observer.log_event("unified_output_created", {"quantitative_keys": [...], "narrative_optional_present": [...]})`

- [x] 5. 단위 테스트 — `UnifiedOutput` 생성 검증
  - **GOAL:** 포맷 표준 4건(FC-1~FC-4)과 optional 필드 None 처리를 자동 검증하여 회귀를 방지한다
  - 테스트 파일: `tests/test_unified_output.py`
  - _Depends: 1, 2, 3_
  - [x] 5.1 `QuantitativeLayer` 변환 검증
    - packet fixture 기반 `packet_to_quantitative()` 반환값 검증
    - FC-1: `change_pct` 소수 2자리 assertion (`"+1.23%"` 형식)
    - FC-2: `total_btc` 소수 2자리 assertion
    - FC-3: BTC 가격 `"$84,321"` 형식 assertion
    - FC-4: `change_bps` 부호 포함 정수 assertion (`"+12bp"` 형식)
  - [x] 5.2 `NarrativeLayer` optional 필드 처리 검증
    - optional 필드가 없는 최소 briefing fixture에서 `sector_mapping` 등이 `None`으로 반환되는지 확인
    - optional 필드가 있는 full briefing fixture에서 정상 파싱되는지 확인
  - [x] 5.3 `UnifiedOutput` 직렬화 검증
    - `to_dict()` 반환값이 JSON serializable인지 확인
    - `translation_status` 허용값 범위 검증

---

## Phase 2 — 대시보드 소비 전환

- [x] 6. `public_site.py` — `QuantitativeLayer` 소비로 전환
  - **GOAL:** 대시보드 정량 데이터를 UnifiedOutput.quantitative에서 직접 읽어 포맷 불일치를 제거한다
  - _Depends: 4_
  - _Rollback: packet 직접 읽기 코드를 주석으로 보존하여 즉시 복구 가능하게 유지_
  - [x] 6.1 `_market_snapshot_items()` 수정
    - `_market_snapshot_items_v2(unified)` 추가; 기존 함수 DEPRECATED 주석 유지
    - `build_public_brief(unified=...)` 분기로 v2 사용
  - [x] 6.2 `_bitcoin_section()` 수정
    - `_bitcoin_section_v2(unified)` 추가; `unified.quantitative.btc` 소비
    - FC-2/FC-3 포맷 QuantitativeLayer에서 이미 적용 — 재포맷 금지 준수
  - [x] 6.3 포맷 표준 FC-2 적용 확인
    - `btc_total_holding` FC-2 포맷은 `packet_to_quantitative()` 에서 적용 완료 확인

- [x] 7. `public_site.py` — `NarrativeLayer` 소비로 전환
  - **GOAL:** 대시보드 서사 데이터를 UnifiedOutput.narrative에서 읽어 이메일·대시보드 간 서사 불일치를 제거한다
  - _Depends: 4_
  - [x] 7.1 `_news_items()` 수정
    - `_news_items_v2(unified, run_at, limit=...)` 추가; `unified.narrative.news` 소비
    - 기존 함수 DEPRECATED 주석 유지 (하위 호환)
  - [x] 7.2 `_x_signals()` 수정
    - `_x_signals_v2(unified, run_at, limit=...)` 추가; `unified.narrative.x_signals` 소비
    - 기존 함수 DEPRECATED 주석 유지 (하위 호환)
  - [x] 7.3 번역 LLM(P1) 호출 위치 검토
    - `briefing_to_narrative()`는 번역 미포함 — raw news/x_signals 추출만 수행
    - `_apply_public_translation()`은 `build_public_brief()` 내 한 번만 호출 → 중복 없음
    - 결론: P1 번역 중복 없음. 현재 위치 유지 (Phase 3 이동 여부는 Task 13에서 재검토)

- [x] 8. Next.js 스키마 호환성 검증
  - **GOAL:** R2 JSON 키 변경이 additive-only 원칙을 준수하여 프론트엔드 breaking change가 없음을 확인한다
  - **CRITICAL:** enum 필드(`topic`, `category`, `sourceTier`, `sentiment`) rename 금지 — 프론트엔드 런타임 오류 유발
  - [x] 8.1 R2 JSON 키 변경 사항 확인
    - v2 함수 출력 키 = v1 출력 키 (symbol,label,value,change,trend,isCached,history / id,category,sourceTier 등)
    - 기존 키 삭제 없음 — additive-only 원칙 준수 확인
  - [x] 8.2 `frontend/lib/brief-schema.ts` 타입 업데이트
    - breaking change 없음 — 기존 타입 변경 불필요
    - v2 함수가 기존과 동일한 JSON 구조 생성 (etf.issuers=[] 빈 배열은 호환)
  - [x] 8.3 enum 필드 rename 금지 확인
    - `category` (macro/bigtech/bitcoin/us-stocks), `sourceTier` (tier1/standard), `sentiment` (bullish/bearish/neutral)
    - v2 함수에서 동일 값 사용 — 0건 변경 확인

- [x] 9. Phase 2 통합 검증
  - **GOAL:** 대시보드 렌더링 결과가 As-Is와 동등함을 확인한다
  - _Depends: 6, 7, 8_
  - [x] 9.1 대시보드 렌더링 결과 비교
    - 전체 테스트 스위트 371 passed, 0 failed (uv run pytest tests/ -v)
    - `build_public_brief(unified=None)` 하위 호환 동작 확인
    - `pipeline.py` → `publish_public_brief(..., unified=unified)` 전달 업데이트
  - [x] 9.2 포맷 표준 4건 대시보드 반영 확인
    - FC-1/FC-4: QuantitativeLayer 생성 시점에 적용 (재포맷 금지 준수)
    - FC-2: btc_total_holding `:,.2f BTC` QuantitativeLayer에서 적용
    - FC-3: btc_spot.value_fmt `$XX,XXX` QuantitativeLayer에서 적용

---

## Phase 3 — 이메일 소비 전환

- [x] 10. `emailer.py` — regex 파싱 제거
  - **GOAL:** LLM 텍스트 기반 수치 역추출 경로를 제거하여 정량 수치 신뢰성을 확보한다
  - **CRITICAL:** 제거 전 `_macro_indicators_from_packet()` 폴백이 실제 실행 중인지 `observer` 로그로 검증 완료 후 진행할 것
  - **DO NOT** 폴백 로직이 검증되지 않은 상태에서 regex 파싱을 먼저 제거하지 말 것
  - [x] 10.1 폴백 정상 동작 검증
    - `_macro_indicators_from_packet()` 단독 실행 시 이메일 렌더링 결과가 정상인지 테스트 fixture로 확인
    - `_stock_indices_from_packet()` 동일 검증
    - **EXPECTED OUTCOME:** 폴백 경로 단독으로 렌더링 결과 정상
  - [x] 10.2 `_parse_macro_indicators()` 제거
    - `emailer.py:1171` `_parse_macro_indicators()` 함수 및 호출부 제거
    - 제거 후 폴백이 자동으로 활성화되는지 확인
  - [x] 10.3 `_parse_stocks()` 제거
    - `emailer.py:1208` `_parse_stocks()` 함수 및 호출부 제거

- [x] 11. `emailer.py` — `QuantitativeLayer` 소비로 전환
  - **GOAL:** 이메일 정량 데이터를 UnifiedOutput.quantitative에서 직접 읽어 포맷 표준을 통일한다
  - _Depends: 10_
  - [x] 11.1 `_build_snapshot_badges()` 수정
    - `unified.quantitative` 읽도록 수정
    - FC-1 포맷(`+.2f`) 이미 QuantitativeLayer에 적용된 값 사용 — emailer 내 자체 포맷팅 제거
    - `emailer.py:934`, `emailer.py:1004` change_pct 포맷 중복 적용 금지 확인
  - [x] 11.2 `_build_btc_data()` 수정
    - `unified.quantitative.btc` 읽도록 수정
    - packet 직접 접근 코드 제거

- [x] 12. `emailer.py` — `NarrativeLayer` 소비로 전환
  - **GOAL:** 이메일 서사 데이터를 UnifiedOutput.narrative에서 읽어 이메일·대시보드 서사를 동기화한다
  - _Depends: 10, 11_
  - [x] 12.1 `_prepare_v2_news_items()` 수정
    - `unified.narrative.news` 읽도록 수비
    - briefing 마크다운 파싱(`section_4_2`) 경로 제거
  - [x] 12.2 이메일 전용 optional 필드 소비
    - `sector_mapping` → 섹터 요약 렌더링
    - `event_calendar` → 이번 주 일정 렌더링
    - `issue_briefings`, `weekly_context`, `sonar_analyses` 각 optional 필드
    - 필드가 `None`이면 해당 섹션 렌더링 생략 (graceful degradation)

- [x] 13. `observer` 폴백 로깅 추가
  - **GOAL:** regex 파싱 완전 제거 전 폴백 빈도를 실측하여 Phase 3 진행 안전성을 확인한다
  - **NOTE:** 이 태스크는 Phase 3 선행 조건 — 10번 태스크 착수 전에 완료해야 한다
  - [x] 13.1 폴백 이벤트 로깅 구현
    - `observer.log_event("briefing_parse_fallback", {"field": ..., "source": "packet_fallback"})` 구현
    - 폴백이 실행될 때마다 기록 — 성공/실패 무관
  - [x] 13.2 폴백 빈도 측정 기간 운영
    - 최소 2회 이상 실 run에서 `briefing_parse_fallback` 이벤트 빈도 확인
    - 빈도가 높으면 태스크 10 착수 전 원인 분석 필요
    - _Expected: run당 0건 — regex 파싱이 정상 시 폴백 실행 안 됨_

- [x] 14. 포맷 표준 일괄 적용 (FC-1~FC-4)
  - **GOAL:** 이메일·대시보드 양 채널의 잔여 포맷 불일치를 QuantitativeLayer 통합으로 일괄 해소한다
  - **IMPORTANT:** QuantitativeLayer 변환(태스크 2)에서 포맷이 이미 적용됐다면 중복 적용 금지 — 각 항목 확인 후 처리
  - [x] 14.1 FC-1: emailer.py change_pct 포맷 통일
    - `emailer.py:934`, `emailer.py:1004` `+.1f` → `+.2f` 확인 및 수정
    - QuantitativeLayer에서 이미 처리 시 emailer 내 자체 포맷팅 코드 제거
  - [x] 14.2 FC-2: public_site.py total_btc 포맷 통일
    - `public_site.py:1039` `:,.0f` → `:,.2f` 확인 및 수정
  - [x] 14.3 FC-3: BTC 가격 단위 통일
    - 이메일/대시보드 양쪽에서 `$84,321` 형식으로 통일
    - QuantitativeLayer 변환에서 처리 완료 시 스킵
  - [x] 14.4 FC-4: change_bps 부호 통일
    - `sign+:.0f` 형식으로 이메일/대시보드 동일 적용 확인

---

## 검증

- [ ] 15. 최종 통합 검증 및 루브릭 잔여 항목 재검증
  - **GOAL:** As-Is 대비 To-Be 동등성을 확인하고, 루브릭 Partial 항목을 완료 판정으로 갱신한다
  - _Depends: 9, 11, 12, 14_
  - [ ] 15.1 이메일 발송 테스트
    - 실제 발송 또는 dry-run으로 이메일 HTML 렌더링 결과 확인
    - 포맷 표준 4건(FC-1~FC-4)이 이메일에 반영됐는지 육안 확인
    - 이메일 전용 optional 섹션이 데이터 있을 때/없을 때 각각 올바르게 렌더링되는지 확인
  - [ ] 15.2 대시보드 JSON 출력 비교 (As-Is vs To-Be)
    - `briefs/{date}.json` vs `unified/{date}.json` 전체 필드 비교
    - additive-only 원칙 준수 — 기존 키 누락 없음 확인
    - 프론트엔드에서 렌더링 오류 없는지 확인
  - [ ] 15.3 루브릭 잔여 Partial 항목 재검증
    - 정량 수치 신뢰 경로: LLM 텍스트 → regex 역추출 완전 제거 확인
    - 포맷 불일치: 4건 모두 해소 확인
    - 채널 독립성: cascading failure 구조 해소 확인
    - LLM 호출 횟수: 실 run artifact에서 B4 조건부 실행 확인
  - [ ] 15.4 LLM 호출 횟수 실측 비교
    - As-Is: B1+B3+B4+U1~U3 = 최대 6회
    - To-Be 목표: B4 조건부 제외 시 3~5회
    - `observer` phase별 usage에서 호출 횟수 확인
    - **EXPECTED OUTCOME:** 정상 실행 기준 LLM 호출 ≤ 5회
