# 구현 계획: 이메일 브리핑 리디자인

## 개요

기존 3-LAYER 텍스트 중심 이메일 브리핑을 mail.md 기획안 기반의 모던 섹션 구조(Section 0~6)로 전면 리디자인한다. 설계 문서의 5단계 마이그레이션 계획에 따라 포맷터 → 프롬프트 → 이메일 빌더 → HTML 파셜 → 텍스트 템플릿 + 통합 테스트 순서로 구현한다.

## Tasks

- [x] 1. Stage 1: 포맷터 + 데이터 모델 (brief_formatting.py)
  - [x] 1.1 새 데이터 모델 타입 정의
    - `brief_formatting.py`에 `SectionMap`, `NewsItemV2`, `SectorMappingItem`, `SectorMapping`, `EventItem`, `MacroIndicator`, `StockItem`, `BTCData` TypedDict 클래스 추가
    - 설계 문서 섹션 1.1의 타입 정의를 그대로 구현
    - 기존 타입(`_SectionGroupState` 등)은 하위 호환을 위해 유지
    - _요구사항: 6.1, 6.2, 7.1_

  - [x] 1.2 `extract_sections()` 섹션 파싱 함수 구현
    - `SECTION_HEADING_V2_RE` 정규식 패턴 추가 (설계 문서 3.1)
    - `SECTION_KEY_MAP` 딕셔너리 정의 (0~6, 4-1~4-3, 5-1~5-3)
    - `extract_sections(body: str) -> SectionMap` 함수 구현
    - 누락된 섹션은 빈 문자열로 처리
    - _요구사항: 6.1, 6.5_

  - [x] 1.3 `serialize_sections()` 직렬화 함수 구현
    - `SECTION_TITLES` 딕셔너리 정의
    - `serialize_sections(section_map: SectionMap) -> str` 함수 구현
    - 라운드트립 속성 보장: `extract_sections(serialize_sections(m)) == m`
    - _요구사항: 6.6_

  - [x] 1.4 `parse_news_items()` 뉴스 파싱 함수 구현
    - `NEWS_ITEM_RE`, `LINK_RE`, `TLDR_RE` 정규식 패턴 추가
    - `_TIER1_SOURCES` 집합 정의 (Reuters, Bloomberg, WSJ, FT, CNBC, CoinDesk)
    - `parse_news_items(section_4_2: str) -> list[NewsItemV2]` 함수 구현
    - ①~⑤ 기준 분할, 헤드라인/본문/링크/TL;DR 추출, 최대 5개
    - _요구사항: 6.2, 4.1, 4.4, 4.5, 4.6_

  - [x] 1.5 `parse_sector_mapping()` 섹터 매핑 파싱 함수 구현
    - `SECTOR_DIRECTION_RE` 정규식 패턴 추가
    - `parse_sector_mapping(section_4_3: str) -> SectorMapping | None` 함수 구현
    - 수혜/압력/중립 3분류 파싱, 3분류 중 하나라도 비면 None 반환
    - _요구사항: 6.3, 13.1, 13.4_

  - [x] 1.6 `parse_event_calendar()` 이벤트 캘린더 파싱 함수 구현
    - `EVENT_LINE_RE` 정규식 패턴 추가
    - `parse_event_calendar(section_6: str) -> list[EventItem]` 함수 구현
    - 오늘 발표 분리, 날짜순 정렬, 5단계 영향도(■□) 파싱
    - _요구사항: 10.1, 10.2_

  - [x] 1.7 기존 `extract_brief_structure()` 하위 호환 유지
    - 기존 함수를 제거하지 않고 내부에서 `extract_sections()` 로 위임하는 래퍼로 변환
    - LAYER 구조 텍스트 감지 시 레거시 파싱으로 자동 폴백
    - _요구사항: 6.5_

  - [x] 1.8 속성 기반 테스트: P1 섹션 파싱 라운드트립
    - **Property 1: 섹션 파싱 라운드트립**
    - 모든 유효한 SectionMap `m`에 대해 `extract_sections(serialize_sections(m)) == m`
    - hypothesis 라이브러리 사용
    - **검증 대상: 요구사항 6.6**

  - [x] 1.9 속성 기반 테스트: P3 뉴스 아이템 파싱 완전성
    - **Property 3: 뉴스 아이템 파싱 완전성**
    - 유효한 Section 4-2 텍스트에 대해 `len(parse_news_items(text)) >= 1`, 모든 아이템에 headline 비어있지 않음, number가 ①~⑤ 중 하나
    - **검증 대상: 요구사항 6.2**

  - [x] 1.10 속성 기반 테스트: P4 섹터 매핑 유효성
    - **Property 4: 섹터 매핑 유효성**
    - `parse_sector_mapping(text)`가 None이 아니면 3분류 모두 1개 이상 항목 존재, 모든 항목에 reason 비어있지 않음
    - **검증 대상: 요구사항 13.4**

- [x] 2. Stage 1 체크포인트
  - Ensure all tests pass, ask the user if questions arise.


- [x] 3. Stage 2: 프롬프트 템플릿 재설계 (brief_instructions.j2, brief_input.j2)
  - [x] 3.1 `brief_instructions.j2` 출력 계약 구조 전면 교체
    - 기존 3-LAYER `<output_contract>` 를 Section 0~6 구조로 교체
    - 설계 문서 2.1의 새 출력 계약 구조 적용
    - Section 0(오늘의 핵심) ~ Section 6(이벤트 캘린더) 전체 구조 정의
    - 조건부 섹션 지시: Section 5-2(sonar_context 존재 시), Section 5-3(x_market_signals 1건+ 시)
    - _요구사항: 5.1, 5.5, 5.7, 5.8_

  - [x] 3.2 `brief_instructions.j2` 문체 규칙 교체
    - 설계 문서 2.1의 `<style_rules>` 적용
    - 친근한 존댓말 어미 ("~이에요", "~네요", "~거든요")
    - 격식체 금지 ("~입니다", "~하였습니다")
    - 금융 전문 용어 부연 설명 필수 지시
    - 숫자 의미 풀어서 설명 지시
    - 분량 제한 제거, 깊이 우선
    - 줄띄기 스타일 가독성 지시
    - _요구사항: 5.9, 5.10, 5.11, 5.12, 5.13, 5.14_

  - [x] 3.3 `brief_instructions.j2` 섹션별 세부 지시 추가
    - Section 4-1: Bloomberg 스타일 서술 단락 (토픽당 3~5문장) 지시
    - Section 4-2: ①~⑤ 번호 + 헤드라인 + 서술 5~8문장 + 원문 링크 + 핵심 한줄 지시
    - Section 4-3: 수혜/압력/중립 3분류 + 판단 근거 한 줄 필수 지시
    - Section 5-1: 요일별 고정 서술 틀 (월/화~목/금) 지시
    - Section 6: 오늘 발표 상단 분리 + 5단계 영향도 지시
    - _요구사항: 5.2, 5.3, 5.4, 5.6, 10.1, 10.2, 13.1, 13.2, 13.3_

  - [x] 3.4 `brief_input.j2` Section 기반 지시로 전환
    - 기존 LAYER 기반 작성 지침을 Section 0~6 기반으로 교체
    - `{% if sonar_context %}` → Section 5-2 생성 지시 추가
    - `{% if x_market_signals %}` → Section 5-3 생성 지시 추가
    - 문체 지시: 격식체 → 친근한 존댓말로 전환
    - 분량 지시: 깊이 우선으로 변경
    - _요구사항: 5.1, 5.7, 5.8_

- [x] 4. Stage 2 체크포인트
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Stage 3: 이메일 빌더 재설계 (emailer.py)
  - [x] 5.1 `_build_snapshot_badges()` 스냅샷 대시보드 빌더 구현
    - S&P 500, 나스닥, BTC, VIX 4개 배지 생성
    - 각 배지에 label, value, direction 키 포함
    - 양수→up, 음수→down, 0→flat 방향 결정
    - 설계 문서 4.2 코드 기반 구현
    - _요구사항: 2.2, 2.3, 2.4, 3.1_

  - [x] 5.2 `_build_btc_data()` BTC 데이터 빌더 구현
    - BTC 현물가, 공포탐욕지수, ETF 목록, 기관 보유 현황 구성
    - 공포탐욕 4단계 레이블링 (0~24 Extreme Fear, 25~49 Fear, 50~74 Greed, 75~100 Extreme Greed)
    - 75 이상 시 "과열 경계" 주석
    - ETF 유입/유출 → "기관 순매수"/"기관 순매도" 레이블
    - 설계 문서 4.3 코드 기반 구현
    - _요구사항: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 5.3 `_build_subject_line()` 메일 제목 생성 로직 구현
    - "[날짜 요일] 브리핑 — [지수 등락] · [BTC 가격] · [핵심 변수]" 형식
    - data_quality.status == critical 시 "[데이터 참고]" 프리픽스
    - `_build_preheader()` 핵심 수치 3개 포함 preheader 생성
    - _요구사항: 12.1, 12.2, 12.3, 9.4_

  - [x] 5.4 `_build_email_context_v2()` 메인 컨텍스트 빌드 함수 구현
    - 설계 문서 4.1의 전체 컨텍스트 빌드 로직 구현
    - `extract_sections()` → 각 파서 호출 → 컨텍스트 딕셔너리 조립
    - 데이터 품질 상태 처리 (ok/degraded/critical)
    - footer_notes 조건부 포함
    - 설계 문서 1.2의 모든 변수 키 반환
    - _요구사항: 1.1, 1.3, 1.4, 6.2, 9.1, 9.2, 9.3_

  - [x] 5.5 거시 지표 및 종목 파서 헬퍼 함수 구현
    - `_parse_macro_indicators(section_1: str) -> list[MacroIndicator]` 구현
    - `_parse_stocks(section_2: str) -> tuple[list[StockItem], list[StockItem]]` 구현
    - `_parse_issue_briefings(section_4_1: str) -> list[dict]` 구현
    - `_parse_sonar(section_5_2: str) -> list[dict] | None` 구현
    - 이상값(anomaly) → "—" 처리, 전일값(is_previous) → True 플래그
    - _요구사항: 1.1, 9.5, 9.6_

  - [x] 5.6 기존 `_build_email_context()` → `_v2` 내부 위임
    - 기존 `_build_email_context()` 함수 내부에서 `_build_email_context_v2()` 호출로 위임
    - `render_briefing_email_html()`, `render_briefing_email_text()`, `build_briefing_message()` 공개 API 시그니처 유지
    - _요구사항: 6.5 (하위 호환)_

  - [x] 5.7 속성 기반 테스트: P2 배지 방향 일관성
    - **Property 2: 배지 방향 일관성**
    - 모든 숫자 문자열 v에 대해: float(v) > 0 → "up", float(v) < 0 → "down", float(v) == 0 → "flat"
    - **검증 대상: 요구사항 2.3, 2.4, 3.1**

  - [x] 5.8 속성 기반 테스트: P5 공포탐욕 레이블 일관성
    - **Property 5: 공포탐욕 레이블 일관성**
    - 모든 정수 v(0~100)에 대해 올바른 레이블 매핑, v >= 75 시 "과열 경계"
    - **검증 대상: 요구사항 7.6, 7.7**

  - [x] 5.9 속성 기반 테스트: P6 데이터 품질 상태 일관성
    - **Property 6: 데이터 품질 상태 일관성**
    - ok → footer_notes 빈 리스트, critical → 제목에 "[데이터 참고]" 포함
    - **검증 대상: 요구사항 9.1, 9.4**

  - [x] 5.10 속성 기반 테스트: P7 스냅샷 배지 개수
    - **Property 7: 스냅샷 배지 개수**
    - 모든 유효한 packet에 대해 len(snapshot_badges) <= 4, 각 배지에 필수 키 존재, direction은 "up"/"down"/"flat" 중 하나
    - **검증 대상: 요구사항 2.2**

- [x] 6. Stage 3 체크포인트
  - Ensure all tests pass, ask the user if questions arise.


- [x] 7. Stage 4: HTML 템플릿 파셜
  - [x] 7.1 `email_macros.html.j2` 공통 매크로 생성
    - `badge(value, direction)` 매크로: 컬러 배지 (상승 #dcfce7/#166534, 하락 #fef2f2/#991b1b, 보합 #f3f4f6/#4b5563)
    - HTML 엔티티 사용: &#9650;(▲), &#9660;(▼), &#8212;(—)
    - ±3% 초과 시 font-weight 800 강조
    - `font-variant-numeric: tabular-nums` 인라인 적용
    - `kr_label()` 매크로: KR 텍스트 배지 (border 1px solid #166534)
    - `section_label(text, color)` 매크로: 섹션 라벨 (border-left 3px)
    - `quality_mark(text)` 매크로: 데이터 품질 인라인 마크 (11px, #94a3b8)
    - _요구사항: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.3, 9.6, 16.6_

  - [x] 7.2 `email_base.html.j2` 마스터 레이아웃 생성
    - `<html lang="ko">`, `<meta name="color-scheme" content="light dark">`
    - MSO 조건부 주석 (border-radius, gradient fallback)
    - `<style>` 블록: 다크 모드 (`prefers-color-scheme: dark`) + 반응형 (max-width: 600px)
    - 다크 모드 색상: 상승 배경 #14532d/텍스트 #4ade80, 하락 배경 #450a0a/텍스트 #fca5a5
    - preheader 숨김 div
    - 600px 이하 모바일 퍼스트 반응형 (싱글 컬럼, 터치 타겟 44px)
    - 한국어 폰트 스택: Apple SD Gothic Neo → Noto Sans KR → Malgun Gothic → Segoe UI → Roboto → sans-serif
    - `{% include %}` 로 모든 파셜 포함, 조건부 섹션 `{% if %}` 제어
    - _요구사항: 1.1, 1.2, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 14.1, 14.4, 15.5, 16.1, 16.4, 16.5_

  - [x] 7.3 `email_header.html.j2` 헤더 + 스냅샷 대시보드 생성
    - 타이포그래피 퍼스트 미니멀 디자인 (letter-spacing 0.08em)
    - 날짜 + 읽기 시간 ("3분 읽기") 표시
    - 그라디언트 액센트 구분선 (Outlook 단색 fallback)
    - 스냅샷 대시보드: S&P 500, 나스닥, BTC, VIX 4개 배지 한 줄 표시
    - `{% from "email_macros.html.j2" import badge %}` 매크로 사용
    - _요구사항: 2.1, 2.2, 2.5, 2.6, 15.4_

  - [x] 7.4 `email_hero.html.j2` 핵심 요약 히어로 섹션 생성
    - border-top 4px solid #1e40af 강조
    - 히어로 제목 32px, font-weight 800, line-height 1.5
    - 배경 #f0f4ff 박스, 패딩 20px
    - 핵심 포인트 별도 줄 배치, 포인트 간 간격 12px+
    - hero_alerts 이상 움직임 bullet 표시
    - 시각적 비중 40% 할당
    - _요구사항: 1.1, 1.2, 1.5, 5.1, 15.1, 15.2, 15.3_

  - [x] 7.5 `email_news.html.j2` 뉴스 카드 반복 블록 생성
    - 3단 구조: 헤드라인(20px, font-weight 800) + 시장 의미(border-left 3px solid #3b82f6) + 한국 투자자 관점(KR 배지)
    - source_tier 1 출처명 font-weight 700 강조
    - 원문 링크 인라인 포함
    - 핵심 한줄 TL;DR (#f0fdf4 배경, #166534 텍스트)
    - 카드 패딩 24px+, 카드 간 간격 16px+
    - 시각적 비중 40% 할당
    - _요구사항: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 15.1, 15.4_

  - [x] 7.6 `email_btc.html.j2` BTC 전용 섹션 생성
    - BTC 현물가 + 공포탐욕지수 표시
    - ETF 5종 테이블 (ticker, 가격, 등락, 거래량)
    - 기관 보유 현황 (official_snapshots 존재 시)
    - 순유입/유출 레이블 (기관 순매수/순매도)
    - 과열 경계 주석 (fear_greed_value >= 75)
    - 조건부 렌더링 (`{% if btc_data %}`)
    - _요구사항: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 16.5_

  - [x] 7.7 `email_market.html.j2` 종목 + 거시 콤팩트 섹션 생성
    - 주요 지수 테이블 (SPY, QQQ, SOXX)
    - 빅테크 10종 콤팩트 표시
    - 거시 지표 테이블 (13~14px 작은 폰트)
    - 이상값 "—" 처리, 전일값 "(전일)" 태그
    - 배경 #f8fafc (콤팩트 보조 섹션 느낌)
    - _요구사항: 1.1, 1.2, 3.1, 9.5, 9.6_

  - [x] 7.8 `email_sector.html.j2` 섹터 매핑 섹션 생성
    - 수혜(▲ #166534) / 압력(▼ #991b1b) / 중립(— #4b5563) 3분류 시각 구분
    - 각 항목에 ticker + 판단 근거 표시
    - 서술 보강 commentary 영역
    - 조건부 렌더링 (`{% if sector_mapping %}`)
    - _요구사항: 13.1, 13.5, 16.5_

  - [x] 7.9 `email_calendar.html.j2` 이벤트 캘린더 섹션 생성
    - 테이블 형식 (시간, 이벤트명, 예상치, 영향도)
    - 오늘 발표 상단 분리 (배경 #f0f9ff)
    - 5단계 영향도 ■□ 표시
    - 이벤트 없으면 섹션 생략 (`{% if event_calendar %}`)
    - _요구사항: 10.1, 10.2, 10.3, 10.4, 16.5_

  - [x] 7.10 `email_footer.html.j2` Footer 생성
    - 데이터 출처 1줄: "데이터: FRED · Stooq · CoinGecko · Perplexity · Grok X Search"
    - 면책 문구 1줄
    - 구독 해지 + GitHub 링크
    - 3줄 이내 통합, 11~12px, 중앙 정렬, #94a3b8
    - 데이터 품질 각주 (degraded/critical 시에만, 11px, #94a3b8)
    - _요구사항: 9.1, 9.2, 9.3, 9.7, 11.1, 11.2, 11.3, 11.4_

  - [x] 7.11 기존 `email.html.j2` → `email_base.html.j2` 리다이렉트
    - 기존 `email.html.j2` 파일을 `{% extends "email_base.html.j2" %}` 또는 `{% include "email_base.html.j2" %}` 래퍼로 변환
    - 하위 호환 유지
    - _요구사항: 16.1_

- [x] 8. Stage 4 체크포인트
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Stage 5: 텍스트 템플릿 + 통합 테스트 + 검증
  - [x] 9.1 `email.txt.j2` 텍스트 템플릿 업데이트
    - 기존 LAYER 구조를 새 Section 0~6 구조에 맞춰 업데이트
    - 섹션별 텍스트 렌더링 (히어로, 뉴스, BTC, 종목, 거시, 섹터 매핑, 이벤트, Footer)
    - 조건부 섹션 처리 (BTC, 섹터 매핑, 이벤트 캘린더, Sonar, X 반응)
    - 데이터 품질 각주 텍스트 버전
    - _요구사항: 1.1, 1.4_

  - [x] 9.2 Jinja2 환경 설정 업데이트
    - `_load_email_environment()` 에서 새 파셜 디렉토리 및 매크로 파일 로드 설정
    - 파셜 간 `{% include %}` 및 `{% from ... import %}` 경로 확인
    - _요구사항: 16.1, 16.4_

  - [x] 9.3 통합 테스트: `_build_email_context_v2()` 전체 흐름
    - 샘플 packet + LLM 출력 텍스트로 전체 컨텍스트 빌드 테스트
    - 모든 변수 키 존재 확인
    - 데이터 품질 상태별 동작 검증 (ok/degraded/critical)
    - _요구사항: 6.2, 9.1, 9.2, 9.3, 9.4_

  - [x] 9.4 렌더링 테스트: 각 파셜 독립 렌더링
    - 각 파셜 파일이 필요한 변수만으로 독립 렌더링 가능한지 확인
    - HTML 출력에 `role="presentation"` 테이블 확인
    - `lang="ko"` 속성 확인
    - 이모지 미사용 확인 (HTML 엔티티만 사용)
    - _요구사항: 14.1, 14.3, 14.4, 16.3_

  - [x] 9.5 접근성 검증 테스트
    - 모든 테이블에 `role="presentation"` 존재 확인
    - 상승/하락 정보: 색상 + 방향 기호(▲/▼/—) 이중 전달 확인
    - CSS ::before 가상 요소, SVG 인라인 미사용 확인
    - _요구사항: 14.1, 14.2, 14.3, 8.8_

  - [x] 9.6 스냅샷 테스트: 전체 HTML 출력 비교
    - 샘플 데이터로 전체 HTML 렌더링 후 스냅샷 저장
    - 라이트 모드 / 다크 모드 CSS 클래스 존재 확인
    - 인라인 스타일 우선 적용 확인
    - _요구사항: 8.3, 8.5_

- [x] 10. V2 HTML 파셜 한국어 라벨 정규화
  - [x] 10.1 V2 HTML 파셜 내 HTML 엔티티로 인코딩된 한국어 텍스트를 실제 한국어 문자로 교체
    - `email_news.html.j2`: `&#xD575;&#xC2EC; &#xB274;&#xC2A4;` → `핵심 뉴스`, `&#xC6D0;&#xBB38; &#xBCF4;&#xAE30;` → `원문 보기`, `&#xD575;&#xC2EC; &#xD55C;&#xC904;` → `핵심 한줄`
    - `email_btc.html.j2`: `&#xACF5;&#xD3EC;&#xD0D0;&#xC695;` → `공포탐욕`, `&#xAC00;&#xACA9;` → `가격`, `&#xB4F1;&#xB77D;` → `등락`, `&#xAC70;&#xB798;&#xB7C9;` → `거래량`, `&#xD569;&#xC0B0; &#xAC70;&#xB798;&#xB7C9;` → `합산 거래량`, `&#xAE30;&#xAD00; &#xBCF4;&#xC720; &#xD604;&#xD669;` → `기관 보유 현황`, `&#xC804;&#xC77C; &#xB300;&#xBE44;` → `전일 대비`
    - `email_sector.html.j2`: `&#xC624;&#xB298; &#xC8FC;&#xBAA9; &#xD750;&#xB984;` → `오늘 주목 흐름`, `&#xC218;&#xD61C; &#xBC29;&#xD5A5;` → `수혜 방향`, `&#xC555;&#xB825; &#xBC29;&#xD5A5;` → `압력 방향`, `&#xC911;&#xB9BD; / &#xAD00;&#xB9DD;` → `중립 / 관망`
    - `email_calendar.html.j2`: `&#xC774;&#xBCA4;&#xD2B8; &#xCE98;&#xB9B0;&#xB354;` → `이벤트 캘린더`, `&#xC2DC;&#xAC04;` → `시간`, `&#xC774;&#xBCA4;&#xD2B8;` → `이벤트`, `&#xC608;&#xC0C1;` → `예상`, `&#xC601;&#xD5A5;&#xB3C4;` → `영향도`, `&#xC624;&#xB298; &#xBC1C;&#xD45C;` → `오늘 발표`
    - `email_header.html.j2`: 이미 한국어 문자 사용 중 (확인만)
    - `email_market.html.j2`: `&#xC2DC;&#xC7A5; &#xC9C0;&#xD45C;` → `시장 지표`, `&#xBE45;&#xD14C;&#xD06C; 10&#xC885;` → `빅테크 10종`, `&#xAC70;&#xC2DC; &#xC9C0;&#xD45C;` → `거시 지표`
    - `email_footer.html.j2`: `&#xB370;&#xC774;&#xD130;` → `데이터`, `&#xBCF8; &#xBA54;&#xC77C;...` → 면책 문구 한국어 원문, `&#xAD6C;&#xB3C5; &#xD574;&#xC9C0;` → `구독 해지`
    - _요구사항: 5.9, 14.4_

  - [x] 10.2 V2 HTML 파셜 한국어 라벨 정규화 테스트
    - 각 V2 파셜 렌더링 결과에 한국어 라벨이 올바르게 표시되는지 확인
    - HTML 엔티티 `&#x` 패턴이 한국어 텍스트 영역에 남아있지 않은지 확인
    - _요구사항: 5.9, 14.4_

- [x] 11. 최종 체크포인트
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. CI 파이프라인 검증
  - [x] 12.1 전체 테스트 로컬 통과 확인
  - [x] 12.2 커밋 및 푸시 (pre-commit ruff format/check 통과)
  - [x] 12.3 GitHub Actions 파이프라인 실행 및 전체 통과 확인
  - [x] 11.1 PBT P1~P7 속성 기반 테스트 전체 구현 및 로컬 통과 확인
    - `tests/test_pbt_email_redesign.py` 생성 (7개 테스트)
    - P1 섹션 라운드트립, P2 배지 방향, P3 뉴스 파싱, P4 섹터 매핑, P5 공포탐욕, P6 데이터 품질, P7 배지 개수
  - [x] 11.2 커밋 및 푸시 (pre-commit ruff format/check 통과)
    - 커밋: `feat: 이메일 브리핑 V2 리디자인 전면 구현 + PBT P1~P7`
    - 16 files changed, 1527 insertions(+), 138 deletions(-)
  - [x] 11.3 GitHub Actions 파이프라인 실행 및 전체 통과 확인
    - Run ID: 23207509079
    - Check formatting ✓, Run lint ✓, Run tests ✓, Run pipeline ✓
    - 21개 스텝 전체 success

## Notes

- `*` 표시된 태스크는 선택 사항이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 추적 가능성을 위해 특정 요구사항을 참조함
- 체크포인트는 단계별 점진적 검증을 보장함
- 속성 기반 테스트(P1~P7)는 보편적 정확성 속성을 검증함
- 단위 테스트는 특정 예제와 엣지 케이스를 검증함
- 기존 공개 API 시그니처는 모두 유지하여 하위 호환성을 보장함
