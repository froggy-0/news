# Design Document

## Overview

requirements.md의 4개 Requirement를 구현하기 위한 설계. 변경 범위는 백엔드 5개 파일 + 프론트엔드 3개 파일이며, 기존 파이프라인 오케스트레이션 구조를 유지하면서 최소 침습적으로 수정한다.

**근본 원인 재확인:**
- Req1: `public_news_analysis_audit`가 `public_context` dict에 포함되지 않아 output JSON 미노출
- Req2(①): `PREFERRED_DOMAINS` 21개가 너무 좁아 88% 후보 탈락
- Req2(②): `_dedup_and_rank`에 최소 출력 보장 없어 희귀 케이스에서 0 반환 가능
- Req3: `x_signals[:PUBLIC_ALL_X_SIGNALS]` 단순 슬라이스로 topic 다양성 통제 없음
- Req4: `XSignalsClient`에 "전체 보기" 토글 없음, `NewsFeed` 0개 시 DataState(표시) → display:none으로 변경 필요

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `src/morning_brief/data/news_policy.py` | PREFERRED_DOMAINS + DOMAIN_SCORES + SOURCE_TIERS 확장 |
| `src/morning_brief/data/news_selection.py` | `_dedup_and_rank`에 `min_output` 파라미터 추가 |
| `src/morning_brief/data/news.py` | `_cap_signals_by_topic` 추가 + `public_context`에 audit 포함 + 상수 업데이트 |
| `src/morning_brief/public_site.py` | `meta.publicNewsAnalysis` 직렬화 + `_PUBLIC_FEATURED_X_LIMIT` 6으로 변경 |
| `schema/brief.types.ts` | `PublicNewsAnalysisAudit` 인터페이스 추가 + `BriefMeta` 필드 추가 |
| `frontend/components/signals/XSignalsClient.tsx` | featuredItems 기본 표시 + "전체 보기" 토글 추가 |
| `frontend/components/news/NewsFeed.tsx` | 0개 → return null, 1개 → 안내 메시지 |
| `frontend/components/news/NewsFeedClient.tsx` | 1개 케이스 안내 메시지 렌더링 |

---

## Requirement 1: Enrichment 가시성 확보

### 현재 상태
`news.py:528-543`에서 `enrich_public_news_packet()`은 `PublicNewsAnalysisAudit`를 반환하고 observer 로그에만 기록한다. `public_context` dict(line 545-584)에 포함되지 않아 output JSON에 전달되지 않는다. `BriefMeta` TypeScript 타입에도 해당 필드가 없다.

### 설계

**1-A. `news.py` — `public_context`에 audit 추가**

`public_context` dict(line 545)에 `"public_news_analysis"` 키를 추가한다.

```python
"public_news_analysis": {
    "candidateCount": public_news_analysis_audit.candidate_count,
    "requestedCount": public_news_analysis_audit.requested_count,
    "successCount": public_news_analysis_audit.success_count,
    "failedCount": public_news_analysis_audit.failed_count,
    "skippedCount": public_news_analysis_audit.skipped_count,
    "status": public_news_analysis_audit.status,
},
```

**1-B. `public_site.py` — `build_public_brief()`에서 `meta`에 포함**

`build_public_brief()`의 `meta` dict 구성 시 `public_context`에서 추출한다.

```python
"publicNewsAnalysis": packet.get("public_news_analysis")
    or public_context.get("public_news_analysis"),
```

> **결정 이유:** `public_context`를 경유하는 이유는 기존 패턴(`source_counts` 등)과 일관성을 유지하기 위함이다. `build_public_brief()`에 직접 파라미터를 추가하면 함수 시그니처가 변경되고 하위 호환성 부담이 생긴다.

**1-C. `schema/brief.types.ts` — 타입 추가**

```typescript
export interface PublicNewsAnalysisAudit {
  candidateCount: number;
  requestedCount: number;
  successCount: number;
  failedCount: number;
  skippedCount: number;
  status: "ok" | "partial" | "failed" | "skipped";
}

// BriefMeta에 추가
publicNewsAnalysis: PublicNewsAnalysisAudit | null;
```

`null` 허용: 이전 브리핑 데이터(필드 없음) 또는 레거시 경로 처리를 위해.

---

## Requirement 2: 채움률 ≥3

### 현재 흐름 (문제 지점 표시)

```
items (all sources merged)
  → filter_public_article_news_candidates()  ← ❶ PREFERRED_DOMAINS 21개로 88% 탈락
  → _dedup_and_rank(max_items=12)            ← ❷ 3개 입력 → 0개 가능
  → filter_public_article_news()
  → _news_items_to_packet()
  → enrich_public_news_packet()
  → public_news_packet (featuredNews 소스)
```

### 설계

**2-A. `news_policy.py` — PREFERRED_DOMAINS 확장**

기존 21개 도메인을 유지하면서 아래 8개를 추가하여 29개로 확장한다.

```python
# 추가 도메인 (tier 분류 및 점수 포함)
"apnews.com",        # tier_2, score 4.0  — 주요 거시 경제 보도
"barrons.com",       # tier_2, score 3.8  — 금융/투자 전문
"marketwatch.com",   # tier_2, score 3.7  — 금융 시장 데이터 중심
"fortune.com",       # tier_2, score 3.5  — 기업/경제 보도
"axios.com",         # tier_2, score 3.5  — 단문 브리핑 형식의 기술/경제
"techcrunch.com",    # tier_2, score 3.5  — AI·빅테크 전문
"theblock.co",       # tier_2, score 3.7  — 암호화폐 온체인 데이터 기반
"cointelegraph.com", # tier_2, score 3.5  — 암호화폐 뉴스
```

> **결정 이유:** Perplexity Sonar가 수집하는 도메인 분포를 고려했을 때 위 8개가 수집 빈도가 높다. `theblock.co`와 `cointelegraph.com`은 암호화폐 커버리지를 보강하며, `apnews.com`은 연준/거시 보도에서 빈번히 등장한다. 35개 이상 목표(requirements AC2)를 초과하는 29개이지만, 추가 도메인은 품질 검증이 부족한 소스이므로 이 8개로 한정한다.

**`SOURCE_TIERS["tier_2"]`에도 위 8개 도메인을 추가**하여 `source_tier()` 함수가 올바른 tier를 반환하도록 한다.

**2-B. `news_selection.py` — `_dedup_and_rank`에 최소 출력 보장**

```python
def _dedup_and_rank(
    items: list[NewsItem],
    max_items: int,
    *,
    min_output: int = 0,
) -> list[NewsItem]:
    by_key: dict[str, NewsItem] = {}
    # ... 기존 dedup 로직 동일 ...

    ranked = _sort_by_score(list(by_key.values()))
    result = _apply_domain_diversity_limit(ranked, max_items=max_items)

    # 최소 출력 보장: 도메인 다양성 제한이 min_output을 만족하지 못하면 완화
    if min_output > 0 and len(result) < min_output and len(ranked) >= min_output:
        return ranked[:min_output]

    return result
```

`build_news_packet()`의 공개 뉴스 ranking 호출만 `min_output=3`으로 변경:
```python
# news.py line 495
public_ranked_items = _dedup_and_rank(
    public_candidate_items,
    max_items=PUBLIC_ALL_NEWS_ITEMS,
    min_output=3,  # 추가
)
```

> **결정 이유:** `min_output`을 `_dedup_and_rank` 파라미터로 추가해 기존 호출자(이메일 경로 등)에 영향 없이 공개 뉴스 경로만 보호한다. 기본값 `0`은 기존 동작 그대로이므로 하위 호환성이 유지된다.

---

## Requirement 3: X 시그널 topic 중복 제거

### 현재 상태
`news.py:498-503`:
```python
public_ranked_signals = x_signals[:PUBLIC_ALL_X_SIGNALS]          # 단순 슬라이스 (12개)
...
featured_publish_signals = publish_signals[:PUBLIC_FEATURED_X_SIGNALS]  # 단순 슬라이스 (5개)
```
`XSignal.topic`은 `"macro"` | `"ai_bigtech"` | `"bitcoin"` | `""` 문자열.

### 설계

**3-A. `news.py` — topic 캡핑 함수 추가**

```python
def _cap_signals_by_topic(
    signals: list[XSignal],
    *,
    total_max: int,
    per_topic_max: int,
    sentiment_diversity: bool = False,
) -> list[XSignal]:
    """topic별 per_topic_max개로 제한하면서 최대 total_max개를 반환.

    sentiment_diversity=True이면 동일 topic 내 두 번째 선택 시
    이미 선택된 sentiment와 다른 sentiment를 우선한다.
    """
    topic_counts: dict[str, int] = {}
    topic_sentiments: dict[str, set[str]] = {}
    result: list[XSignal] = []
    deferred: list[XSignal] = []  # 같은 sentiment로 인해 1차에서 미선택된 항목

    for signal in signals:
        topic = signal.topic or "unknown"
        count = topic_counts.get(topic, 0)
        if count >= per_topic_max:
            continue

        if sentiment_diversity and count >= 1:
            chosen = topic_sentiments.get(topic, set())
            if signal.sentiment in chosen:
                deferred.append(signal)
                continue

        result.append(signal)
        topic_counts[topic] = count + 1
        topic_sentiments.setdefault(topic, set()).add(signal.sentiment)
        if len(result) >= total_max:
            return result

    # 2차 패스: sentiment 제한 없이 deferred 항목으로 채움
    for signal in deferred:
        topic = signal.topic or "unknown"
        if topic_counts.get(topic, 0) >= per_topic_max:
            continue
        result.append(signal)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(result) >= total_max:
            break

    return result
```

**3-B. `news.py` — 기존 슬라이스 대체**

```python
# 변경 전
public_ranked_signals = x_signals[:PUBLIC_ALL_X_SIGNALS]          # 12개 단순 슬라이스
...
featured_publish_signals = publish_signals[:PUBLIC_FEATURED_X_SIGNALS]  # 5개 단순 슬라이스

# 변경 후
public_ranked_signals = _cap_signals_by_topic(                     # allXSignals: 총 12개, topic당 4개
    x_signals,
    total_max=PUBLIC_ALL_X_SIGNALS,   # 12
    per_topic_max=4,
)
...
featured_publish_signals = _cap_signals_by_topic(                  # featuredXSignals: 총 6개, topic당 2개
    publish_signals,
    total_max=PUBLIC_FEATURED_X_SIGNALS,  # 6
    per_topic_max=2,
    sentiment_diversity=True,
)
```

**3-C. 상수 업데이트**

```python
# news.py
PUBLIC_FEATURED_X_SIGNALS = 6  # 5 → 6

# public_site.py
_PUBLIC_FEATURED_X_LIMIT = 6   # 5 → 6
```

> **결정 이유:** `_cap_signals_by_topic`을 `_dedup_and_rank`와 별도 함수로 분리한 이유는 X 시그널과 뉴스 아이템의 랭킹 기준이 다르기 때문이다. X 시그널에는 `_item_score()`를 적용할 수 없으므로 독립 함수가 적절하다. `sentiment_diversity`를 `bool` 파라미터로 분리한 이유는 `allXSignals`에는 sentiment 다양성보다 topic 다양성이 더 중요하기 때문이다.

---

## Requirement 4: 뉴스와 X 시그널의 균형 있는 표시

### 현재 상태
- `XSignalsClient`: `allItems`가 있으면 전체를 그대로 렌더. "전체 보기" 토글 없음.
- `NewsFeed`: `featuredItems.length === 0 && allItems.length === 0`이면 `DataState`(안내 메시지) 표시.

### 설계

**4-A. `XSignalsClient.tsx` — featuredItems 기본 + "전체 보기" 토글**

```tsx
"use client";
import { useState } from "react";

export function XSignalsClient({ featuredItems, allItems }: ...) {
  const [showAll, setShowAll] = useState(false);
  const displayed = showAll ? allItems : featuredItems;
  const hasMore = allItems.length > featuredItems.length;

  return (
    <section ...>
      ...
      <XSignalsList items={displayed} ... />
      {hasMore && (
        <button onClick={() => setShowAll(v => !v)}>
          {showAll ? "접기" : `전체 보기 (${allItems.length}개)`}
        </button>
      )}
    </section>
  );
}
```

> **결정 이유:** `"use client"` 지시어와 `useState`를 추가하는 것이 가장 단순하다. SSG 빌드와 충돌하지 않으며 기존 파일 구조를 유지한다.

**4-B. `NewsFeed.tsx` — 0개 → 숨김, 1개 → 안내 메시지**

```tsx
// 0개: 섹션 숨김 (기존 DataState 렌더 제거)
if (featuredItems.length === 0 && allItems.length === 0) {
  return null;  // display:none 효과
}

// 1개: NewsFeedClient에 insufficientData prop 전달
if (variant === "home") {
  return (
    <NewsFeedClient
      featuredItems={featuredItems}
      allItems={allItems}
      showInsufficientWarning={featuredItems.length === 1}
    />
  );
}
```

**4-C. `NewsFeedClient.tsx` — 안내 메시지 조건부 렌더**

```tsx
export function NewsFeedClient({
  featuredItems,
  allItems,
  showInsufficientWarning = false,
}: {
  ...
  showInsufficientWarning?: boolean;
}) {
  return (
    <section ...>
      ...
      {showInsufficientWarning && (
        <p className="text-sm text-white/40">분석 기사가 충분하지 않습니다</p>
      )}
      <NewsFeedList items={items} ... />
    </section>
  );
}
```

---

## 데이터 흐름 (변경 후)

```
build_news_packet()
  ├─ filter_public_article_news_candidates()     [PREFERRED_DOMAINS: 29개]
  ├─ _dedup_and_rank(max=12, min_output=3)       [최소 3개 보장]
  ├─ filter_public_article_news()
  ├─ enrich_public_news_packet()
  │    └─ → public_news_analysis_audit
  ├─ _cap_signals_by_topic(total=12, per_topic=4)  [allXSignals]
  ├─ _cap_signals_by_topic(total=6, per_topic=2,   [featuredXSignals]
  │    sentiment_diversity=True)
  └─ public_context {
       "featured_news", "all_news",
       "featured_x_signals", "all_x_signals",
       "public_news_analysis",   ← 신규
       "source_counts"
     }

build_public_brief()
  └─ meta {
       ...,
       "publicNewsAnalysis": {...}  ← 신규
     }
```

---

## 영향 범위 및 회귀 리스크

| 변경 | 리스크 | 완화 방법 |
|------|--------|-----------|
| PREFERRED_DOMAINS 확장 | 저품질 도메인 유입 가능 | 추가 도메인을 모두 검증된 tier-1/2 미디어로 제한 |
| `_dedup_and_rank` min_output | 도메인 다양성 일시 완화 | 기본값 0, 공개 경로만 `min_output=3` 적용 |
| X 시그널 슬라이스 → cap 함수 | topic 필드 빈 값(`""`) 처리 필요 | `topic or "unknown"` 처리로 빈 값 안전하게 처리 |
| `NewsFeed` return null | 0개 시 섹션 완전 숨김으로 레이아웃 간격 변화 가능 | 인접 섹션 스타일 확인 필요 |

---

## 미변경 사항 (기존 동작 유지)

- `_filter_public_news_for_display()`: summaryKo + interpretation 한글 검증 로직 그대로
- `enrich_public_news_packet()` 내부 로직: 실패 항목 제외, translation fallback 없음
- `filter_public_article_news_candidates()` 내부 필터 기준 (x_handle_source, x_domain_url 등)
- 이메일 경로의 `_dedup_and_rank` 호출: `min_output` 기본값 0으로 영향 없음
