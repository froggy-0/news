# 뉴스 수집 아키텍처 재설계 계획: Perplexity + Grok 통합

> 작성일: 2026-03-15
> 상태: 설계 단계

---

## 1. 현재 문제 진단

### 1.1 현재 아키텍처와 각 프로바이더 역할

```
┌─ Perplexity Search API ─────── 기사 URL 링크 수집 (주 소스) ── 현재 0건 실패
│
├─ Grok X Search ─────────────── 공식 X 핸들 포스트 수집 ─────── 활성 핸들 3개, 대부분 0건
│
├─ Legacy RSS / NewsAPI ──────── 폴백 뉴스 수집 ────────────── 1건 수준
│
└─ OpenAI web_search ─────────── 최종 백필 ─────────────────── 품질 낮은 5건으로 겨우 채움
```

### 1.2 Perplexity 실패 원인

| 문제 | 상세 |
|------|------|
| **도메인 필터 역효과** | `ft.com` 허용 → `markets.ft.com` 시세 페이지만 대거 반환. 실제 기사 0건 |
| **검색 결과만 수집** | Search API는 링크 목록만 반환. Perplexity의 정보 종합·요약 능력을 전혀 활용하지 못함 |
| **4토픽 × 4단계 재시도** | 15회 API 호출에도 기사 0건. 같은 실패 반복 |

### 1.3 Grok 실패 원인

| 문제 | 상세 |
|------|------|
| **활성 X 핸들이 3개뿐** | 15개 엔티티 중 `x_verified=true`가 AMD, Fidelity, BlackRock만. NVIDIA, Microsoft, Meta 등은 모두 미등록 |
| **공식 계정 = 저빈도** | 대기업 공식 계정은 "시장에 물질적으로 중요한" 포스트를 자주 올리지 않음 |
| **macro_regulator 그룹 비활성** | Fed, Treasury, SEC의 X 핸들이 등록되지 않아 검색 자체 불가 |
| **X Search만 사용** | Grok의 **Web Search 기능을 전혀 활용하지 않음** |
| **프롬프트가 지나치게 엄격** | "Ignore reposts, routine marketing, greetings" → 대부분의 포스트가 필터링됨 |

### 1.4 핵심 통찰

**Perplexity Finance** (`perplexity.ai/finance`)가 보여주는 시장 요약:
```
The NASDAQ 100 dropped 189 points to close at 29,697 on Friday after
hotter-than-expected PCE inflation data — core PCE rising 0.4% month-over-month
— crushed rate-cut hopes and sent 10-year Treasury yields up 8 basis points
to 4.32%.
```

이 품질은 **Search API가 아닌 Sonar Chat Completions API**로 재현 가능하다.

**Grok**은 X 포스트 검색에만 쓰이고 있지만, **Web Search + 키워드 기반 X Search**를 조합하면 실시간 시장 반응과 뉴스를 동시에 수집하는 독립 소스가 될 수 있다.

---

## 2. 재설계 방향

### 2.1 3-Provider 병렬 수집 아키텍처

```
[현재]
Perplexity Search API → 기사 URL 수집(실패) → Grok X 핸들 검색(0건) → Legacy → OpenAI 백필

[개선]
┌─ Perplexity Sonar ──── 토픽별 시장 요약 + citations ────── 핵심 컨텍스트
│  (Chat Completions)    (도메인 필터 제거, LLM이 자유 검색)
│
├─ Grok ──────────────── 2가지 역할 병렬 수행 ──────────── 실시간 보강
│  ├─ X Search ───────── 키워드 기반 시장 반응/속보 ─────── (핸들 제한 해제)
│  └─ Web Search ─────── 실시간 뉴스 기사 수집 ────────── (신규 활용)
│
└─ OpenAI web_search ─── 최종 백필 (품질 미달 시만) ────── 안전망
```

### 2.2 각 프로바이더의 새로운 역할

| 프로바이더 | 현재 역할 | 새 역할 | 강점 활용 |
|-----------|----------|---------|----------|
| **Perplexity Sonar** | 기사 URL 나열 | **시장 요약 텍스트 생성** | 웹 전체 검색 + LLM 종합 능력 |
| **Grok X Search** | 공식 핸들 3개 포스트 | **키워드 기반 시장 반응 수집** | X 실시간 데이터 접근 |
| **Grok Web Search** | 미사용 | **실시간 뉴스 기사 수집** | 웹 검색 + LLM 분석 |
| **OpenAI** | 백필 + 브리핑 생성 | 브리핑 생성 + 최종 백필 | 브리핑 작성에 집중 |

### 2.3 왜 이 조합인가

```
Perplexity Sonar  = "무슨 일이 있었는지" 종합 요약 (분석가 리포트)
Grok X Search     = "시장이 어떻게 반응하는지" 실시간 맥박 (트레이더 데스크)
Grok Web Search   = "어떤 기사가 나왔는지" 최신 뉴스 (뉴스 와이어)
```

세 소스가 **서로 다른 성격의 정보**를 제공해서 브리핑이 풍부해진다:
- Sonar: 수치 + 인과관계 + 출처가 통합된 내러티브
- Grok X: 금융 전문가/기관의 실시간 시장 해석 (뉴스 기사에 없는 것)
- Grok Web: 최신 뉴스 헤드라인 + URL (기존 NewsItem 호환)

---

## 3. Perplexity Sonar 상세 설계

### 3.1 API 전환: Search → Chat Completions

| 항목 | Search API (현재) | Sonar Chat Completions (개선) |
|------|------------------|---------------------------------|
| 반환 형태 | `results: [{title, url, snippet}]` | `content: "요약 텍스트"` + `citations: [url]` + `search_results: [...]` |
| 도메인 필터 | allowlist 필수 | **denylist만** 또는 생략 |
| 정보 종합 | 없음 (링크 나열) | **LLM이 여러 소스를 읽고 종합** |
| 구조화 출력 | 없음 | `response_format: json_schema` |
| 인용 추적 | URL만 | `citations` 배열 + 본문 `[1]` 참조 번호 |

### 3.2 Sonar API 호출 구조

```python
response = client.chat.completions.create(
    model="sonar",
    messages=[
        {"role": "system", "content": sonar_system_prompt},
        {"role": "user", "content": sonar_topic_prompt},
    ],
    search_domain_filter=[           # denylist만
        "-markets.ft.com",
        "-data.coindesk.com",
        "-downloads.coindesk.com",
        "-sponsored.bloomberg.com",
        "-cn.wsj.com",
        "-jp.reuters.com",
    ],
    search_recency_filter="day",     # 주말이면 "week"
    response_format={
        "type": "json_schema",
        "json_schema": TOPIC_SUMMARY_SCHEMA,
    },
    temperature=0.1,
    max_tokens=1500,
)
```

### 3.3 토픽별 Sonar 프롬프트

**공통 시스템 프롬프트** (`sonar_system.j2`):
```
You are a financial market analyst writing a daily morning brief.
Your summaries must be factual, cite specific numbers, and reference sources.
Prefer Reuters, Bloomberg, WSJ, FT, and CNBC as primary sources.
Do not speculate. If data is unavailable, say so.
Output as JSON matching the provided schema.
```

**macro** (`sonar_topic_macro.j2`):
```
Summarize the latest US macro-economic developments
from the {{ time_range }}:

1. Federal Reserve policy signals and rate expectations
2. Treasury yields (2Y, 10Y) levels and drivers
3. Inflation or employment data if newly released
4. US Dollar Index (DXY) movement
5. VIX and risk sentiment

For each item include: specific numbers, percentage changes,
and the reporting source. Skip items with no significant development.
```

**us_equity** (`sonar_topic_us_equity.j2`):
```
Summarize the latest US equity market developments
from the {{ time_range }}:

1. S&P 500 and Nasdaq 100 closing levels and daily changes
2. Sector leadership/laggards and rotation drivers
3. Semiconductor index (SOX) performance
4. Notable individual stock moves (±3% or more) with reasons
5. Futures direction (ES, NQ) if available

Include specific numbers and reporting sources.
```

**ai_bigtech** (`sonar_topic_ai_bigtech.j2`):
```
Summarize the latest AI and Big Tech developments
from the {{ time_range }}:

1. Earnings, guidance, or major announcements from:
   NVDA, MSFT, AAPL, AMZN, GOOGL, META, TSM, AMD, AVGO
2. AI infrastructure spending, partnerships, or product launches
3. Regulatory actions affecting Big Tech
4. Stock price moves with percentage changes

Include specific numbers and reporting sources.
```

**bitcoin** (`sonar_topic_bitcoin.j2`):
```
Summarize the latest Bitcoin and crypto market developments
from the {{ time_range }}:

1. BTC spot price and 24h change
2. Spot Bitcoin ETF flows (IBIT, BITB, GBTC) — net inflows/outflows in USD
3. Crypto regulatory news (SEC, CFTC)
4. Bitcoin dominance and market sentiment
5. Notable correlations with traditional markets (S&P 500, gold, dollar)

Include specific numbers and reporting sources.
```

### 3.4 Sonar 응답 JSON 스키마

```json
{
  "name": "market_topic_summary",
  "strict": true,
  "schema": {
    "type": "object",
    "required": ["topic", "summary_text", "key_data_points", "market_implication"],
    "properties": {
      "topic": {
        "type": "string"
      },
      "summary_text": {
        "type": "string",
        "description": "2-4 paragraph narrative summary with specific numbers"
      },
      "key_data_points": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["label", "value", "change", "source"],
          "properties": {
            "label": {"type": "string"},
            "value": {"type": "string"},
            "change": {"type": "string"},
            "source": {"type": "string"}
          },
          "additionalProperties": false
        }
      },
      "market_implication": {
        "type": "string",
        "description": "One sentence: what this means for markets today"
      },
      "notable_stocks": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["ticker", "reason", "change_pct"],
          "properties": {
            "ticker": {"type": "string"},
            "reason": {"type": "string"},
            "change_pct": {"type": "string"}
          },
          "additionalProperties": false
        }
      }
    },
    "additionalProperties": false
  }
}
```

### 3.5 응답 활용 흐름

```
Sonar 응답
  ├─ choices[0].message.content  → JSON 파싱 → TopicSummary (요약 텍스트 + 구조화 데이터)
  ├─ citations                   → 출처 URL 리스트 (하단 참고 출처용)
  └─ search_results              → NewsItem 변환 (하위 호환 + 품질 평가용)
```

---

## 4. Grok 활용 재설계

### 4.1 현재 Grok 문제 상세

```
registry에 15개 엔티티 등록
  └─ x_verified=true:  AMD, Fidelity, BlackRock (3개)
  └─ x_verified=false: Fed, Treasury, SEC, NVIDIA, Microsoft, Meta,
                        Apple, TSMC, ASML, Bitwise, Grayscale, ARK (12개)
       → X 핸들 없음 → Grok 검색 대상에서 완전 제외
       → 결과: 거의 항상 0건
```

**근본 원인:** 기업 공식 계정은 마케팅/PR 위주라 시장에 중요한 포스트가 드물다.
금융 시장의 실시간 정보는 **뉴스 매체, 금융 기자, 애널리스트, 속보 계정**에 집중되어 있다.

### 4.2 Grok 새 역할: 2가지 도구 병렬 활용

Grok API는 **X Search**와 **Web Search** 두 도구를 모두 지원한다.
현재는 X Search만, 그것도 화이트리스트 핸들 방식으로만 사용 중이다.

#### 역할 A: X Search — 금융 전문 계정 + 키워드 기반 시장 반응 수집

**현재**: `allowed_x_handles=["AMD", "Fidelity", "BlackRock"]` → 기업 공식 3개만
**개선**: **금융 뉴스 매체 + 애널리스트 + 속보 계정** 위주로 전환, 키워드 병행

핵심 전환 포인트: 기업이 뭘 올렸는지가 아니라, **금융 전문가들이 시장을 어떻게 해석하는지**를 수집한다.

### 4.3 X Search 대상 계정 티어 설계

Grok X Search의 `allowed_x_handles`는 최대 10개로 제한된다.
따라서 **검색 그룹별로 최적의 10개 핸들을 선별**하고, 키워드로 범위를 보충한다.

#### Tier 1: 실시간 속보 + 뉴스 매체 (매일 수십~수백 건, 가장 빠름)

| 핸들 | 계정명 | 포스팅 빈도 | 가치 |
|------|--------|-----------|------|
| `@DeItaone` | Walter Bloomberg | 하루 수백 건 | **무료 Bloomberg 터미널 대용.** 트레이더 필수. 헤드라인 실시간 중계 |
| `@FirstSquawk` | First Squawk | 하루 수백 건 | 실시간 시장 속보 집계 |
| `@markets` | Bloomberg Markets | 하루 수십 건 | Bloomberg 시장 전용 계정 |
| `@WSJmarkets` | WSJ Markets | 하루 수십 건 | WSJ 시장 전용 속보 |
| `@ReutersBiz` | Reuters Business | 하루 수십 건 | Reuters 비즈니스 전용 |
| `@CNBC` | CNBC | 하루 수십 건 | 실시간 시장 뉴스 |
| `@FT` | Financial Times | 하루 다수 | 심층 분석 |
| `@MarketWatch` | MarketWatch | 하루 다수 | 시장 데이터/투자 뉴스 |

#### Tier 2: 매크로/Fed 전문가 (매일, 시장 방향성 해석)

| 핸들 | 이름 | 소속 | 가치 |
|------|------|------|------|
| `@NickTimiraos` | Nick Timiraos | WSJ Fed 수석 담당 | **"Fed 대변인"으로 불림.** Fed 정책 방향 사실상 가장 빠른 해석 |
| `@lisaabramowicz1` | Lisa Abramowicz | Bloomberg TV 앵커 | 채권/매크로 시장 실시간 해석 |
| `@elerianm` | Mohamed El-Erian | Allianz 수석 고문 | 매크로 전략, 시장 영향력 매우 높음 |
| `@LizAnnSonders` | Liz Ann Sonders | Schwab 수석 전략가 | 데이터 기반 시장 분석, 차트 공유 |
| `@federalreserve` | Federal Reserve | 공식 | FOMC 결정, 정책 발표 |
| `@USTreasury` | U.S. Treasury | 공식 | 재정 정책, 국채 발행 |
| `@SECGov` | SEC | 공식 | 규제 공고, 집행 조치 (크립토 ETF 승인 등) |

#### Tier 3: 빅테크/반도체 전문가

| 핸들 | 이름 | 소속 | 가치 |
|------|------|------|------|
| `@DivesTech` | Dan Ives | Wedbush 테크 리서치 헤드 | **빅테크 주가 영향력 최고.** 목표가 변경이 시장 움직임 |
| `@nvidia` | NVIDIA | 공식 | AI/GPU 제품 발표, 파트너십 |
| `@Microsoft` | Microsoft | 공식 | AI 투자, 클라우드 발표 |
| `@Meta` | Meta | 공식 | AI 모델, 인프라 투자 |
| `@AMD` | AMD | 공식 | CPU/GPU 제품 발표 |
| `@ASMLcompany` | ASML | 공식 | 반도체 장비 수주, 가이던스 |

#### Tier 4: 비트코인/크립토 전문가

| 핸들 | 이름 | 소속 | 가치 |
|------|------|------|------|
| `@EricBalchunas` | Eric Balchunas | Bloomberg Intelligence | **BTC ETF 분석 최고 권위자.** ETF 자금 흐름 실시간 공유 |
| `@NateGeraci` | Nate Geraci | ETF Store 대표 | 크립토 ETF 시장 예측, 매일 포스팅 |
| `@saylor` | Michael Saylor | MicroStrategy 회장 | BTC 기관 투자 대표 주자, 매수 공시 |
| `@CoinDesk` | CoinDesk | 크립토 뉴스 매체 | 크립토 속보, 매일 수십 건 |
| `@Grayscale` | Grayscale | GBTC 운용사 | ETF 자금 흐름, 운용 공지 |
| `@ARKInvest` | ARK Invest | ARKB 운용사 | 혁신 투자/BTC ETF |
| `@BitwiseInvest` | Bitwise | BITB 운용사 | 크립토 인덱스 ETF |

### 4.4 X Search 그룹별 호출 설계

Grok `x_search` 도구의 `allowed_x_handles`는 최대 10개이므로,
**토픽별로 가장 관련성 높은 10개 핸들을 선별**하여 그룹을 구성한다.

#### 그룹 1: `macro_and_equity` (매크로 + 주식 시장 반응)

```python
x_search(
    allowed_x_handles=[
        "DeItaone",          # 실시간 속보
        "FirstSquawk",       # 실시간 속보
        "markets",           # Bloomberg Markets
        "WSJmarkets",        # WSJ Markets
        "NickTimiraos",      # Fed 전문
        "lisaabramowicz1",   # 매크로/채권
        "elerianm",          # 매크로 전략
        "LizAnnSonders",     # 시장 전략
        "CNBC",              # 시장 뉴스
        "DivesTech",         # 빅테크 영향
    ],
    from_date=...,
    to_date=...,
)
```

**프롬프트:**
```
Search X for the most significant market-moving posts from the last 24 hours.
Focus on:
1. Fed policy signals, interest rate expectations, Treasury yield moves
2. S&P 500, Nasdaq market reaction and trader sentiment
3. Breaking economic data (CPI, PCE, jobs, GDP)
4. Notable analyst calls or market-moving commentary

For each post, extract:
- headline: one-line summary of the key information
- summary: the core market insight in 1-2 sentences
- why_it_matters: market implication for US equity/bond investors
- sentiment: bullish / bearish / neutral
- source_handle: @handle of the poster
- posted_at: ISO8601 timestamp

Return the top 6 most impactful posts. Prioritize posts with high engagement
and from accounts known for breaking market news.
Skip routine marketing, greetings, and non-market-related posts.
If a post is a repost, use the original source.
```

#### 그룹 2: `crypto_and_etf` (비트코인 + 크립토 ETF)

```python
x_search(
    allowed_x_handles=[
        "DeItaone",          # 실시간 속보
        "EricBalchunas",     # BTC ETF 분석
        "NateGeraci",        # 크립토 ETF
        "saylor",            # BTC 기관 투자
        "CoinDesk",          # 크립토 뉴스
        "Grayscale",         # GBTC 운용사
        "ARKInvest",         # ARKB 운용사
        "BitwiseInvest",     # BITB 운용사
        "SECGov",            # 규제 공고
        "markets",           # Bloomberg Markets
    ],
    from_date=...,
    to_date=...,
)
```

**프롬프트:**
```
Search X for the most significant Bitcoin and crypto market posts
from the last 24 hours. Focus on:
1. Bitcoin ETF flow data (IBIT, BITB, GBTC inflows/outflows)
2. Crypto regulatory news (SEC, CFTC decisions)
3. BTC price action and market sentiment
4. Institutional Bitcoin adoption signals
5. Notable analyst commentary on crypto markets

Return the top 4 most impactful posts.
Prioritize posts with specific data points (flow numbers, price levels).
Skip promotional content and price predictions without data backing.
```

### 4.5 키워드 기반 오픈 검색 (핸들 제한 없음)

`allowed_x_handles`를 지정하지 않으면 Grok이 X 전체를 키워드로 검색한다.
이 모드는 **특정 이벤트에 대한 광범위한 시장 반응**을 수집할 때 사용한다.

```python
# 핸들 제한 없는 키워드 검색
x_search(
    from_date=...,
    to_date=...,
    # allowed_x_handles 생략 → 전체 X 검색
)
```

**프롬프트:**
```
Search X for the most discussed financial market topics in the last 24 hours.
Look for posts about: {dynamic_keywords}

{dynamic_keywords}는 market_packet에서 자동 생성:
- 전일 대비 ±2% 이상 움직인 종목명
- VIX가 25 이상이면 "VIX spike volatility"
- FOMC 회의 주간이면 "FOMC rate decision"
- 실적 발표 시즌이면 해당 종목 "earnings"

Return posts from verified financial accounts, analysts, or major news outlets.
Exclude spam, bot accounts, and promotional content.
```

**이 모드의 장점:**
- Tier 1-4에 포함되지 않은 **새로운 영향력 있는 계정**의 포스트도 발견
- 예상치 못한 이벤트(지정학, 자연재해, CEO 사임 등)에 대한 반응 포착
- 10개 핸들 제한 우회

### 4.6 X Search 출력 스키마

```json
{
  "signals": [
    {
      "headline": "짧은 요약 제목",
      "summary": "포스트 핵심 내용 1-2문장",
      "why_it_matters": "시장 의미 1문장",
      "sentiment": "bullish | bearish | neutral",
      "source_handle": "@handle",
      "source_type": "news_outlet | analyst | official | trader | other",
      "posted_at": "ISO8601",
      "engagement_signal": "high | medium | low",
      "topic": "macro | us_equity | ai_bigtech | bitcoin",
      "citations": ["url"]
    }
  ],
  "overall_sentiment": {
    "macro": "bullish | bearish | neutral | mixed",
    "equity": "bullish | bearish | neutral | mixed",
    "crypto": "bullish | bearish | neutral | mixed"
  }
}
```

#### 역할 B: Web Search — 실시간 뉴스 기사 수집 (신규)

Grok API의 `web_search` 도구는 현재 **완전히 미사용** 상태다.
이것을 활용하면 Perplexity와 **독립적인 뉴스 소스**로 기능한다.

```python
chat = client.chat.create(
    model="grok-4-1-fast-non-reasoning",  # 저가 고속 모델
    tools=[
        web_search(
            excluded_domains=["markets.ft.com", "data.coindesk.com"],
        )
    ],
    tool_choice="required",
    response_format="json_object",
)
```

**Web Search 프롬프트:**
```
Search the web for the most important financial news articles
from the last 24 hours covering:
1. US macro economy (Fed, rates, inflation, employment)
2. US equity markets (S&P 500, Nasdaq, sector moves)
3. AI and Big Tech (NVDA, MSFT, AAPL, AMZN, GOOGL, META)
4. Bitcoin and crypto (ETF flows, regulation, price)

Return the top 5-8 most market-moving articles as JSON.
For each: title, url, source, published_at, topic, one-sentence summary.
Prefer Reuters, Bloomberg, WSJ, FT, CNBC.
Exclude data pages, stock quote pages, and non-English articles.
```

**출력 스키마:**
```json
{
  "articles": [
    {
      "title": "기사 제목",
      "url": "https://...",
      "source": "Reuters",
      "published_at": "ISO8601",
      "topic": "macro | us_equity | ai_bigtech | bitcoin",
      "summary": "핵심 내용 1문장"
    }
  ]
}
```

### 4.7 Grok 모델 선택과 비용

| 모델 | 용도 | 가격 (input/output per 1M) | 비고 |
|------|------|---------------------------|------|
| `grok-4.20-beta-latest-non-reasoning` | 현재 사용 중 | $2.00 / $6.00 | 비쌈 |
| **`grok-4-1-fast-non-reasoning`** | **권장** | **$0.20 / $0.50** | 10배 저렴, 충분한 성능 |

**비용 예측:**

| 역할 | 호출 수 | 모델 | 예상 비용 |
|------|--------|------|----------|
| X Search: macro_and_equity | 1회 | grok-4-1-fast | ~$0.001 + $0.005 (x_search) |
| X Search: crypto_and_etf | 1회 | grok-4-1-fast | ~$0.001 + $0.005 (x_search) |
| Web Search | 1회 | grok-4-1-fast | ~$0.001 + $0.005 (web_search) |
| **Grok 소계** | **3회** | | **~$0.018** |

### 4.8 X Search 결과의 브리핑 활용

X 시그널은 뉴스 기사와 다른 **독특한 가치**를 제공한다:

```
[뉴스 기사]  "PCE 인플레이션이 전월 대비 0.4% 상승했다" (사실 보도)
[X 시그널]   "@NickTimiraos: 이 PCE 수치는 3월 FOMC에서 금리 동결을
             사실상 확정짓는다. 6월 인하 기대도 후퇴할 것" (해석/전망)
[X 시그널]   "@DeItaone: *FED FUNDS FUTURES NOW PRICING ONLY TWO CUTS
             IN 2026, DOWN FROM THREE" (실시간 시장 반응 데이터)
```

**브리핑 반영 방식:**
- LAYER 1 `오늘 체크할 포인트`: X 시그널의 핵심 해석 반영
- LAYER 2 `시장 의미`, `한국 투자자 관점`: X 전문가 해석을 "시장에서는 ~로 해석했습니다" 형태로 인용
- LAYER 2 `왜 중요한지`: 여러 X 시그널의 공통 센티먼트 종합
- `overall_sentiment`로 LAYER 1 판단(매수 관심/관망/리스크 주의) 보조 근거

### 4.9 X 핸들 레지스트리 확장

`official_signal_registry.json`을 확장하여 금융 전문 계정을 추가한다.
새 카테고리 체계:

```json
{
  "version": 2,
  "entities": [
    // --- 기존: 기업 공식 (유지) ---
    { "category": "ai_bigtech_primary", "x_handle": "nvidia", ... },
    { "category": "btc_etf_primary", "x_handle": "Grayscale", ... },

    // --- 신규: 금융 속보 매체 ---
    { "category": "market_news_wire",
      "entity_id": "walter_bloomberg",
      "entity_name": "Walter Bloomberg",
      "x_handle": "DeItaone",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 1,
      "notes": "실시간 헤드라인 중계. 트레이더 필수 계정" },
    { "category": "market_news_wire",
      "entity_id": "first_squawk",
      "x_handle": "FirstSquawk",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 1 },
    { "category": "market_news_wire",
      "entity_id": "bloomberg_markets",
      "x_handle": "markets",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 2 },
    { "category": "market_news_wire",
      "entity_id": "wsj_markets",
      "x_handle": "WSJmarkets",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 2 },

    // --- 신규: 매크로/Fed 전문가 ---
    { "category": "macro_analyst",
      "entity_id": "nick_timiraos",
      "entity_name": "Nick Timiraos",
      "x_handle": "NickTimiraos",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 1,
      "notes": "WSJ Fed 수석 담당. 'Fed 대변인'으로 불림" },
    { "category": "macro_analyst",
      "entity_id": "lisa_abramowicz",
      "x_handle": "lisaabramowicz1",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 2 },
    { "category": "macro_analyst",
      "entity_id": "mohamed_el_erian",
      "x_handle": "elerianm",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 2 },

    // --- 신규: 테크/반도체 전문가 ---
    { "category": "tech_analyst",
      "entity_id": "dan_ives",
      "entity_name": "Dan Ives",
      "x_handle": "DivesTech",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 2,
      "notes": "Wedbush 테크 리서치 헤드. 목표가 변경이 시장 움직임" },

    // --- 신규: 크립토 ETF 전문가 ---
    { "category": "crypto_analyst",
      "entity_id": "eric_balchunas",
      "entity_name": "Eric Balchunas",
      "x_handle": "EricBalchunas",
      "x_search_group": "crypto_and_etf",
      "x_search_priority": 1,
      "notes": "Bloomberg Intelligence ETF 애널리스트. BTC ETF 분석 최고 권위자" },
    { "category": "crypto_analyst",
      "entity_id": "nate_geraci",
      "x_handle": "NateGeraci",
      "x_search_group": "crypto_and_etf",
      "x_search_priority": 2 },
    { "category": "crypto_analyst",
      "entity_id": "michael_saylor",
      "x_handle": "saylor",
      "x_search_group": "crypto_and_etf",
      "x_search_priority": 2,
      "notes": "MicroStrategy 회장. BTC 기관 매수 공시 채널" },

    // --- 신규: 규제 기관 (공식 X 핸들 등록) ---
    { "category": "macro_regulator",
      "entity_id": "federal_reserve",
      "x_handle": "federalreserve",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 3 },
    { "category": "macro_regulator",
      "entity_id": "us_treasury",
      "x_handle": "USTreasury",
      "x_search_group": "macro_and_equity",
      "x_search_priority": 3 },
    { "category": "macro_regulator",
      "entity_id": "sec",
      "x_handle": "SECGov",
      "x_search_group": "crypto_and_etf",
      "x_search_priority": 3 }
  ]
}
```

> 참고: `x_search_priority` 1 = 반드시 포함, 2 = 우선 포함, 3 = 공간 있으면 포함

---

## 5. 통합 데이터 흐름

### 5.1 새로운 파이프라인 전체 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│ build_news_packet()                                                 │
│                                                                     │
│  ┌─── 병렬 실행 ────────────────────────────────────────────────┐   │
│  │                                                               │   │
│  │  [A] Perplexity Sonar (4 토픽)                               │   │
│  │    → macro_summary, us_equity_summary,                        │   │
│  │      ai_bigtech_summary, bitcoin_summary                      │   │
│  │    → citations (출처 URL)                                      │   │
│  │    → search_results → NewsItem                                │   │
│  │                                                               │   │
│  │  [B] Grok X Search (키워드 기반, 2그룹)                       │   │
│  │    → 시장 반응 포스트 (sentiment, engagement)                  │   │
│  │    → X 시그널 NewsItem                                        │   │
│  │                                                               │   │
│  │  [C] Grok Web Search (1회)                                    │   │
│  │    → 최신 뉴스 기사 리스트                                     │   │
│  │    → 뉴스 NewsItem                                            │   │
│  │                                                               │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  [병합] 3개 소스 결과를 통합                                        │
│    → TopicSummary (Sonar)                                           │
│    → NewsItem 리스트 (Sonar search_results + Grok Web + Grok X)     │
│    → X Signals (Grok X Search → 시장 반응 컨텍스트)                 │
│    → citations 통합                                                 │
│                                                                     │
│  [폴백] 3개 모두 실패 시 → Legacy RSS + OpenAI 백필                 │
│                                                                     │
│  [최종] packet에 패키징                                              │
└─────────────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────────────┐
│ generate_briefing()                                                 │
│                                                                     │
│  packet 구조:                                                       │
│  {                                                                  │
│    "macro": [...],                    ← 기존 시장 지표 (yfinance 등)│
│    "us_indices": [...],                                             │
│    "tech_stocks": [...],                                            │
│    "bitcoin": {...},                                                │
│    "news": [...],                     ← NewsItem (하위 호환)        │
│    "topic_summaries": {               ← [신규] Sonar 시장 요약      │
│      "macro": { summary_text, key_data_points, ... },               │
│      "us_equity": { ... },                                          │
│      "ai_bigtech": { ... },                                         │
│      "bitcoin": { ... }                                             │
│    },                                                               │
│    "x_market_signals": [              ← [신규] Grok X 시장 반응     │
│      { headline, sentiment, source_handle, ... }                    │
│    ],                                                               │
│    "topic_citations": [...]           ← [신규] 통합 인용 URL        │
│  }                                                                  │
│                                                                     │
│  OpenAI 브리핑 프롬프트:                                             │
│  1. topic_summaries = 핵심 컨텍스트 (수치, 인과관계)                 │
│  2. x_market_signals = 시장 반응 컬러 (sentiment, 실시간 해석)       │
│  3. news = 개별 기사 참고 (LAYER 2 뉴스 항목)                       │
│  4. citations = 하단 출처                                            │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 OpenAI 브리핑에서 각 소스 활용 방식

| 소스 | 브리핑 LAYER | 활용 방식 |
|------|-------------|----------|
| **Sonar topic_summaries** | LAYER 1 (한줄 판단), LAYER 3 (종목) | 수치, 등락률, 거시 해석의 **핵심 근거** |
| **Grok X Signals** | LAYER 1 (체크포인트), LAYER 2 (뉴스) | "시장에서는 ~로 해석" 문장의 근거, 실시간 센티먼트 |
| **Grok Web + Sonar search_results** | LAYER 2 (뉴스 헤드라인) | 뉴스 항목, 한국어 번역 대상 |
| **기존 market_packet** | LAYER 1 (핵심 수치), LAYER 3 (거시 지표) | 원/달러, 나스닥 선물, 공포탐욕지수 등 |

### 5.3 브리핑 프롬프트 변경

**`brief_input.j2` 확장:**

```jinja2
<market_data_json>
{{ packet_json }}
</market_data_json>

<news_focus_json>
{{ news_focus_json }}
</news_focus_json>

{% if topic_summaries_json %}
<topic_summaries>
{{ topic_summaries_json }}
</topic_summaries>

topic_summaries 활용 규칙:
- Perplexity가 웹을 검색해 작성한 토픽별 시장 요약이다.
- 이 요약의 수치와 해석을 우선 근거로 사용한다.
- news_focus_json과 충돌하면 topic_summaries를 따른다.
{% endif %}

{% if x_market_signals_json %}
<x_market_signals>
{{ x_market_signals_json }}
</x_market_signals>

x_market_signals 활용 규칙:
- X(구 Twitter)에서 수집한 금융 전문가·기관의 실시간 시장 반응이다.
- "시장에서는 ~로 해석했습니다" 문장의 근거로 활용한다.
- sentiment 필드로 시장 분위기를 판단하되, 단정적 표현은 금지한다.
- engagement_signal이 high인 포스트를 우선 참고한다.
{% endif %}
```

---

## 6. 구현 단계

### Phase 1: Perplexity Sonar 전환

**대상 파일:**

| 파일 | 작업 |
|------|------|
| `perplexity_search.py` | `_sonar_chat_once()`, `_parse_sonar_response()` 신규. 기존 Search API 코드는 폴백으로 보존 |
| `prompts/sonar_system.j2` | 신규 |
| `prompts/sonar_topic_*.j2` (4개) | 신규 |
| `config.py` | `PERPLEXITY_USE_SONAR_SUMMARY`, `PERPLEXITY_SONAR_MODEL`, `PERPLEXITY_SONAR_MAX_TOKENS` 추가 |

### Phase 2: Grok X Search 키워드 전환

**대상 파일:**

| 파일 | 작업 |
|------|------|
| `grok_official_signals.py` | 키워드 기반 검색 그룹 추가. `allowed_x_handles` 없는 호출 경로 |
| `official_signal_registry.json` | 미검증 엔티티 X 핸들 추가. 키워드 검색 그룹 정의 |
| `prompts/grok_x_search_*.j2` (2-4개) | 신규: 토픽별 X 검색 프롬프트 |
| `config.py` | `GROK_MODEL` 기본값을 `grok-4-1-fast-non-reasoning`으로 변경 |

### Phase 3: Grok Web Search 추가

**대상 파일:**

| 파일 | 작업 |
|------|------|
| `grok_official_signals.py` 또는 `grok_web_search.py` (신규) | `web_search` 도구 호출 함수 |
| `prompts/grok_web_search.j2` | 신규: 웹 뉴스 수집 프롬프트 |
| `config.py` | `GROK_WEB_SEARCH_ENABLED` 환경변수 |

### Phase 4: 수집 오케스트레이션 통합

**대상 파일:**

| 파일 | 작업 |
|------|------|
| `news.py` | Sonar + Grok X + Grok Web 병합 로직. `topic_summaries`, `x_market_signals` 패키징 |
| `news_packet.py` | Grok Web → NewsItem 변환. X Signal → dict 변환 |
| `data_quality.py` | `topic_summaries` 존재 여부 반영. 품질 평가 기준 완화 |
| `pipeline.py` | `topic_summaries`, `x_market_signals`를 packet에 추가 |

### Phase 5: 브리핑 프롬프트 업데이트

**대상 파일:**

| 파일 | 작업 |
|------|------|
| `prompts/brief_input.j2` | `topic_summaries`, `x_market_signals` 블록 추가 |
| `prompts/brief_instructions.j2` | 3개 소스 활용 지시 추가 |
| `briefing.py` | 신규 데이터를 프롬프트에 전달하는 렌더링 로직 |

### Phase 6: Observability + 테스트

**대상 파일:**

| 파일 | 작업 |
|------|------|
| `observability.py` | Sonar/Grok 이벤트 기록 |
| `tests/test_perplexity_search.py` | Sonar 호출/파싱/폴백 테스트 |
| `tests/test_grok_signals.py` | 키워드 X Search + Web Search 테스트 |
| `tests/test_pipeline_observability.py` | 통합 E2E 테스트 |
| `README.md` | 신규 환경변수 문서화 |

---

## 7. 폴백 전략

```
[1차 — 병렬 실행]
├─ Perplexity Sonar (4 토픽)        → TopicSummary + citations + NewsItem
├─ Grok X Search (키워드, 2 그룹)   → X Signal + NewsItem
└─ Grok Web Search (1회)            → NewsItem

[2차 — 개별 실패 시]
├─ Sonar 실패한 토픽만 → 기존 Perplexity Search API
├─ Grok X Search 실패 → 기존 핸들 기반 X Search 폴백
└─ Grok Web Search 실패 → 무시 (다른 소스로 충분)

[3차 — 전체 실패 시]
├─ Legacy RSS + NewsAPI
└─ OpenAI web_search 백필

[최종 안전망]
└─ 기존 market_packet 데이터만으로 브리핑 생성 (degraded)
```

---

## 8. 비용 예측

| 프로바이더 | 현재 비용/실행 | 개선 비용/실행 | 변화 |
|-----------|--------------|--------------|------|
| Perplexity | ~$0.075 (15회 Search) | ~$0.032 (4회 Sonar) | -57% |
| Grok | ~$0.022 (2회 X Search, 비싼 모델) | ~$0.018 (3회, 저가 모델) | -18% |
| OpenAI | ~$0.007 (4회 brief+review) | ~$0.007 (동일) | 0% |
| **합계** | **~$0.104** | **~$0.057** | **-45%** |

> 참고: 결과 품질은 0건→4토픽 요약+X시그널+뉴스기사로 대폭 향상.

---

## 9. 마이그레이션 전략

### 9.1 환경변수

```bash
# Perplexity Sonar
PERPLEXITY_USE_SONAR_SUMMARY=true          # Sonar 모드 활성화
PERPLEXITY_SONAR_MODEL=sonar               # sonar / sonar-pro
PERPLEXITY_SONAR_MAX_TOKENS=1500           # 토픽당 최대 출력
PERPLEXITY_SONAR_TEMPERATURE=0.1           # 낮을수록 사실 중심

# Grok
GROK_MODEL=grok-4-1-fast-non-reasoning    # 저가 고속 모델로 전환
GROK_X_KEYWORD_SEARCH_ENABLED=true         # 키워드 기반 X Search
GROK_WEB_SEARCH_ENABLED=true               # Web Search 신규 활용
GROK_X_SEARCH_MAX_ITEMS=6                  # X Search 최대 결과
GROK_WEB_SEARCH_MAX_ITEMS=8                # Web Search 최대 결과
```

### 9.2 단계적 롤아웃

| 단계 | 내용 | 롤백 |
|------|------|------|
| **Step 1** | Sonar macro 토픽만 테스트 | `PERPLEXITY_USE_SONAR_SUMMARY=false` |
| **Step 2** | Sonar 4토픽 전체 + Grok 키워드 X Search | 각 환경변수로 개별 비활성화 |
| **Step 3** | Grok Web Search 추가 | `GROK_WEB_SEARCH_ENABLED=false` |
| **Step 4** | 1주일 운영 후 기존 Search API 폴백 코드 제거 여부 결정 | - |

### 9.3 하위 호환

- `packet["news"]`: 기존과 동일한 `list[dict]` 구조 유지
- `packet["topic_summaries"]`: 신규 필드 — `{% if %}` 조건부로 점진 도입
- `packet["x_market_signals"]`: 신규 필드 — 없어도 브리핑 생성 가능
- 모든 신규 기능은 환경변수로 개별 on/off 가능

---

## 10. 수정 대상 파일 요약

| 파일 | 변경 | 설명 |
|------|------|------|
| `src/morning_brief/data/sources/perplexity_search.py` | **대폭 수정** | Sonar 호출, 응답 파싱, 폴백 오케스트레이션 |
| `src/morning_brief/data/sources/grok_official_signals.py` | **대폭 수정** | 키워드 X Search, Web Search 추가 |
| `src/morning_brief/data/news.py` | 수정 | 3-provider 병합, topic_summaries/x_signals 패키징 |
| `src/morning_brief/data/news_packet.py` | 수정 | Grok Web → NewsItem, X Signal → dict 변환 |
| `src/morning_brief/data/data_quality.py` | 수정 | topic_summaries 기반 품질 평가 |
| `src/morning_brief/briefing.py` | 수정 | 신규 데이터를 프롬프트에 전달 |
| `src/morning_brief/pipeline.py` | 소폭 수정 | packet에 신규 필드 추가 |
| `src/morning_brief/config.py` | 수정 | Sonar + Grok 환경변수 추가 |
| `src/morning_brief/observability.py` | 수정 | Sonar/Grok 이벤트 기록 |
| `src/morning_brief/data/registry/official_signal_registry.json` | 수정 | X 핸들 추가, 키워드 그룹 정의 |
| `src/morning_brief/prompts/sonar_system.j2` | **신규** | Sonar 시스템 프롬프트 |
| `src/morning_brief/prompts/sonar_topic_macro.j2` | **신규** | macro 토픽 프롬프트 |
| `src/morning_brief/prompts/sonar_topic_us_equity.j2` | **신규** | us_equity 토픽 프롬프트 |
| `src/morning_brief/prompts/sonar_topic_ai_bigtech.j2` | **신규** | ai_bigtech 토픽 프롬프트 |
| `src/morning_brief/prompts/sonar_topic_bitcoin.j2` | **신규** | bitcoin 토픽 프롬프트 |
| `src/morning_brief/prompts/grok_x_market.j2` | **신규** | Grok 키워드 X Search 프롬프트 |
| `src/morning_brief/prompts/grok_web_search.j2` | **신규** | Grok Web Search 프롬프트 |
| `src/morning_brief/prompts/brief_input.j2` | 수정 | topic_summaries, x_market_signals 블록 |
| `src/morning_brief/prompts/brief_instructions.j2` | 수정 | 3개 소스 활용 지시 |
| `tests/test_perplexity_search.py` | 수정 | Sonar 테스트 추가 |
| `tests/test_grok_signals.py` | 수정 | 키워드 X + Web Search 테스트 |
| `tests/test_pipeline_observability.py` | 수정 | 통합 E2E 테스트 |
| `README.md` | 수정 | 신규 환경변수 문서화 |

---

## 11. 리스크와 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| Sonar 할루시네이션 수치 | 잘못된 브리핑 | `temperature=0.1` + market_packet 수치와 cross-check + OpenAI 검수 |
| Grok X 키워드 검색 노이즈 | 저품질 시그널 | `engagement_signal` 필터 + 프롬프트에서 "financial analysts, institutional accounts" 지정 |
| Grok Web Search 중복 | Sonar와 같은 기사 | URL 기반 중복 제거 (기존 `_dedup_and_rank` 재활용) |
| API 장애 동시 발생 | 전체 수집 실패 | 3-provider 독립 + Legacy RSS + OpenAI 백필 = 5중 폴백 |
| 비용 초과 | Sonar 토큰 과금 | max_tokens 1500, 저가 Grok 모델, 환경변수로 즉시 비활성화 |
| X 검색 rate limit | Grok 호출 차단 | circuit breaker 기존 코드 재활용 + Web Search 독립 실행 |
| Sonar 첫 json_schema 지연 | 10-30초 추가 | 타임아웃 35초, 이후 캐시 자동 적용 |

---

## 12. 기대 효과

| 지표 | 현재 | 개선 후 |
|------|------|---------|
| Perplexity 수집 기사 | **0건** | 4개 토픽 요약 + search_results |
| Grok X 시그널 | **0건** (핸들 3개) | 키워드 기반 시장 반응 4-6건 |
| Grok Web 뉴스 | **미사용** | 최신 뉴스 5-8건 |
| 총 뉴스 소스 | 1-5건 (대부분 백필) | **15-20건** (3개 독립 소스) |
| 브리핑 데이터 품질 | degraded / critical | **ok** 예상 |
| 검수(review) 통과율 | 낮음 (None 노출, 미완성) | 대폭 개선 예상 |
| 비용 | ~$0.104/실행 | **~$0.057/실행** (-45%) |
| LAYER 2 뉴스 품질 | 영어 원문, 출처 불명 | 한국어 번역 가능한 고품질 뉴스 |
| 시장 반응 컨텍스트 | 없음 | X 기반 실시간 센티먼트 반영 |
