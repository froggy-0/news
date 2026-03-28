# Implementation Plan: Frontend SSG Redesign Migration

## Overview

이 작업은 운영 프론트의 SSG 구조와 JSON 계약을 유지한 채, `sovereign-brief/` 샘플의 시각 언어와 상호작용을 `frontend/`에 이식하는 마이그레이션이다. 구현은 전역 디자인 시스템과 상단 크롬을 먼저 고정한 뒤, 홈 히어로와 데이터 섹션, 아카이브, 공개 산출물, 회귀 검증 순서로 진행한다.

## Tasks

- [x] 1. Stage 1: 전역 디자인 시스템과 폰트 기반 교체
  - [x] 1.1 `frontend/app/layout.tsx`의 폰트 로딩을 샘플 기준 계층으로 재구성한다
    - `Pretendard + Inter + JetBrains Mono + Instrument Serif` 기준으로 전역 폰트 변수와 fallback 전략을 정리한다
    - 외부 CDN 의존 없이 self-host 또는 문서화된 fallback 경로를 준비한다
    - _Requirements: 2, 3, 14, 16_
  - [x] 1.2 `frontend/app/globals.css`를 샘플 디자인 토큰 기준으로 재정렬한다
    - 색상, 간격, border density, radius, glow, scanline, blur, hover, CTA, drawer 스타일 토큰을 정리한다
    - 페이지별 스타일 복붙이 아니라 공용 primitive가 재사용할 수 있는 CSS 계층으로 구성한다
    - _Requirements: 2, 14, 16_
  - [x] 1.3 공용 레이아웃 기반 요소를 새 디자인 시스템에 맞게 정리한다
    - `ScrollProgressBar`, 푸터 표면, 공통 shell, panel, section primitive를 새 토큰으로 옮긴다
    - 이후 홈/아카이브/상세가 동일 토큰을 공유하도록 기준 컴포넌트를 준비한다
    - _Requirements: 2, 14, 17_

- [x] 2. Stage 1 검증: 디자인 시스템과 빌드 기반 회귀 확인
  - [x] 2.1 정적 빌드 스모크 검증을 수행한다
    - `cd frontend && npm run lint`
    - `cd frontend && npm run build:fixture`
    - 폰트 로딩, 전역 스타일, 기본 레이아웃 적용으로 인해 라우팅이나 정적 export가 깨지지 않는지 확인한다
    - _Requirements: 1, 14, 16_
  - [x] 2.2 샘플 대비 시각 토대가 맞는지 확인한다
    - 상단 진행바, 배경 질감, scanline, 기본 타이포그래피 인상이 샘플과 유사한지 빠르게 대조한다
    - _Requirements: 2, 14_

- [x] 3. Stage 2: 공용 상단 크롬과 히스토리 메뉴 이식
  - [x] 3.1 `frontend/components/layout/SiteHeader.tsx`를 샘플 기반 상단 크롬 구조로 대체하거나 분리한다
    - 메뉴 버튼, 상단 상태 라벨, 날짜/시간 블록, variant별 카피를 새 구조에 맞게 재설계한다
    - 홈/아카이브 목록/아카이브 상세에서 동일 컴포넌트를 재사용할 수 있게 props를 정리한다
    - _Requirements: 2, 5, 13, 14_
  - [x] 3.2 히스토리 메뉴 클라이언트 아일랜드를 구현한다
    - `HistoryDrawerClient` 또는 동등 구조를 만들고 `isOpen`, `visibleCount`, 오버레이, ESC 닫기, 포커스 복귀를 처리한다
    - 메뉴 데이터는 클라이언트 fetch가 아니라 서버에서 `BriefIndex`를 읽어 props로 전달한다
    - _Requirements: 1, 5, 15, 16_
  - [x] 3.3 홈, `/archive`, `/archive/[date]` 페이지 엔트리에 히스토리 메뉴 데이터를 연결한다
    - `fetchIndex()`를 공유해 현재 날짜 여부와 이동 링크를 일관되게 만든다
    - `/archive` 페이지도 홈과 동일한 메뉴 경험을 제공하도록 연결한다
    - _Requirements: 5, 13, 15_

- [x] 4. Stage 2 검증: 히스토리 메뉴 동작과 접근성 확인
  - [x] 4.1 메뉴 상호작용 검증 시나리오를 추가한다
    - 홈, 아카이브 목록, 아카이브 상세 각각에서 메뉴 열기/닫기/더보기/날짜 이동 시나리오를 검증한다
    - ESC 닫기, 오버레이 클릭 닫기, 포커스 이동을 확인한다
    - _Requirements: 5, 13, 16_
  - [x] 4.2 빌드 타임 데이터 연결 회귀를 확인한다
    - `generateStaticParams()` 결과와 히스토리 메뉴에 노출되는 날짜 집합이 일치하는지 점검한다
    - _Requirements: 1, 5, 15_

- [x] 5. Checkpoint - 상단 크롬 기반 완료
  - 디자인 시스템, 상단 크롬, 히스토리 메뉴가 SSG 구조를 깨지 않고 홈/아카이브 경로에서 공통으로 동작해야 한다
  - _검증: `npm run lint`, `npm run build:fixture`, 메뉴 수동 확인 또는 Playwright 시나리오 통과_

- [x] 6. Stage 3: 홈 히어로와 구독 입력 UI 샘플 충실도 이식
  - [x] 6.1 홈 히어로 전용 컴포넌트를 구현한다
    - 샘플 기준의 headline 계층, scatter text, 보조 카피, CTA, 레이아웃 밀도를 홈 첫 화면에 이식한다
    - reduced motion 환경에서 모션 없이도 정보 위계가 유지되도록 fallback을 둔다
    - _Requirements: 2, 3, 16_
  - [x] 6.1.1 `데이터 인텔리전스` ScatterText 효과를 샘플 충실도로 이식한다
    - 샘플의 흩어졌다 모이는 텍스트 효과를 별도 클라이언트 컴포넌트로 구현하거나 이식한다
    - 단순 fade/slide로 대체하지 않고, 샘플과 같은 인상의 문자 단위 분산/재조합 효과를 우선 보존한다
    - _Requirements: 2, 3_
  - [x] 6.2 샘플의 터미널 효과를 홈 전용 클라이언트 컴포넌트로 이식한다
    - 타이핑 애니메이션과 상태 라인을 구현하되, 운영 계약에 없는 fake 수치는 넣지 않는다
    - visual feel은 유지하되 실제 메타 또는 고정 안내 문구 수준으로 제한한다
    - _Requirements: 2, 3, 12, 16_
  - [x] 6.3 기존 구독 처리 흐름을 홈 히어로 UI에 연결한다
    - 현재 `SubscriptionForm`의 제출 로직을 재사용 가능한 hook/helper로 분리하거나 동등 구조로 옮긴다
    - 샘플 입력 UI/CTA 스타일 안에서 `submitting`, `success`, `error`, 입력 초기화 동작을 유지한다
    - _Requirements: 3, 4, 16_

- [x] 7. Stage 3 검증: 히어로와 구독 흐름 회귀 확인
  - [x] 7.1 구독 API/서비스 회귀 테스트를 유지 및 보강한다
    - 기존 `subscription-service`, `subscriptions-api` 테스트를 유지하고, 새 hero 입력 UI와 연결돼도 동작 의미가 바뀌지 않는지 확인한다
    - _Requirements: 4_
  - [x] 7.2 홈 히어로 인터랙션 검증을 수행한다
    - 이메일 입력, 제출 버튼 상태, 성공/오류 메시지, 터미널/모션 fallback을 검증한다
    - _Requirements: 3, 4, 16_

- [x] 8. Stage 4: 홈 데이터 섹션 재구성
  - [x] 8.1 홈 요약/정량 지표/테마 섹션을 샘플 언어로 재설계한다
    - `JudgmentBlock`, `StocksBoard`, `BitcoinPanel`, `TopicGrid`를 샘플의 시각 언어에 맞게 재작성하거나 분해한다
    - 데이터 계약에 없는 `Fear & Greed history`, fake status, mock values는 도입하지 않는다
    - _Requirements: 2, 6, 7, 8, 9, 12, 15_
  - [x] 8.2 홈 뉴스/X/데이터 상태 섹션을 샘플 언어로 재설계한다
    - featured/all 토글이 필요하면 홈에서만 클라이언트 아일랜드로 제한한다
    - 뉴스와 X 시그널은 별도 섹션으로 유지하고, 메타데이터/품질 상태는 하단 보조 레이어로 정리한다
    - 샘플 드로어의 하단 상태 블록은 fake `Uptime/Latency` 대신 `dataQuality`, `translationStatus`, `sourceCounts` 기반 운영 카드로 치환한다
    - _Requirements: 2, 6, 10, 11, 12, 16_
  - [x] 8.3 홈 페이지 조립을 새 정보 구조 기준으로 재배치한다
    - 순서를 `요약 → 정량 지표 → 테마 → 뉴스 → X 시그널 → 데이터 상태`로 고정한다
    - optional 섹션은 숨기되 핵심 블록은 상태 문구와 함께 유지한다
    - _Requirements: 6, 7, 8, 9, 10, 11, 12_

- [x] 9. Stage 4 검증: 홈 데이터 렌더링 회귀 확인
  - [x] 9.1 fixture 기반 홈 렌더링 검증을 추가한다
    - `ok`, `degraded`, `critical`, optional section 없음, cached 값 포함 케이스에서 레이아웃이 무너지지 않는지 확인한다
    - _Requirements: 6, 7, 8, 9, 10, 11, 12, 15_
  - [x] 9.2 홈의 featured/all 및 상태 노출 규칙을 점검한다
    - 뉴스/X 토글, 품질 배너, 선택 섹션 숨김 규칙을 검증한다
    - _Requirements: 10, 11, 12, 16_

- [x] 10. Checkpoint - 홈 페이지 충실도 완료
  - 홈 첫 화면이 샘플의 인상과 상호작용을 유지하면서도 운영 JSON 계약과 SSG 요구를 만족해야 한다
  - _검증: 홈 수동 비교, `npm run lint`, `npm test`, `npm run build:fixture`_

- [x] 11. Stage 5: 아카이브 상세/목록과 공개 산출물 보존
  - [x] 11.1 `/archive/[date]` 상세 페이지를 새 구조에 맞게 재구성한다
    - 상단 크롬, 요약, 정량 보드, 본문, 토픽, 전체 뉴스, 전체 X 시그널을 상세 밀도에 맞게 정리한다
    - 현재 `BriefBody`, `StocksBoard`, `BitcoinPanel`, `NewsFeed`, `XSignals`를 샘플 디자인 언어로 통합한다
    - _Requirements: 5, 6, 7, 8, 9, 10, 11, 12, 13_
  - [x] 11.2 `/archive` 목록 페이지를 새 구조에 맞게 재구성한다
    - 날짜 목록, 발행 시각, 품질 상태, headline 노출을 샘플 톤에 맞게 다시 배치한다
    - 홈/상세와 동일한 상단 메뉴 경험을 유지한다
    - _Requirements: 5, 13, 14, 16_
  - [x] 11.3 공개 부가 산출물과 진입점을 유지한다
    - 상세 본문의 markdown download, 푸터 링크, `rss.xml`, `llms.txt`, 페이지 metadata/공유 metadata를 유지한다
    - 디자인 변경으로 접근 경로나 노출 위치가 바뀌더라도 기능 자체는 사라지지 않게 한다
    - 홈 메타데이터의 `description`은 `글로벌 마켓 데이터의 정교한 연결, 원본의 무결성으로 완성하는 투자 주권.` 고정 문구를 사용한다
    - _Requirements: 17_

- [x] 12. Stage 5 검증: 아카이브/산출물 회귀 확인
  - [x] 12.1 정적 라우트와 메타데이터를 검증한다
    - `/archive`, `/archive/[date]`, `generateStaticParams`, `generateMetadata`가 모두 새 구조에서 정상 동작하는지 확인한다
    - _Requirements: 1, 5, 13, 17_
  - [x] 12.2 공개 산출물과 다운로드 경로를 검증한다
    - `rss.xml`, `llms.txt`, markdown download 진입점, 푸터 링크가 유지되는지 확인한다
    - _Requirements: 17_

- [x] 13. Stage 6: hydration 경계 정리와 잔여 회귀 방지
  - [x] 13.1 클라이언트 아일랜드 범위를 최종 정리한다
    - 메뉴 드로어, 히어로 효과, 터미널, 구독 입력, 홈 featured/all 토글 등 실제 상호작용에만 hydration을 남긴다
    - 서버에서 렌더링 가능한 섹션은 client 컴포넌트 의존을 제거한다
    - _Requirements: 1, 15, 16_
  - [x] 13.2 더 이상 쓰이지 않는 이전 디자인 흔적을 정리한다
    - 구형 헤더/히어로/스타일/보조 컴포넌트가 남아 혼동을 주지 않도록 정리한다
    - 단, 구독 API, 정적 산출물, 데이터 계층처럼 유지해야 할 구조는 건드리지 않는다
    - _Requirements: 1, 14, 17_
  - [x] 13.3 버전 업그레이드와 본 작업을 분리한다
    - 이번 브랜치에서는 Next.js/React 메이저 업그레이드를 수행하지 않고, 디자인 이식과 회귀 검증에만 집중한다
    - _Requirements: 1, 2_

- [x] 14. Stage 6 검증: 전체 회귀와 시각 QA 완료
  - [x] 14.1 전체 자동 검증을 수행한다
    - `cd frontend && npm run lint`
    - `cd frontend && npm test`
    - `cd frontend && npm run build:fixture`
    - _Requirements: 1, 15, 17_
  - [x] 14.2 Playwright 및 수동 시각 비교를 수행한다
    - `cd frontend && npm run qa:playwright`
    - 홈/아카이브 목록/아카이브 상세를 샘플과 나란히 비교해 메뉴, 히어로, `데이터 인텔리전스` ScatterText 효과, 입력 UI, 터미널, 섹션 밀도, hover/glow/scanline 인상을 검증한다
    - _Requirements: 2, 3, 4, 5, 6, 13, 16_

- [x] 15. Checkpoint - 최종 완료 기준 확인
  - 운영 프론트가 Next.js SSG 구조를 유지한 채 샘플 디자인과 상호작용을 높은 충실도로 재현해야 한다
  - 데이터 계약, 구독 처리, 공개 산출물, 메타데이터, 아카이브 경로에 회귀가 없어야 한다
  - _검증: `npm run lint`, `npm test`, `npm run build:fixture`, `npm run qa:playwright` 결과 기록_
