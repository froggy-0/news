# 데이터 소스 및 품질 기준

코드 기반 실제 호출 경로·폴백·품질 판정 기준을 한 곳에 정리한 문서입니다.

---

## 1. 시장 데이터

| 데이터 (canonical_key) | 1차 소스 / 엔드포인트 | 폴백 | 상태 |
|---|---|---|---|
| `us10y` 미국 10년물 | FRED `DGS10` → `api.stlouisfed.org/fred/series/observations` | yfinance `^TNX` ×0.1 | ✅ |
| `us2y` 미국 2년물 | FRED `DGS2` → 동일 | — | ✅ |
| `vix` VIX | FRED `VIXCLS` → 동일 | yfinance `^VIX` | ✅ |
| `dxy` 달러 인덱스 | FRED `DTWEXAFEGS` (연준 AFE 무역가중 달러 지수) | yfinance `DX=F` | ✅ |
| `hy_spread` 하이일드 스프레드 | FRED `BAMLH0A0HYM2` (ICE BofA 미국 HY 스프레드) | — | ✅ |
| `usdkrw` 원달러 | KIS `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice` (`FID_COND_MRKT_DIV_CODE="X"`, `FID_INPUT_ISCD="FX@KRW"`) | yfinance `KRW=X` | ✅ |
| `nq_futures` 나스닥선물 | yfinance `NQ=F` | — | ✅ |
| `dow30` 다우30 | KIS `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice` (`FID_COND_MRKT_DIV_CODE="N"`, `FID_INPUT_ISCD=".DJI"`) | yfinance `^DJI` | ✅ |
| `kospi` 코스피 | KIS `/uapi/domestic-stock/v1/quotations/inquire-index-price` (`FID_COND_MRKT_DIV_CODE="U"`, `FID_INPUT_ISCD="0001"`) | yfinance `^KS11` | ✅ |
| `kosdaq` 코스닥 | KIS `/uapi/domestic-stock/v1/quotations/inquire-index-price` (`FID_COND_MRKT_DIV_CODE="U"`, `FID_INPUT_ISCD="1001"`) | yfinance `^KQ11` | ✅ |
| `spy/qqq/soxx` 미국지수 | KIS `/uapi/overseas-price/v1/quotations/price` | yfinance | ✅ |
| 빅테크 10종 | KIS `/uapi/overseas-price/v1/quotations/price` | yfinance | ✅ |
| BTC ETF 가격 5종 | KIS `/uapi/overseas-price/v1/quotations/price` | yfinance | ✅ |
| `btc` 현물 가격 | CoinGecko `api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true` | yfinance `BTC-USD` | ✅ |
| BTC ETF 보유량 (IBIT) | `ishares.com/us/products/333011/…` HTML 파싱 | — | ✅ |
| BTC ETF 보유량 (BITB) | `bitbetf.com` `__NEXT_DATA__` JSON 파싱 | — | ✅ |
| Fear & Greed | `api.alternative.me/fng/?limit=1` | — | ✅ |

**FRED 호출**: 최근 15개 관측값 중 유효한 최신 2개로 변화량(bp) 계산
**yfinance 호출**: `period="7d", interval="1d"` 일봉 마지막 2행
**KIS 호출**: 해외주식 현재체결가(`price`)와 환율 일자별 시세(`inquire-daily-chartprice`)를 사용하며, 실패 시 yfinance로 폴백

**데이터 검증 범위** (`market_policy.py`):

| key | 허용 범위 | 이탈 시 |
|---|---|---|
| `dxy` | 95 ~ 130 | `anomaly` → price 제거 |
| `vix` | 10 ~ 80 | 동일 |
| `us10y` | 0.5 ~ 8.0% | 동일 |
| `btc` | $10,000 ~ $200,000 | 동일 |
| `dow30` | 10,000 ~ 80,000 | 동일 |
| `kospi` | 1,000 ~ 6,500 | 동일 |
| `kosdaq` | 300 ~ 2,000 | 동일 |
| `spy` | $300 ~ $700 | 동일 |
| `hy_spread` | 1.5 ~ 20.0% | 동일 |

수집 실패 시 전일 캐시 복원 (`is_previous_value=True`). 캐시도 없으면 `missing`.

### KIS phase 1 contract 검증

- standalone probe: `python scripts/kis_parameter_probe.py`
- live contract test: `python -m pytest -q -m live_kis tests/test_kis_live_contract.py`
- production 편입 범위: `usdkrw`, `dow30`, `kospi`, `kosdaq`
- future phase로 남긴 후보: `sp500`, `nasdaq100`, `nasdaq_composite`, `jpykrw`, `eurkrw`, `cnykrw`, 한국 국채, 원자재

**폐기된 경로**:
- `us3m / ^IRX` — 단기금리 항목 제거됨 (CANONICAL_LABELS에서 삭제)
- `DX-Y.NYB` — 상장폐지, 0% 성공 → 하위 호환 캐시 키만 유지
- `DX=F` (yfinance ICE Dollar Futures) — FRED DTWEXAFEGS로 교체, 현재는 FRED 실패 시 폴백으로만 사용
- GBTC direct fetch — Grayscale 429 차단 → 제거
- Perplexity structured BTC ETF — 빈 배열만 반환 → direct fetch primary 승격

---

## 2. 뉴스 데이터

수집 → 중복제거 → 점수 기반 랭킹 순서. 각 소스는 독립 실패 허용.

| 순서 | 소스 | 방식 | 발동 조건 |
|---|---|---|---|
| 1 | **Grok 공식 X 시그널** | `xai_sdk` x_search, allowlist 계정 최근 48h | 항상 |
| 2 | **Perplexity Sonar** | `perplexity` SDK, model=`sonar` (기본값, `PERPLEXITY_SONAR_MODEL`로 변경 가능), 4개 토픽 | 항상 |
| 3 | **Grok X 키워드** | `xai_sdk` x_search, 시장 키워드 검색 24h | 항상 |
| 4 | **Grok 웹 검색** | `xai_sdk` web search | 선택적 |
| 5 | **Perplexity Search** | `perplexity` SDK | Sonar 미사용 시 |
| 6 | **Gemini Grounding** | `google.genai` + GoogleSearch tool, `gemini-2.0-flash` | Perplexity 0건 시 |
| 7 | **Google News RSS** | `feedparser` + `news.google.com/rss/search?q=…` | 품질 미달 시 |
| 8 | **NewsAPI** | `newsapi.org/v2/everything`, PREFERRED_DOMAINS 필터 | 품질 미달 시 |

**Grok 공식 X allowlist 그룹**:
- `macro_regulator` → topic: `macro` (Fed, SEC, 재무부)
- `ai_bigtech_primary` → topic: `ai_bigtech` (빅테크 IR 계정)
- `btc_etf_primary` → topic: `bitcoin` (ETF 운용사)

**Sonar 토픽**: `macro`, `us_equity`, `ai_bigtech`, `bitcoin`

**Google RSS 쿼리** (`news_policy.py`):
```
"Fed interest rates US Treasury yields"
"US stock market Nasdaq S&P 500 semiconductor"
"NVIDIA Microsoft Apple Amazon Google Meta AMD TSM ASML AVGO"
"Bitcoin ETF flows regulation"
```

**신뢰 도메인 계층**:
- Tier 1 (score 4.5~5.0): `reuters.com`, `bloomberg.com`, `wsj.com`, `ft.com`, `federalreserve.gov`, `home.treasury.gov`, `sec.gov`
- Tier 2 (score 3.8~4.0): `cnbc.com`, `coindesk.com`, `ishares.com`, `bitbetf.com`, 빅테크 IR 도메인 12종

---

## 3. 품질 판정 기준 (`data_quality.py`)

| 지표 | 임계값 |
|---|---|
| `news_count` | MIN 3 → 미달 시 **critical** |
| `preferred_news_count` | MIN 2 |
| `tier_1_news_count` | MIN 1 |
| `unique_news_domains` | MIN 3 |
| `fresh_news_count` (24h 이내) | MIN 2 |
| `topic_coverage_count` | MIN 2 (4개 토픽 중) |

```
ok        →  모든 기준 충족
degraded  →  경고 1개 이상 → OpenAI web_search 백필 트리거
critical  →  뉴스 3건 미만 또는 가격 누락률 ≥ 80% → 이메일 발송 스킵
```

---

## 4. 재시도·공급자 정책 (`provider_runtime.py`)

- 재시도 대상: `429 / 5xx / timeout` 만. `404` 등 영구 실패는 즉시 포기.
- 기본값: 최대 3회, 1.2초 기저 지수 백오프. `Retry-After` 헤더 우선.
- circuit breaker: `open_circuit()` 호출 시 해당 실행 내 이후 요청 전량 스킵.
