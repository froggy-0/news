# 데이터 소스 및 품질 기준

코드 기반 실제 호출 경로, 폴백, 품질 판정 기준을 정리한 문서입니다.

---

## 1. 시장 데이터

### 1.1 거시 지표

| 데이터 (canonical_key) | 1차 소스 | 폴백 | 단위 |
|---|---|---|---|
| `us10y` 미국 10년물 | FRED `DGS10` | yfinance `^TNX` (×0.1) | % |
| `us2y` 미국 2년물 | FRED `DGS2` | — | % |
| `vix` VIX | FRED `VIXCLS` | yfinance `^VIX` | 포인트 |
| `dxy` 달러 인덱스 | FRED `DTWEXAFEGS` (연준 AFE 무역가중) | yfinance `DX=F` | 포인트 |
| `hy_spread` 하이일드 스프레드 | FRED `BAMLH0A0HYM2` (ICE BofA) | — | % |

FRED: 최근 15개 관측값 중 유효한 최신 2개로 변화량(bp) 계산. yfinance: `period="7d", interval="1d"` 일봉 마지막 2행.

### 1.2 지수·주식

| 데이터 (canonical_key) | 1차 소스 | 폴백 |
|---|---|---|
| `dow30` 다우30 | KIS `inquire-daily-chartprice` (`.DJI`) | yfinance `^DJI` |
| `spy` S&P 500 ETF | KIS `price` | yfinance `SPY` |
| `qqq` Nasdaq 100 ETF | KIS `price` | yfinance `QQQ` |
| `soxx` 반도체 ETF | KIS `price` | yfinance `SOXX` |
| `kospi` 코스피 | KIS `inquire-index-price` (`0001`) | yfinance `^KS11` |
| `kosdaq` 코스닥 | KIS `inquire-index-price` (`1001`) | yfinance `^KQ11` |
| 빅테크 10종 | KIS `price` | yfinance |
| BTC ETF 가격 5종 | KIS `price` | yfinance |

빅테크: `NVDA`, `MSFT`, `AAPL`, `AMZN`, `GOOGL`, `META`, `AMD`, `TSM`, `ASML`, `AVGO`

### 1.3 한국 투자자 참고 지표

| 데이터 (canonical_key) | 1차 소스 | 폴백 |
|---|---|---|
| `usdkrw` 원/달러 환율 | KIS `inquire-daily-chartprice` (`FX@KRW`) | yfinance `KRW=X` |
| `nq_futures` 나스닥 선물 | yfinance `NQ=F` | — |

### 1.4 암호화폐

| 데이터 | 1차 소스 | 폴백 |
|---|---|---|
| BTC 현물 가격 | Binance Spot klines | CoinGecko → yfinance `BTC-USD` |
| Fear & Greed Index | `api.alternative.me/fng/?limit=1` | — |
| BTC ETF 보유량 (IBIT) | `ishares.com` structured file → HTML fallback | aggregator reference-only |
| BTC ETF 보유량 (BITB) | `bitbetf.com` 공식 다운로드 / `__NEXT_DATA__` / HTML | aggregator reference-only |
| BTC ETF 보유량 (GBTC/BTC) | `etfs.grayscale.com` XLSX 직링크 | aggregator reference-only |

BTC ETF는 Bronze/Silver/Gold 계층으로 저장됩니다. 공식 issuer source를 primary로 사용하고, aggregator 데이터는 reference-only로 분리 기록합니다.

### 1.5 데이터 검증 범위

| canonical_key | 허용 범위 | 이탈 시 |
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

---

## 2. 뉴스·시그널 데이터

수집 → 중복 제거 → 점수 기반 랭킹 순서. 각 소스는 독립 실패 허용.

### 2.1 수집 소스

| 순서 | 소스 | 방식 | 발동 조건 |
|---|---|---|---|
| 1 | CoinDesk API | `data-api.coindesk.com/news/v1/article/list` 역방향 페이지네이션 | 기본 (`COINDESK_NEWS_ENABLED`) |
| 2 | Grok 공식 X 시그널 | `xai_sdk` x_search, allowlist 계정 최근 48h | 기본, 소량 |
| 3 | Perplexity Sonar | `perplexity` SDK, 4개 토픽별 구조화 요약 | 기본 |
| 4 | Perplexity Search | `perplexity` SDK 직접 검색 | CoinDesk가 약한 macro/us_equity 보강 |
| 5 | Grok X 키워드 검색 | `xai_sdk` x_search, 시장 키워드 24h | CoinDesk+Perplexity 품질 미달 시 |
| 6 | Grok Web Search | `xai_sdk` web search | 선택적 (`GROK_WEB_SEARCH_ENABLED`) |
| 7 | Gemini Grounding | `google.genai` + GoogleSearch, `gemini-2.0-flash` | CoinDesk/Perplexity 0건 시 |
| 8 | Google News RSS | `feedparser` + `news.google.com/rss/search` | 품질 미달 시 |
| 9 | NewsAPI | `newsapi.org/v2/everything` | 품질 미달 시 |

### 2.2 Grok 공식 X allowlist 그룹

| 그룹 | 토픽 매핑 | 대상 |
|---|---|---|
| `macro_regulator` | `macro` | 연준, SEC, 재무부 등 정책 기관 |
| `btc_etf_primary` | `bitcoin` | ETF 운용사 (Fidelity, BlackRock 등) |
| `macro_and_equity` | X 키워드 검색용 | 거시·주식 시장 계정 |
| `crypto_and_etf` | X 키워드 검색용 | 암호화폐·ETF 계정 |

`ai_bigtech_primary` 그룹은 현재 비활성 (빅테크 IR 계정은 X 시그널 대비 정보 밀도가 낮아 제외).

### 2.3 신뢰 도메인 계층

| 등급 | 도메인 | score |
|---|---|---|
| Tier 1 | `reuters.com`, `bloomberg.com`, `wsj.com`, `ft.com`, `federalreserve.gov`, `home.treasury.gov`, `sec.gov` | 4.5~5.0 |
| Tier 2 | `cnbc.com`, `coindesk.com`, `ishares.com`, `bitbetf.com`, 빅테크 IR 도메인 | 3.8~4.0 |

---

## 3. 감성 분석

### 3.1 FinBERT

| 항목 | 값 |
|---|---|
| 모델 | `ProsusAI/finbert` |
| 입력 | 영문 원본 텍스트 (title + summary + why_it_matters) |
| 출력 | sentimentScore (-1.0~1.0), sentimentConfidence (0~1) |
| 적용 대상 | 뉴스, X 시그널, 공개 뉴스 카드 |
| 활성화 | `FINBERT_ENABLED` (기본 `true`) |
| 모델 고정 | `FINBERT_MODEL_REVISION`으로 commit hash 고정 |

ML 의존성(`transformers`, `torch`)은 `requirements-ml.txt`에 별도 관리. 미설치 환경에서도 파이프라인 정상 동작.

---

## 4. Sentiment Join 파이프라인 데이터 소스

`make sentiment-join`으로 실행. 브리핑 파이프라인보다 **먼저** 실행됩니다.

### 4.1 수집 소스

| 데이터 | 1차 소스 | 폴백 |
|---|---|---|
| R2 감성 점수 | R2 버킷 (브리핑 파이프라인 산출물) | — |
| Fear & Greed Index | `api.alternative.me/fng/` | — |
| BTC 가격·거래량 | Binance `data-api.binance.vision` (Spot klines) | KIS → yfinance `BTC-USD` |
| USD/KRW 종가 | KIS `inquire-daily-chartprice` (`FX@KRW`) | yfinance `KRW=X` |
| VIX | FRED `VIXCLS` (optional, `FRED_API_KEY` 필요) | — |
| BTC 펀딩비 | Lambda → `fapi.binance.com` | Bybit 공개 API → NaN |
| BTC 미결제약정 | Lambda → `fapi.binance.com` | Bybit 공개 API → NaN |
| BTC Long/Short Ratio | Lambda → `fapi.binance.com` | Bybit 공개 API → NaN |
| BTC ETF flows | 공식 발행사 페이지 | — |

### 4.2 선물 데이터 fallback 체인

GitHub Actions(US IP)에서 `fapi.binance.com`이 HTTP 451(지역 제한)로 차단됩니다.

```
FUTURES_LAMBDA_ARN 설정 시 (GitHub Actions 권장):
  Lambda(ap-northeast-2) → Seoul IP → fapi.binance.com
  ↓ 실패 시
  Bybit 공개 API (geo-restriction 없음)
  ↓ 실패 시
  NaN — 파이프라인 계속 진행

FUTURES_LAMBDA_ARN 미설정 시 (로컬):
  fapi.binance.com 직접 → Bybit → NaN
```

### 4.3 Lambda 인프라

| 항목 | 값 |
|---|---|
| 함수명 | `binance-futures-fetcher` |
| 리전 | `ap-northeast-2` (Seoul) |
| 아키텍처 | ARM64 (Graviton2) |
| 런타임 | Python 3.11, stdlib만 사용 |
| 호출 권한 | `kr-pr-ses-news-v1a` → `lambda:InvokeFunction` |
| 배포 | `bash lambda/binance_futures/deploy.sh` |

### 4.4 통계 분석에 사용되는 변수

| 분석 | 대상 변수 |
|---|---|
| ADF+KPSS 정상성 검정 | `btc_log_return`, `news_sentiment_mean`, `fng_value`, `funding_rate`, `btc_long_short_ratio`, `oi_change_pct`, `etf_net_inflow_usd`, `usdkrw_log_return`, `volume_change_pct` (9개) |
| Granger 총 검정 수 | (16 + 5) × 3 lag = 63 검정, BH-FDR 보정 |
| 하이브리드 지수 (full) | `news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `btc_long_short_ratio_lag1`, `etf_net_inflow_usd_lag1`, `volume_change_pct_lag1`, `vix_lag1` |
| 하이브리드 지수 (core) | `news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `volume_change_pct_lag1` |
| Risk Overlay (RegimeState) | `vix_lag1`, `btc_realized_vol_20d_lag1`, `funding_rate_zscore_30d`, `fng_value`, `oi_price_divergence_flag_7d` |

---

## 5. Supabase (신호 기록 및 구독 관리)

### 5.1 signal_log 테이블

매일 발송된 신호를 기록하고 7일 후 BTC 수익률로 적중 여부를 자동 평가합니다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `signal_date` | date (unique) | 신호 발송일 |
| `regime_state` | text | BullQuiet / BullHeated / BearPanic / Choppy / Transitional |
| `vol_level` | text | High / Mid / Low |
| `vol_trend` | text | rising / falling / stable |
| `overlay_decision` | text | promote / research_only |
| `confidence` | text | HIGH / MEDIUM / null (신호 없는 날) |
| `reasons` | jsonb | `["vol_regime_v2_promoted", "vol_quiet", ...]` |
| `btc_price_open` | numeric | 발송 시점 BTC 가격 |
| `btc_price_7d` | numeric | 7일 후 BTC 가격 (자동 채워짐) |
| `ret_7d` | numeric | (price_7d / price_open) - 1 |
| `hit` | boolean | 신호 방향 적중 여부 (long-only 기준) |

**쓰기 경로**: `pipeline.py` → `signal_logger.log_signal()` (발송 직후)
**읽기 경로**: `signal_logger.fetch_track_record()` → `packet["signal_track_record"]` → 이메일 트랙레코드 블록
**채우기**: `scripts/fill_signal_outcomes.py` (파이프라인 성공 후 GitHub Actions 스텝)

환경변수: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — 미설정 시 기록 건너뜀, 파이프라인 계속 진행.

### 5.2 구독 테이블

| 테이블 | 역할 |
|---|---|
| `subscriptions` | 이메일 구독자 목록 (active/inactive) |

자세한 내용: [docs/subscriptions-ops.md](subscriptions-ops.md)

---

## 6. Cloudflare R2 (산출물 저장소)

| 경로 | 내용 | 쓰기 주체 |
|---|---|---|
| `analytics/sentiment/latest.json` | 최신 Sentiment Join artifact (riskOverlay 포함) | run-sentiment-join |
| `analytics/sentiment/YYYY-MM-DD.json` | 날짜별 artifact | run-sentiment-join |
| `briefs/YYYY-MM-DD.json` | 공개 브리핑 JSON | run-brief |
| `index.json` | 날짜 인덱스 | run-brief |

환경변수: `R2_PUBLIC_BUCKET`, `R2_S3_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` — 미설정 시 로컬에만 저장.

---

## 7. 품질 판정 기준

### 7.1 뉴스 품질 (`data_quality.py`)

| 지표 | 임계값 |
|---|---|
| `news_count` | MIN 3 → 미달 시 critical |
| `preferred_news_count` | MIN 2 |
| `tier_1_news_count` | MIN 1 |
| `unique_news_domains` | MIN 3 |
| `fresh_news_count` (24h 이내) | MIN 2 |
| `topic_coverage_count` | MIN 2 (4개 토픽 중) |

```
ok        → 모든 기준 충족
degraded  → 경고 1개 이상 → OpenAI web_search 백필 트리거
critical  → 뉴스 3건 미만 또는 가격 누락률 ≥ 80% → 이메일 발송 스킵
```

### 7.2 Sentiment Join 행 수 제약

| 행 수 | 가능한 분석 |
|---|---|
| < 10 | Lag-1 컬럼만 생성 |
| 10~29 | PCA 하이브리드 지수 추가 |
| 30~179 | ADF+KPSS 정상성 검정 추가 |
| 180~359 | Granger 인과 검정 + Alpha Validation (Walk-Forward fold 1~2개) |
| 360+ | Granger 검정력 향상, Walk-Forward fold 7~8개 (권장) |

---

## 8. 재시도·공급자 정책

- 재시도 대상: `429 / 5xx / timeout`만. `404`, `451` 등 영구 실패는 즉시 포기.
- 기본값: 최대 3회, 1.2초 기저 지수 백오프. `Retry-After` 헤더 우선.
- circuit breaker: `open_circuit()` 호출 시 해당 실행 내 이후 요청 전량 스킵.

---

## 9. 폐기된 경로

| 경로 | 사유 |
|---|---|
| `us3m / ^IRX` | 단기금리 항목 제거 |
| `DX-Y.NYB` | 상장폐지, 0% 성공 → 하위 호환 캐시 키만 유지 |
| BTC ETF aggregator snapshot | primary 합산 제외, reference-only 저장 |
| `ai_bigtech_primary` X 그룹 | 빅테크 IR 계정 정보 밀도 낮아 비활성 |
| 단일 `hybrid_index` 컬럼 | v4에서 full/core 이중 지수로 교체, 삭제됨 |
| BTC T+7 방향 예측 신호 | 학술적으로 불가능 수준의 난이도 → Risk Overlay Score로 방향 전환 |
