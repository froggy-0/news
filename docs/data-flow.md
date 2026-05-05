# 데이터 수집·정제 흐름 (Data Flow)

브리핑 이메일이 발송되기 전까지 파이프라인이 수집·가공하는 모든 데이터를 정리한 문서입니다.
두 개의 독립 파이프라인이 순차적으로 실행됩니다: **Sentiment Join → 브리핑**.

---

## 전체 실행 순서

```
GitHub Actions 22:40 UTC (한국시간 07:40)
│
├─ [Job 1] run-sentiment-join
│   감성·심리 지표 수집 → 통계 검정 → Risk Overlay 산출 → R2 업로드
│
└─ [Job 2] run-brief  (needs: run-sentiment-join)
    ├─ R2에서 latest.json 다운로드 (Risk Overlay 포함)
    ├─ 시장 데이터 + 뉴스 수집
    ├─ LLM 브리핑 생성
    ├─ 이메일 발송 (Risk Overlay 블록 포함)
    ├─ Supabase signal_log 기록
    └─ fill_signal_outcomes.py (7일 전 신호 결과 채우기)
        │
        └─ [Job 3] deploy-frontend  (needs: run-brief)
```

---

## 파이프라인 1: Sentiment Join

```
┌──────────────────────────────────────────────────────────────────┐
│  진입점: scripts/build_sentiment_join.py                         │
│  GitHub Actions: run-sentiment-join job                          │
├──────────────────────────────────────────────────────────────────┤
│  Phase 1: 데이터 수집                                            │
│    ├─ R2 감성 점수 (브리핑 파이프라인 산출물)                    │
│    ├─ Fear & Greed Index (api.alternative.me/fng/)               │
│    ├─ BTC 가격·거래량                                            │
│    │    Binance data-api.binance.vision (Spot klines)            │
│    │    → KIS → yfinance BTC-USD                                 │
│    ├─ USD/KRW 종가 (KIS → yfinance KRW=X)                       │
│    ├─ VIX (FRED API, optional — 키 미설정 시 전 행 NaN)          │
│    ├─ BTC 선물 지표 3종                                          │
│    │    funding_rate / open_interest_usd / btc_long_short_ratio  │
│    │    1차: Lambda(ap-northeast-2) → fapi.binance.com           │
│    │    2차: Bybit 공개 API                                      │
│    │    3차: NaN (파이프라인 계속 진행)                           │
│    └─ BTC ETF flows (공식 발행사 페이지)                         │
├──────────────────────────────────────────────────────────────────┤
│  Phase 2~6: 변환·통계·지수 생성                                  │
│    날짜 정규화 → forward-fill → inner join → 이상값 필터         │
│    → ADF+KPSS → Granger (63 검정, BH-FDR) → VIF+PCA            │
│    → full/core 하이브리드 지수 (0~100)                           │
├──────────────────────────────────────────────────────────────────┤
│  Phase 7: vol_regime_v2 overlay gate 평가                        │
│    JSONL에 누적된 hit_rate·coverage·p-value 롤링 평가            │
│    promote 조건: hit_rate ≥ 0.55, coverage 0.45~0.70,           │
│                  p ≤ 0.10, 최소 14일 기록                        │
├──────────────────────────────────────────────────────────────────┤
│  Phase 8: Risk Overlay Score 산출                                │
│    compute_risk_overlay(master_df, overlay_gate_decision)        │
│    → Layer 1: RegimeState (BullQuiet/Heated/BearPanic/…)        │
│    → Layer 2: VolEnvironment (High/Mid/Low + rising/stable/…)   │
│    → Layer 3: SignalConfidence (HIGH/MEDIUM/None)                │
│    → fe_artifact["riskOverlay"] = risk_ov.to_dict()             │
├──────────────────────────────────────────────────────────────────┤
│  Phase 9: 저장·업로드                                            │
│    Parquet 저장 (sentiment_join_master_YYYYMMDD.parquet)         │
│    latest.json 저장 (riskOverlay 포함)                           │
│    R2 업로드: analytics/sentiment/latest.json                    │
│              analytics/sentiment/YYYY-MM-DD.json                 │
└──────────────────────────────────────────────────────────────────┘
```

---

## 파이프라인 2: 브리핑

```
┌─────────────────────────────────────────────────────────────────────┐
│  진입점: python main.py once                                        │
│  GitHub Actions: run-brief job (needs: run-sentiment-join)          │
├─────────────────────────────────────────────────────────────────────┤
│  Pre-flight: latest.json 다운로드                                   │
│    R2 → data/sentiment_join/latest.json                             │
│    실패 시 로컬 파일 사용 (이전 실행 artifact)                       │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 1: Market Data                                               │
│  build_market_packet()                                              │
│    ├─ 거시 지표 (FRED → yfinance fallback)                          │
│    ├─ 미국 지수 ETF proxy (KIS → yfinance)                          │
│    └─ 비트코인 스냅샷                                               │
│        ├─ BTC 현물 (Binance → CoinGecko → yfinance)                │
│        ├─ Fear & Greed Index (alternative.me)                       │
│        └─ BTC ETF 공식 보유량/순유입                                │
├─────────────────────────────────────────────────────────────────────┤
│  Display-only Market Data                                           │
│  fetch_newsletter_display_data()                                    │
│    ├─ 한국 지수 (KOSPI/KOSDAQ: KIS → yfinance)                     │
│    ├─ 빅테크 10종 (KIS → yfinance)                                  │
│    └─ BTC ETF 가격·거래량 (KIS → yfinance)                         │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 2: News Data                                                 │
│  build_news_packet()                                                │
│    ├─ CoinDesk API (기본)                                           │
│    ├─ Grok 공식 X 시그널 (allowlist 계정)                           │
│    ├─ Perplexity Sonar (4개 토픽별 구조화 요약)                     │
│    ├─ Grok X 키워드 검색                                            │
│    ├─ Gemini Grounding (fallback)                                   │
│    └─ Legacy (RSS + NewsAPI, 품질 미달 시)                          │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 3: Risk Overlay 로드                                         │
│  _load_risk_overlay()                                               │
│    경로 1 (선호): latest.json → riskOverlay 필드 직접 읽기          │
│    경로 2 (로컬 fallback): parquet 직접 읽어 재산출                 │
│    → packet["risk_overlay"] = risk_overlay.to_dict()               │
│                                                                     │
│  Supabase 설정 시 트랙레코드 조회:                                  │
│    fetch_track_record(days=90)                                      │
│    → packet["signal_track_record"] = {...}                          │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 4: 데이터 품질 평가 + OpenAI 백필 (선택)                    │
│  assess_data_quality() → ok / degraded / critical                  │
│  backfill_news_with_web_search() (degraded 시)                      │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 5: 브리핑 생성 + 검수                                        │
│  generate_briefing() → OpenAI API                                   │
│    → validate_and_rewrite_briefing() (최대 1회 재작성)              │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 6: 공개 산출물 발행                                          │
│  publish_public_brief()                                             │
│    R2 업로드: index.json, briefs/YYYY-MM-DD.json                    │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 7: 이메일 발송                                               │
│  SesSender.send()                                                   │
│    _build_signal_block(packet) → 이메일 신호 블록 생성              │
│    HTML (email_signal.html.j2 포함) + plain text → AWS SES 발송     │
├─────────────────────────────────────────────────────────────────────┤
│  Phase 8: 신호 기록                                                 │
│  log_signal() → Supabase signal_log upsert                         │
│    signal_date, regime_state, vol_level, vol_trend,                │
│    overlay_decision, confidence, reasons, btc_price_open           │
├─────────────────────────────────────────────────────────────────────┤
│  Post-pipeline: 신호 결과 채우기                                    │
│  scripts/fill_signal_outcomes.py                                    │
│    signal_date + 7일 이후, btc_price_7d 비어있는 레코드 조회        │
│    yfinance로 7일 후 BTC 가격 수집 → ret_7d, hit 업데이트          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Risk Overlay Score 상세

`src/morning_brief/analysis/sentiment_join/risk_overlay.py`

### Layer 1: RegimeState

최신 행의 피처를 기반으로 시장 구조를 분류합니다.

| 상태 | 조건 | 신호 발화 |
|---|---|---|
| **BearPanic** | VIX ≥ 90일 q80 AND FNG ≤ 20 | 가능 (역발산) |
| **BullHeated** | funding_zscore ≥ 1.5 AND (FNG ≥ 80 OR OI 과열) | ❌ 불가 |
| **BullQuiet** | VIX < 90일 q40 AND rv < 45일 q45 AND 20 < FNG < 80 | 가능 |
| **Transitional** | 방향성 있음, 위 조건 미충족 | 가능 |
| **Choppy** | 방향성 판단 불가 | ❌ 불가 |

사용 피처: `vix_lag1`, `btc_realized_vol_20d_lag1`, `funding_rate_zscore_30d`, `fng_value`, `oi_price_divergence_flag_7d`

### Layer 2: VolEnvironment

단기(7일) vs 중기(20일) realized vol 비교로 레벨과 방향을 산출합니다.

| 레벨 | 기준 |
|---|---|
| High | rv_now ≥ 60일 q67 |
| Low | rv_now ≤ 60일 q33 |
| Mid | 그 사이 |

방향(rising/falling/stable): `rv_short_7d / rv_now` 비율. 1.15 이상 → rising, 0.85 이하 → falling.

### Layer 3: SignalConfidence

overlay gate 결과와 현재 regime을 결합해 신호 신뢰도를 판단합니다.

| 신뢰도 | 조건 |
|---|---|
| **HIGH** | overlay_gate == promote AND 긍정 사유 ≥ 2 AND 부정 사유 == 0 |
| **MEDIUM** | 긍정 사유 ≥ 1 AND 부정 사유 ≤ 1 |
| **None** | BullHeated/Choppy regime, 또는 조건 미달 |

긍정 사유: `vol_regime_v2_promoted`, `vol_quiet`, `funding_normal`, `fng_contrarian`
부정 사유: `regime_unfavorable`, `vol_elevated`, `funding_overheated`

### to_dict() 출력 (latest.json riskOverlay 필드)

```json
{
  "regimeState": "BullQuiet",
  "regimeDescription": "안정 상승 — 신호 우호적",
  "regimeRaw": {
    "vix_now": 16.4, "vix_q80": 22.1, "vix_q40": 17.3,
    "rv_now": 0.41, "rv_q45": 0.48,
    "funding_zscore": 0.3, "fng": 52.0, "oi_divergence_flag": 0
  },
  "volLevel": "Low",
  "volTrend": "falling",
  "volDescription": "변동성 낮음, falling",
  "signalConfidence": "HIGH",
  "signalReasons": ["vol_regime_v2_promoted", "vol_quiet", "funding_normal"],
  "signalReasonLabels": ["vol_regime_v2 overlay gate 통과", "변동성 안정 구간", "자금조달 비율 정상"],
  "overlayGateDecision": "promote"
}
```

---

## 2. Market Packet 상세

### 2.1 거시 지표 (`packet["macro"]`)

| canonical_key | 지표 | 1차 소스 | 폴백 |
|---|---|---|---|
| `us10y` | 미국 10년 국채 금리 | FRED `DGS10` | yfinance `^TNX` |
| `us2y` | 미국 2년 국채 금리 | FRED `DGS2` | — |
| `dxy` | 달러 인덱스 | FRED `DTWEXAFEGS` | yfinance `DX=F` |
| `vix` | VIX | FRED `VIXCLS` | yfinance `^VIX` |
| `hy_spread` | 하이일드 스프레드 | FRED `BAMLH0A0HYM2` | — |

### 2.2 비트코인 (`packet["bitcoin"]`)

```python
{
    "spot": MarketPoint,          # BTC 현물
    "etf_points": [MarketPoint],  # display-only
    "fear_greed_value": int,      # 0~100
    "fear_greed_label": str,
    "official_etf_snapshots": [...],
    "official_etf_total_btc": float,
    "official_etf_total_aum_usd": float,
}
```

`MarketPoint.__dict__` 공통 필드:
```python
{
    "label": str, "ticker": str,
    "price": float | None,
    "change_pct": float | None,
    "resolved_value": float | None,   # btc_price_open 추출에 사용
    "validation_status": str,          # ok / missing / anomaly / previous_value
}
```

---

## 3. News Packet 상세

### 3.1 수집 우선순위

| 순서 | 소스 | 역할 |
|---|---|---|
| 1 | CoinDesk API | BTC 전문 뉴스 (기본) |
| 2 | Grok 공식 X 시그널 | 정책 기관·ETF 운용사 시그널 |
| 3 | Perplexity Sonar | 토픽별 구조화 요약 |
| 4 | Grok X 키워드 검색 | 시장 반응 시그널 |
| 5 | Gemini Grounding | fallback |
| 6 | Legacy (RSS + NewsAPI) | 품질 미달 시 보충 |

---

## 4. 최종 Packet 구조 요약

OpenAI 프롬프트 + 이메일 렌더링에 전달되는 `packet` dict 전체 키:

```python
packet = {
    # 시장 데이터
    "generated_at_utc": str,
    "macro": [MarketPoint],
    "korea_watch": [MarketPoint],
    "us_indices": [MarketPoint],
    "tech_stocks": [MarketPoint],
    "bitcoin": { ... },
    "data_footer_notes": [str],

    # 뉴스 데이터
    "news": [NewsItem as dict],

    # 보강 데이터 (조건부)
    "topic_summaries": { ... },        # Sonar 요약
    "x_market_signals": [ ... ],       # X 시그널
    "sonar_context": { ... },          # Sonar 맥락 보강
    "web_search_references": [str],    # OpenAI web_search 백필 시

    # Risk Overlay (Sentiment Join 결과)
    "risk_overlay": {                  # _load_risk_overlay() → latest.json
        "regimeState": str,
        "regimeDescription": str,
        "regimeRaw": dict,
        "volLevel": str,
        "volTrend": str,
        "volDescription": str,
        "signalConfidence": str | None,
        "signalReasons": [str],
        "signalReasonLabels": [str],
        "overlayGateDecision": str,
    },

    # 트랙레코드 (Supabase 설정 시)
    "signal_track_record": {
        "signal_count": int,      # 신호 있었던 날 수
        "hit_count": int,         # 적중 수
        "hit_rate": float | None, # 최근 90일 적중률
        "days_evaluated": int,    # 평가된 날 수
    },

    # Sentiment Join 인텔리전스
    "sentiment_intelligence": { ... },

    # 품질 메타
    "data_quality": {
        "status": "ok" | "degraded" | "critical",
        "warnings": [str],
        ...
    },
}
```

---

## 5. 신호 기록 흐름 (signal_log)

```
이메일 발송 시도 후 (성공·실패 무관)
    │
    ├─ risk_overlay 있음 AND SUPABASE_URL 설정됨
    │   → log_signal() → Supabase signal_log upsert
    │       (signal_date, regime_state, vol_level, vol_trend,
    │        overlay_decision, confidence, reasons: list,
    │        btc_price_open)
    │
    └─ fill_signal_outcomes.py (파이프라인 성공 후 별도 스텝)
        signal_date + 7 <= today AND btc_price_7d IS NULL 인 행 조회
        → yfinance BTC-USD 7일 후 가격 수집
        → btc_price_7d, ret_7d, hit 업데이트
```

`hit = True`: 신호 있는 날(confidence != null), 7일 후 BTC 수익 > 0 (long-only 가정)

---

## 6. 이메일 신호 블록 렌더링

`emailer.py → _build_signal_block(packet)` → `signal_block` dict → `email_signal.html.j2`

```
BTC 신호 신뢰도
├─ 시장 상태: 🟢 안정 상승 — 신호 우호적     ← RegimeState (항상)
├─ 변동성: 변동성 낮음 ↓                      ← VolEnvironment (항상)
├─ 오늘의 신호: ⚡ 신호 신뢰도 높음           ← SignalConfidence (조건부)
│   - vol_regime_v2 overlay gate 통과
│   - 변동성 안정 구간
│   - 자금조달 비율 정상
└─ 최근 90일 적중률: 63% (12회 신호)          ← signal_track_record (Supabase)
```

신호 없는 날: "오늘은 신호 없음 — Choppy 구간으로 관망 권고"

---

## 7. 데이터 특성 및 갱신 주기

| 데이터 | 갱신 주기 | 활용 |
|---|---|---|
| 거시 지표 6종 | 실시간~1일 | 추세 분석 |
| 미국 지수 3종 | 실시간 | 섹터 비교 |
| 빅테크 10종 | 실시간 | 모멘텀 스크리닝 |
| BTC 현물 + ETF | 실시간 | 유동성 분석 |
| BTC ETF 공식 보유량 | 1일 | 기관 자금 흐름 |
| Fear & Greed | 1일 | 센티먼트 지표 |
| Risk Overlay (RegimeState) | 1일 (Sentiment Join) | 시장 구조 판단 |
| Risk Overlay (SignalConfidence) | 1일 | 신호 신뢰도 판단 |
| 신호 트랙레코드 | 7일 후 자동 채워짐 | 신호 적중률 통계 |
| Sonar 토픽 요약 | 실행 시 | 토픽별 요약 |
| X 시장 시그널 | 실행 시 | 실시간 반응 |
