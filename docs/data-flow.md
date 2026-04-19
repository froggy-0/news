# 데이터 수집·정제 흐름 (Data Flow)

브리핑 이메일이 발송되기 전까지 파이프라인이 수집·가공하는 모든 데이터를 정리한 문서입니다.
최종 `packet` dict가 OpenAI 프롬프트에 전달되어 브리핑을 생성하고, 이메일로 발송됩니다.

---

## 파이프라인 전체 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│  Phase 1: Market Data                                               │
│  build_market_packet()                                              │
│    ├─ 거시 지표 (FRED → yfinance fallback)                          │
│    ├─ 검증된 실제 지수 (dow30: KIS → yfinance fallback)              │
│    ├─ 미국 지수 ETF proxy (KIS → yfinance fallback)                  │
│    └─ 비트코인 스냅샷                                                │
│        ├─ BTC 현물 (CoinGecko → yfinance fallback)                   │
│        ├─ Fear & Greed Index (alternative.me)                       │
│        └─ BTC ETF 공식 보유량/순유입 (IBIT+BITB direct fetch)        │
├─────────────────────────────────────────────────────────────────────┤
│  Display-only Market Data                                           │
│  fetch_newsletter_display_data()                                    │
│    ├─ 한국 투자자 참고 지표 (usdkrw: KIS → yfinance, nq: yfinance)   │
│    ├─ 국내 대표지수 (kospi/kosdaq: KIS → yfinance fallback)         │
│    ├─ 빅테크 10종 (KIS → yfinance fallback)                         │
│    └─ BTC ETF 가격·거래량 (KIS → yfinance)                          │
├─────────────────────────────────────────────────────────────────────┤
│  시장 키워드 추출                                                    │
│  extract_market_keywords() → build_search_keywords()                │
│    VIX 급등, 금리 급변, 지수 급등락, 개별주 ±3%↑, BTC ±3%↑ 감지     │
│    → 토픽별(macro/ai_bigtech/bitcoin/us_equity) 검색 키워드 생성     │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 2: News Data                                                 │
│  build_news_packet()                                                │
│    ├─ Grok 공식 X 시그널 (allowlist 계정만)                          │
│    ├─ Perplexity Sonar 토픽별 요약 + citations → NewsItem 추출       │
│    ├─ Grok X 키워드 검색 (시장 반응 시그널)                          │
│    ├─ Grok Web Search (선택)                                        │
│    ├─ Perplexity Search API (Sonar 미사용 시)                        │
│    ├─ Gemini grounding fallback (Perplexity 0건 시)                  │
│    └─ Legacy fallback: RSS + NewsAPI (품질 미달 시)                  │
│    → 병합 → 중복 제거 → 랭킹 → 최종 뉴스 리스트                     │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 3: Sonar 맥락 보강                                           │
│  fetch_sonar_context()                                              │
│    뉴스 상위 12건을 Sonar에 보내 교차 분석 + 핵심 내러티브 생성       │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 4: 데이터 품질 평가                                          │
│  assess_data_quality()                                              │
│    → ok / degraded / critical 판정                                  │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 5: OpenAI web_search 백필 (선택)                             │
│  backfill_news_with_web_search()                                    │
│    품질 미달 시 OpenAI web_search로 추가 뉴스 보강                   │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 6: 브리핑 생성 + 검수                                        │
│  generate_briefing() → OpenAI API                                   │
│    packet 전체를 Jinja 프롬프트에 주입 → 한국어 해석형 리포트 생성    │
│    → validate_and_rewrite_briefing()                                │
│    → 초안 검수 → 문제 시 최대 1회 자동 재작성                        │
│    → 구조 검증 → 실패 시 안전 기본 브리핑으로 대체                   │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 7: 이메일 발송                                               │
│  SesSender.send()                                                   │
│    Markdown → HTML 렌더링 + plain text fallback → AWS SES 발송       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Market Packet 상세

`build_market_packet()`이 반환하는 dict 구조입니다.

### 1.1 거시 지표 (`packet["macro"]`)

FRED에서 가져오는 지표와 yfinance fallback 전용 지표가 합산됩니다.

| canonical_key | 지표 | FRED series | yfinance fallback | 단위 |
|---|---|---|---|---|
| `us10y` | 미국 10년 국채 금리 | `DGS10` | `^TNX` (×0.1 스케일) | % |
| `us2y` | 미국 2년 국채 금리 | `DGS2` | — | % |
| `dxy` | 달러 인덱스 (연준 무역가중) | `DTWEXAFEGS` | `DX=F` | 포인트 |
| `vix` | 변동성 지수 | `VIXCLS` | `^VIX` | 포인트 |
| `hy_spread` | 하이일드 스프레드 | `BAMLH0A0HYM2` | — | % |

FRED 성공 시 이미 가져온 키는 건너뛰고, 나머지만 yfinance로 보충합니다.

각 항목의 데이터 필드 (`MarketPoint.__dict__`):
```python
{
    "label": str,               # 표시 이름
    "ticker": str,              # 원본 티커
    "price": float | None,      # 현재 값
    "change_pct": float | None, # 비금리 자산 전일 대비 변동률 (%)
    "change_bps": float | None, # 금리 자산 전일 대비 변화폭 (bp)
    "canonical_key": str,       # 정규화 키
    "is_previous_value": bool,  # 캐시 대체 여부
    "validation_status": str,   # ok / missing / anomaly / previous_value
    "raw_value": float | None,  # 수집 원본 값
    "resolved_value": float | None,  # 검증 후 최종 값
    "resolution_reason": str,   # 검증/대체 사유
}
```

### 1.2 검증된 실제 지수 (`packet["validated_indices"]`)

| canonical_key | 지표 | 소스 | 비고 |
|---|---|---|---|
| `dow30` | 다우30 | KIS `inquire-daily-chartprice` (`.DJI`) → yfinance `^DJI` | phase 1 direct index |

### 1.3 미국 지수 ETF proxy (`packet["us_indices"]`)

| canonical_key | 지표 | 소스 |
|---|---|---|
| `spy` | S&P 500 ETF | KIS `price` → yfinance `SPY` |
| `qqq` | Nasdaq 100 ETF | KIS `price` → yfinance `QQQ` |
| `soxx` | 반도체 ETF | KIS `price` → yfinance `SOXX` |

### 1.4 Display-only 섹션 (`render_packet`)

`build_market_packet()`은 `korea_watch`, `tech_stocks`, `bitcoin.etf_points`를 비워 둔 채 반환하고, 실제 뉴스레터/공개 렌더링 직전에 `fetch_newsletter_display_data()`가 아래 섹션을 채웁니다.

#### `render_packet["korea_watch"]`

| canonical_key | 지표 | 소스 | 비고 |
|---|---|---|---|
| `usdkrw` | 원/달러 환율 | KIS `inquire-daily-chartprice` (`FX@KRW`) → yfinance `KRW=X` | |
| `nq_futures` | 나스닥 선물 | yfinance `NQ=F` | |

#### `render_packet["korea_indices"]`

| canonical_key | 지표 | 소스 | 비고 |
|---|---|---|
| `kospi` | 코스피 | KIS `inquire-index-price` (`0001`) → yfinance `^KS11` | phase 1 domestic index |
| `kosdaq` | 코스닥 | KIS `inquire-index-price` (`1001`) → yfinance `^KQ11` | phase 1 domestic index |

#### `render_packet["tech_stocks"]`

`NVDA`, `MSFT`, `AAPL`, `AMZN`, `GOOGL`, `META`, `AMD`, `TSM`, `ASML`, `AVGO`

- 소스: KIS → yfinance fallback
- 변동률 절대값 기준 내림차순 정렬 (가장 많이 움직인 종목이 먼저)

### 1.5 비트코인 (`packet["bitcoin"]`)

```python
{
    "spot": MarketPoint,          # BTC 현물 (CoinGecko → yfinance fallback)
    "etf_points": [MarketPoint],  # display-only path에서 채워짐
    "fear_greed_value": int | None,  # 0~100
    "fear_greed_label": str | None,  # 극단적 공포 ~ 극단적 탐욕
    # 공식 ETF 보유량
    "official_etf_snapshots": [BitcoinEtfIssuerSnapshot],
    "official_etf_total_btc": float | None,
    "official_etf_total_aum_usd": float | None,
}
```

`BitcoinEtfIssuerSnapshot` 필드:
```python
{
    "ticker": str,              # IBIT / BITB / GBTC / BTC
    "issuer": str,
    "source_url": str,          # 공식 issuer 페이지 URL
    "as_of_date": date,         # 기준일
    "shares_outstanding": int,
    "daily_volume": int,
    "aum_usd": float,
    "total_btc": float,
    "bitcoin_per_share": float,
    "source_type": str,         # official_json / official_csv / official_html
    "quality_status": str,      # ok / degraded / critical
}
```

### 1.6 데이터 검증

모든 `MarketPoint`는 수집 후 두 단계 정제를 거칩니다:

1. **캐시 대체**: 현재 값이 `None`이면 전일 캐시에서 복원 (`is_previous_value=True`, `validation_status="previous_value"`)
2. **이상값 검증**: canonical_key별 기대 범위를 벗어나면 `anomaly`(가격 제거), 데이터 자체가 없으면 `missing`

검증 결과는 `packet["data_footer_notes"]`에 문자열 리스트로 기록됩니다.

금리(`us10y`, `us2y`)는 사용자 노출 시 `% 변화율`이 아니라 `bp` 기준으로 해석합니다.
BTC ETF는 총 BTC 보유량과 총 AUM만 사용자-facing 보조지표로 유지하고, `critical` 또는 reference-only 스냅샷은 합산에서 제외합니다.

---

## 2. 시장 키워드 자동 추출

`extract_market_keywords()`가 수집된 시장 수치에서 이상 움직임을 감지해 검색 키워드를 생성합니다.

| 조건 | 생성 키워드 예시 |
|---|---|
| VIX > 25 | `volatility spike market fear March 17 2026` |
| US10Y 변동률 > ±1% | `treasury yields surge March 17 2026` |
| SPY 변동률 > ±1.5% | `S&P 500 selloff March 17 2026` |
| 개별 기술주 변동률 > ±3% | `NVDA surge March 17 2026` |
| BTC 변동률 > ±3% | `bitcoin drop March 17 2026` |

이 키워드는 `build_search_keywords()`에서 토픽별로 분류되어 Perplexity/Grok 뉴스 검색 쿼리에 주입됩니다.

---

## 3. News Packet 상세

### 3.1 수집 소스와 우선순위

| 순서 | 소스 | 역할 | 데이터 |
|---|---|---|---|
| 1 | **Grok 공식 X 시그널** | allowlist 공식 계정(Fed, SEC 등)의 최근 48h 포스트 | `NewsItem` (provider=`grok_official_x`) |
| 2 | **Perplexity Sonar 요약** | 토픽별(macro/ai_bigtech/bitcoin/us_equity) 구조화 요약 | `TopicSummary` + citations에서 `NewsItem` 추출 |
| 3 | **Grok X 키워드 검색** | 시장 반응 시그널 + 추가 검색 키워드 | `XSignal` + `NewsItem` + 키워드 |
| 4 | **Grok Web Search** | 웹 뉴스 보강 (선택) | `NewsItem` |
| 5 | **Perplexity Search API** | Sonar 미사용 시 직접 검색 | `NewsItem` |
| 6 | **Gemini grounding** | Perplexity 0건 시 Google Search 기반 fallback | `NewsItem` |
| 7 | **Legacy (RSS + NewsAPI)** | 품질 미달 시 보충 | `NewsItem` |

### 3.2 뉴스 정제 과정

```
수집 → source_handle 기반 dedup (공식 X ↔ 키워드 X 중복 제거)
     → _merge_rank() (소스별 병합 + 점수 기반 정렬)
     → _dedup_and_rank() (제목/URL 중복 제거 + 최종 랭킹)
     → 최종 news_packet (list[dict])
```

### 3.3 각 뉴스 항목의 필드

`news_items_to_packet()`이 `NewsItem`을 dict로 변환할 때 추가 메타 필드를 붙입니다.

```python
{
    "title": str,                   # 기사 제목
    "url": str,                     # 원문 URL
    "source": str,                  # 출처 도메인 또는 X 핸들
    "published_at": str | None,     # 발행 시각 (ISO)
    "domain": str,                  # URL에서 추출한 도메인
    "source_tier": int,             # 출처 등급 (1=최상위, 숫자 클수록 낮음)
    "preferred_source": bool,       # 신뢰 도메인 여부
    "age_hours": float | None,     # 발행 후 경과 시간
    "topic": str | None,           # macro / ai_bigtech / bitcoin / us_equity
    "provider": str | None,        # perplexity / grok_official_x / grok_x_keyword / rss / newsapi 등
    "summary": str | None,         # 요약
    "why_it_matters": str | None,  # 시장 영향 해석
    "citations": [str],            # 근거 URL 리스트
    "official_source": bool,       # 공식 X 시그널 여부
}
```

### 3.4 Perplexity Sonar 토픽 요약 (`packet["topic_summaries"]`)

토픽별로 Sonar가 생성한 구조화 요약입니다. 뉴스 리스트와 별도로 프롬프트에 주입됩니다.

```python
{
    "macro": {
        "topic": "macro",
        "summary_text": str,           # 토픽 전체 요약
        "key_data_points": [           # 핵심 수치
            {"metric": str, "value": str}
        ],
        "market_implication": str,     # 시장 함의
        "notable_stocks": [            # 관련 종목
            {"ticker": str, "reason": str}
        ],
        "citations": [str],           # 출처 URL
    },
    "ai_bigtech": { ... },
    "bitcoin": { ... },
    "us_equity": { ... },
}
```

### 3.5 X 시장 반응 시그널 (`packet["x_market_signals"]`)

Grok X 키워드 검색으로 수집한 실시간 시장 반응입니다.

```python
[
    {
        "headline": str,          # 시그널 제목
        "summary": str,           # 요약
        "why_it_matters": str,    # 시장 영향
        "sentiment": str,         # bullish / bearish / neutral
        "source_handle": str,     # X 계정 핸들
        "posted_at": str | None,  # 포스트 시각 (ISO)
        "topic": str,             # 토픽 분류
        "citations": [str],       # 관련 URL
    }
]
```

---

## 4. Sonar 맥락 보강 (`packet["sonar_context"]`)

뉴스 상위 12건을 Sonar에 보내 교차 분석한 결과입니다.

```python
{
    "analyses": [
        {
            "topic": str,               # 분석 주제
            "context": str,             # 기사의 심층 배경
            "cross_sector_link": str,   # 다른 섹터와의 연결점
        }
    ],
    "key_narrative": str,         # 오늘 시장의 핵심 내러티브 한 줄
}
```

---

## 5. 데이터 품질 평가 (`packet["data_quality"]`)

```python
{
    "status": "ok" | "degraded" | "critical",
    "zero_price_ratio": float,                  # 가격 누락 비율
    "warnings": [str],
    "news_count": int,
    "preferred_news_count": int,                # 신뢰 도메인 기사 수
    "tier_1_news_count": int,                   # Reuters/Bloomberg/WSJ/FT/CNBC/CoinDesk
    "unique_news_domains": int,
    "fresh_news_count": int,                    # 24h 이내 기사
    "topic_coverage_count": int,                # 커버된 토픽 수 (최대 4)
    "citation_backed_count": int,               # 근거 URL 있는 기사 수
    "explained_count": int,                     # why_it_matters 있는 기사 수
    "perplexity_item_count": int,
    "perplexity_citation_backed_count": int,
    "perplexity_explained_count": int,
    "official_signal_count": int,
}
```

판정 기준:
- `critical`: 뉴스 < 최소 기준 또는 가격 누락 ≥ 80%
- `degraded`: 경고 사항 존재 (도메인 다양성 부족, 신선도 낮음 등)
- `ok`: 모든 기준 충족

---

## 6. 최종 Packet 구조 요약

OpenAI 프롬프트에 전달되는 `packet` dict의 전체 키:

```python
packet = {
    # 시장 데이터
    "generated_at_utc": str,
    "macro": [MarketPoint],
    "korea_watch": [MarketPoint],
    "us_indices": [MarketPoint],
    "tech_stocks": [MarketPoint],
    "bitcoin": { ... },                    # 섹션 1.5 참조
    "data_footer_notes": [str],

    # 뉴스 데이터
    "news": [NewsItem as dict],            # 섹션 3.3 참조

    # 보강 데이터 (조건부)
    "topic_summaries": { ... },            # 섹션 3.4 (Sonar 요약 있을 때)
    "x_market_signals": [ ... ],           # 섹션 3.5 (X 시그널 있을 때)
    "sonar_context": { ... },              # 섹션 4 (Sonar 맥락 보강 성공 시)
    "web_search_references": [str],        # OpenAI web_search 백필 시

    # 품질 메타
    "data_quality": { ... },               # 섹션 5
}
```

---

## 7. 브리핑 생성 → 이메일 발송

1. `packet` 전체를 JSON으로 직렬화해 Jinja 프롬프트(`brief_instructions.j2` + `brief_input.j2`)에 주입
2. `topic_summaries`와 `sonar_context`가 있으면 프롬프트에 추가 맥락으로 포함
3. OpenAI API로 한국어 해석형 브리핑 생성
4. 검수(`brief_validator`) → 문제 시 최대 1회 재작성(`brief_rewrite`) — `generate_briefing()` 내부에서 수행
5. 구조 검증 → 실패 시 안전 기본 브리핑으로 대체
6. 최종 Markdown에 품질 알림 + 출처 참조 블록 + footer note 추가
7. Markdown → HTML 변환 (Jinja `email.html.j2` 템플릿) + plain text fallback
8. AWS SES (`ap-northeast-2`, sender `no-reply@sovereignbriefing.com`)로 발송

---

## 8. 활용 관점에서 본 데이터 특성

| 데이터 | 갱신 주기 | 특성 | 활용 가능성 |
|---|---|---|---|
| 거시 지표 6종 | 실시간~1일 | 정량, 변동률 포함 | 추세 분석, 알림 조건 |
| 미국 지수 3종 | 실시간 | 정량, ETF 기반 | 섹터 비교 |
| 빅테크 10종 | 실시간 | 변동률 정렬됨 | 모멘텀 스크리닝 |
| BTC 현물 + ETF 2종 | 실시간 | 가격 + 거래량 | 유동성 분석 |
| BTC ETF 공식 보유량 | 1일 | 구조화, issuer 검증 | 기관 자금 흐름 추적 |
| Fear & Greed | 1일 | 0~100 스케일 | 센티먼트 지표 |
| 환율/선물 | 실시간 | 한국 투자자 관점 | 환헤지 판단 |
| Sonar 토픽 요약 | 실행 시 | 구조화 텍스트 + 수치 | 토픽별 요약 재활용 |
| X 시장 시그널 | 실행 시 | 센티먼트 태깅됨 | 실시간 반응 분석 |
| Sonar 맥락 분석 | 실행 시 | 교차 분석 + 내러티브 | 스토리라인 생성 |
| 뉴스 기사 | 실행 시 | 출처·토픽·근거 URL 포함 | 딥다이브 링크 |
| 시장 키워드 | 실행 시 | 이상 움직임 기반 자동 생성 | 검색 쿼리, 알림 트리거 |

---

## 9. Sentiment Join 분석 파이프라인

브리핑 파이프라인과 독립된 분석용 배치입니다. 감성·심리 지표와 BTC 수익률 간의 통계적 관계를 검증하고, 실전 예측 성능(Alpha Validation)을 정량 평가합니다.

GitHub Actions `Build Sentiment Time Join Parquet` job 또는 `make sentiment-join`으로 실행합니다.

```
┌──────────────────────────────────────────────────────────────────┐
│  진입점: scripts/build_sentiment_join.py                         │
│  GitHub Actions: run-sentiment-join job (run-brief 성공 후 실행) │
├──────────────────────────────────────────────────────────────────┤
│  Phase 1: 데이터 수집                                             │
│    ├─ R2 감성 점수 (브리핑 파이프라인 산출물)                      │
│    ├─ Fear & Greed Index (api.alternative.me/fng/)               │
│    ├─ BTC 가격·거래량                                             │
│    │    Binance data-api.binance.vision (Spot klines)            │
│    │    → KIS → yfinance BTC-USD                                 │
│    ├─ USD/KRW 종가                                               │
│    │    KIS inquire-daily-chartprice → yfinance KRW=X           │
│    ├─ VIX (FRED API, optional — 키 미설정 시 전 행 NaN)          │
│    ├─ BTC 선물 지표 3종                                           │
│    │    funding_rate / open_interest_usd / btc_long_short_ratio  │
│    │    1차: Lambda(ap-northeast-2) → fapi.binance.com           │
│    │    2차: Bybit 공개 API (geo-restriction 없음)                │
│    │    3차: NaN (파이프라인 계속 진행)                            │
│    └─ BTC ETF flows (공식 발행사 페이지)                          │
│         gold history 미존재 시 latest snapshot fallback 가능       │
│         단, fallback은 historical coverage로 승격하지 않음         │
├──────────────────────────────────────────────────────────────────┤
│  Phase 2: 데이터 변환                                             │
│    ├─ 날짜 정규화 (UTC → YYYY-MM-DD)                              │
│    ├─ 달력 reindex (VIX, USD/KRW 주말 공백 보정)                  │
│    ├─ forward-fill (가격 공백일 보정, 최대 2~3일)                  │
│    └─ 수익률 계산 (btc_log_return, btc_return, usdkrw_*)          │
├──────────────────────────────────────────────────────────────────┤
│  Phase 3: Join + Lag 컬럼 생성                                    │
│    R2 sentiment 보유 날짜 기준 inner join                         │
│    → Lag-1 컬럼 생성 (funding_rate_lag1, oi_change_pct_lag1 등)  │
│    → 이상값 필터 (Z-score 기반, is_outlier 플래그)               │
├──────────────────────────────────────────────────────────────────┤
│  Phase 4: 통계 검정 (run_statistical_tests)                       │
│    ├─ ADF+KPSS 공동 정상성 검정 (9개 변수, 30행 이상)             │
│    └─ Granger 인과 검정                                           │
│         순방향 16쌍 + 역방향 5쌍 × 3 lag = 63 검정               │
│         Benjamini-Hochberg FDR 보정 일괄 적용                    │
│         AIC 기반 최적 lag 선택                                    │
├──────────────────────────────────────────────────────────────────┤
│  Phase 5: 하이브리드 지수 (compute_hybrid_indices)                │
│    ├─ full: 7개 feature + VIF gate(threshold=10) + PCA            │
│    │    news_sentiment, FNG, funding_rate, long_short_ratio,     │
│    │    etf_net_inflow, volume_change, VIX(optional)             │
│    └─ core: 4개 feature (큐레이션, VIF 미적용) + PCA              │
│         news_sentiment, FNG, funding_rate, volume_change         │
│    structured source coverage가 낮으면 ETF/OI/LSR feature는       │
│    Parquet에는 저장되지만 통계/PCA 입력에서는 gate-out            │
│    → 0~100 min-max score 변환                                    │
│    → fng_value_lag1 부호 앵커로 방향성 통일                       │
├──────────────────────────────────────────────────────────────────┤
│  Phase 6: Lag-1 Score 컬럼 생성                                   │
│    full_hybrid_index_score → full_hybrid_index_score_lag1        │
│    core_hybrid_index_score → core_hybrid_index_score_lag1        │
│    (look-ahead bias 방지)                                        │
├──────────────────────────────────────────────────────────────────┤
│  Phase 7: Alpha Validation (run_alpha_validation)                 │
│    ├─ Hit Rate: 5개 predictor 방향 적중률 + Confusion Matrix      │
│    ├─ Correlation: Pearson(정상성 기반 차분) + Spearman            │
│    │    predictor vs btc_log_return + predictor 간 다중공선성     │
│    ├─ Backtest: 신호 기반 매수/현금 전략 vs Buy & Hold            │
│    │    Alpha, Sharpe Ratio, Max Drawdown, 거래 비용 반영         │
│    └─ Walk-Forward: 120일 train / 30일 test rolling window       │
│         full + core 양쪽 out-of-sample 성능 평가                 │
├──────────────────────────────────────────────────────────────────┤
│  Phase 8: 스키마 검증 + 저장                                      │
│    ├─ MASTER_SCHEMA (pandera strict=True) 검증                    │
│    ├─ Parquet 저장 + 메타데이터 (sentiment_join_stats)            │
│    │    ADF, Granger, hit_rates, correlations, backtest,         │
│    │    walk_forward, hybrid_indices, structured_sources 포함     │
│    ├─ R2 업로드 (R2_PUBLIC_BUCKET 설정 시)                        │
│    └─ 로컬 파일 보관: SENTIMENT_JOIN_RETAIN_DAYS일 (기본 30)      │
└──────────────────────────────────────────────────────────────────┘
```

### 9.1 주요 환경변수

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `SENTIMENT_JOIN_LOOKBACK_DAYS` | `180` | 수집 기간 (1~730일). 360일 이상 권장 |
| `FUTURES_LAMBDA_ARN` | `""` | Lambda 프록시 ARN. 설정 시 Binance 직접 호출 건너뜀 |
| `SENTIMENT_JOIN_OUTPUT_DIR` | `data/sentiment_join` | 로컬 출력 경로 |
| `SENTIMENT_JOIN_RETAIN_DAYS` | `30` | 로컬 보관 기간 |
| `SENTIMENT_JOIN_R2_MAX_CONCURRENCY` | `10` | R2 업로드 동시성 |
| `SENTIMENT_JOIN_BINANCE_KEY` | `""` | Binance API key (Spot klines) |
| `KIS_APP_KEY` / `KIS_APP_SECRET` | `""` | KIS API 인증 (USD/KRW) |
| `FRED_API_KEY` | `""` | FRED API key (VIX, optional) |

R2 관련 canonical 키는 `R2_PUBLIC_BUCKET`, `R2_S3_ENDPOINT`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`입니다.

### 9.2 Parquet 출력 스키마 (MASTER_SCHEMA)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `date` | str | UTC 날짜 (YYYY-MM-DD), unique |
| `news_sentiment_mean` | float | 일별 뉴스 감성 평균 (-1.0~1.0) |
| `news_sentiment_std` | float | 일별 뉴스 감성 표준편차 |
| `n_articles` | Int64 | 일별 기사 수 |
| `fng_value` | Int64 | Fear & Greed Index (0~100) |
| `btc_log_return` | float | BTC 로그 수익률 |
| `btc_return` | float | BTC 단순 수익률 |
| `btc_quote_volume` | float | BTC 거래대금 |
| `usdkrw_log_return` | float | USD/KRW 로그 수익률 |
| `funding_rate` | float | BTC 선물 펀딩비 |
| `open_interest_usd` | float | BTC 선물 미결제약정 (USD) |
| `btc_long_short_ratio` | float | BTC Long/Short Ratio |
| `oi_change_pct` | float | 미결제약정 변화율 |
| `volume_change_pct` | float | 거래량 변화율 |
| `etf_total_btc` | float | BTC ETF 총 보유량 |
| `etf_total_aum_usd` | float | BTC ETF 총 AUM |
| `etf_net_inflow_usd` | float | BTC ETF 순유입 |
| `vix` | float | VIX (optional) |
| `btc_direction_label` | str | BTC 방향 라벨 (up/down/flat) |
| `is_outlier` | bool | 이상값 플래그 |
| `full_hybrid_index` | float | full 하이브리드 지수 (raw PC1) |
| `full_hybrid_index_score` | float | full 하이브리드 점수 (0~100) |
| `core_hybrid_index` | float | core 하이브리드 지수 (raw PC1) |
| `core_hybrid_index_score` | float | core 하이브리드 점수 (0~100) |
| `*_lag1` | float | 각 지표의 Lag-1 값 (look-ahead bias 방지) |

### 9.3 Alpha Validation 상세

5개 Predictor에 대해 독립적으로 분석을 수행합니다.

| Predictor | Threshold | 방향 | Granger 연계 |
|---|---|---|---|
| `news_sentiment_mean_lag1` | 0 | 정방향 | `news_sentiment_mean` |
| `fng_value_lag1` | 50 | 정방향 | `fng_value` |
| `vix_lag1` | 24 | 반전 (> 24 → bearish) | — |
| `full_hybrid_index_score_lag1` | 50 | 정방향 | — |
| `core_hybrid_index_score_lag1` | 50 | 정방향 | — |

각 Predictor에 대해 산출되는 지표:

| 분석 | 지표 | 설명 |
|---|---|---|
| Hit Rate | hit_rate, TP/FP/TN/FN, Precision, Recall, F1 | 방향 적중률 및 분류 성능 |
| Correlation | Pearson r/p-value, Spearman ρ/p-value | 수익률 상관 (비정상 시 Pearson 차분) |
| Backtest | strategy_cumret, bnh_cumret, alpha, sharpe, max_drawdown | 누적 수익 백테스트 |
| Walk-Forward | fold별 hit_rate, cumret, alpha → 평균 | out-of-sample 성능 |

Granger 검정에서 유의하지 않은 Predictor에는 `granger_significant: false` 플래그가 부여됩니다.

명시적 백필 스크립트는 뉴스 감성과 BTC 선물 OI/LSR를 지원합니다. BTC 선물 OI/LSR는
로컬에서 `scripts/backfill_btc_futures.py --provider coinalyze`로 `btc_futures_daily`에 적재합니다.
Coinalyze OI는 기존 Binance daily 계약과 맞추기 위해 `date + 1일`로 저장하고, LSR는 같은 UTC 날짜로 저장합니다.
ETF는 `btc_etf_gold` history를 우선 사용하고 최신 스냅샷 fallback은 historical backfill로 보지 않습니다.
futures는 funding과 OI/LSR를 분리 평가하며, OI/LSR coverage 미달 시 raw 컬럼은 저장하되 분석 입력에서는 제외합니다.

### 9.4 Parquet 메타데이터 구조 (sentiment_join_stats)

```json
{
  "run_id": "sentiment-join-20260418",
  "generated_at_utc": "2026-04-18T08:57:26+00:00",
  "adf": { "btc_log_return": { "conclusion": "stationary", ... }, ... },
  "granger_results": [ { "predictor": "...", "target": "...", "lag": 1, "pvalue_adjusted": 0.03, "significant": true, ... } ],
  "granger_correction": { "method": "benjamini_hochberg", "n_tests": 63, ... },
  "hybrid_indices": {
    "full": {
      "pca_summary": { "status": "ok", "selected_features": [...], ... },
      "excluded_features": [ { "feature": "etf_net_inflow_usd_lag1", "reason": "btc_etf_history_unavailable" } ],
      "quality_status": "degraded",
      ...
    },
    "core": { ... }
  },
  "structured_sources": {
    "btc_etf": { "mode": "gold_history", "coverage": { "ratio": 0.92 }, "quality_status": "ok" },
    "futures": { "mode": "binance", "oi_quality_status": "degraded", "lsr_quality_status": "ok", ... }
  },
  "hit_rates": [ { "predictor": "news_sentiment_mean_lag1", "hit_rate": 0.55, "f1": 0.59, "granger_significant": true, ... } ],
  "correlations": [ { "col_a": "...", "col_b": "btc_log_return", "pearson_r": 0.12, "spearman_rho": 0.15, ... } ],
  "backtest": [ { "predictor": "...", "alpha": 0.05, "sharpe_ratio": 1.2, "max_drawdown": -0.08, ... } ],
  "walk_forward": {
    "full": { "folds": [...], "avg_hit_rate": 0.52, "avg_alpha": 0.01, ... },
    "core": { ... }
  },
  "granger_executed": true,
  "granger_eligible_rows": 360,
  "rows_before_outlier_filter": 360,
  "rows_after_outlier_filter": 360
}
```

### 9.5 행 수와 분석 가능 범위

| 행 수 | 가능한 분석 |
|---|---|
| < 10 | Lag-1 컬럼만 생성, 나머지 전부 NaN/skip |
| 10~29 | PCA 하이브리드 지수 생성 가능 |
| 30~179 | ADF+KPSS 정상성 검정 추가 |
| 180~359 | Granger 인과 검정 + Alpha Validation 추가 (Walk-Forward fold 1~2개) |
| 360+ | Granger 검정력 향상, Walk-Forward fold 7~8개 (권장) |

### 9.6 Property-Based Testing

Alpha Validation의 정확성은 9개 Hypothesis property-based test로 검증됩니다.

| Property | 검증 내용 |
|---|---|
| Lag-1 shift 불변량 | lag1[i] == original[i-1], lag1[0] == NaN |
| Hit Rate CM 일관성 | TP+FP+TN+FN == n_valid, hit_rate ∈ [0,1] |
| 상관 계산 일관성 | scipy.stats 직접 호출과 수치적 동일 |
| 정상성 기반 차분 | 비정상 → Pearson 차분, Spearman 항상 원본 |
| Alpha round-trip | alpha == strategy_cumret - bnh_cumret |
| 거래 비용 단조성 | cost ≥ 0 → strategy_return(cost) ≤ strategy_return(0) |
| Walk-Forward 분할 | train/test 비겹침, 길이 일치 |
| Metadata round-trip | JSON 직렬화 → 역직렬화 원본 복원 |
| Granger 플래그 일관성 | forward significant 판정 로직 검증 |
