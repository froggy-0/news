# R2 JSON 저장 기준

## 목적

이 문서는 현재 프론트엔드가 실제로 읽는 값을 기준으로, 백엔드가 R2에 어떤 JSON 파일을 어떤 형태로 올려야 하는지 정리합니다.

핵심 원칙은 두 가지입니다.

1. 공개 프론트는 **이메일용 원시 packet**을 그대로 읽지 않습니다.
2. 공개 프론트는 `schema/brief.types.ts` 기준의 **정규화된 JSON 계약**만 읽습니다.

즉, 백엔드는 이메일 렌더링용 값과 공개 프론트용 값을 분리해 생각해야 합니다.

## 현재 프론트가 실제로 읽는 R2 경로

현재 프론트의 데이터 진입점은 `frontend/lib/r2.ts`입니다.

- `index.json`
- `briefs/{YYYY-MM-DD}.json`

예시:

```text
https://<R2_PUBLIC_BASE_URL>/index.json
https://<R2_PUBLIC_BASE_URL>/briefs/2026-03-21.json
```

## 파일별 계약

### 1. `index.json`

아카이브 목록과 정적 경로 생성을 위해 필요합니다.

```json
{
  "dates": ["2026-03-21", "2026-03-20", "2026-03-19"],
  "updatedAt": "2026-03-21T00:18:00Z"
}
```

필드:

| 경로 | 타입 | 필수 | 용도 |
|---|---|---:|---|
| `dates` | `string[]` | 예 | `/archive`, `generateStaticParams` |
| `updatedAt` | `string` | 예 | 상단 발행 시각 표시 |

### 2. `briefs/{date}.json`

홈 화면과 아카이브 상세가 함께 쓰는 날짜별 브리핑입니다.

홈은 `index.json`의 최신 날짜를 읽어 해당 날짜 JSON을 사용합니다.

## 공개 브리프 JSON 루트 스키마

공개 프론트는 아래 구조를 기대합니다.

```json
{
  "meta": {},
  "marketSnapshot": {},
  "aiJudgment": {},
  "topicSummaries": [],
  "techStocks": [],
  "bitcoin": {},
  "featuredXSignals": [],
  "allXSignals": [],
  "featuredNews": [],
  "allNews": []
}
```

기준 파일:

- `schema/brief.types.ts`
- `frontend/lib/brief-schema.ts`

## 루트 필드별 저장 기준

### `meta`

```json
{
  "date": "2026-03-21",
  "generatedAt": "2026-03-21T00:18:00Z",
  "dataQuality": "ok",
  "qualityNotes": [],
  "displayHeadline": "오늘은 관망 국면입니다.",
  "sourceCounts": {
    "newsCandidates": 18,
    "newsRanked": 12,
    "newsFeatured": 5,
    "newsAll": 12,
    "xSignalCandidates": 8,
    "xSignalRanked": 8,
    "xSignalFeatured": 5,
    "xSignalAll": 8
  },
  "translationStatus": "ok"
}
```

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `meta.date` | `string` | 예 | `YYYY-MM-DD` |
| `meta.generatedAt` | `string` | 예 | ISO8601 |
| `meta.dataQuality` | `"ok" \| "degraded" \| "critical"` | 예 | 품질 배지 |
| `meta.qualityNotes` | `string[]` | 예 | 품질 경고 목록 |
| `meta.displayHeadline` | `string` | 예 | 목록과 hero용 정리 headline |
| `meta.sourceCounts` | `object` | 예 | public 후보/featured/full 개수 추적 |
| `meta.translationStatus` | `"ok" \| "partial" \| "failed"` | 예 | 공개 텍스트 번역 상태 |

### `marketSnapshot`

```json
{
  "items": [
    {
      "symbol": "US10Y",
      "label": "미국 10년물",
      "value": "4.32%",
      "change": "+6bp",
      "trend": "up",
      "isCached": false,
      "history": [4.21, 4.24, 4.28, 4.32]
    }
  ]
}
```

`marketSnapshot.items`는 홈 상단 티커와 지수 heatmap의 공용 데이터입니다.

중요:

- 공개 화면에서는 `items.length >= 3`일 때만 상단 티커를 노출합니다.
- 0~2개만 남으면 `marketSnapshot.items`는 빈 배열로 내리고, 아래 시장/BTC 카드만 유지합니다.

각 item 필드:

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `symbol` | `string` | 예 | 프론트는 심볼로 필터링 |
| `label` | `string` | 예 | 한국어 표시명 |
| `value` | `string \| null` | 예 | 값 없으면 `null` |
| `change` | `string \| null` | 예 | 예: `+6bp`, `-1.43%` |
| `trend` | `"up" \| "down" \| "neutral" \| null` | 예 | 색상/톤 |
| `isCached` | `boolean` | 예 | 캐시 대체 표시 |
| `history` | `number[]` | 예 | sparkline 용, 없어도 빈 배열은 필요 |

## 대시보드에 반드시 있어야 하는 단순 수치

### 상단 티커용 심볼

홈 화면 상단 티커는 아래 심볼을 **직접 고정 목록으로 필터링**합니다.

- `US10Y`
- `DXY`
- `VIX`
- `KRW`
- `NQ1!`
- `BTC`

이 값이 빠지면 홈 상단 티커에 해당 항목이 아예 나오지 않습니다.

### 지수 heatmap용 심볼

홈 화면 지수 보드는 아래 심볼을 **직접 고정 목록으로 필터링**합니다.

- `SPX`
- `QQQ`
- `SOXX`

이 값이 빠지면 `미국 증시 흐름`의 핵심 지수 보드가 비게 됩니다.

### 히트맵/스파크라인 품질 권장

다음 필드는 단순 수치처럼 보여도 UX에 직접 쓰입니다.

| 필드 | 용도 | 권장 |
|---|---|---|
| `value` | 큰 숫자 본문 | 필수 |
| `change` | 색상/방향/부호 | 필수 |
| `trend` | 히트맵 톤 | 필수 |
| `history` | sparkline | 지수 심볼에는 사실상 필수 |

즉, 단순한 값이라도 공개 대시보드에 들어갈 항목은 **문자열 수치 + 방향 + 히스토리**까지 같이 저장하는 편이 맞습니다.

## `aiJudgment`

```json
{
  "headline": "오늘은 관망 국면입니다.",
  "body": "오늘은 관망 국면입니다.\n\n금리 상방 압력이...",
  "summaryLead": "장기 금리가 다시 올라 위험자산의 밸류에이션 부담이 커졌습니다.",
  "summarySupport": "반도체 중심으로 선별 강세가 이어질 수 있습니다."
}
```

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `headline` | `string` | 예 | hero headline |
| `body` | `string` | 예 | 본문 markdown |
| `summaryLead` | `string` | 예 | 홈 판단 카드의 첫 요약 |
| `summarySupport` | `string \| null` | 예 | 홈 판단 카드의 보조 요약 |

권장:

- `headline`은 한 줄 결론
- `body`는 상세에서 읽는 정제된 최종 브리핑 markdown
- 홈은 `headline + summaryLead + summarySupport`만 사용

## `topicSummaries`

```json
[
  {
    "topic": "macro",
    "label": "거시",
    "summary": "금리와 달러 강세가 기술주에 부담을 줬습니다.",
    "keyMetric": "미국 10년물 4.32%",
    "relatedStocks": ["QQQ", "SOXX"]
  }
]
```

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `topic` | `"macro" \| "bigtech" \| "bitcoin" \| "us-stocks"` | 예 | 고정 enum |
| `label` | `string` | 예 | 한국어 표시명 |
| `summary` | `string` | 예 | 카드 본문 |
| `keyMetric` | `string \| null` | 예 | 핵심 수치 |
| `relatedStocks` | `string[] \| null` | 예 | 관련 티커 |

권장:

- 4개 토픽 모두 제공
  - `macro`
  - `bigtech`
  - `bitcoin`
  - `us-stocks`

## `techStocks`

```json
[
  {
    "symbol": "NVDA",
    "name": "NVIDIA",
    "price": "$119.53",
    "change": "-1.22%",
    "trend": "down",
    "absChangeNum": 1.22,
    "isCached": false
  }
]
```

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `symbol` | `string` | 예 | 티커 |
| `name` | `string` | 예 | 종목명 |
| `price` | `string \| null` | 예 | 없으면 `null` |
| `change` | `string \| null` | 예 | 없으면 `null` |
| `trend` | `"up" \| "down" \| "neutral" \| null` | 예 | 색상/톤 |
| `absChangeNum` | `number \| null` | 예 | 정렬/후속 확장용 |
| `isCached` | `boolean` | 예 | 캐시 표시 |

권장:

- 5종 이상 유지
- `price`, `change`, `trend`는 가급적 모두 채움

## `bitcoin`

```json
{
  "price": "$84,120",
  "change": "+2.31%",
  "trend": "up",
  "fearGreedIndex": {
    "value": 63,
    "label": "탐욕"
  },
  "etf": {
    "totalHolding": "983,240.13 BTC",
    "totalAum": "$98,422,000,000",
    "issuers": [
      {
        "name": "IBIT",
        "holding": "568,120.54 BTC",
        "aum": "$57,900,000,000",
        "sourceUrl": "https://..."
      }
    ]
  }
}
```

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `price` | `string \| null` | 예 | BTC 현물 |
| `change` | `string \| null` | 예 | 변동률 |
| `trend` | `"up" \| "down" \| "neutral" \| null` | 예 | 색상/톤 |
| `fearGreedIndex` | object or `null` | 예 | 값 없으면 `null` |
| `fearGreedIndex.value` | `number` | 조건부 | 0~100 |
| `fearGreedIndex.label` | `string` | 조건부 | 한국어 라벨 |
| `etf` | object or `null` | 예 | 값 없으면 `null` |
| `etf.totalHolding` | `string \| null` | 예 | 공식 합계만 |
| `etf.totalAum` | `string \| null` | 예 | 공식 합계만 |
| `etf.issuers` | array | 예 | 발행사 목록 |
| `etf.issuers[].name` | `string` | 예 | 운용사/ETF명 |
| `etf.issuers[].holding` | `string \| null` | 예 | 공식 보유량 |
| `etf.issuers[].aum` | `string \| null` | 예 | 공식 AUM |
| `etf.issuers[].sourceUrl` | `string` | 예 | 공식 링크. 없으면 빈 문자열 |

중요:

- 현재 공개 프론트는 **총 보유량**과 **총 AUM**만 전면 노출합니다.
- stale 추정치, 환산치, 순유입 추정값은 공개 JSON에 넣지 않는 편이 맞습니다.

## `featuredXSignals` / `allXSignals`

```json
[
  {
    "id": "amd-2026-03-21-1",
    "postedAt": "2026-03-20T23:40:00Z",
    "impact": "반도체 수급 기대를 자극할 수 있습니다.",
    "sentiment": "bullish",
    "content": "..."
  }
]
```

또는

```json
null
```

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `featuredXSignals` | `XSignal[] \| null` | 예 | 홈 노출용 최대 5건 |
| `allXSignals` | `XSignal[] \| null` | 예 | 상세 노출용 최대 12건 |
| `id` | `string` | 조건부 | 리스트 key |
| `postedAt` | `string` | 조건부 | ISO8601 |
| `impact` | `string` | 조건부 | 시장 영향 |
| `sentiment` | `"bullish" \| "bearish" \| "neutral"` | 조건부 | 톤 |
| `content` | `string` | 조건부 | 한국어 우선 공개 요약 |
| `rawContent` | `string \| null` | 조건부 | 상세에서만 보조 노출할 영어 원문 |

중요:

- 현재 화면은 `featuredXSignals === null` 또는 빈 배열이면 섹션을 숨깁니다.
- 홈은 `featuredXSignals`만, 상세는 `allXSignals`를 사용합니다.

## `featuredNews` / `allNews`

```json
[
  {
    "id": "macro-2026-03-21-1",
    "publishedAt": "2026-03-20T22:00:00Z",
    "category": "macro",
    "title": "연준 위원 발언 이후 금리 경계가 다시 강해졌습니다.",
    "interpretation": "한국 투자자 기준으로 성장주 할인율 부담이 다시 커질 수 있습니다.",
    "summaryKo": "고금리 환경이 성장주 할인율 부담을 키웁니다.",
    "rawTitle": null,
    "source": "Reuters",
    "sourceTier": "tier1",
    "url": "https://...",
    "urgency": "high",
    "tags": ["금리", "연준"]
  }
]
```

| 경로 | 타입 | 필수 | 비고 |
|---|---|---:|---|
| `featuredNews` | `NewsItem[]` | 예 | 홈 노출용 최대 5건 |
| `allNews` | `NewsItem[]` | 예 | 상세 노출용 최대 12건 |
| `id` | `string` | 예 | 리스트 key |
| `publishedAt` | `string` | 예 | ISO8601 |
| `category` | `"macro" \| "bigtech" \| "bitcoin" \| "us-stocks"` | 예 | 고정 enum |
| `title` | `string` | 예 | 한국어 우선 headline |
| `interpretation` | `string \| null` | 예 | 한국어 한 줄 해석 |
| `summaryKo` | `string \| null` | 예 | 홈/상세 공통 표시용 한국어 제목 |
| `rawTitle` | `string \| null` | 예 | 영어 원문 제목 보존용 |
| `source` | `string` | 예 | 브랜드/출처명 |
| `sourceTier` | `"tier1" \| "standard"` | 예 | 중요도 |
| `url` | `string` | 예 | 원문 링크 |
| `urgency` | `"high" \| "medium" \| "low"` | 예 | 강조도 |
| `tags` | `string[]` | 예 | 태그 |

권장:

- `featuredNews`는 5건
- `allNews`는 최대 12건
- 기본 표시는 `summaryKo` 우선
- 영어 원문은 `rawTitle`로 분리하고 상세에서만 보조 노출
- publish 품질 gate를 통과하지 못하면 `featuredNews`, `allNews`는 빈 배열이 될 수 있습니다.
- 테스트/예시 도메인, placeholder 제목, low-value 해석 항목은 공개 JSON에서 제외합니다.

## 프론트에서 실제로 안 쓰는 이메일용 값

백엔드에는 현재 이메일 렌더링용 원시 값이 더 많습니다. 예를 들면:

- `packet.macro`
- `packet.korea_watch`
- `packet.us_indices`
- `packet.tech_stocks`
- `packet.bitcoin.spot`
- `packet.data_footer_notes`
- LLM body의 `section_0`, `section_4_2`, `section_4_3`, `section_6`

하지만 공개 프론트는 이 원시 값을 그대로 읽지 않고, 아래처럼 이미 정규화된 값만 읽습니다.

- `marketSnapshot`
- `aiJudgment`
- `topicSummaries`
- `techStocks`
- `bitcoin`
- `featuredXSignals`
- `allXSignals`
- `featuredNews`
- `allNews`

즉, R2에 올릴 공개 JSON은 **이메일 packet dump**가 아니라 **프론트 계약에 맞춘 별도 산출물**이어야 합니다.

## 현재 구현 기준 최소 업로드 세트

현재 공개 프론트를 살리기 위한 최소 파일 세트는 아래입니다.

```text
index.json
briefs/YYYY-MM-DD.json
```

최소한 아래는 항상 채워져야 합니다.

1. `index.json.dates`
2. `index.json.updatedAt`
3. `brief.meta`
4. `brief.marketSnapshot.items`
5. `brief.aiJudgment`
6. `brief.topicSummaries`
7. `brief.techStocks`
8. `brief.bitcoin`
9. `brief.featuredNews`
10. `brief.allNews`

`featuredXSignals`, `allXSignals`는 `null` 허용입니다.

## 실제 검증 기준

현재 코드 기준으로 아래를 통과하면 공개 JSON 계약이 맞다고 볼 수 있습니다.

```bash
cd /Users/giwon/code/news/frontend && npm run test
cd /Users/giwon/code/news/frontend && npm run build
```

추가로 홈 대시보드가 요구하는 심볼이 실제 fixture에 들어 있는지도 확인할 수 있습니다.

필수 심볼:

- 티커: `US10Y`, `DXY`, `VIX`, `KRW`, `NQ1!`, `BTC`
- 지수 보드: `SPX`, `QQQ`, `SOXX`

이 문서는 현재 코드 기준의 저장 계약입니다. 백엔드가 어떤 내부 packet이나 템플릿 값을 쓰든, 최종적으로는 이 계약에 맞는 정규화 JSON을 R2에 올리는 방식이 가장 안전합니다.
