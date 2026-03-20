# Design — 금융 뉴스 데일리 프론트 페이지

> Version 2.0 | 2026-03-21
> 기준 Requirements: `docs/specs/requirements.md`

---

## 요약

이 설계는 현재 저장소의 **Python 브리핑 파이프라인**과 **Vite 기반 프론트 프로토타입**을 기준으로, 목표 상태인 **Next.js App Router + R2 JSON + Cloudflare Pages** 구조를 정의한다.

핵심 원칙은 세 가지다.

1. 프론트는 **순수 표시 레이어**로 동작한다.
2. 데이터 계약은 `schema/brief.types.ts` 를 기준으로 고정한다.
3. 핵심 섹션은 값이 없어도 상태를 드러내고, 보조 섹션만 숨긴다.

---

## 1. 현재 저장소와 목표 상태

### 현재 상태

- 파이프라인 서브시스템은 `src/morning_brief` 에 있다.
- GitHub Actions 공개 워크플로우는 현재 `.github/workflows/morning-brief.yml` 이다.
- `frontend/` 는 Vite + React 기반의 AI Studio 프로토타입이다.
  - `frontend/src/App.tsx`
  - `frontend/src/main.tsx`
  - `frontend/src/index.css`
  - `frontend/package.json`
- 아직 `schema/brief.types.ts` 는 없다.
- 아직 프론트 전용 배포 워크플로우와 R2 fetch 계층도 없다.

### 목표 상태

- 파이프라인은 계속 `src/morning_brief` 를 사용한다.
- 프론트는 `frontend/` 아래 Next.js App Router 구조로 교체한다.
- JSON 계약은 `schema/brief.types.ts` 로 고정한다.
- 파이프라인은 날짜별 JSON과 최신 JSON을 게시하고, 프론트는 그것을 읽어 정적 페이지를 빌드한다.

---

## 2. 목표 아키텍처

### 서브시스템 구분

| 서브시스템 | 실제 위치 | 역할 |
| --- | --- | --- |
| Pipeline | `src/morning_brief/` | 데이터 수집, 브리핑 생성, 품질 상태 생성, JSON 게시 |
| Frontend | `frontend/` | Next.js SSG 렌더링, 아카이브, RSS, `llms.txt` |
| Schema | `schema/` | 파이프라인과 프론트가 공유하는 JSON 계약 |

### 게시 흐름

```text
morning-brief.yml
  → 파이프라인 실행
  → 브리핑/시장/뉴스 결과 생성
  → 날짜별 JSON 게시
  → latest.json 갱신
  → index.json 갱신
  → frontend 빌드/배포 트리거
```

### 저장 구조

```text
briefs/
  latest.json
  2026-03-21.json
  2026-03-20.json
index.json
```

---

## 3. 프론트 목표 구조

### 디렉토리

```text
frontend/
  app/
    layout.tsx
    page.tsx
    archive/
      page.tsx
      [date]/
        page.tsx
    rss.xml/
      route.ts
    llms.txt/
      route.ts
    globals.css
  components/
    layout/
    brief/
    market/
    news/
    signals/
    bitcoin/
    ui/
  lib/
    r2.ts
    brief-schema.ts
    format.ts
  public/
  next.config.ts
  package.json
  tsconfig.json
postcss.config.mjs
schema/
  brief.types.ts
```

### 마이그레이션 원칙

- 현재 `frontend/src/*` 와 Vite 진입점은 교체 대상이다.
- 기존 프로토타입의 시각 요소는 필요할 때만 이식한다.
- Gemini, Express, dotenv 같은 프로토타입 전용 의존성은 목표 구조에 포함하지 않는다.

---

## 4. 데이터 계약

### 계약 기준

- 계약의 단일 기준 파일은 `schema/brief.types.ts`
- 파이프라인은 이 스키마에 맞는 JSON을 게시해야 한다.
- 프론트는 이 계약을 읽고 runtime validation 을 수행한다.
- validation 방식은 **가벼운 TypeScript validator 함수**로 고정한다. 별도 스키마 런타임 라이브러리는 1차 범위에서 도입하지 않는다.

### 상위 스키마

```ts
export interface BriefIndex {
  dates: string[];
  updatedAt: string;
}

export interface BriefData {
  meta: BriefMeta;
  marketSnapshot: MarketSnapshot;
  aiJudgment: AIJudgment;
  topicSummaries: TopicSummary[];
  techStocks: TechStock[];
  bitcoin: BitcoinSection;
  xSignals: XSignal[] | null;
  news: NewsItem[];
}
```

### 메타와 품질 상태

```ts
export interface BriefMeta {
  date: string;
  generatedAt: string;
  dataQuality: 'ok' | 'degraded' | 'critical';
  qualityNotes: string[];
}
```

### 시장 스냅샷

```ts
export interface MarketSnapshot {
  items: TickerItem[];
}

export interface TickerItem {
  symbol: string;
  label: string;
  value: string | null;
  change: string | null;
  trend: 'up' | 'down' | 'neutral' | null;
  isCached: boolean;
  history: number[];
}
```

### 브리핑과 토픽

```ts
export interface AIJudgment {
  headline: string;
  body: string;
}

export interface TopicSummary {
  topic: 'macro' | 'bigtech' | 'bitcoin' | 'us-stocks';
  label: string;
  summary: string;
  keyMetric: string | null;
  relatedStocks: string[] | null;
}
```

### 종목, 뉴스, X 시그널

```ts
export interface TechStock {
  symbol: string;
  name: string;
  price: string | null;
  change: string | null;
  trend: 'up' | 'down' | 'neutral' | null;
  absChangeNum: number | null;
  isCached: boolean;
}

export interface NewsItem {
  id: string;
  publishedAt: string;
  category: 'macro' | 'bigtech' | 'bitcoin' | 'us-stocks';
  title: string;
  interpretation: string | null;
  source: string;
  sourceTier: 'tier1' | 'standard';
  url: string;
  urgency: 'high' | 'medium' | 'low';
  tags: string[];
}

export interface XSignal {
  id: string;
  postedAt: string;
  impact: string;
  sentiment: 'bullish' | 'bearish' | 'neutral';
  content: string;
}
```

### 비트코인 섹션

```ts
export interface BitcoinSection {
  price: string | null;
  change: string | null;
  trend: 'up' | 'down' | 'neutral' | null;
  fearGreedIndex: FearGreedIndex | null;
  etf: BTCEtfSection | null;
}

export interface FearGreedIndex {
  value: number;
  label: string;
}

export interface BTCEtfSection {
  totalHolding: string | null;
  totalAum: string | null;
  issuers: BTCEtfIssuer[];
}

export interface BTCEtfIssuer {
  name: string;
  holding: string | null;
  aum: string | null;
  sourceUrl: string;
}
```

### 현재 파이프라인 packet 과의 매핑

| 현재 packet | 목표 계약 |
| --- | --- |
| `macro`, `korea_watch`, `us_indices`, `bitcoin.spot` | `marketSnapshot.items` |
| `tech_stocks` | `techStocks` |
| `bitcoin.fear_greed_value`, `bitcoin.fear_greed_label` | `bitcoin.fearGreedIndex` |
| `bitcoin.official_etf_total_btc`, `bitcoin.official_etf_total_aum_usd`, `bitcoin.official_etf_snapshots` | `bitcoin.etf` |
| `data_footer_notes` | `meta.qualityNotes` 또는 품질 주석 표시용 메타 |

이 매핑은 구현 단계에서 파이프라인 게시 JSON 정규화 작업으로 반영한다.

---

## 5. 페이지와 렌더링 규칙

### 경로

| 경로 | 역할 | 데이터 |
| --- | --- | --- |
| `/` | 최신 브리핑 랜딩 | `briefs/latest.json` |
| `/archive` | 날짜 목록 | `index.json` |
| `/archive/[date]` | 날짜별 상세 | `briefs/YYYY-MM-DD.json` |
| `/rss.xml` | RSS 피드 | `index.json` + 날짜별 JSON |
| `/llms.txt` | AI 친화 텍스트 | 정적 또는 생성형 텍스트 |

### 핵심 블록

아래 블록은 값이 부족해도 숨기지 않는다.

- 오늘의 판단
- 상단 핵심 수치
- 브리핑 본문
- 주요 뉴스
- BTC 핵심 블록

값이 없을 때는 `이번 집계에서는 확인되지 않았어요` 또는 `N/A` 같은 상태 문구를 노출한다.

### 보조 블록

아래 블록은 값이 없으면 숨길 수 있다.

- 일부 토픽 카드
- X 시그널
- ETF 발행사 상세 현황

### 품질 상태 표시

| 조건 | 동작 |
| --- | --- |
| `dataQuality === 'ok'` | 경고 배너 없음 |
| `dataQuality === 'degraded'` | 상단 품질 배너 표시 |
| `dataQuality === 'critical'` | 품질 배너 + 본문 신뢰도 경고 표시 |
| `value === null` | 빈칸 금지, `N/A` 또는 상태 표시 |
| `isCached === true` | `CACHED` 표시 |
| `xSignals === null` | X 시그널 섹션 미노출 |

### 아카이브 규칙

- `/archive` 목록 페이지에는 TickerBar 를 표시하지 않는다.
- `/archive/[date]` 상세는 메인과 같은 정보 구조를 따른다.

---

## 6. 데이터 접근 계층

### fetch 유틸

`frontend/lib/r2.ts`

```ts
export async function fetchLatest(): Promise<BriefData>
export async function fetchBriefByDate(date: string): Promise<BriefData>
export async function fetchIndex(): Promise<BriefIndex>
```

### validation 유틸

`frontend/lib/brief-schema.ts`

- JSON shape 확인
- 필수 필드 누락 시 에러 throw 또는 degraded fallback 처리
- 날짜 문자열과 품질 상태 문자열 검증

---

## 7. CI/CD 목표 구조

### 현재 유지되는 워크플로우

- `.github/workflows/morning-brief.yml`
  - 현재 파이프라인 실행 기준
  - 브리핑 생성, 메일 발송, 아티팩트 산출 담당

### 추가될 워크플로우

- `frontend.yml`
  - R2 최신 JSON 및 인덱스 fetch
  - Next.js 정적 빌드
  - Cloudflare Pages 배포

### 운영 기준

- 공개 브리핑 경험은 KST 08:00 기준
- 파이프라인 실패 시 프론트는 기존 공개본 유지

---

## 8. 테스트와 검증 기준

### 계약 검증

- `schema/brief.types.ts` 기준 fixture validation
- Python 출력과 프론트 입력 사이 필드 일치 여부 확인

### 프론트 검증

- 최신 JSON 렌더링
- `ok`, `degraded`, `critical` 상태별 표시 차이
- null 데이터와 cached 데이터 렌더링
- `/archive/[date]` 정적 경로 생성

### 빌드 검증

- `frontend` 빌드 성공
- RSS 생성
- `llms.txt` 제공
- Cloudflare Pages 대상 산출 성공

---

## 9. 현재 저장소와 목표 상태 차이

현재 구현자는 아래 차이를 항상 의식해야 한다.

1. `frontend/` 는 아직 Vite 프로토타입이며, 목표는 Next.js 다.
2. `schema/brief.types.ts` 는 아직 없고 새로 도입해야 한다.
3. 현재 공개 워크플로우는 `morning-brief.yml` 하나이며, 프론트 배포 워크플로우는 새로 추가해야 한다.
4. 구독/수신거부는 이번 범위에 포함되지 않는다.

