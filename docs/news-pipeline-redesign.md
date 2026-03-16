# 뉴스 파이프라인 재설계 계획

> 작성일: 2026-03-16
> 배경: 주말 실행에서 Perplexity Search API 4개 토픽 전부 수집 0건 발생. Grok 공식 시그널 4건만으로 브리핑 생성.
> 근본 원인: Search API에 allowlist 6개 도메인만 허용 → 주말에 해당 도메인 신규 기사 없음 → 데이터 페이지만 반환 → 필터에 전부 걸림

---

## 현재 뉴스 수집 흐름 (AS-IS)

```
Perplexity Search API (allowlist 6개 도메인, 토픽별 3~4단계 retry = 15회 호출)
  → raw 결과 24~28건 반환되지만 전부 markets.ft.com/data/* 패턴
  → _is_allowed_domain() allowlist 재검증 + _is_disallowed_market_data_result() deny
  → 유효 기사 0건

Grok official signals (켜짐) → 4건 수집 ← 유일한 수확
Grok X keyword (꺼짐)
Grok web search (꺼짐)

Legacy fallback (RSS + NewsAPI) → 주말이라 역시 0건

OpenAI web backfill → 파싱 가능한 기사 0건

최종: Grok 시그널 4건만으로 브리핑 생성 (degraded)
```

**문제의 본질**: Perplexity `search_domain_filter`에 allowlist로 ft.com, bloomberg.com 등 6개만 허용 → 검색 엔진의 자유도를 과도하게 제한. 주말/비장중에 이 도메인들의 신규 기사가 없으면 정적 페이지가 올라와 전부 필터링됨.

---

## 재설계 방향 (TO-BE)

```
[Phase 1] 광범위 수집 — 병렬 실행
├─ Grok official signals (현행 유지, 켜짐)
├─ Grok X keyword (활성화, 그룹 확장)
├─ Grok web search (활성화)
├─ Perplexity Search API (allowlist → deny list 전환)
└─ NewsAPI + RSS (현행 legacy)

[Phase 2] 맥락 보강 — Perplexity Sonar
  Phase 1 수집 결과의 제목+요약을 기반으로 심층 맥락 분석

[Phase 3] 브리핑 생성 + 검수 — OpenAI (현행 유지)
```

---

## Phase 1 상세: 광범위 수집

### 1-1. Grok 활용 극대화

현재 Grok 3개 모듈 중 1개만 켜져 있음. 나머지 2개를 활성화하여 1차 수집 커버리지를 넓힘.

#### A. grok_official_signals — 현행 유지

- 상태: **켜짐** (기본값)
- 역할: 검증된 공식 X 핸들(24개 엔티티) 모니터링
- 그룹: `macro_regulator`, `ai_bigtech_primary`, `btc_etf_primary`
- 로그 실적: 4건/실행 — 주말에도 안정적으로 동작
- 변경사항: 없음

#### B. grok_x_keyword — 활성화 + 그룹 확장

- 상태: **꺼짐** → 켜짐으로 변경 (`GROK_X_KEYWORD_SEARCH_ENABLED=true`)
- 역할: 주제별 키워드 기반 X 검색으로 시장 반응/분석가 코멘터리 수집
- xai_sdk 도구: `x_search` + `allowed_x_handles` + `from_date`/`to_date`

현재 문제점과 개선:

| 항목 | 현재 | 개선 |
|------|------|------|
| 그룹 커버리지 | `macro_and_equity`, `crypto_and_etf` 2개만 | `ai_bigtech_primary`, `btc_etf_primary` 추가 → 4개 그룹 |
| 프롬프트 | 영문 고정 | 주말 맥락 추가 (금요일 장마감 이후 분석 포함 유도) |
| 결과 품질 | 프롬프트 의존 | `why_it_matters` 필드 검증 추가 |
| 중복 | official signals과 중복 가능 | `source_handle` 기반 dedup 필요 |

구현 변경:

```python
# grok_x_keyword.py — 그룹 추가
GROUP_PROMPTS = {
    MACRO_EQUITY_GROUP: MACRO_EQUITY_PROMPT,
    CRYPTO_ETF_GROUP: CRYPTO_ETF_PROMPT,
    "ai_bigtech_primary": AI_BIGTECH_PROMPT,     # 신규
    "btc_etf_primary": BTC_ETF_PRIMARY_PROMPT,    # 신규
}

GROUP_TOPIC_MAP = {
    MACRO_EQUITY_GROUP: "macro",
    CRYPTO_ETF_GROUP: "bitcoin",
    "ai_bigtech_primary": "ai_bigtech",           # 신규
    "btc_etf_primary": "bitcoin",                  # 신규
}
```

```python
# AI/빅테크 프롬프트 (신규)
AI_BIGTECH_PROMPT = """Search X for the most significant AI and Big Tech posts from the last {lookback_hours} hours.
Focus on:
1. NVIDIA, AMD, TSMC, ASML semiconductor news and analyst commentary
2. Microsoft, Apple, Amazon, Google, Meta strategic moves
3. AI infrastructure, data center capex, model announcements
4. Earnings guidance, revenue signals, product launches

Return the top {max_items} most market-moving posts as JSON array "signals":
- headline, summary, why_it_matters, sentiment, source_handle, posted_at
Skip marketing, promotional, and non-market posts.
Output format: {{"signals": [...]}}"""
```

#### C. grok_web_search — 활성화 + 품질 보강

- 상태: **꺼짐** → 켜짐으로 변경 (`GROK_WEB_SEARCH_ENABLED=true`)
- 역할: Grok `web_search` 도구로 최신 금융 뉴스 기사 URL 수집
- xai_sdk 도구: `web_search` + `excluded_domains`

현재 문제점과 개선:

| 항목 | 현재 | 개선 |
|------|------|------|
| `why_it_matters` | 미설정 | 프롬프트에 필드 추가, NewsItem 생성 시 반영 |
| `citations` | 미설정 | `include=["inline_citations"]` 추가 |
| 날짜 제어 | 프롬프트 텍스트 의존 ("last 24 hours") | 주말 감지 → "last 48 hours" 또는 "since Friday market close" |
| 토픽 검증 | 없음 | 반환된 topic 값을 `{macro, us_equity, ai_bigtech, bitcoin}` 정규화 |

```python
# grok_web_search.py — 주말 대응
def _build_prompt(max_items: int) -> str:
    time_window = "last 48 hours" if _is_weekend() else "last 24 hours"
    weekend_hint = (
        "\nIt is currently the weekend. Include Friday post-market analysis, "
        "weekly review articles, and forward-looking previews for next week."
        if _is_weekend() else ""
    )
    return WEB_SEARCH_PROMPT.format(
        max_items=max_items,
        time_window=time_window,
        weekend_hint=weekend_hint,
    )
```

#### D. Grok 공통 인프라 개선

**서킷 브레이커 분리**: 현재 3개 모듈 전부 `GROK_PROVIDER = "grok"` 공유 → 하나가 429 맞으면 전부 차단됨.

```python
# 모듈별 provider 분리
GROK_OFFICIAL_PROVIDER = "grok_official"
GROK_KEYWORD_PROVIDER = "grok_keyword"
GROK_WEB_PROVIDER = "grok_web"
```

또는 최소한 429 시 "해당 모듈만 중단, 나머지는 계속" 로직 필요.

**official signals와 keyword 간 중복 제거**: `source_handle` + `headline` 유사도 기반으로 같은 포스트 필터링.

### 1-2. Perplexity Search API: allowlist → deny list 전환

**핵심 변경**: `search_domain_filter`를 allowlist에서 deny list로 전환하여 검색 자유도 확보.

#### 현재 구조의 이중 필터 문제

```
[1단계] API 요청 — search_domain_filter = ["reuters.com", "bloomberg.com", ...] (allowlist)
  → Perplexity가 이 6개 도메인 안에서만 검색
  → 주말에 이 도메인들에 신규 기사 없으면 데이터 페이지 반환

[2단계] 결과 파싱 — _is_allowed_domain(url, allowlist) 재검증
  → 같은 allowlist로 한번 더 필터링
  → 다른 좋은 도메인의 기사가 있어도 차단
```

#### 변경: deny list 기반으로 전환

```
[1단계] API 요청 — search_domain_filter = ["-markets.ft.com", "-data.coindesk.com", ...]
  → 쓰레기 도메인만 제외, 나머지는 자유 검색
  → Perplexity가 관련성 높은 기사를 폭넓게 탐색 가능

[2단계] 결과 파싱 — deny 필터만 적용 (기존 3개 유지 + 확장)
  → _is_disallowed_market_data_result() — 데이터 페이지 차단
  → _is_topic_landing_page() — 인덱스/랜딩 페이지 차단
  → _is_invalid_news_title() — 짧은 제목, 비영어 차단
  → (신규) _is_low_quality_source() — SEO 스팸, 포럼, 소셜 미디어 차단
```

#### API 파라미터 변경

```python
# AS-IS: allowlist
TOPIC_SPECS = (
    SearchTopic(
        name="macro",
        domain_filter=("reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com", "marketwatch.com"),
        ...
    ),
)

# TO-BE: deny list (모든 토픽 공통)
SEARCH_DENY_DOMAINS = (
    "-markets.ft.com",
    "-data.coindesk.com",
    "-downloads.coindesk.com",
    "-sponsored.bloomberg.com",
    "-cn.wsj.com",
    "-jp.reuters.com",
    "-apps.apple.com",
    "-podcasts.apple.com",
    "-status.perplexity.ai",
)
```

#### _parse_results() 변경

```python
# AS-IS: allowlist 재검증
def _parse_results(*, payload, topic, allowed_domains=None):
    domain_allowlist = allowed_domains or topic.domain_filter
    for raw in _flatten_results(payload):
        if not _is_allowed_domain(url, domain_allowlist):  # ← 제거
            continue

# TO-BE: deny만 적용, allowlist 제거
def _parse_results(*, payload, topic):
    for raw in _flatten_results(payload):
        if _is_disallowed_market_data_result(title=title, url=url):
            continue
        if _is_topic_landing_page(topic=topic.name, url=url, title=title):
            continue
        if _is_invalid_news_title(title):
            continue
        if _is_low_quality_source(url):  # 신규
            continue
```

#### 신규 deny 필터: _is_low_quality_source()

allowlist 제거 시 SEO 스팸 등 저품질 소스 유입 방지 필요:

```python
LOW_QUALITY_DOMAINS = {
    # 소셜 미디어 / 포럼
    "reddit.com", "twitter.com", "x.com", "facebook.com",
    "linkedin.com", "quora.com", "medium.com",
    # 가격 집계 / 데이터 포탈
    "tradingview.com", "investing.com", "stockanalysis.com",
    "finance.yahoo.com", "google.com/finance",
    # 위키 / 참조
    "wikipedia.org", "investopedia.com",
    # 구인 / 비관련
    "glassdoor.com", "indeed.com",
}

def _is_low_quality_source(url: str) -> bool:
    domain = normalize_domain(url)
    return any(domain_matches(domain, blocked) for blocked in LOW_QUALITY_DOMAINS)
```

#### 품질 보정: 소프트 랭킹

allowlist를 제거하면 다양한 도메인에서 기사가 들어옴. 신뢰 도메인 우선순위는 **하드 필터가 아닌 랭킹 점수**로 유지:

```python
# news_policy.py의 기존 DOMAIN_SCORES가 이 역할을 이미 수행
# reuters.com: 5.0, bloomberg.com: 5.0, wsj.com: 4.5, ...
# 알 수 없는 도메인: 0.0 (기본)

# news_selection._item_score()에서 domain_score가 랭킹에 반영됨
# → 신뢰 도메인 기사가 자연스럽게 상위로 올라감
# → 비신뢰 도메인 기사도 수집은 되지만 하위 랭킹
```

#### SearchTopic 간소화

```python
# AS-IS: 토픽별 allowlist 도메인 관리
SearchTopic(
    name="macro",
    domain_filter=("reuters.com", "bloomberg.com", ...),
    retry_domain_filter=("reuters.com", "bloomberg.com", ...),  # 확장판
)

# TO-BE: 공통 deny list 사용, 토픽별 도메인 관리 불필요
SearchTopic(
    name="macro",
    # domain_filter, retry_domain_filter 제거 또는 공통 deny list 참조
)
```

#### retry 전략 간소화

현재 3~4단계 retry(last_updated → date_range → broad)는 allowlist 안에서 결과를 찾기 위한 것이었음.
deny list 전환 후에는 1차 검색의 자유도가 높아지므로 retry 단계를 줄일 수 있음:

```
AS-IS: 1차 검색 → last_updated retry → date_range retry → broad retry (15회)
TO-BE: 1차 검색 → recency 확장 retry (최대 8회 = 4토픽 × 2단계)
```

### 1-3. NewsAPI + RSS — 현행 유지

변경 없음. Grok + Perplexity가 모두 실패할 때의 최종 안전망 역할.

---

## Phase 2 상세: Perplexity Sonar 맥락 보강

### 역할 전환

```
AS-IS: Sonar = 비활성 (PERPLEXITY_USE_SONAR_SUMMARY=false)
TO-BE: Sonar = Phase 1 수집 결과를 바탕으로 심층 맥락 분석
```

**Sonar는 "수집"이 아니라 "분석"을 담당.** Phase 1에서 수집된 기사 제목+요약 목록을 Sonar 프롬프트에 넣고, Sonar의 웹 검색 기능이 자동으로 배경 맥락을 탐색하게 함.

### 기존 Sonar 코드와의 차이

| 항목 | 기존 perplexity_sonar.py | 재설계 |
|------|--------------------------|--------|
| 입력 | 토픽 프롬프트 (고정) | Phase 1 수집 결과 (동적) |
| 역할 | 독립 수집 | 맥락 보강 + 교차 검증 |
| 출력 | TopicSummary + citation NewsItem | 기사별 market_context + 교차 검증 결과 |
| 호출 횟수 | 토픽 4개 × 1회 = 4회 | 통합 1회 (전체 수집 결과를 한번에) |
| 모델 | `sonar` (기본) | 평일 `sonar` / 주말 `sonar-pro` |

### Sonar 프롬프트 설계

```python
SONAR_CONTEXT_PROMPT = """아래는 오늘 수집된 주요 금융 뉴스 시그널 목록입니다.

{collected_signals}

위 시그널들을 바탕으로:
1. 각 시그널의 배경(Context)을 웹에서 추가 검색하여 보강해주세요
2. 서로 연관되거나 상충하는 시그널이 있으면 교차 검증해주세요
3. 한국 투자자 관점에서 오늘 시장의 핵심 내러티브를 정리해주세요
4. 각 분석에 출처를 명확히 표시해주세요

데이터 포탈 페이지, 시세 조회 페이지는 출처로 사용하지 마세요.
"""
```

핵심: **Sonar에 URL을 주입하지 않음** (공식 가이드 비권장). 대신 기사 제목+요약 텍스트를 주고, Sonar가 자체 웹 검색으로 맥락을 찾게 함.

### 출력 스키마

```python
SONAR_CONTEXT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "news_context_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "required": ["analyses", "key_narrative"],
            "properties": {
                "analyses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["signal_ref", "background", "market_impact", "confidence"],
                        "properties": {
                            "signal_ref": {"type": "string", "description": "원본 시그널 제목"},
                            "background": {"type": "string", "description": "추가 검색으로 확인한 배경"},
                            "market_impact": {"type": "string", "description": "시장 영향 분석"},
                            "cross_references": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "관련/상충하는 다른 시그널 참조"
                            },
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        },
                        "additionalProperties": False,
                    },
                },
                "key_narrative": {"type": "string", "description": "오늘 시장의 핵심 스토리 1~2문장"},
            },
            "additionalProperties": False,
        },
    },
}
```

### Sonar 결과의 활용

Sonar 분석 결과는 **브리핑 생성 프롬프트에 추가 맥락으로 주입**:

```
OpenAI 브리핑 생성 입력:
  - 시장 데이터 (market.py) — 숫자
  - Phase 1 뉴스 시그널 — 기사 목록
  - Phase 2 Sonar 분석 — 맥락, 내러티브, 교차 검증 (신규)
```

### Sonar 실패 시

Sonar가 실패해도 Phase 1 수집 결과와 시장 데이터만으로 브리핑 생성 가능 (현행과 동일). Sonar는 품질 향상 레이어이지 필수 레이어가 아님.

---

## Phase 3: 브리핑 생성 + 검수 — OpenAI (현행 유지)

변경 없음. 기존 `briefing.py` + `brief_review.py` 흐름 유지.

다만 Phase 2 Sonar 분석 결과가 추가되므로 **프롬프트 템플릿에 맥락 섹션 추가** 필요.

---

## 구현 우선순위

### Step 1: Perplexity Search API deny list 전환 (즉시 효과, 핵심)

- `search_domain_filter` allowlist → deny list
- `_parse_results()`에서 `_is_allowed_domain()` 제거
- `_is_low_quality_source()` deny 필터 추가
- retry 3~4단계 → 2단계로 간소화
- **예상 효과**: 주말에도 다양한 도메인에서 기사 수집 가능

검증:
```bash
SEND_EMAIL=false python3 main.py once --print-brief
# observability 로그에서 perplexity_items_collected 확인
```

### Step 2: Grok X keyword + web search 활성화

- `GROK_X_KEYWORD_SEARCH_ENABLED=true`
- `GROK_WEB_SEARCH_ENABLED=true`
- grok_x_keyword에 `ai_bigtech_primary`, `btc_etf_primary` 그룹 추가
- grok_web_search에 주말 대응 + `why_it_matters` + `citations` 추가
- 서킷 브레이커 모듈별 분리

검증:
```bash
GROK_X_KEYWORD_SEARCH_ENABLED=true GROK_WEB_SEARCH_ENABLED=true SEND_EMAIL=false python3 main.py once --print-brief
# grok_signals_collected, grok_x_keyword, grok_web_search 로그 확인
```

### Step 3: Sonar 맥락 보강 레이어 구현

- Phase 1 수집 결과를 Sonar 프롬프트에 주입하는 새 함수
- JSON Schema 구조화 출력
- 브리핑 프롬프트 템플릿에 맥락 섹션 추가
- `PERPLEXITY_USE_SONAR_SUMMARY=true` 활성화

### Step 4: 안정화 + 튜닝

- 1~2주 운영하며 observability 로그 모니터링
- 도메인 다양성, 토픽 커버리지, 품질 점수 추이 확인
- 필요시 deny list 확장, 프롬프트 조정
- legacy fallback 비중 축소 여부 판단 (rollout 메커니즘 활용)

---

## 비용 영향

| 항목 | AS-IS | TO-BE |
|------|-------|-------|
| Perplexity Search API | 15회/실행 ($0.075) | 4~8회/실행 ($0.02~0.04) |
| Perplexity Sonar | 0회 | 1회/실행 (sonar ~$0.005~0.01) |
| Grok | 4회/실행 | 6~8회/실행 (keyword 2~4 + web 1 + official 3) |
| OpenAI | 4회/실행 | 4회/실행 (변경 없음) |

Grok 호출이 늘지만 Perplexity Search 호출이 줄어 전체 비용은 유사하거나 소폭 증가.

---

## 리스크와 대응

| 리스크 | 대응 |
|--------|------|
| Perplexity deny list 전환 후 저품질 기사 유입 | `_is_low_quality_source()` deny 필터 + 소프트 랭킹으로 방어 |
| Grok 3개 모듈 동시 활성화 시 rate limit | 모듈별 서킷 브레이커 분리 + 요청 간격 제어 |
| Grok X keyword + official signals 결과 중복 | source_handle 기반 dedup |
| Sonar JSON Schema cold start (10~30초) | 첫 실행 후 캐싱됨, 파이프라인 timeout 여유 확보 |
| Grok web search 토픽 분류 오류 | 정규화 + fallback topic 할당 |

---

## 요약

```
Phase 1 (수집 극대화):
  Perplexity Search → deny list 전환으로 검색 자유도 확보
  Grok × 3 모듈 전부 활성화로 X 실시간 + 웹 뉴스 커버리지 확대
  Legacy → 최종 안전망 유지

Phase 2 (맥락 분석):
  Sonar → Phase 1 결과 기반 배경 탐색 + 교차 검증 + 내러티브 정리

Phase 3 (브리핑):
  OpenAI → 시장 데이터 + 뉴스 + Sonar 맥락을 종합하여 브리핑 생성
```
