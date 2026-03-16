# 뉴스 파이프라인 재설계 계획

> 작성일: 2026-03-16
배경: 주말 실행에서 Perplexity Search API 4개 토픽 전부 수집 0건 발생. Grok 공식 시그널 4건만으로 브리핑 생성.
근본 원인: Search API에 allowlist 6개 도메인만 허용 → 주말에 해당 도메인 신규 기사 없음 → 데이터 페이지만 반환 → 필터에 전부 걸림
> 

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

**문제의 본질**: Perplexity `search_domain_filter`에 allowlist로 [ft.com](http://ft.com/), [bloomberg.com](http://bloomberg.com/) 등 6개만 허용 → 검색 엔진의 자유도를 과도하게 제한. 주말/비장중에 이 도메인들의 신규 기사가 없으면 정적 페이지가 올라와 전부 필터링됨.

---

## 재설계 방향 (TO-BE)

```
[Phase 1] 키워드 추출 — 병렬 실행
├─ 시장 데이터 기반 키워드 자동 추출 (항상 실행, Grok 독립)
└─ Grok official signals + X keyword (가능 시 보강)

[Phase 2] 뉴스 수집 — 병렬 실행
├─ Perplexity Search API (deny list + recency + 키워드 타겟 검색)
├─ Gemini Flash fallback (Perplexity 0건 시)
└─ Legacy RSS (최종 안전망)

[Phase 3] 맥락 보강 — Perplexity Sonar
  Phase 2 수집 결과 상위 N건 기반 심층 맥락 분석

[Phase 4] 브리핑 생성 + 검수
├─ OpenAI GPT-5 mini (브리핑 생성)
└─ Claude Haiku 4.5 (브리핑 검수)
```

### 핵심 설계 원칙

```
1. Grok과 Perplexity는 독립적으로 동작 가능해야 함
   Grok 장애 → 시장 데이터 키워드로 Perplexity 단독 실행
   Perplexity 0건 → Gemini Flash fallback

2. 키워드는 두 소스에서 합산
   시장 데이터 기반 (항상 가능, 후행)
   Grok X 트렌딩 (가능할 때 보강, 선행)

3. Grok web search 비활성 유지
   Perplexity와 웹 수집 역할 중복
   출처 URL 추적은 Perplexity가 더 신뢰성 높음
   Grok은 X 실시간 시그널 + 키워드 추출 전담

4. Perplexity는 키워드 기반 타겟 검색 1회만
   기본 검색 + 키워드 검색 2회 호출은 비용 대비 중복 기사 증가
   키워드 합산 후 타겟 검색 1회로 통합
```

---

## Phase 1 상세: 키워드 추출

### 1-1. 시장 데이터 기반 키워드 자동 추출 (항상 실행)

Grok 장애와 완전히 무관하게 항상 동작하는 기본 키워드 소스.
이미 수집된 시장 수치에서 오늘 화제 키워드를 자동 생성.

```python
def extract_market_keywords(market_data: MarketPacket) -> list[str]:
    keywords = []
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%B %d %Y")

    if market_data.vix and market_data.vix.value > 25:
        keywords.append(f"volatility spike market fear {today}")
    if market_data.us10y and abs(market_data.us10y.change_pct or 0) > 1.0:
        direction = "surge" if market_data.us10y.change_pct > 0 else "drop"
        keywords.append(f"treasury yields {direction} {today}")
    if market_data.spx and abs(market_data.spx.change_pct or 0) > 1.5:
        direction = "rally" if market_data.spx.change_pct > 0 else "selloff"
        keywords.append(f"S&P 500 {direction} {today}")
    for ticker, stock in market_data.tech_stocks.items():
        if abs(stock.change_pct or 0) > 3.0:
            direction = "surge" if stock.change_pct > 0 else "decline"
            keywords.append(f"{ticker} {direction} {today}")
    if market_data.btc and abs(market_data.btc.change_pct or 0) > 3.0:
        direction = "rally" if market_data.btc.change_pct > 0 else "drop"
        keywords.append(f"bitcoin {direction} {today}")

    return keywords
```

**특성**: 수치에 이미 반영된 후행 정보. 신뢰도 높음. 항상 사용 가능.

### 1-2. Grok 키워드 추출 (가능 시 보강)

**특성**: X 실시간 트렌딩. 수치에 미반영된 선행 시그널 포착 가능.

### A. grok_official_signals — 현행 유지

- 상태: **켜짐** (기본값)
- 역할: 검증된 공식 X 핸들(24개 엔티티) 모니터링
- 그룹: `macro_regulator`, `ai_bigtech_primary`, `btc_etf_primary`
- 로그 실적: 4건/실행 — 주말에도 안정적으로 동작
- 변경사항: 없음

### B. grok_x_keyword — 활성화 + 그룹 확장

- 상태: **꺼짐** → 켜짐 (`GROK_X_KEYWORD_SEARCH_ENABLED=true`)
- 역할: X 실시간 트렌딩 키워드 추출 + 섹터별 분류
- 출력: 섹터별 키워드 dict (Perplexity 타겟 검색에 주입)

현재 문제점과 개선:

| 항목 | 현재 | 개선 |
| --- | --- | --- |
| 그룹 커버리지 | `macro_and_equity`, `crypto_and_etf` 2개 | `ai_bigtech_primary`, `btc_etf_primary` 추가 → 4개 |
| 프롬프트 | 영문 고정 | 주말 맥락 추가 (금요일 장마감 이후 분석 포함 유도) |
| 결과 품질 | 프롬프트 의존 | `why_it_matters` 필드 검증 추가 |
| 중복 | official signals과 중복 가능 | `source_handle` 기반 dedup |
| 출력 구조 | 시그널 목록 | 섹터별 키워드 분류 추가 |

```python
# grok_x_keyword.py — 그룹 추가 + 키워드 추출 출력
GROUP_PROMPTS = {
    MACRO_EQUITY_GROUP: MACRO_EQUITY_PROMPT,
    CRYPTO_ETF_GROUP: CRYPTO_ETF_PROMPT,
    "ai_bigtech_primary": AI_BIGTECH_PROMPT,      # 신규
    "btc_etf_primary": BTC_ETF_PRIMARY_PROMPT,    # 신규
}

GROUP_TOPIC_MAP = {
    MACRO_EQUITY_GROUP: "macro",
    CRYPTO_ETF_GROUP: "bitcoin",
    "ai_bigtech_primary": "ai_bigtech",           # 신규
    "btc_etf_primary": "bitcoin",                 # 신규
}

# 키워드 추출 출력 구조
GrokKeywordOutput = {
    "keywords_by_sector": {
        "macro":      ["Fed 금리동결", "treasury yields surge"],
        "ai_bigtech": ["NVDA 수출규제", "Meta AI 투자"],
        "bitcoin":    ["BTC ETF 유입", "규제 동향"],
    },
    "signals": [...],  # 기존 시그널 목록 유지
}
```

```python
# AI/빅테크 프롬프트 (신규)
AI_BIGTECH_PROMPT = """Search X for the most significant AI and Big Tech posts
from the last {lookback_hours} hours.
Focus on:
1. NVIDIA, AMD, TSMC, ASML semiconductor news and analyst commentary
2. Microsoft, Apple, Amazon, Google, Meta strategic moves
3. AI infrastructure, data center capex, model announcements
4. Earnings guidance, revenue signals, product launches

Return the top {max_items} most market-moving posts as JSON:
{{
  "keywords": ["keyword1", "keyword2"],
  "signals": [
    {{
      "headline": "...",
      "summary": "...",
      "why_it_matters": "...",
      "sentiment": "bullish|bearish|neutral",
      "source_handle": "...",
      "posted_at": "ISO8601"
    }}
  ]
}}
Skip marketing, promotional, and non-market posts."""
```

### C. grok_web_search — 비활성 유지

- 상태: **꺼짐** 유지 (활성화하지 않음)
- 이유: Perplexity와 웹 뉴스 수집 역할 중복. 출처 URL 추적 신뢰성은 Perplexity가 높음.
- Grok은 X 실시간 시그널 + 키워드 추출에 집중.

### D. 키워드 합산

```python
def build_search_keywords(
    market_keywords: list[str],
    grok_keywords: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    """
    시장 데이터 키워드 + Grok 키워드 합산.
    Grok 장애 시 시장 데이터 키워드만으로 동작.
    """
    result = {
        "macro": [],
        "ai_bigtech": [],
        "bitcoin": [],
        "us_equity": [],
    }

    # 시장 데이터 키워드 분배 (항상)
    for kw in market_keywords:
        if any(k in kw for k in ["treasury", "Fed", "yields", "dollar"]):
            result["macro"].append(kw)
        elif any(k in kw for k in ["bitcoin", "BTC"]):
            result["bitcoin"].append(kw)
        elif any(k in kw for k in ["S&P", "Nasdaq", "SOXX"]):
            result["us_equity"].append(kw)
        else:
            result["ai_bigtech"].append(kw)

    # Grok 키워드 보강 (가능 시)
    if grok_keywords:
        for sector, kws in grok_keywords.items():
            if sector in result:
                result[sector].extend(kws)

    return result
```

### E. Grok 서킷 브레이커 분리

현재 2개 모듈이 `GROK_PROVIDER = "grok"` 공유 → 하나가 429 맞으면 전부 차단.

```python
# 모듈별 provider 분리
GROK_OFFICIAL_PROVIDER = "grok_official"
GROK_KEYWORD_PROVIDER = "grok_keyword"
# GROK_WEB_PROVIDER 불필요 (비활성 유지)
```

---

## Phase 2 상세: 뉴스 수집

### 2-1. Perplexity Search API — 메인

**핵심 변경 3가지**:

1. allowlist → deny list 전환 (검색 자유도 확보)
2. `search_recency_filter: "day"` 추가 (24시간 이내 기사만)
3. Phase 1 키워드를 쿼리에 주입 (타겟 검색)

### allowlist → deny list 전환

현재 구조의 이중 필터 문제:

```
[1단계] API 요청 — allowlist 6개 도메인 제한
  → 주말 신규 기사 없으면 데이터 페이지 반환

[2단계] 결과 파싱 — 같은 allowlist 재검증
  → 다른 좋은 도메인 기사도 차단
```

변경 후:

```
[1단계] API 요청 — deny list + recency filter
  → 쓰레기 도메인만 제외, 나머지 자유 검색
  → search_recency_filter: "day" → 24시간 이내 기사만

[2단계] 결과 파싱 — deny 필터만 적용
  → 데이터 페이지 차단
  → 저품질 소스 차단
  → 비영어 제목 차단
```

### API 파라미터

```python
# TO-BE: deny list + recency (모든 토픽 공통)
SEARCH_DENY_DOMAINS = (
    "-markets.ft.com",
    "-data.coindesk.com",
    "-downloads.coindesk.com",
    "-sponsored.bloomberg.com",
    "-cn.wsj.com",
    "-jp.reuters.com",
    "-apps.apple.com",
    "-podcasts.apple.com",
    "-tv.apple.com",
    "-status.perplexity.ai",
)

# 쿼리 구성: 날짜 + 키워드 주입
def build_query(topic: str, keywords: list[str]) -> str:
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%B %d %Y")
    kw_str = " ".join(keywords[:3]) if keywords else ""
    base = {
        "macro":      f"U.S. macro market news {today}",
        "us_equity":  f"U.S. stock market news {today}",
        "ai_bigtech": f"AI big tech market news {today}",
        "bitcoin":    f"bitcoin crypto market news {today}",
    }[topic]
    return f"{base} {kw_str}".strip()

# API 호출 파라미터
params = {
    "model": "sonar",
    "search_domain_filter": SEARCH_DENY_DOMAINS,
    "search_recency_filter": "day",  # 핵심 추가
    "messages": [{"role": "user", "content": query}],
}
```

### _parse_results() 변경

```python
# AS-IS: allowlist 재검증
def _parse_results(*, payload, topic, allowed_domains=None):
    domain_allowlist = allowed_domains or topic.domain_filter
    for raw in _flatten_results(payload):
        if not _is_allowed_domain(url, domain_allowlist):  # ← 제거
            continue

# TO-BE: deny만 적용
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

### 신규 deny 필터: _is_low_quality_source()

```python
LOW_QUALITY_DOMAINS = {
    "reddit.com", "twitter.com", "x.com", "facebook.com",
    "linkedin.com", "quora.com", "medium.com",
    "tradingview.com", "investing.com", "stockanalysis.com",
    "finance.yahoo.com", "google.com/finance",
    "wikipedia.org", "investopedia.com",
    "glassdoor.com", "indeed.com",
}

def _is_low_quality_source(url: str) -> bool:
    domain = normalize_domain(url)
    return any(domain_matches(domain, blocked) for blocked in LOW_QUALITY_DOMAINS)
```

### 소프트 랭킹 (기존 유지)

allowlist 제거 후 신뢰 도메인 우선순위는 하드 필터가 아닌 랭킹 점수로 유지:

```python
# news_policy.py 기존 DOMAIN_SCORES 활용
# reuters.com: 5.0, bloomberg.com: 5.0, wsj.com: 4.5 ...
# 알 수 없는 도메인: 0.0 (수집은 되나 하위 랭킹)
```

### SearchTopic 간소화

```python
# AS-IS: 토픽별 allowlist 도메인 관리
SearchTopic(
    name="macro",
    domain_filter=("reuters.com", "bloomberg.com", ...),
    retry_domain_filter=("reuters.com", "bloomberg.com", ...),
)

# TO-BE: 공통 deny list 사용, 토픽별 도메인 관리 불필요
SearchTopic(
    name="macro",
    # domain_filter, retry_domain_filter 제거
    # 공통 SEARCH_DENY_DOMAINS 참조
)
```

### retry 전략 간소화

```
AS-IS: 1차 검색 → last_updated retry → date_range retry → broad retry (15회)
TO-BE: 1차 검색 → recency 확장 retry (최대 8회 = 4토픽 × 2단계)

이유: allowlist 안에서 결과를 찾기 위한 retry였음.
     deny list 전환 + recency filter로 1차 검색 품질이 높아지므로 불필요.
```

### 2-2. Gemini 2.5 Flash — fallback (Perplexity 0건 시)

```python
if perplexity_valid_count == 0:
    gemini_news = fetch_gemini_grounding(
        query=f"U.S. stock market news today {today}",
        keywords=final_keywords,
        # Google Search grounding 500 RPD 무료
    )
```

Perplexity와 역할 분리:

- Perplexity: 뉴스 수집 메인 + 출처 URL 추적
- Gemini: Perplexity 0건 시만 실행, Google News 접근성 활용

### 2-3. Legacy RSS + NewsAPI — 최종 안전망

변경 없음. Perplexity 0건 AND Gemini 0건 시 실행.

---

## Phase 3 상세: Perplexity Sonar 맥락 보강

### 역할

```
AS-IS: Sonar = 비활성 (PERPLEXITY_USE_SONAR_SUMMARY=false)
TO-BE: Sonar = Phase 2 수집 결과 기반 심층 맥락 분석
```

Sonar는 “수집”이 아닌 “분석” 전담. Phase 2에서 수집된 기사 제목+요약을 입력으로 받아 Sonar의 웹 검색으로 배경 맥락을 탐색.

### 입력 토큰 관리 (중요)

Phase 2 수집 결과 전체를 주입하면 40~46건 = 8,000~12,000 토큰. Sonar 단가 $1.00/1M이지만 입력이 클수록 품질 저하.

```python
# 섹터별 상위 3건으로 제한 → 총 12~15건
sonar_input_items = []
for sector in ["macro", "ai_bigtech", "bitcoin", "us_equity"]:
    top3 = sorted(
        [item for item in phase2_news if item.topic == sector],
        key=lambda x: x.domain_score,
        reverse=True,
    )[:3]
    sonar_input_items.extend(top3)

# 예상 토큰: 약 2,000~3,000 (적정 수준)
```

### Sonar 프롬프트

```python
SONAR_CONTEXT_PROMPT = """아래는 오늘 수집된 주요 금융 뉴스 시그널 목록입니다.

{collected_signals}

위 시그널들을 바탕으로:
1. 각 시그널의 배경(Context)을 웹에서 추가 검색하여 보강하세요
2. 서로 연관되거나 상충하는 시그널이 있으면 교차 검증하세요
3. 한국 투자자 관점에서 오늘 시장의 핵심 내러티브를 정리하세요
4. 각 분석에 출처를 명확히 표시하세요

주의: 데이터 포탈 페이지, 시세 조회 페이지는 출처로 사용하지 마세요.
주의: Sonar에 URL을 직접 주입하지 않음 (공식 가이드 비권장).
      기사 제목+요약 텍스트만 입력, Sonar가 자체 웹 검색으로 맥락 탐색.
"""
```

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
                        "required": [
                            "signal_ref", "background",
                            "market_impact", "confidence"
                        ],
                        "properties": {
                            "signal_ref": {
                                "type": "string",
                                "description": "원본 시그널 제목"
                            },
                            "background": {
                                "type": "string",
                                "description": "추가 검색으로 확인한 배경"
                            },
                            "market_impact": {
                                "type": "string",
                                "description": "시장 영향 분석"
                            },
                            "cross_references": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "관련/상충하는 다른 시그널"
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"]
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "key_narrative": {
                    "type": "string",
                    "description": "오늘 시장의 핵심 스토리 1~2문장"
                },
            },
            "additionalProperties": False,
        },
    },
}
```

### 모델 선택

```python
sonar_model = "sonar-pro" if _is_weekend() else "sonar"
# 주말: 기사 수 적어 sonar-pro의 심층 검색이 더 유효
# 평일: sonar로 충분, 비용 절감
```

### Sonar 결과 활용

```
OpenAI 브리핑 생성 입력:
  - 시장 데이터 (숫자)
  - Phase 2 뉴스 시그널 (기사 목록)
  - Phase 3 Sonar 분석 (맥락, 내러티브, 교차 검증) ← 신규
```

### Sonar 실패 시

Phase 2 결과 + 시장 데이터만으로 브리핑 생성 (현행 동일). Sonar는 품질 향상 레이어이지 필수 아님.

---

## Phase 4 상세: 브리핑 생성 + 검수

### OpenAI GPT-5 mini — 브리핑 생성 (현행 유지)

변경 없음. Jinja2 템플릿에 Phase 3 Sonar 맥락 섹션 추가만 필요.

### Claude Haiku 4.5 — 브리핑 검수 (교체)

```
AS-IS: OpenAI GPT-5 mini 검수
  문제: JSON truncated 사례 발생 → fallback 브리핑 발동

TO-BE: Claude Haiku 4.5 검수
  장점: 구조화 출력 정확도 높음
        prompt caching 90% 할인 (검수 프롬프트는 static 비율 높음)
  효과: JSON truncated 문제 구조적 해소
        fallback 브리핑 발동 빈도 감소
```

---

## 섹터 확장 로드맵 (향후)

현재 1→2→3→4 단계 구조는 변경 없이 유지. 섹터 확장 시 Phase 2부터 병렬 분기.

```
현재 (단일 브리핑)
  Phase 1: 키워드 추출 (1회 공통)
  Phase 2: 뉴스 수집 (4개 토픽)
  Phase 3: Sonar 종합
  Phase 4: OpenAI 생성 + Claude 검수
  → 브리핑 1개 → 전체 발송

섹터 확장 후 (병렬 파이프라인)
  Phase 1: 키워드 추출 (1회 공통, 변경 없음)
           Grok이 섹터별 키워드 분류 출력
           ↓
  Phase 2~4: 섹터별 병렬 실행
  ┌─────────────────────────────────────┐
  │ semiconductor  ai    macro  bitcoin  │
  │ Perplexity    ...    ...    ...      │
  │ Sonar         ...    ...    ...      │
  │ OpenAI 생성   ...    ...    ...      │
  │ Claude 검수   ...    ...    ...      │
  └─────────────────────────────────────┘
  → 섹터별 브리핑 N개
  → 구독자 섹터 설정 기반 개별 발송

추가 비용: 섹터당 ~$0.018/실행 (Perplexity + Sonar + OpenAI + Claude 각 1회)
구조 변경: Phase 1 동일, Phase 2부터 병렬 복사만으로 확장 가능
```

---

## 구현 우선순위

### Step 1: Perplexity deny list + recency + 키워드 쿼리 (즉시 효과, 핵심)

- `search_domain_filter` allowlist → deny list
- `search_recency_filter: "day"` 추가
- 쿼리에 날짜 + 키워드 주입
- `_parse_results()`에서 `_is_allowed_domain()` 제거
- `_is_low_quality_source()` deny 필터 추가
- retry 15회 → 8회로 간소화

검증:

```bash
SEND_EMAIL=false python3 main.py once --print-brief
# perplexity_items_collected 로그에서 FT 데이터 페이지 없음 확인
# 유효 기사 건수 확인
```

### Step 2: 시장 데이터 기반 키워드 자동 추출

- `extract_market_keywords()` 구현
- `build_search_keywords()` 구현
- Perplexity 쿼리에 키워드 주입

검증:

```bash
# 로그에서 market_keywords_extracted 이벤트 확인
# Perplexity 쿼리에 키워드 포함 여부 확인
```

### Step 3: Grok X keyword 활성화 + 그룹 확장

- `GROK_X_KEYWORD_SEARCH_ENABLED=true`
- `ai_bigtech_primary`, `btc_etf_primary` 그룹 추가
- 키워드 추출 출력 구조 추가
- 서킷 브레이커 모듈별 분리 (official / keyword)
- official signals와 keyword 중복 제거 (source_handle 기반)

검증:

```bash
GROK_X_KEYWORD_SEARCH_ENABLED=true SEND_EMAIL=false python3 main.py once --print-brief
# grok_signals_collected, grok_x_keyword 로그 확인
# 키워드 추출 결과 확인
```

### Step 4: ~~Claude Haiku 검수 교체~~ → OpenAI 단일 검수 유지

> **결정 변경 (2026-03-16)**: 비용 효율성 재검토 결과 OpenAI 단일 유지로 결정.
> JSON truncated 문제는 `max_output_tokens=2000` + `json_schema` strict 모드로 해결.

- `brief_review.py` — `VALIDATOR_MAX_OUTPUT_TOKENS` 2000, `json_schema` strict 모드
- Anthropic 의존성 전체 제거 (`requirements.txt`, `config.py`, `llm_provider_policy.py`, `observability.py`)

검증:

```bash
# brief_review 로그에서 JSON parse 오류 없음 확인
# fallback 브리핑 미발동 확인
```

### Step 5: Gemini Flash fallback 추가

- `fetch_gemini_grounding()` 구현
- Perplexity 0건 시 자동 실행
- Google Search grounding 500 RPD 무료 한도 모니터링

### Step 6: Sonar 맥락 보강 레이어

- Phase 2 상위 3건 × 4섹터 = 12건 입력 제한 구현
- JSON Schema 구조화 출력
- 브리핑 프롬프트 템플릿에 맥락 섹션 추가
- 주말 `sonar-pro` / 평일 `sonar` 모델 선택
- `PERPLEXITY_USE_SONAR_SUMMARY=true` 활성화

### Step 7: 안정화 + 튜닝

- 1~2주 운영하며 observability 로그 모니터링
- 도메인 다양성, 토픽 커버리지, 품질 점수 추이 확인
- deny list 확장 여부 판단
- Sonar 입력 건수 최적화 (12건 → 조정)
- legacy fallback 비중 추이 확인

---

## 비용 영향

| 항목 | AS-IS | TO-BE |
| --- | --- | --- |
| Perplexity Search | 15회/실행 (~$0.075) | 8회/실행 (~$0.040) |
| Perplexity Sonar | 0회 | 1회/실행 (~$0.008) |
| Gemini Flash | 0회 | 0.3회 평균 (~$0.001) |
| Grok | 4회/실행 (~$0.003) | 6회/실행 (~$0.005) |
| OpenAI | 4회/실행 (~$0.007) | 4회/실행 (~$0.007) |
| Claude Haiku | 0회 | 2회/실행 (~$0.002) |
| **총계** | **~$0.085** | **~$0.063** |

Perplexity Search retry 간소화로 비용 감소. Sonar + Claude 추가되지만 전체 비용은 오히려 감소.

---

## 리스크와 대응

| 리스크 | 대응 |
| --- | --- |
| Perplexity deny list 전환 후 저품질 기사 유입 | `_is_low_quality_source()` + 소프트 랭킹 방어 |
| Grok 장애 | 시장 데이터 키워드로 Perplexity 독립 실행 |
| Grok keyword + official signals 중복 | source_handle 기반 dedup |
| Sonar JSON cold start (10~30초) | 첫 실행 후 캐싱. 파이프라인 timeout 여유 확보 |
| Sonar 입력 과다 시 품질 저하 | 섹터별 상위 3건 제한 (총 12건) |
| Claude Haiku JSON 출력 실패 | fallback으로 기존 검수 로직 유지 |
| Gemini 500 RPD 초과 | 카운터 모니터링. 초과 시 Legacy RSS로 직행 |

---

## 요약

```
Phase 1 (키워드 추출):
  시장 데이터 기반 자동 추출 (항상, Grok 독립)
  Grok X keyword (가능 시 보강, 선행 시그널)
  합산 키워드 → Perplexity 타겟 검색에 주입

Phase 2 (뉴스 수집):
  Perplexity Search → deny list + recency + 키워드 타겟 검색
  Gemini Flash → Perplexity 0건 시 fallback
  Legacy RSS → 최종 안전망

Phase 3 (맥락 분석):
  Sonar → Phase 2 상위 12건 기반 배경 탐색 + 교차 검증
  주말 sonar-pro / 평일 sonar

Phase 4 (브리핑):
  OpenAI → 시장 데이터 + 뉴스 + Sonar 맥락 종합 생성
  Claude Haiku → 구조화 검수 (JSON truncated 해소)
```