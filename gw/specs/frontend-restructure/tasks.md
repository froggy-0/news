# Implementation Plan: frontend-restructure

## Overview

dead code 제거 → 컴포넌트 단순화 → 페이지 재구성 → 신규 컴포넌트 순으로 진행한다.
제거 작업을 먼저 해서 타입 오류를 조기에 잡고, 이후 변경이 깨끗한 베이스 위에서 이뤄지도록 한다.
각 Checkpoint에서 `npm run lint`(TS 타입 검사)와 `npm run build:fixture`(정적 빌드)를 통과해야 다음 단계로 넘어간다.

---

## Tasks

### Phase 1 — Dead Code 제거 (R4, R5)

- [x] 1. `lib/history.ts` — status card 타입·함수 제거
  - `DrawerStatusCard` 타입 삭제
  - `buildMetaStatusCards` 함수 삭제
  - `qualityLabel`, `translationLabel` import 삭제 (history.ts 내에서만 사용, format.ts 함수 자체는 유지)
  - _Requirements: R5.1_

- [x] 2. `SiteHeader.tsx` — statusCards prop 제거
  - `statusCards: DrawerStatusCard[]` prop 시그니처 삭제
  - `DrawerStatusCard` import 삭제
  - `HistoryDrawerClient`에 `statusCards` 전달하는 코드 삭제
  - _Requirements: R5.2_

- [x] 3. `HistoryDrawerClient.tsx` — statusCards param 제거
  - `statusCards: _statusCards` 파라미터 삭제
  - `DrawerStatusCard` import 삭제
  - _Requirements: R5.3_

- [x] 4. `app/archive/page.tsx` — latestBrief 불필요 fetch 제거
  - `fetchBriefByDate` import 삭제
  - `latestBrief` 변수 및 `fetchBriefByDate(index.dates[0])` 호출 삭제
  - `buildMetaStatusCards` import 및 호출 삭제
  - `SiteHeader`에서 `statusCards` prop 전달 제거
  - fallback statusCards 객체 리터럴도 함께 삭제
  - _Requirements: R5.4_

- [x] 5. `app/archive/[date]/page.tsx` — statusCards 전달 제거
  - `buildMetaStatusCards` import 및 호출 삭제
  - `SiteHeader`에서 `statusCards` prop 전달 제거
  - _Requirements: R5.2_

- [x] 6. `app/page.tsx` — statusCards 전달 제거
  - `buildMetaStatusCards` import 및 호출 삭제
  - `SiteHeader`에서 `statusCards` prop 전달 제거
  - _Requirements: R5.2_

- [x] 7. `TerminalPanel.tsx` — 2개 라인 제거
  - `lines` 배열에서 뉴스/X 수집 건수 라인(3번째) 삭제
  - `lines` 배열에서 번역 상태 라인(4번째) 삭제
  - `qualityLabel`, `translationLabel` import 삭제 (TerminalPanel에서만 제거, ArchiveDateList·MetadataSection은 유지)
  - `sourceCounts`, `dataQuality`, `translationStatus` 참조 제거
  - _Requirements: R4.1, R4.2, R4.3_

- [x] 8. **Checkpoint 1** — dead code 제거 검증
  - `cd frontend && npm run lint` → 타입 오류 0개 확인
  - `npm run build:fixture` → 빌드 성공 확인
  - `grep -r 'statusCards' frontend/components frontend/app` 결과 0건 확인

---

### Phase 2 — variant="home" 제거 (R3)

- [x] 9. `JudgmentBlock.tsx` — variant 제거
  - `variant` prop 및 타입 선언 삭제
  - section className: 항상 `border-b border-white/10 px-6 py-16`
  - container: 항상 `max-w-6xl`
  - 내부 `max-w-4xl` 분기 → `max-w-4xl` 단일값 유지 (detail 기준)
  - _Requirements: R3.1, R3.2, R3.3_

- [x] 10. `TopicGrid.tsx` — variant 제거
  - `variant` prop 및 타입 선언 삭제
  - 그리드 className: 항상 `md:grid-cols-2`
  - 첫 번째 카드 `md:col-span-2 xl:col-span-2` 조건부 span 제거
  - 텍스트 사이즈 분기 제거 → 항상 `text-[15px] leading-8`
  - _Requirements: R3.1, R3.2, R3.3_

- [x] 11. `StocksBoard.tsx` — variant 제거 + copy 교체
  - `variant` prop 및 타입 선언 삭제
  - `compactMetrics` / `compactStocks` 슬라이싱 로직 삭제 → 항상 전체 항목 사용
  - 지표 그리드: 항상 `lg:grid-cols-4 xl:grid-cols-7`
  - 기술주 그리드: 항상 `xl:grid-cols-5`
  - "홈에서는 핵심 두 개 지표만..." → `"전체 지표를 한눈에 확인합니다."`
  - "대표 종목 네 개만 먼저 보여주고..." → `"주요 기술주의 시세와 등락을 확인합니다."`
  - 상승/하락 legend 항상 렌더링 (기존 detail 분기 코드 그대로 유지)
  - _Requirements: R3.1, R3.2, R3.3, R3.4_

- [x] 12. `BitcoinPanel.tsx` — variant 제거
  - `variant` prop 및 타입 선언 삭제
  - `compactHome` 변수 및 compact 카드 그리드 분기 전체 삭제
  - 항상 detail view (가격 + 공포탐욕 + ETF 테이블) 렌더링
  - _Requirements: R3.1, R3.2, R3.3_

- [x] 13. `NewsFeed.tsx` — variant 제거
  - `variant` prop 및 타입 선언 삭제
  - home 분기 (`NewsFeedClient` 호출) 삭제
  - 항상 detail view (전체 뉴스 리스트) 렌더링
  - `NewsFeedClient` import 삭제 (파일 자체는 삭제하지 않음)
  - `showRawTitle` prop 유지
  - _Requirements: R3.1, R3.2, R3.3_

- [x] 14. `XSignals.tsx` — variant 제거
  - `variant` prop 및 타입 선언 삭제
  - home 분기 (`XSignalsClient` 호출) 삭제
  - 항상 detail view (전체 시그널 리스트) 렌더링
  - 빈 상태 헤딩 분기 제거 → 항상 `"전체 X 시그널"` / `"Full Signal Flow"`
  - `XSignalsClient` import 삭제 (파일 자체는 삭제하지 않음)
  - `showRawToggle` prop 유지
  - _Requirements: R3.1, R3.2, R3.3_

- [x] 15. `app/archive/[date]/page.tsx` — variant="detail" call site 정리
  - `StocksBoard`에서 `variant="detail"` prop 제거
  - `NewsFeed`에서 `variant="detail"` prop 제거
  - `XSignals`에서 `variant="detail"` prop 제거
  - `JudgmentBlock`, `BitcoinPanel`, `TopicGrid`는 이미 variant 없이 호출 중 — 변경 불필요
  - _Requirements: R3.2_

- [x] 16. **Checkpoint 2** — variant 제거 검증
  - `npm run lint` → 타입 오류 0개 확인
  - `npm run build:fixture` → 빌드 성공 확인
  - `grep -r 'variant.*home' frontend/components` → 0건 확인
  - `grep -r 'variant.*detail' frontend/app` → 0건 확인

---

### Phase 3 — 페이지 재구성 (R1, R2)

- [x] 17. `HomeHero.tsx` — CTA 변경 + 구독 앵커 추가
  - prop 추가: `latestDate: string`
  - "오늘 브리프 먼저 읽기" CTA href: `#brief` → `` `/archive/${latestDate}` ``
  - "뉴스 흐름 보기" CTA `<a>` 태그 전체 삭제
  - CTA 버튼 감싸는 flex 컨테이너 정리 (버튼 1개 기준)
  - SubscriptionForm 감싸는 카드 div에 `id="subscribe"` 추가
  - _Requirements: R1.2, R1.3_

- [x] 18. `app/page.tsx` — 랜딩 전용으로 단순화
  - 삭제 import: `JudgmentBlock`, `TopicGrid`, `StocksBoard`, `BitcoinPanel`, `NewsFeed`, `XSignals`
  - JSX에서 위 6개 컴포넌트 제거
  - `HomeHero`에 `latestDate={brief.meta.date}` prop 추가
  - `buildHistoryEntries` 호출 유지 (HistoryDrawer용)
  - `fetchLatest()` + `fetchIndex()` 호출 유지
  - _Requirements: R1.1, R1.2, R1.4, R1.5_

- [x] 19. **Checkpoint 3** — 페이지 재구성 검증
  - `npm run lint` → 타입 오류 0개 확인
  - `npm run build:fixture` → 빌드 성공 확인
  - `npm run dev:fixture` 실행 후 `/` 접근 → HomeHero만 렌더링 확인
  - `/archive` 날짜 클릭 → `/archive/[date]` 전체 브리프 데이터 렌더링 확인
  - "오늘 브리프 읽기" CTA 클릭 → `/archive/{latest-date}`로 이동 확인

---

### Phase 4 — BottomTabBar 신규 구현 (R6)

- [x] 20. `components/layout/BottomTabBar.tsx` — 신규 생성
  - `"use client"` 선언
  - `usePathname()`으로 활성 탭 판단
    - 홈: `pathname === "/"`
    - 아카이브: `pathname.startsWith("/archive")`
    - 구독: 항상 비활성 (navigate 역할만)
  - 탭 구성 (lucide-react 아이콘):
    - 홈(`/`) — `HomeIcon`
    - 아카이브(`/archive`) — `ArchiveIcon`
    - 구독(`/#subscribe`) — `MailIcon`
  - 스타일:
    - `fixed bottom-0 inset-x-0 z-[65] md:hidden`
    - `border-t border-white/10 bg-black/85 backdrop-blur-md`
    - 각 탭: `flex-1 flex flex-col items-center justify-center gap-1 min-h-[56px]`
    - 활성: `text-white`, 비활성: `text-white/40`
    - 아이콘: `h-5 w-5`, 라벨: `text-[10px] font-mono uppercase tracking-[0.08em]`
  - _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5, R6.7_

- [x] 21. `globals.css` — iOS safe area 지원 클래스 추가
  - 다음 CSS 추가:
    ```css
    @supports (padding-bottom: env(safe-area-inset-bottom)) {
      .bottom-tab-safe {
        padding-bottom: env(safe-area-inset-bottom);
      }
    }
    ```
  - `BottomTabBar`의 최외곽 div에 `bottom-tab-safe` 클래스 적용
  - _Requirements: R6.5_

- [x] 22. `app/layout.tsx` — BottomTabBar 통합 + 모바일 패딩
  - `BottomTabBar` import 추가
  - `<BottomTabBar />` 를 `page-shell` 안, `page-inner` 밖에 배치 (full-width 보장)
  - `page-inner` div에 `pb-14 md:pb-0` 추가 (탭 바 높이 56px 확보)
  - _Requirements: R6.3, R6.6, R6.7_

- [x] 23. **Checkpoint 4 (최종)** — 전체 통합 검증
  - `npm run lint` → 타입 오류 0개 확인
  - `npm run build:fixture` → 빌드 성공 확인
  - `npm test` → 기존 테스트 통과 확인
  - 모바일 뷰포트(375px)에서 하단 탭 바 표시 확인
  - 데스크탑 뷰포트(1280px)에서 탭 바 미표시 확인
  - 탭 바 영역만큼 콘텐츠 하단 패딩 적용되어 가려지지 않음 확인
  - 구독 탭 클릭 → `/#subscribe` 이동 → SubscriptionForm 스크롤 확인
  - _Requirements: R6 전체_
