# Perplexity API 사용 분석 — 공식 Docs 기반 (2026-03-15)

> 공식 문서 출처:
> - Search API: https://docs.perplexity.ai/docs/search/quickstart
> - Search API Reference: https://docs.perplexity.ai/api-reference/search-post
> - Domain Filter: https://docs.perplexity.ai/docs/search/filters/domain-filter
> - Date/Time Filters: https://docs.perplexity.ai/docs/search/filters/date-time-filters
> - Sonar API: https://docs.perplexity.ai/docs/sonar/quickstart

---

## 1. API 선택: 두 가지 다른 API를 혼용 중

Perplexity는 현재 3개의 독립 API를 제공합니다:

| API | 엔드포인트 | 용도 | SDK 메서드 |
|-----|-----------|------|-----------|
| **Search API** | `POST /search` | 원시 웹 검색 결과 (title, url, snippet, date) | `client.search.create()` |
| **Sonar API** | `POST /chat/completions` | LLM 생성 응답 + 웹 검색 기반 | `client.chat.completions.create()` |
| **Agent API** | `POST /agent` | 에이전트 워크플로우, structured output, 3rd party 모델 | `client.agent.create()` |

프로젝트에서는 **두 가지를 혼용**하고 있습니다:

### 뉴스 수집 (`perplexity_search.py`) → Search API ✅

```python
# perplexity_search.py:_search_once()
response = client.search.create(
    query=_search_query_value(query),
    max_results=SEARCH_MAX_RESULTS,
    search_domain_filter=_search_domain_filter_values(domain_filter),
    search_language_filter=["en"],
    country="US",
)
```

### BTC ETF 참조 (`btc_etf_official.py`) → Sonar API (Chat Completions)

```python
# btc_etf_official.py:_request_reference_snapshots()
response = client.chat.completions.create(
    model=BTC_ETF_REFERENCE_MODEL,  # "sonar"
    messages=[...],
    search_domain_filter=list(BTC_ETF_REFERENCE_DOMAINS),
    search_recency_filter="month",
    search_mode="web",
    response_format={"type": "json_schema", ...},
)
```

**이 구분 자체는 적절합니다.** 뉴스는 원시 검색 결과가 필요하고, ETF 참조는 LLM이 구조화된 JSON을 생성해야 하므로 각각 맞는 API를 사용하고 있습니다.

---

## 2. Search API 사용 분석 (`perplexity_search.py`)

### 2-1. ✅ 올바르게 사용하는 부분

**Multi-query 지원**

```python
# SearchTopic의 query가 tuple일 때 list로 변환
def _search_query_value(query: SearchQuery) -> str | list[str]:
    if isinstance(query, tuple):
        queries = [candidate.strip() for candidate in query if candidate.strip()]
        if len(queries) == 1:
            return queries[0]
        return queries
    return str(query).strip()
```

공식 문서: "You can include up to 5 queries in a single multi-query request"
→ 코드에서 토픽별 query가 최대 3개 tuple이므로 제한 내에서 사용 중. ✅

**Domain filter 형식**

```python
def _search_domain_filter_values(domain_filter: tuple[str, ...]) -> list[str]:
    # URL prefix 형태(https://...)는 path가 있으면 제외하고 도메인만 추출
    parsed = urlparse(body if "://" in body else f"https://{body}")
    if parsed.path not in {"", "/"}:
        continue
    normalized = normalize_domain(body).removeprefix("www.")
```

공식 문서: "Domains should be provided without the protocol" / "Don't include path"
→ URL prefix를 도메인으로 정규화하는 로직이 있어 형식은 맞음. ✅

**Recency filter 값**

```python
recency_filter: str = "day"  # SearchTopic 기본값
retry_recency_filter: str | None = None  # retry 시 "week"
```

공식 문서: `"day"`, `"week"`, `"month"`, `"year"` 허용
→ 사용 중인 값은 모두 유효. ✅

**Date filter 형식**

```python
def _search_date_range(days_back: int) -> tuple[str, str]:
    now = _utc_now()
    after_dt = now - timedelta(days=days_back)
    return after_dt.strftime("%m/%d/%Y"), now.strftime("%m/%d/%Y")
```

공식 문서: `"%m/%d/%Y"` 형식 필수
→ 정확히 일치. ✅

### 2-2. ⚠️ 문제가 있는 부분

#### 문제 A: domain_filter에 URL prefix가 들어가지만 실제로는 무시됨

```python
# TOPIC_SPECS 정의에서
SearchTopic(
    name="ai_bigtech",
    domain_filter=(
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        FT_CONTENT_URL_PREFIX,  # "https://www.ft.com/content/"  ← URL prefix
        "cnbc.com",
    ),
    retry_domain_filter=(
        ...
        "https://investor.nvidia.com",           # URL prefix
        "https://news.microsoft.com/source/",    # URL prefix + path
        "https://www.apple.com/newsroom/",       # URL prefix + path
        ...
    ),
)
```

`_search_domain_filter_values()`에서 path가 있는 URL은 **건너뜁니다**:

```python
parsed = urlparse(body if "://" in body else f"https://{body}")
if parsed.path not in {"", "/"}:
    continue  # ← "https://www.ft.com/content/" 같은 건 여기서 탈락
```

공식 문서: "Don't include path (path filtering coming soon)" / "Incorrect: `nature.com/articles`"

**결과:**
- `FT_CONTENT_URL_PREFIX` (`https://www.ft.com/content/`)는 Search API의 `search_domain_filter`에 **전달되지 않습니다**. path가 있어서 필터링됨.
- `retry_domain_filter`의 `https://investor.nvidia.com`, `https://news.microsoft.com/source/` 등도 path가 있으면 탈락.
- 이 URL prefix들은 `_is_allowed_domain()`에서 **결과 필터링용**으로만 작동합니다.

이것이 의도된 설계인지 불분명합니다. `domain_filter`라는 이름이 두 가지 역할(API 요청 필터 + 결과 후처리 필터)을 겸하고 있어 혼란을 줍니다.

#### 문제 B: `max_tokens` / `max_tokens_per_page` 미사용

공식 문서에서 제공하는 콘텐츠 추출 제어 파라미터를 사용하지 않습니다:

```python
# 현재 코드 — snippet 길이 제어 없음
request_kwargs: dict[str, object] = {
    "query": _search_query_value(query),
    "max_results": SEARCH_MAX_RESULTS,
    "search_domain_filter": ...,
    "search_language_filter": ["en"],
    "country": "US",
}
# max_tokens, max_tokens_per_page 없음
```

공식 문서:
- `max_tokens`: 기본 10,000, 전체 결과의 snippet 총량 제어
- `max_tokens_per_page`: 기본 4,096, 개별 결과의 snippet 길이 제어

뉴스 수집 용도에서는 snippet이 짧아도 되므로 `max_tokens_per_page=512` 정도로 설정하면 비용과 응답 시간을 줄일 수 있습니다. (Search API는 요청당 과금이지만, 서버 처리 시간에 영향)

#### 문제 C: `search_recency_filter`와 date filter 동시 사용

```python
# _search_once() 호출 시
request_kwargs = {...}
if recency_filter:
    request_kwargs["search_recency_filter"] = recency_filter
if search_after_date_filter:
    request_kwargs["search_after_date_filter"] = search_after_date_filter
```

공식 문서: "`search_recency_filter` cannot be combined with specific date filters"

코드에서는 retry 단계별로 분리해서 사용하고 있어 실제로 동시 전달되는 경우는 없어 보입니다:
- 1차: `recency_filter="day"` (date filter 없음)
- 2차 (last_updated retry): `recency_filter=None` + `last_updated_*` filter
- 3차 (date_range retry): `recency_filter=None` + `search_after/before_date_filter`
- 4차 (broad retry): `recency_filter="week"` (date filter 없음)

하지만 `_search_once()`의 인터페이스가 모든 필터를 동시에 받을 수 있어, 호출자가 실수로 둘 다 전달하면 API 에러가 발생할 수 있습니다. 방어 코드가 없습니다.

#### 문제 D: Response의 `last_updated` 필드 활용 부족

Search API 응답 스키마:
```json
{
  "results": [{
    "title": "<string>",
    "url": "<string>",
    "snippet": "<string>",
    "date": "<string>",
    "last_updated": "<string>"
  }]
}
```

코드에서는 `date`와 `last_updated`를 모두 확인하지만 우선순위가 `date` 먼저입니다:

```python
# _parse_results()
published_at=_parse_datetime(raw.get("date") or raw.get("last_updated")),
```

뉴스 기사의 경우 `date`(발행일)가 더 적절하므로 이 우선순위는 맞습니다. ✅

하지만 `last_updated`가 `date`보다 최신인 경우(기사 업데이트)를 별도로 활용하지 않습니다. 신선도 판단에 `last_updated`를 보조 지표로 쓸 수 있습니다.

### 2-3. 🔴 놓치고 있는 기능

#### `search_recency_filter`에 `"hour"` 옵션

공식 API Reference: `Available options: hour, day, week, month, year`

코드에서는 `"day"`와 `"week"`만 사용합니다. 뉴스 수집 특성상 `"hour"` 옵션으로 최신 속보를 우선 확인하는 1차 시도를 추가할 수 있습니다.

#### Multi-query 결과 구조 차이 미처리

공식 문서: "For single queries, `search.results` is a flat list. For multi-query requests, results are grouped per query in the same order."

코드의 `_flatten_results()`가 이를 처리하고 있습니다:

```python
def _flatten_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results", [])
    for item in results:
        if isinstance(item, dict):
            flattened.append(item)
        if isinstance(item, list):  # multi-query 결과 처리
            for nested in item:
                if isinstance(nested, dict):
                    flattened.append(nested)
    return flattened
```

이 부분은 잘 처리되어 있습니다. ✅

---

## 3. Sonar API (Chat Completions) 사용 분석 (`btc_etf_official.py`)

### 3-1. ⚠️ 구 Sonar API 엔드포인트 사용

```python
response = client.chat.completions.create(
    model=BTC_ETF_REFERENCE_MODEL,  # "sonar"
    messages=[...],
    search_domain_filter=list(BTC_ETF_REFERENCE_DOMAINS),
    search_recency_filter="month",
    search_mode="web",
    response_format={"type": "json_schema", ...},
)
```

공식 Sonar API quickstart에서 보여주는 현재 방식:

```python
# 공식 문서 예시
completion = client.chat.completions.create(
    model="sonar-pro",
    messages=[{"role": "user", "content": "..."}]
)
```

**문제점:**
- `model="sonar"` — 공식 문서에서 현재 모델은 `sonar`, `sonar-pro`, `sonar-reasoning-pro`. `sonar`는 유효하지만 가장 기본 모델.
- `search_domain_filter`, `search_recency_filter`, `search_mode` — 이 파라미터들은 **Search API**의 파라미터입니다. Sonar API(Chat Completions)에서 이 파라미터들이 공식적으로 지원되는지 문서에 명시되어 있지 않습니다.
- `response_format={"type": "json_schema", ...}` — Sonar API 문서에서 structured output은 언급되지만, 공식 문서는 이를 **Agent API**에서 사용하라고 안내합니다: "For structured outputs and third-party models, use our Agent API."

**실제 동작 여부:** Perplexity SDK가 내부적으로 이 파라미터들을 전달할 수 있고, 서버가 처리할 수도 있지만, 공식 문서에 명시되지 않은 비공식 사용입니다. API 변경 시 예고 없이 깨질 수 있습니다.

### 3-2. 🔴 Agent API로 마이그레이션 권장

BTC ETF 참조 데이터 수집은 다음 요구사항을 가집니다:
- 특정 도메인만 참조
- 구조화된 JSON 응답
- 웹 검색 기반

이는 정확히 **Agent API**의 용도입니다:

```
Agent API: "Orchestrate agentic workflows across all supported frontier models
with built-in web search, URL fetching, and reasoning controls."
```

공식 문서가 structured output을 Agent API에서 사용하라고 안내하므로, `btc_etf_official.py`의 Sonar Chat Completions 호출을 Agent API로 마이그레이션하는 것이 안전합니다.

---

## 4. 공통 문제

### 4-1. SDK import 경로

```python
from perplexity import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    Perplexity,
    RateLimitError,
)
```

공식 문서: `pip install perplexityai` / `from perplexity import Perplexity`

패키지 이름은 `perplexityai`이지만 import는 `perplexity`입니다. 이는 공식 SDK의 설계이므로 문제 없습니다. ✅

### 4-2. 에러 처리 중복

`perplexity_search.py`와 `btc_etf_official.py`에 거의 동일한 에러 변환 코드가 복제되어 있습니다:

```python
# perplexity_search.py
def _to_http_fetch_error(exc: Exception) -> HttpFetchError: ...
def _format_status_error(exc: APIStatusError) -> str: ...
def _retry_after_seconds_from_exception(exc: Exception) -> float | None: ...

# btc_etf_official.py — 거의 동일한 함수
def _to_http_fetch_error(exc: Exception) -> HttpFetchError: ...
def _format_status_error(exc: APIStatusError) -> str: ...
def _retry_after_seconds_from_exception(exc: Exception) -> float | None: ...
```

공통 Perplexity 에러 핸들러로 추출할 수 있습니다.

### 4-3. Usage 파싱의 과도한 방어 코드

```python
def _usage_snapshot(response: object, payload: dict[str, Any]) -> dict[str, int | None]:
    usage = _usage_container(response, payload)
    return {
        "input_tokens": _first_usage_int(usage, ("prompt_tokens",), ("input_tokens",)),
        "output_tokens": _first_usage_int(usage, ("completion_tokens",), ("output_tokens",)),
        "cached_input_tokens": _first_usage_int(
            usage,
            ("input_tokens_details", "cache_read_input_tokens"),
            ("input_tokens_details", "cache_creation_input_tokens"),
            ("input_tokens_details", "cached_tokens"),
            ("prompt_tokens_details", "cached_tokens"),
        ),
        ...
    }
```

Search API 응답에는 `usage` 필드가 **없습니다**. API Reference 응답 스키마:

```json
{"results": [...], "id": "<string>", "server_time": "<string>"}
```

Search API는 요청당 과금이므로 토큰 사용량이 없습니다. 이 usage 파싱 코드는 Search API 호출에서는 항상 `None`을 반환하며, `usage_parse_failures`를 불필요하게 기록할 수 있습니다.

---

## 5. 요약

| 항목 | 상태 | 설명 |
|------|------|------|
| Search API 기본 사용 | ✅ | `client.search.create()` 올바르게 사용 |
| Multi-query 지원 | ✅ | tuple → list 변환, 결과 flatten 처리 |
| Domain filter 형식 | ⚠️ | API에는 도메인만 전달하지만, URL prefix가 `domain_filter`에 혼재 |
| Date filter 형식 | ✅ | `%m/%d/%Y` 정확히 일치 |
| Recency filter 값 | ✅ | `"day"`, `"week"` 유효 |
| `max_tokens` / `max_tokens_per_page` | ❌ 미사용 | 비용/속도 최적화 여지 |
| Recency + date filter 동시 사용 방지 | ⚠️ | 현재 호출 패턴에서는 안전하지만 방어 코드 없음 |
| BTC ETF: Sonar Chat Completions | ⚠️ | 비공식 파라미터 사용 (`search_domain_filter` 등) |
| BTC ETF: structured output | 🔴 | 공식 문서는 Agent API 권장 |
| 에러 핸들러 중복 | ⚠️ | 두 모듈에 동일 코드 복제 |
| Search API usage 파싱 | ⚠️ | Search API에 usage 없음, 불필요한 파싱 시도 |

### 권장 조치 (우선순위순)

1. **BTC ETF 참조를 Agent API로 마이그레이션** — 현재 Sonar Chat Completions에서 비공식 파라미터를 사용 중이며, structured output은 Agent API가 공식 경로
2. **`domain_filter`의 이중 역할 분리** — API 전달용 도메인 목록과 결과 후처리용 URL prefix를 별도 필드로 관리
3. **`max_tokens_per_page` 설정 추가** — 뉴스 snippet은 512 토큰이면 충분, 응답 시간 개선
4. **Recency + date filter 동시 사용 방어** — `_search_once()`에서 둘 다 전달되면 경고 또는 하나만 사용
5. **에러 핸들러 공통화** — Perplexity SDK 에러 → `HttpFetchError` 변환을 한 곳으로
6. **Search API 호출에서 usage 파싱 제거** — Search API는 토큰 과금이 아님
