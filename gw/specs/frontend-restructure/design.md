# Design — frontend-restructure

## Overview

6개 Requirements를 16개 파일 변경으로 구현한다.
핵심 원칙: 새 파일은 `BottomTabBar.tsx` 하나만 추가하고, 나머지는 기존 파일에서 코드를 제거하는 방향으로 진행한다.

---

## 변경 파일 목록

| 파일 | 변경 유형 | 관련 Req |
|------|-----------|----------|
| `app/page.tsx` | 대폭 단순화 | R1, R3, R5 |
| `app/archive/page.tsx` | dead code 제거 | R5 |
| `app/archive/[date]/page.tsx` | dead code 제거 | R5 |
| `app/layout.tsx` | BottomTabBar 추가, 모바일 패딩 | R6 |
| `components/hero/HomeHero.tsx` | CTA 변경, id 추가, prop 변경 | R1 |
| `components/hero/TerminalPanel.tsx` | 라인 2개 제거 | R4 |
| `components/layout/SiteHeader.tsx` | statusCards prop 제거 | R5 |
| `components/layout/HistoryDrawerClient.tsx` | statusCards param 제거 | R5 |
| `components/layout/BottomTabBar.tsx` | **신규 생성** | R6 |
| `components/brief/JudgmentBlock.tsx` | variant 제거 | R3 |
| `components/brief/TopicGrid.tsx` | variant 제거 | R3 |
| `components/market/StocksBoard.tsx` | variant 제거, copy 교체 | R3 |
| `components/bitcoin/BitcoinPanel.tsx` | variant 제거 | R3 |
| `components/news/NewsFeed.tsx` | variant 제거 | R3 |
| `components/signals/XSignals.tsx` | variant 제거 | R3 |
| `lib/history.ts` | buildMetaStatusCards, DrawerStatusCard 제거 | R5 |

---

## 설계 상세

### R1 — app/page.tsx 단순화

**현재**: `fetchLatest()` + `fetchIndex()` → HomeHero + JudgmentBlock + StocksBoard + BitcoinPanel + TopicGrid + NewsFeed + XSignals

**변경 후**: `fetchLatest()` + `fetchIndex()` → HomeHero만

```
// 제거할 import들
- JudgmentBlock, TopicGrid, BriefBody
- StocksBoard, BitcoinPanel
- NewsFeed, XSignals

// 유지
+ fetchLatest() → brief.meta.date (latestDate), brief.meta.displayHeadline (heroHeadline)
+ fetchIndex() → historyEntries (HistoryDrawer 공급)
```

**왜 fetchLatest()를 유지하나**: HomeHero의 "오늘의 핵심 판단" 카드가 헤드라인과 CTA 날짜를 필요로 함.
**왜 fetchIndex()를 유지하나**: SiteHeader의 HistoryDrawer가 전체 날짜 목록을 필요로 함.

---

### R1 — HomeHero.tsx CTA 변경

**prop 변경**: `heroSeed` 유지, `latestDate: string` prop 추가

```
// 현재
<a href="#brief" className="hero-cta-primary">오늘 브리프 먼저 읽기</a>
<a href="#news" className="hero-cta-secondary">뉴스 흐름 보기</a>

// 변경 후
<a href={`/archive/${latestDate}`} className="hero-cta-primary">오늘 브리프 읽기</a>
// "뉴스 흐름 보기" 제거
```

**구독 폼 앵커 추가**: BottomTabBar "구독" 탭이 `/#subscribe`로 링크하므로, SubscriptionForm 감싸는 카드 div에 `id="subscribe"` 추가.

---

### R3 — variant 제거 컴포넌트별 상세

#### JudgmentBlock
- `variant` prop 제거 (기본값 "detail"이었으므로 항상 detail 동작)
- section: 항상 `border-b border-white/10 px-6 py-16`
- container: 항상 `max-w-6xl`
- 내부 `max-w-4xl` → `max-w-4xl` (detail 기준 그대로 유지)

#### StocksBoard
- `variant` prop 제거
- `compactMetrics`/`compactStocks` 슬라이싱 로직 제거 → 항상 전체 표시
- 그리드: 항상 `lg:grid-cols-4 xl:grid-cols-7` (metrics), `xl:grid-cols-5` (stocks)
- 홈 참조 문구 교체:
  - "홈에서는 핵심 두 개 지표만..." → "전체 지표를 한눈에 확인합니다."
  - "대표 종목 네 개만 먼저 보여주고..." → "주요 기술주의 시세와 등락을 확인합니다."

#### BitcoinPanel
- `variant` prop 제거
- `compactHome` 분기 전체 제거 (compact 카드 그리드 view)
- 항상 detail view (가격 + 공포탐욕 + ETF 테이블) 렌더링

#### TopicGrid
- `variant` prop 제거
- 그리드: 항상 `md:grid-cols-2` (detail 기준)
- 첫 번째 카드 `md:col-span-2 xl:col-span-2` span 제거
- 텍스트 사이즈 분기 제거: 항상 `text-[15px] leading-8`

#### NewsFeed
- `variant` prop 제거
- home 분기(`NewsFeedClient` 호출) 제거
- 항상 detail view 렌더링 (전체 뉴스 리스트)
- **주의**: `showRawTitle` prop은 유지 (기능적으로 별개)

#### XSignals
- `variant` prop 제거
- home 분기(`XSignalsClient` 호출) 제거
- 항상 detail view 렌더링 (전체 시그널 리스트)
- 빈 상태 섹션 헤딩: "실시간 X 시그널" / "전체 X 시그널" 분기 → 항상 "전체 X 시그널"로 단일화
- **주의**: `showRawToggle` prop은 유지

---

### R4 — TerminalPanel 간소화

`lines` 배열에서 3, 4번 항목 제거:

```
// 제거
{ text: `뉴스 ${meta.sourceCounts.newsCandidates}건 / X ...`, type: "INFO", ... }
{ text: `번역 상태 ${translationLabel(meta.translationStatus)} ...`, type: "ANALYSIS", ... }

// 유지
{ text: "system.intelligence — sovereign brief", type: "SYSTEM" }
{ text: `발행 기준일 ${meta.date} · 생성 시각 ${formatIssueTime(meta.generatedAt)} KST`, type: "INFO", ... }
```

`translationLabel`, `qualityLabel` import도 함께 제거.

---

### R5 — Status card dead code 제거

#### lib/history.ts
- `DrawerStatusCard` 타입 삭제
- `buildMetaStatusCards` 함수 삭제
- `qualityLabel`, `translationLabel` import 삭제 (다른 곳에서 미사용 확인 후)

#### SiteHeader.tsx
- `statusCards: DrawerStatusCard[]` prop 제거
- `buildMetaStatusCards` import 제거

#### HistoryDrawerClient.tsx
- `statusCards: _statusCards` 파라미터 제거 (이미 unused였음)
- `DrawerStatusCard` import 제거

#### app/archive/page.tsx
```
// 제거
- latestBrief 변수 (fetchBriefByDate 호출)
- buildMetaStatusCards 호출
- statusCards prop 전달

// 단순화 후
const index = await fetchIndex();
const items = await Promise.all(index.dates.map(...fetchArchiveSummaryByDate));
// SiteHeader에 statusCards 없이 historyEntries만 전달
```

#### app/page.tsx, app/archive/[date]/page.tsx
- `buildMetaStatusCards` 호출 및 `statusCards` prop 전달 제거

---

### R6 — BottomTabBar 신규 구현

#### 컴포넌트 구조
```
components/layout/BottomTabBar.tsx  ← "use client"
```

**탭 정의:**
```
[
  { label: "홈",     href: "/",         icon: HomeIcon },
  { label: "아카이브", href: "/archive",  icon: ArchiveIcon },
  { label: "구독",   href: "/#subscribe", icon: MailIcon },
]
```

**활성 상태 판단:**
- `usePathname()` 사용
- `홈`: pathname === "/"
- `아카이브`: pathname.startsWith("/archive")
- `구독`: 항상 비활성 (외부 링크 역할, 클릭 시 `/`로 이동)

**스타일:**
```
fixed bottom-0 inset-x-0 z-[65]   ← SiteHeader(z-70) 아래, 일반 콘텐츠 위
md:hidden                          ← 데스크탑에서 숨김
border-t border-white/10
bg-black/85 backdrop-blur-md
h-14 (56px)
safe-area: pb-safe (iOS 홈 인디케이터 대응)
```

**탭 아이템:**
```
- 세로 정렬: icon + label 텍스트
- 아이콘 크기: h-5 w-5
- 라벨: 10px, font-mono, uppercase, tracking-[0.08em]
- 활성: text-white / icon stroke white
- 비활성: text-white/40 / icon stroke white/40
- 터치 타겟: flex-1, min-h-[56px]
```

#### layout.tsx 통합

```tsx
// 추가
import { BottomTabBar } from "@/components/layout/BottomTabBar";

// page-inner에 모바일 하단 패딩 추가
<div className="page-inner pb-14 md:pb-0">
  {children}
  <SiteFooter />
</div>
<BottomTabBar />   ← page-shell 내부, page-inner 밖
```

**왜 page-inner 밖에 배치하나**: `page-inner`는 max-width 제한이 있지만 BottomTabBar는 full-width여야 하므로.

#### iOS Safe Area 대응

`globals.css`에 추가:
```css
@supports (padding-bottom: env(safe-area-inset-bottom)) {
  .bottom-tab-bar {
    padding-bottom: env(safe-area-inset-bottom);
  }
}
```

또는 Tailwind `pb-safe` 유틸리티 사용 (Next.js 15 + Tailwind v4 환경에서 확인 필요).

---

## 데이터 흐름 변경 요약

### 변경 전
```
app/page.tsx
  fetchLatest() → brief (전체 데이터)
  fetchIndex()  → index
  → HomeHero + 6개 데이터 섹션

app/archive/page.tsx
  fetchIndex()
  fetchBriefByDate(dates[0]) → latestBrief (statusCards용)
  Promise.all(dates.map(fetchArchiveSummaryByDate))
```

### 변경 후
```
app/page.tsx
  fetchLatest() → brief.meta.date, brief.meta.displayHeadline (랜딩 최소 데이터)
  fetchIndex()  → index (HistoryDrawer용)
  → HomeHero만

app/archive/page.tsx
  fetchIndex()
  Promise.all(dates.map(fetchArchiveSummaryByDate))
  // latestBrief 호출 제거
```

---

## 영향 없는 파일

- `app/archive/[date]/page.tsx` — statusCards 제거 외 구조 변경 없음
- `components/news/NewsFeedClient.tsx` — NewsFeed에서 더 이상 호출 안 하지만 파일 자체는 유지 (삭제는 별도 cleanup)
- `components/signals/XSignalsClient.tsx` — 동일
- `lib/r2.ts`, `lib/format.ts` — 변경 없음
- `schema/brief.types.ts` — 변경 없음
