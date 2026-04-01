# Tasks Document

## Overview

- **Spec**: public-news-feed-quality
- **완료 일시**: 2026-04-01
- **총 태스크**: 17개 + Checkpoint 4개

변경 순서는 의존성 기준으로 정렬: 정책(도메인) → 랭킹 로직 → 가시성 → X 시그널 → 프론트엔드.

---

## Tasks

### Task 1 — PREFERRED_DOMAINS 확장

_Requirements: 2.1, 2.2_

`src/morning_brief/data/news_policy.py`에서 아래 3곳을 수정한다.

- `PREFERRED_DOMAINS` set에 8개 도메인 추가:
  `apnews.com`, `barrons.com`, `marketwatch.com`, `fortune.com`,
  `axios.com`, `techcrunch.com`, `theblock.co`, `cointelegraph.com`
- `DOMAIN_SCORES` dict에 각 도메인 점수 추가 (design.md 점수표 참고)
- `SOURCE_TIERS["tier_2"]` set에 동일 8개 도메인 추가

- [x] Task 1 완료

---

### Task 2 — 도메인 정책 테스트

_Requirements: 2.1, 2.2_

`tests/` 내 도메인 관련 기존 테스트가 통과하는지 확인하고, 신규 도메인에 대한 케이스를 추가한다.

- `is_preferred_domain("https://apnews.com/article/xyz")` → `True` 확인
- `source_tier("https://theblock.co/post/xyz")` → `"tier_2"` 확인
- `domain_score("https://barrons.com/article/xyz")` → `3.8` 확인
- `make lint && pytest tests/ -k "domain or policy" -v` 통과 확인

- [x] Task 2 완료

---

### Task 3 — `_dedup_and_rank` min_output 파라미터 추가

_Requirements: 2.3_

`src/morning_brief/data/news_selection.py`의 `_dedup_and_rank` 함수에 `min_output: int = 0` 키워드 파라미터를 추가한다.

```python
def _dedup_and_rank(
    items: list[NewsItem],
    max_items: int,
    *,
    min_output: int = 0,
) -> list[NewsItem]:
    ...
    ranked = _sort_by_score(list(by_key.values()))
    result = _apply_domain_diversity_limit(ranked, max_items=max_items)

    if min_output > 0 and len(result) < min_output and len(ranked) >= min_output:
        return ranked[:min_output]

    return result
```

`src/morning_brief/data/news.py` line 495에서 공개 뉴스 경로만 `min_output=3` 추가:
```python
public_ranked_items = _dedup_and_rank(
    public_candidate_items,
    max_items=PUBLIC_ALL_NEWS_ITEMS,
    min_output=3,
)
```

- [x] Task 3 완료

---

### Task 4 — `_dedup_and_rank` min_output 테스트

_Requirements: 2.3_

`tests/` 에 `_dedup_and_rank` min_output 동작 테스트를 추가한다.

- 입력 5개, `min_output=3`, 도메인 다양성 제한으로 결과가 2개가 될 상황 → 3개 반환 확인
- 입력 2개, `min_output=3` → ranked가 3개 미만이므로 결과 2개(완화 미발동) 확인
- `min_output=0` (기본값) → 기존 동작 그대로 확인
- `pytest tests/ -k "dedup_and_rank" -v` 통과

- [x] Task 4 완료

---

### ✅ Checkpoint 1

도메인 정책 + 랭킹 로직 변경 검증.

```bash
make fmt && make lint && make test
```

- [x] Checkpoint 1 통과 — 결과: ___

---

### Task 5 — `public_context`에 audit 추가

_Requirements: 1.1_

`src/morning_brief/data/news.py`의 `public_context` dict(line 545 부근)에 `"public_news_analysis"` 키를 추가한다.

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

- [x] Task 5 완료

---

### Task 6 — `build_public_brief()`에 `meta.publicNewsAnalysis` 직렬화

_Requirements: 1.1, 1.2, 1.3_

`src/morning_brief/public_site.py`의 `build_public_brief()` 내 `meta` dict에 아래를 추가한다.

```python
"publicNewsAnalysis": (
    packet.get("public_news_analysis")
    or public_context.get("public_news_analysis")
),
```

- [x] Task 6 완료

---

### Task 7 — TypeScript 타입 업데이트

_Requirements: 1.1_

`schema/brief.types.ts`를 수정한다.

1. `PublicNewsAnalysisAudit` 인터페이스 추가:
```typescript
export interface PublicNewsAnalysisAudit {
  candidateCount: number;
  requestedCount: number;
  successCount: number;
  failedCount: number;
  skippedCount: number;
  status: "ok" | "partial" | "failed" | "skipped";
}
```

2. `BriefMeta`에 필드 추가:
```typescript
publicNewsAnalysis: PublicNewsAnalysisAudit | null;
```

- [x] Task 7 완료

---

### Task 8 — Enrichment 가시성 테스트

_Requirements: 1.1, 1.2, 1.3_

- `enrich_public_news_packet()` 반환 audit이 `public_context["public_news_analysis"]`에 올바르게 담기는지 확인
- enrichment 비활성화 시 `status == "skipped"`, `requestedCount == 0`, `skippedCount == candidateCount` 불변식 확인
- 일부 실패 시 `불변식 A: requestedCount == successCount + failedCount` 확인
- `pytest tests/ -k "public_news_analysis or enrichment" -v` 통과
- `cd frontend && npm run lint` 타입 오류 없음 확인

- [x] Task 8 완료

---

### ✅ Checkpoint 2

Enrichment 가시성 변경 검증.

```bash
make check
cd frontend && npm run lint
```

- [x] Checkpoint 2 통과 — 결과: ___

---

### Task 9 — `_cap_signals_by_topic` 함수 추가

_Requirements: 3.1, 3.2_

`src/morning_brief/data/news.py`에 신규 함수를 추가한다 (상수 선언부 아래, `build_news_packet` 위).

```python
def _cap_signals_by_topic(
    signals: list[XSignal],
    *,
    total_max: int,
    per_topic_max: int,
    sentiment_diversity: bool = False,
) -> list[XSignal]:
    topic_counts: dict[str, int] = {}
    topic_sentiments: dict[str, set[str]] = {}
    result: list[XSignal] = []
    deferred: list[XSignal] = []

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

- [x] Task 9 완료

---

### Task 10 — 기존 슬라이스 → `_cap_signals_by_topic` 교체 + 상수 업데이트

_Requirements: 3.1, 3.2, 3.3, 3.4_

`src/morning_brief/data/news.py`:

1. 상수 변경: `PUBLIC_FEATURED_X_SIGNALS = 5` → `6`
2. line 498 교체:
```python
# 변경 전
public_ranked_signals = x_signals[:PUBLIC_ALL_X_SIGNALS]

# 변경 후
public_ranked_signals = _cap_signals_by_topic(
    x_signals,
    total_max=PUBLIC_ALL_X_SIGNALS,
    per_topic_max=4,
)
```
3. line 503 교체:
```python
# 변경 전
featured_publish_signals = publish_signals[:PUBLIC_FEATURED_X_SIGNALS]

# 변경 후
featured_publish_signals = _cap_signals_by_topic(
    publish_signals,
    total_max=PUBLIC_FEATURED_X_SIGNALS,
    per_topic_max=2,
    sentiment_diversity=True,
)
```

`src/morning_brief/public_site.py`:
- `_PUBLIC_FEATURED_X_LIMIT = 5` → `6`

- [x] Task 10 완료

---

### Task 11 — X 시그널 topic 캡핑 테스트

_Requirements: 3.1, 3.2, 3.3, 3.4_

- `_cap_signals_by_topic(signals, total_max=6, per_topic_max=2)`: macro 3개 입력 시 2개만 반환 확인
- `sentiment_diversity=True`: macro bullish 2개 → 첫 번째 bullish 선택 후 두 번째 bullish deferred → bearish가 있으면 bearish 우선 확인
- `sentiment_diversity=True`: 같은 sentiment만 있을 때 2개 모두 선택 확인 (2차 패스)
- topic 필드 빈 문자열(`""`) 입력 시 `"unknown"`으로 처리되어 crash 없음 확인
- `pytest tests/ -k "cap_signals or x_signal" -v` 통과

- [x] Task 11 완료

---

### ✅ Checkpoint 3

X 시그널 topic 캡핑 변경 검증.

```bash
make check
```

- [x] Checkpoint 3 통과 — 결과: ___

---

### Task 12 — `XSignalsClient.tsx` 토글 추가

_Requirements: 4.1, 4.4_

`frontend/components/signals/XSignalsClient.tsx`를 수정한다.

- 파일 상단에 `"use client";` 추가
- `useState` import 추가
- `showAll` state 추가 (기본값 `false`)
- `displayed = showAll ? allItems : featuredItems`
- `hasMore = allItems.length > featuredItems.length`일 때 토글 버튼 렌더:
  - `showAll=false`: `전체 보기 (${allItems.length}개)`
  - `showAll=true`: `접기`

- [x] Task 12 완료

---

### Task 13 — `NewsFeed.tsx` 0개/1개 분기 처리

_Requirements: 4.3_

`frontend/components/news/NewsFeed.tsx`를 수정한다.

- **0개 케이스** (`featuredItems.length === 0 && allItems.length === 0`):
  기존 `DataState` 렌더 → `return null`로 교체
- **`variant === "home"` 분기**에 `showInsufficientWarning` prop 전달:
```tsx
<NewsFeedClient
  featuredItems={featuredItems}
  allItems={allItems}
  showInsufficientWarning={featuredItems.length === 1}
/>
```

- [x] Task 13 완료

---

### Task 14 — `NewsFeedClient.tsx` 안내 메시지 렌더링

_Requirements: 4.3_

`frontend/components/news/NewsFeedClient.tsx`에 `showInsufficientWarning` prop을 추가한다.

```tsx
export function NewsFeedClient({
  featuredItems,
  allItems,
  showInsufficientWarning = false,
}: {
  featuredItems: NewsItem[];
  allItems: NewsItem[];
  showInsufficientWarning?: boolean;
}) {
  ...
  return (
    <section ...>
      ...
      {showInsufficientWarning && (
        <p className="text-sm text-white/40 font-mono">
          분석 기사가 충분하지 않습니다
        </p>
      )}
      <NewsFeedList items={items} ... />
    </section>
  );
}
```

- [x] Task 14 완료

---

### Task 15 — 프론트엔드 테스트

_Requirements: 4.1, 4.3, 4.4_

- `cd frontend && npm run lint` 타입 오류 없음 확인
- `npm test` 통과 확인
- fixture 데이터로 개발 서버 실행 후 수동 확인:
  - `npm run dev:fixture`
  - X 시그널 섹션에 featuredItems만 표시 + "전체 보기" 토글 동작 확인
  - AI 뉴스 분析 섹션: `featuredNews` 3개 이상 정상 표시 확인

- [x] Task 15 완료

---

### ✅ Checkpoint 4

프론트엔드 변경 + 전체 통합 검증.

```bash
cd frontend && npm run lint && npm test
make check
```

- [x] Checkpoint 4 통과 — 결과: ___

---

### Task 16 — `make check` 최종 통합 검증

_Requirements: 1, 2, 3, 4_

모든 변경사항 합산 후 최종 검증.

```bash
make fmt
make lint
make test
make typecheck
make check
```

- 모든 기존 테스트 통과 확인
- 새로 추가한 테스트 포함하여 regression 없음 확인

- [x] Task 16 완료

---

## 구현 후 필수 확인 로그

> (requirements.md에서 이관)

파이프라인 1회 실행 후 순서대로 확인:

1. `non_preferred_domain` 필터 탈락률 — 이전 88%에서 50% 이하로 감소했는지
2. `_dedup_and_rank` 입출력 수 — 입력 N개 → 출력 ≥3개인지 (0개 반환 여부가 핵심)
3. `meta.publicNewsAnalysis.candidateCount` — output JSON에서 ≥5인지
4. `meta.publicNewsAnalysis.requestedCount` — `candidateCount`와 같은지 (skip 없을 때)
5. `featuredNews` 길이 — output JSON에서 ≥3인지
6. `featuredXSignals` topic 분포 — macro/ai_bigtech/bitcoin 각 최대 2개인지
