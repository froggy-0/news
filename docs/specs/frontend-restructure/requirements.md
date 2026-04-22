# Requirements — frontend-restructure

## Introduction

현재 `/`(홈)에 랜딩 콘텐츠와 브리프 전체 데이터가 혼재해 UX가 복잡하다.
랜딩을 순수 진입점으로 분리하고, 브리프 콘텐츠는 `/archive/[date]` 단일 라우트로 통일한다.
아울러 `variant="home"` 분기·미사용 status card 코드를 제거해 컴포넌트를 단순화하고,
모바일 하단 탭 바를 도입해 엄지 손가락 탐색을 개선한다.

## Glossary

- **랜딩 페이지**: `/` — 서비스 소개 + 구독 유도만 담당하는 순수 진입점
- **상세 페이지**: `/archive/[date]` — 브리프 전체 데이터를 보여주는 유일한 뷰
- **아카이브 목록**: `/archive` — 날짜별 발행본 인덱스
- **latest-date**: 빌드 타임 `fetchLatest()`로 확정되는 최신 발행일
- **하단 탭 바**: 모바일(md 미만)에서만 표시되는 고정 하단 네비게이션

---

## Requirements

### Requirement 1: 랜딩 페이지 콘텐츠 분리

**User Story:**
As a 신규 방문자,
I want 진입 시 서비스 소개와 구독 폼만 보고,
so that 핵심 메시지에 집중하고 브리프로 자연스럽게 이동할 수 있다.

#### Acceptance Criteria

1. WHEN 사용자가 `/`에 접근하면, THE 페이지 SHALL `HomeHero`(H1, "오늘의 핵심 판단" 카드, 구독 폼, TerminalPanel)만 렌더링하고 `JudgmentBlock`, `StocksBoard`, `BitcoinPanel`, `TopicGrid`, `NewsFeed`, `XSignals`를 렌더링하지 않는다.
2. WHEN `HomeHero`의 "오늘 브리프 먼저 읽기" CTA를 클릭하면, THE 링크 SHALL `/archive/{latest-date}`로 이동한다 (빌드 타임 `fetchLatest()` 주입).
3. THE "뉴스 흐름 보기" CTA SHALL 제거된다.
4. THE `app/page.tsx` SHALL `fetchLatest()`와 `fetchIndex()` 두 가지를 빌드 타임에 호출한다 (`fetchLatest()`는 헤드라인·latest-date 주입용, `fetchIndex()`는 HistoryDrawer 공급용).
5. THE 랜딩 페이지 SHALL 의도적으로 미니멀하게 유지하며 추가 섹션을 삽입하지 않는다.

---

### Requirement 2: 브리프 상세 뷰 단일화

**User Story:**
As a 구독자,
I want 최신·과거 브리프를 동일한 URL 패턴(`/archive/[date]`)으로 읽고,
so that 일관된 경험을 갖는다.

#### Acceptance Criteria

1. THE `/archive/[date]` SHALL `JudgmentBlock`, `StocksBoard`, `BitcoinPanel`, `BriefBody`, `TopicGrid`, `NewsFeed`, `XSignals`를 모두 렌더링한다.
2. THE `/archive/[date]` SHALL 최신 발행일과 과거 발행일에 동일한 레이아웃을 적용한다.
3. THE `SiteHeader`의 variant 레이블 SHALL 최신·과거 날짜 무관하게 동일하게 표시한다 (별도 "최신" 표시 없음).

---

### Requirement 3: `variant="home"` dead code 제거

**User Story:**
As a 개발자,
I want 사용되지 않는 `variant="home"` 분기를 제거하고,
so that 컴포넌트 복잡도를 줄이고 단일 동작으로 단순화한다.

#### Acceptance Criteria

1. THE `StocksBoard`, `NewsFeed`, `XSignals`, `JudgmentBlock`, `TopicGrid`, `BitcoinPanel` SHALL `variant="home"` 분기 코드를 포함하지 않는다.
2. IF `variant` prop이 잔존하면, THE 컴포넌트 SHALL 단일 동작(기존 `detail` 기준)만 수행하거나 prop 자체를 제거한다.
3. THE 제거 후 기존 `variant="detail"` 동작이 유지된다.
4. THE `StocksBoard`의 기술주 섹션 설명 문구 SHALL "홈"을 언급하지 않는 단일 맥락 텍스트로 교체된다.

---

### Requirement 4: TerminalPanel 간소화

**User Story:**
As a 방문자,
I want TerminalPanel에서 핵심 정보만 보고,
so that 과도한 기술 지표 없이 발행 컨텍스트를 빠르게 파악한다.

#### Acceptance Criteria

1. THE `TerminalPanel` SHALL `system.intelligence — sovereign brief` 라인과 `발행 기준일 · 생성 시각` 라인, 총 2줄만 표시한다.
2. THE "뉴스 N건 / X N건 정합성 점검" 라인 SHALL 제거된다.
3. THE "번역 상태" 라인 SHALL 제거된다.

---

### Requirement 5: 미사용 status card 코드 제거

**User Story:**
As a 개발자,
I want `buildMetaStatusCards`, `DrawerStatusCard`, `statusCards` prop 체인을 제거하고,
so that `HistoryDrawerClient`에서 이미 사용하지 않는 dead code를 없앤다.

#### Acceptance Criteria

1. THE `lib/history.ts` SHALL `buildMetaStatusCards` 함수와 `DrawerStatusCard` 타입을 포함하지 않는다.
2. THE `SiteHeader` SHALL `statusCards` prop을 받지 않는다.
3. THE `HistoryDrawerClient` SHALL `statusCards` prop을 받지 않는다.
4. THE `/archive` 페이지 SHALL `statusCards` 생성 목적의 `fetchBriefByDate` 호출을 포함하지 않는다.

---

### Requirement 6: 모바일 하단 탭 바

**User Story:**
As a 모바일 사용자,
I want 화면 하단에 고정된 탭 바로 주요 페이지를 엄지 손가락으로 탐색하고,
so that 상단 헤더까지 손을 올리지 않고 빠르게 이동할 수 있다.

#### Acceptance Criteria

1. THE 하단 탭 바 SHALL 뷰포트 너비 `md`(768px) 미만에서만 표시된다.
2. THE 하단 탭 바 SHALL 세 개의 탭(`홈` → `/`, `아카이브` → `/archive`, `구독` → `/#subscribe` 앵커로 이동 후 구독 폼 포커스)을 포함한다.
3. THE 하단 탭 바 SHALL 화면 하단에 고정(`position: fixed, bottom: 0`)되며 페이지 콘텐츠 위에 z-index로 표시된다.
4. THE 현재 활성 경로에 해당하는 탭 SHALL 시각적으로 활성 상태로 표시된다.
5. THE 하단 탭 바의 높이 SHALL 최소 56px 이상으로 터치 타겟을 확보한다.
6. THE 하단 탭 바가 표시될 때, THE 페이지 콘텐츠 SHALL 탭 바 높이만큼 하단 패딩을 추가해 가려지지 않도록 한다.
7. THE 데스크탑(md 이상)에서는 기존 `SiteHeader`의 HistoryDrawer가 네비게이션을 담당하며 하단 탭 바는 렌더링되지 않는다.

---

## 결정 사항 요약

| 항목 | 결정 |
|------|------|
| 랜딩 페이지 길이 | 의도적 미니멀 (추가 섹션 없음) |
| 상세 페이지 헤더 레이블 | 최신·과거 무관 동일 ("Archive Detail") |
| 모바일 CTA 버튼 너비 | 현행 유지 (full-width 변경 없음) |
| 하단 탭 바 대상 | 모바일 전용 (md 미만) |
| 하단 탭 구성 | 홈 / 아카이브 / 구독 |
| 구독 탭 동작 | `/#subscribe` 앵커 이동 후 폼 포커스 |
