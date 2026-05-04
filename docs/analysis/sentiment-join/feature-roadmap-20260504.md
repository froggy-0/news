# Feature Roadmap — 복합 수급 인덱스 설계 (2026-05-04)

## 배경

### vol_regime_v2 Fold1 실패 진단 요약

4-fold time-series CV에서 Fold1(2024-11-18 ~ 2025-03-27)의 vol_regime_v2 HR=0.508로 동전 던지기 수준.
원인 분석 결과:

| 신호 × 레짐 | 일수 | HR | avg fwd_ret |
|---|---|---|---|
| SHORT + bull(MA200↑) | 37일 | 0.622 | -0.014 | ← 정상 |
| LONG  + bull(MA200↑) | 14일 | 0.357 | -0.011 | ← 실패 |
| SHORT + bear(MA200↓) | 10일 | 0.300 | +0.015 | ← 실패 |

**근본 원인**: vol_regime_v2는 변동성 *상태*를 측정하지, 방향성을 측정하지 않는다.
동일한 low-vol 조건이 "조용한 매집(상승 선행)"과 "조용한 분배(하락 선행)"를 구분하지 못한다.
MA200 필터는 이 문제를 해결하지 못함 (worst fold 0.508 → 0.333으로 악화).

### 전략 전환 배경

단일 feature 순차 검증 방식은 n=539 샘플에서 통계 파워 부족으로 BH 보정 통과 불가.
논문에서 검증된 지표들을 묶어 **복합 수급 인덱스** 하나로 만들고,
인덱스 단위로 ablation → vol_regime_v2와 조합 검증하는 방향으로 전환.

---

## 지표 목록 및 타당성 검토

### P0: PoC 즉시 착수

#### 1. `exchange_netflow_7d`
**의미**: 최근 7일 거래소 BTC 순유입(+)/순유출(-) 누적값.
순유출 지속 = 고래·기관의 자기 보관 이동 → 매집 신호.
순유입 지속 = 매도 준비 → 분배 신호.

**Fold1과의 연결**: low-vol 구간이 "조용한 매집인가, 조용한 분배인가"를 구분하는 가장 직접적인 on-chain 후보.
vol_regime_v2가 방향 정보 없이 vol state만 볼 때, 수급 방향을 보완한다.

**타당성**: ✅ 강함. Ki Young Ju(CryptoQuant), Glassnode 연구에서 반복 검증.
Exchange flow와 BTC 단기 수익률의 음의 상관은 선행 연구 다수.

**주의사항**: 거래소 분류 오류(custodial wallet 혼입), 데이터 제공자별 수치 편차.
절대값 기준이므로 시장 규모 변화에 취약 → zscore 버전과 반드시 병행.

**데이터 소스**: CryptoQuant (유료), CoinMetrics Community (무료, rate limit), Glassnode (일별 유료)
**우선순위**: P0-1

---

#### 2. `exchange_netflow_zscore_30d`
**의미**: exchange_netflow_7d의 최근 30일 기준 z-score.
"평소 대비 비정상적인 유입·유출인지"를 측정.

**Fold1과의 연결**: Fold1처럼 특정 regime에서 절대값이 아닌 *변화*가 방향 오류를 줄이는지 확인.
예: 평소엔 유입이 많은 거래소도 갑작스러운 유출 급증 = 매집 신호.

**타당성**: ✅ 우리 z-score 접근 방식과 일관성 있음.
`funding_rate_zscore_30d`, `btc_taker_imbalance_zscore_30d`와 동일 패턴.
선행 연구에서 abnormal flow가 normal flow보다 예측력 높다는 근거 존재.

**구현**: exchange_netflow_7d 수집 후 `shift(1).rolling(30, min_periods=20)` 적용.
신규 코드 최소화.

**우선순위**: P0-2 (exchange_netflow_7d와 동시 구현)

---

### P1: Taker flow (기존 구현 완료)

#### 3. `btc_taker_buy_ratio_7d`
**의미**: 최근 7일 Binance BTC 체결에서 공격적 매수 체결 비율.
taker buy = 매수자가 호가를 넘어 체결 → 즉각적 매수 압력 proxy.

**상태**: ✅ **이미 구현됨** (`join.py:383`, `validate.py:123`).
Binance klines index[10] 기반, 추가 API 호출 없음.

**타당성**: ✅ Kyle(1985) 이후 order flow imbalance 연구의 핵심 지표.
crypto에서는 Binance klines taker volume이 공개되어 있어 활용 용이.
low-vol 구간에서 실제 매수 압력 축적 여부를 직접 관찰 가능.

**주의사항**: 거래소 내부 체결 흐름이므로 on-chain flow와 방향이 다를 수 있음.
단독 신호로는 약함 (ablation HR=0.539, Sharpe=+0.67) → 인덱스 구성 요소로 활용.

**우선순위**: P1-1

---

#### 4. `btc_taker_imbalance_zscore_30d`
**의미**: taker buy ratio의 30일 z-score. 단순 비율보다 과열/침체 정도를 측정.

**상태**: ✅ **이미 구현됨** (`join.py:386`, `statistical_tests.py:49`).

**타당성**: ✅ z-score 정규화로 regime 변화에 강건.
vol2 AND 조합에서 HR=0.652 (최고치). 단, worst fold와 bootstrap CI 추가 확인 필요.

**우선순위**: P1-2

---

### P1: Market Breadth

#### 5. `binance_top10_up_ratio_7d`
**의미**: Binance 거래량 상위 10개 코인 중 최근 7일 수익률 양수 비율.
"몇 개가 올랐는지" → 상승 확산도(breadth).

**타당성**: ✅ Equity market에서 Advance-Decline ratio는 주요 breadth indicator로 검증됨.
Crypto에서 BTC 단독 상승이 altcoin 동반 없으면 단기 반전 가능성 높다는 논거 있음.
BTC만 보는 현재 파이프라인의 단일 자산 편향을 보완.

**주의사항**: "top10" 정의 필요 (시가총액 기준 vs Binance 거래량 기준).
분기별 구성 변경 처리 로직 필요.

**데이터 소스**: Binance `/api/v3/klines` (무료, 기존 인프라 재사용 가능)
**우선순위**: P1-3

---

#### 6. `binance_top10_equal_weight_return_7d`
**의미**: Binance top10 코인의 7일 수익률 단순 평균.
breadth가 "몇 개"라면, 이 지표는 "평균 강도".

**타당성**: ✅ #5와 직교하는 정보를 일부 제공.
BTC가 강한데 altcoin 전체가 약하면 선택적 자금 집중 → 다른 해석 필요.

**주의사항**: #5와 강한 상관 예상. PCA 후 독립 성분이 실제로 분리되는지 확인 필요.
인덱스에서 둘 다 포함 시 이중 계산 위험.

**우선순위**: P1-4

---

### P2: Macro Liquidity

#### 7. `stablecoin_total_supply_change_7d`
**의미**: USDT+USDC 발행량 7일 변화율. 스테이블코인 공급 증가 = crypto 내 달러 유동성 증가.

**타당성**: ⚠️ 중간. 개념적으로 타당하나 주의 필요.
- 공급 증가가 실제 매수로 이어지기까지 lag 불명확
- Tether 발행은 수요 선행이 아니라 거래소 입금 후 사후 발행 가능
- 선행 연구: Lyons & Viswanath-Natraj(2023) — stablecoin 공급과 BTC 가격 관계 혼재된 결과

**데이터 소스**: DefiLlama API (무료) 또는 CoinGecko
**우선순위**: P2-1

---

#### 8. `usd_broad_index_change_7d` (구 `dxy_change_7d`)
**의미**: DTWEXBGS(광의 달러지수) 7일 변화율. 달러 강세 = 위험자산 헤드윈드.
ICE DXY 대신 FRED DTWEXBGS 사용 — 교역 가중 광의지수로 더 포괄적.
`usd_broad_index_zscore_30d` (30일 z-score) 동시 파생.

**타당성**: ✅ 강함. 표준 macro factor.
BTC와 DXY의 음의 상관은 다수 논문에서 확인 (Bouri et al., Dyhrberg et al.).

**상태**: ✅ **구현 완료 (2026-05-04)**
- `sources/macro_history.py` — FRED DTWEXBGS 수집 (주별, 7일 ffill)
- `join.py::_add_macro_features()` — `usd_broad_index_change_7d`, `usd_broad_index_zscore_30d` + lag1 파생
- `validate.py::MASTER_SCHEMA` 등록 (`required=False`)
- **품질 검증**: 90일 기준 58 raw rows, ffill 후 NaN 3개(최신 미발표분), change_7d 범위 ±1.6%

**주의사항**: VIX와 부분 중복 (달러 강세 = 리스크 오프 = VIX 상승). 독립 기여 확인 필요.

**우선순위**: P2-2

---

#### 9. `nasdaq_return_7d`
**의미**: Nasdaq Composite 7일 수익률. BTC ETF 이후 BTC-equity 동행성 증가.

**타당성**: ✅ ETF 승인 이후(2024-01~) BTC와 Nasdaq 상관이 유의미하게 상승.
Yermack(1996) 이후 "BTC is uncorrelated with equities" 테제가 ETF 시대에 약화됨.
risk-on/risk-off 국면을 BTC 단독 지표보다 명확하게 구분 가능.

**상태**: ✅ **구현 완료 (2026-05-04)**
- `sources/macro_history.py` — FRED NASDAQCOM 수집 (일별, 2일 ffill)
- `join.py::_add_macro_features()` — `nasdaq_return_7d` + lag1 파생
- `validate.py::MASTER_SCHEMA` 등록 (`required=False`)
- **품질 검증**: 90일 기준 62 raw rows, ffill 후 NaN 3개, return_7d 범위 ±7.4%

**데이터 소스**: FRED (NASDAQCOM)
**우선순위**: P2-3

---

#### 10. `us10y_change_7d`
**의미**: 미국 10년물 국채 수익률 7일 변화. 금리 상승 = 위험자산 밸류에이션 압박.

**타당성**: ✅ 표준 macro factor.
금리 상승 구간에서 growth asset 전반에 부담. BTC도 예외 아님.
FRED DGS10 — 이미 구축된 인프라로 무료 수집 가능.

**상태**: ✅ **구현 완료 (2026-05-04)**
- `sources/macro_history.py` — FRED DGS10 수집 (일별, 2일 ffill)
- `join.py::_add_macro_features()` — `us10y_change_7d` + lag1 파생
- `validate.py::MASTER_SCHEMA` 등록 (`required=False`)
- **품질 검증**: 90일 기준 62 raw rows, ffill 후 NaN 3개, change_7d 범위 ±19bp

**주의사항**: 단기(7d) 변화는 노이즈가 크고, 수준보다 변화율이 더 예측력 있다는 근거 있음.
DXY와의 다중공선성 주의.

**우선순위**: P2-4

---

## 수집 가능성 요약

| # | Feature | 상태 | 소스 | 비용 | 난이도 |
|---|---|---|---|---|---|
| 3 | btc_taker_buy_ratio_7d | ✅ 구현됨 | Binance klines | 무료 | — |
| 4 | btc_taker_imbalance_zscore_30d | ✅ 구현됨 | Binance klines | 무료 | — |
| 8 | usd_broad_index_change_7d (+zscore) | ✅ 구현됨 (2026-05-04) | FRED DTWEXBGS | 무료 | — |
| 10 | us10y_change_7d | ✅ 구현됨 (2026-05-04) | FRED DGS10 | 무료 | — |
| 9 | nasdaq_return_7d | ✅ 구현됨 (2026-05-04) | FRED NASDAQCOM | 무료 | — |
| 7 | stablecoin_supply_change_7d | — | DefiLlama | 무료 | 낮음 |
| 5 | binance_top10_up_ratio_7d | — | Binance API | 무료 | 중간 |
| 6 | binance_top10_ew_return_7d | — | Binance API | 무료 | 중간 |
| 1 | exchange_netflow_7d | 스캐폴딩 있음 | CryptoQuant/CoinMetrics | **유료** | 높음 |
| 2 | exchange_netflow_zscore_30d | 스캐폴딩 있음 | CryptoQuant/CoinMetrics | **유료** | 높음 |

---

## 복합 수급 인덱스 설계 방향

### 목표

10개 feature → 인덱스 1개 → vol_regime_v2 AND 인덱스 단위로 ablation.
개별 feature p-value 검증이 아니라 인덱스 레벨에서 HR/Sharpe/worst-fold 통과 여부로 판단.

### 구성 레이어

```
Layer 1 — On-chain 수급 (새로 수집)
  exchange_netflow_7d          → 방향성 신호
  exchange_netflow_zscore_30d  → 이상 감지

Layer 2 — 거래소 체결 흐름 (기존)
  btc_taker_buy_ratio_7d
  btc_taker_imbalance_zscore_30d

Layer 3 — Market Breadth (새로 수집)
  binance_top10_up_ratio_7d
  binance_top10_ew_return_7d

Layer 4 — Macro (새로 수집, FRED)
  dxy_change_7d
  nasdaq_return_7d
  us10y_change_7d
  stablecoin_supply_change_7d
```

### 합산 방식 후보

| 방식 | 장점 | 단점 |
|---|---|---|
| Equal weight | 단순, 과적합 없음 | 노이즈 feature 희석 안 됨 |
| PCA 1st component | 공통 분산 추출 | 경제적 해석 어려움 |
| 논문 weight (사전 정의) | 과적합 방지, 해석 가능 | 가중치 근거 필요 |
| Signal count (≥k/n 동의) | 직관적, robust | 임계값 설정 필요 |

**권장**: Signal count 방식 (n개 중 k개 동의) 우선. 논문 weight는 exchange outflow PoC 이후.

### 검증 기준 (pre-registration)

인덱스 채택 조건 (이 중 전부 충족):
- 전체 기간 HR ≥ 0.58 (vol_regime_v2 baseline 대비 +2%p 이상)
- 전체 기간 Sharpe CI 하한 > 0 (bootstrap 2000회, block=14)
- worst fold HR ≥ 0.50 (Fold1 포함, 동전 던지기 이상)
- coverage ≥ 20% (신호 희소성 방지)

---

## 실행 순서 (권장)

```
Sprint 1 (2026-05-04 완료):
  ✅ usd_broad_index_change_7d + zscore_30d  (FRED DTWEXBGS)
  ✅ us10y_change_7d                          (FRED DGS10)
  ✅ nasdaq_return_7d                         (FRED NASDAQCOM)
  → 품질 검증 통과 — 다음 단계: ablation (baseline 대비 HR/Sharpe/worst-fold 변화)
  [ ] stablecoin_supply_change_7d  (DefiLlama) — 미완
  [ ] binance_top10_up_ratio_7d, binance_top10_ew_return_7d  (Binance) — 미완

Sprint 2 (진행 예정): ablation + Layer 2+3+4 인덱스 PoC
  → 구현된 macro 3개 + taker 2개로 ablation 실행
  → baseline(vol_regime_v2) 대비 HR / net-Sharpe / worst-fold 변화 확인
  → stablecoin, binance_top10 수집 후 인덱스 구성
  → Fold1 포함 4-fold CV 검증

Sprint 3 (API 결정 후): exchange_netflow P1 PoC
  → CoinMetrics Community 또는 CryptoQuant 결정
  → exchange_netflow_7d, exchange_netflow_zscore_30d 추가
  → 최종 인덱스 재검증
```
