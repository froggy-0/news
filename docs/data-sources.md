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
| BTC ETF 보유량 (IBIT) | `ishares.com` structured file 우선, HTML fallback | aggregator reference-only | ✅ |
| BTC ETF 보유량 (BITB) | `bitbetf.com` 공식 다운로드 / `__NEXT_DATA__` / HTML fallback | aggregator reference-only | ✅ |
| BTC ETF 보유량 (GBTC/BTC) | `etfs.grayscale.com` XLSX 우선, HTML fallback | aggregator reference-only | ✅ |
| BTC ETF 보유량 (FBTC) | `digital.fidelity.com` 공식 페이지 파싱 | aggregator reference-only | ✅ |
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
- BTC ETF aggregator snapshot — primary 합산 제외, reference-only 저장
- Perplexity structured BTC ETF — primary 미사용, reference-only 보조 경로로만 유지

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

- 재시도 대상: `429 / 5xx / timeout` 만. `404`, `451` 등 영구/지역 실패는 재시도 없이 즉시 포기.
- 기본값: 최대 3회, 1.2초 기저 지수 백오프. `Retry-After` 헤더 우선.
- circuit breaker: `open_circuit()` 호출 시 해당 실행 내 이후 요청 전량 스킵.

| provider key | retryable statuses | max_attempts | 비고 |
|---|---|---|---|
| `binance_futures` | 429, 500-504 | 3 | 451(지역 차단)은 재시도 안 함 → Lambda 폴백으로 전환 |
| `bybit` | 429, 500-504 | 3 | 공개 API, 인증 불필요 |

---

## 5. Sentiment Join 분석 파이프라인 데이터 소스

`scripts/build_sentiment_join.py` (`make sentiment-join`)에서 사용하는 소스 목록입니다.
브리핑 파이프라인과 독립 실행되며, 출력은 `data/sentiment_join/master_{YYYYMMDD}.parquet`입니다.

| 데이터 | 1차 소스 | 폴백 | 상태 |
|---|---|---|---|
| BTC 가격·거래량 | Binance `data-api.binance.vision/api/v3/klines` (공식 미러, geo-restriction 없음) | KIS → yfinance `BTC-USD` | ✅ |
| USD/KRW 종가 | KIS `inquire-daily-chartprice` (`FX@KRW`) | yfinance `KRW=X` | ✅ |
| Fear & Greed | `api.alternative.me/fng/` | — | ✅ |
| BTC 펀딩비 (`funding_rate`) | Lambda(ap-northeast-2) → `fapi.binance.com/fapi/v1/fundingRate` | Bybit `api.bybit.com/v5/market/funding/history` | ✅ |
| BTC 미결제약정 (`open_interest_usd`) | Lambda(ap-northeast-2) → `fapi.binance.com/futures/data/openInterestHist` | Bybit `api.bybit.com/v5/market/open-interest` | ✅ |
| BTC Long/Short Ratio | Lambda(ap-northeast-2) → `fapi.binance.com/futures/data/globalLongShortAccountRatio` | Bybit `api.bybit.com/v5/market/account-ratio` | ✅ |
| R2 감성 점수 | R2 버킷 (브리핑 파이프라인 산출물 parquet) | — | ✅ |
| BTC ETF flows | Grayscale/공식 발행사 페이지 (`etfs.grayscale.com` 등) | — | ⚠️ 429 차단 빈번 |

### 5.1 선물 데이터 fallback 체인

GitHub Actions(US IP)에서 `fapi.binance.com`이 HTTP 451(지역 제한)로 차단됩니다.
`FUTURES_LAMBDA_ARN` 환경변수로 ap-northeast-2 Lambda를 프록시로 사용합니다.

```
FUTURES_LAMBDA_ARN 설정 시 (GitHub Actions 권장):
  1차: Lambda(ap-northeast-2) 호출 → Seoul IP → fapi.binance.com ✓
       ↓ 실패 시
  2차: Bybit 공개 API (geo-restriction 없음, 인증 불필요)
       ↓ 실패 시
  NaN 프레임 반환 — 파이프라인은 계속 진행

FUTURES_LAMBDA_ARN 미설정 시 (로컬 환경 등):
  1차: fapi.binance.com 직접 시도
       ↓ 실패 시 (로컬 IP가 허용된 경우라면 성공)
  2차: Bybit → NaN
```

### 5.2 Lambda 인프라

| 항목 | 값 |
|---|---|
| 함수명 | `binance-futures-fetcher` |
| 리전 | `ap-northeast-2` (Seoul) |
| ECR 이미지 | `254849613915.dkr.ecr.ap-northeast-2.amazonaws.com/news:binance-futures-fetcher` |
| 아키텍처 | ARM64 (Graviton2) |
| 런타임 | Python 3.11, stdlib만 사용 (외부 의존성 없음) |
| Lambda 실행 역할 | `kr-pr-lambda-binance-futures-v1` |
| 호출 권한 (GHA) | `kr-pr-ses-news-v1a` — `lambda:InvokeFunction` |
| CloudWatch 로그 그룹 | `/aws/lambda/binance-futures-fetcher` |
| 배포 방법 | 수동: `bash lambda/binance_futures/deploy.sh` |

CloudWatch 정상 로그 예시:
```
[INFO] source=fapi.binance.com symbol=BTCUSDT range=2026-04-08~2026-04-12
       funding_days=5(latest=-0.000118) oi_days=5(latest=7207692419) lsr_days=5(latest=0.7425)
```

### 5.3 Parquet 출력 스키마

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `date` | str | YYYY-MM-DD |
| `news_sentiment_mean` / `_std` | float | FinBERT 뉴스 감성 평균/표준편차 |
| `n_articles` | int | 감성 점수 부여 기사 수 |
| `signal_sentiment_mean` / `_std` | float | X 시그널 감성 평균/표준편차 |
| `n_signals` | int | 시그널 수 |
| `fng_value` | int | Fear & Greed (0~100) |
| `btc_quote_volume` | float | BTC 거래대금 (USD) |
| `btc_log_return` / `btc_return` | float | BTC 일간 수익률 |
| `usdkrw_log_return` / `usdkrw_return` | float | USD/KRW 일간 수익률 |
| `funding_rate` | float | BTC 일별 합산 펀딩비 |
| `open_interest_usd` | float | BTC 미결제약정 (USD) |
| `btc_long_short_ratio` | float | BTC Long/Short 비율 |
| `etf_total_btc` / `_aum_usd` / `_net_inflow_usd` | float | BTC ETF 집계 |
| `*_lag1` | float | 전일 지연값 (2행 이상 필요) |
| `is_outlier` | bool | Z-score 이상값 여부 |
| `hybrid_index` | float | VIF+PCA 기반 복합 지표 (최소 행 수 필요) |

**Parquet 메타데이터:**
- `btc_source`: 가격 수집 소스 (`binance` / `kis` / `yfinance`)
- `ffill_days`: forward-fill 적용 일수
- `sentiment_join_stats`: ADF/Granger/PCA/VIF 진단 요약 JSON
- `hybrid_index_diagnostics`: PCA 요약

**행 수 제약:**
- lag 컬럼: 2행 이상 필요 (부족 시 NaN)
- ADF/Granger 검정: 30행 이상 권장
- hybrid_index (PCA): feature 수 이상 행 필요
- 행 수는 R2에 누적된 브리핑 실행 횟수에 비례
