# Sovereign Index + Regime Signal — 부가가치 기준점 문서

**작성일**: 2026-05-07  
**기준 커밋**: `26fcc71` (fix: Sovereign Index labelKo 번역 맵 키 불일치 수정)  
**목적**: 향후 두 트랙 아키텍처의 부가가치를 입증하기 위한 "before" 기준점 기록

---

## 1. 두 트랙 아키텍처 개요

| 트랙 | 이름 | 역할 | 예측력 |
|---|---|---|---|
| Track A | Sovereign Sentiment Gauge | PCA 기반 0-100 시황 맥락 표시 | ❌ (시황 컨텍스트 전용) |
| Track B | Sovereign Regime Signal | vol_regime_v2 + RiskOverlay 방향성 예측 | ✅ (통계 검증 완료) |

두 트랙은 목적이 다르기 때문에 충돌하지 않고 상호 보완합니다.  
- Track A: "지금 시장 분위기가 어디쯤인가" (독자 맥락 제공)  
- Track B: "다음 7일 BTC 상승 확률이 통계적으로 높은가" (운영 신호)

---

## 2. Track A: Sovereign Sentiment Gauge 현황

### 구성 (2026-05-07)

**PCA Full Model** (8 features, explainedVariance=85.0%)

| Feature | PC1 Loadings |
|---|---|
| fng_value_lag1 | +0.484 (최강 기여) |
| news_sentiment_mean_lag1 | +0.476 |
| vix_regime_score_lag1 | +0.343 |
| funding_rate_lag1 | +0.289 |
| etf_net_inflow_usd_lag1 | +0.281 |
| vix_lag1 | −0.311 |
| btc_long_short_ratio_lag1 | −0.402 |
| volume_change_pct_lag1 | −0.009 (거의 무기여) |

**PC1 경제적 해석**: fng·뉴스감성(+0.48)이 높고 롱숏비·VIX(-0.40, -0.31)가 낮을수록 커지는 **BTC 시장 위험선호 복합 지수** — 낙관적 감성과 낮은 공포가 동시에 확인될 때 상승. (파이프라인이 매일 자동 생성: `sovereignIndex.pcInterpretation`)

**PCA Core Model** (4 features, explainedVariance=80.2%): fng, funding, news_sentiment, volume_change

### 생산 값 (2026-05-01 기준, R2 artifact에서 확인)

- `score`: 57.0
- `zone`: neutral
- `labelKo`: 중립
- `qualityStatus`: ok

### 한계

- PCA는 분산 극대화 목적이므로 수익률 예측력과 직접 관련 없음
- `_minmax_score()` 스케일링이 전체 히스토리 min/max 사용 → 룩어헤드 바이어스 잠재적 존재
- 단독으로는 운영 신호로 사용 불가

---

## 3. Track B: Sovereign Regime Signal — vol_regime_v2 통계

### 베이스라인 비교 (7일 horizon, 2026-05-07 latest.json 기준)

| 신호 | Hit Rate | Hit Rate CI | Sharpe | Coverage | Max DD |
|---|---|---|---|---|---|
| **vol_regime_v2** | **0.607** | 0.515 ~ 0.693 | **5.66** | 56.3% | **-0.64** |
| vol_regime | 0.548 | 0.478 ~ 0.628 | 2.50 | 97.9% | -1.87 |
| always_up | 0.518 | 0.431 ~ 0.599 | -0.66 | 98.7% | -4.33 |
| btc_momo_20d | 0.485 | 0.417 ~ 0.562 | 0.57 | 94.9% | -1.97 |
| fng_contrarian | 0.483 | 0.362 ~ 0.599 | -2.15 | 38.5% | -2.30 |

**vol_regime_v2가 모든 베이스라인 대비 최우수**:
- Hit Rate: +8.9pp 리드 (vs always_up)
- Sharpe: +3.2 리드 (vs vol_regime)
- Max Drawdown: 가장 낮음 (-0.64)

### Overlay Gate (promotionGate) 현황

```
decision: promote
nRecords: 22일치
rollingHitRate: 0.615
rollingCoverage: 0.562
rollingPMedian: 0.014
hitRateOk: true
coverageOk: true
pValueOk: true
message: "3개 rolling 기준 충족 — 승격 검토 가능"
```

- **60일 누적 확인 후 운영 적용 여부 결정** (현재 22일)
- CI가 분리되지 않아 `decision_strict: research_only` (BH 구조적 한계)
- Cost sensitivity: breakeven ~53.5 bps/leg (taker 7bps 대비 충분한 마진)

### 신호 메커니즘

vol_regime_v2는 순수 변동성 기반 신호로 감성 데이터 미포함:
- VIX < 90일 40분위 (저변동성 환경)
- BTC 실현변동성 20일 < 45일 45분위  
- → 두 조건 모두 충족 시 Long 포지션

---

## 4. 프론트엔드 노출 현황 (Before → After)

### Before (`26fcc71` 기준)

```
페이지 레이아웃:
 RiskOverlayPanel   → 별도 섹션 (시장 상태 | 변동성 | 오늘의 신호)
 SovereignIndexPanel → 게이지만 표시 (점수 57/100 | 구간 표시)
```

두 섹션이 시각적으로 분리되어 있어, 독자가 "두 트랙이 병렬로 존재한다"는 개념을 직관적으로 파악하기 어렵다.

### After (2026-05-07 구현 예정)

```
페이지 레이아웃:
 RiskOverlayPanel   → 유지 (상세 설명 역할)
 SovereignIndexPanel → 게이지 + 레짐 신호 푸터 추가
   ┌──────────────────────────────────────────────┐
   │  시황 게이지 (PCA)          현재 구간         │
   │  57 / 100                   중립 구간         │
   │  중립                       [GaugeBar]        │
   │                             [ZoneLegend]      │
   ├──────────────────────────────────────────────┤
   │  레짐 신호 (예측)   [안정 상승] [롱 활성] [검증됨] │
   └──────────────────────────────────────────────┘
```

SovereignIndexPanel이 두 트랙을 한 눈에 보여주는 통합 패널로 진화.

---

## 5. 향후 부가가치 측정 계획

### 단기 (30일)

- [ ] Overlay Gate 기록 계속 축적 (현재 22일 → 목표 60일)
- [ ] 신호 트랙레코드 7일 후부터 `hit` 필드 채워짐 시작
- [ ] `signal_log` Supabase 테이블에서 실적 집계

### 중기 (90일)

- [ ] vol_regime_v2 vs always_up 실적 비교 (90일 누적)
- [ ] Track A (Sentiment Gauge)와 Track B (Regime Signal) 상관관계 분석
  - 감성이 레짐 전환을 선행하는지 Granger 검정

### 입증 지표

| 지표 | 현재 기준 | 목표 |
|---|---|---|
| vol_regime_v2 실적 Hit Rate | 0.607 (backtest) | 실거래 60일 평균 > 0.55 |
| Overlay Gate p-value | 0.014 (22일) | 60일 후 p < 0.05 유지 |
| vs always_up 누적 수익 차이 | (측정 시작) | > +5pp |

---

## 6. 관련 파일

| 파일 | 역할 |
|---|---|
| `src/morning_brief/analysis/sentiment_join/hybrid_index.py` | Sovereign Gauge PCA 계산 |
| `src/morning_brief/analysis/sentiment_join/risk_overlay.py` | Regime Signal 계산 |
| `src/morning_brief/analysis/sentiment_join/baselines.py` | vol_regime_v2 신호 정의 |
| `src/morning_brief/analysis/sentiment_join/frontend_artifact.py` | 브리프 JSON 변환 |
| `frontend/components/brief/SovereignIndexPanel.tsx` | 시황 게이지 + 레짐 신호 표시 |
| `frontend/components/brief/RiskOverlayPanel.tsx` | 상세 리스크 오버레이 표시 |
| `data/sentiment_join/latest.json` | 최신 분석 결과 (로컬) |
