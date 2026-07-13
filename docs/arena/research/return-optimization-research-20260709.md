# 수익률 극대화 리서치 & 개선 계획 (2026-07-09)

> **성격**: 코드 수정 없는 리서치 기반 계획 문서. 현재 아레나(arena-spot-v4 / arena-params-v26 /
> arena-features-v8 / portfolio-risk-v2) 수집·분석·분류 로직의 각 레이어를 최신 논문·오픈소스와
> 대조해 개선 후보를 우선순위화한다. 모든 후보는 **기존 검증 파이프라인**(macro 백필 백테스트
> `scripts/analysis/backtest_with_macro_backfill.py` + walk-forward wf-v1)으로 검증 후 채택한다.

---

## 0. 요약 (TL;DR)

| 순위 | 개선 후보 | 대상 레이어 | 기대효과 | 코드량 | 근거 강도 |
|---|---|---|---|---|---|
| P1 | 통계적 점프모델(SJM) 레짐 분류 | `regime.py` (전 알고 공유 게이트) | 레짐 오분류 감소 → 전 알고 개선 | 중 | ★★★ (피어리뷰 + 전용 오픈소스) |
| P2 | 검증 인프라 강화: DSR·PBO·CPCV | 파라미터 튜닝 전반 | 과적합 손실 방지 (방어적 수익) | 소 | ★★★ (업계 표준) |
| P3 | 변동성 추정기 교체 (6봉 → EWMA/블렌드) | `execution_rules.py` 사이징 | 사이징 노이즈 감소 → MaxDD 개선 | 소 | ★★★ (Moreira-Muir 계열) |
| P4 | 메타라벨링 (2차 필터 모델) | 전 알고 진입 필터/사이징 | 승률·정밀도 향상, 저품질 진입 차단 | 대 | ★★☆ (실증 혼재, 방법론 확립) |
| P5 | 거래소 넷플로우 피처 (기존 TODO 승격) | `sources/exchange_outflow.py` | 신규 예측 피처 (USDT 유입 → BTC 수익 예측) | 중 | ★★☆ (2024-25 실증) |
| P6 | 시간대 시즌럴리티 게이트 | 진입 타이밍 (신규 소형 게이트) | 진입 품질 개선 (Monday Asia open 등) | 소 | ★★☆ (2025 실증, 소멸 리스크) |
| P7 | FNG 지속기간(persistence) 피처 | `fng_contrarian` 품질 게이트 | 역발산 진입 품질 향상 | 소 | ★★☆ |
| P8 | 섀도우 전용: MAB 자본 배분 메타레이어 | 리서치 슬리브 | 장기 제품 확장 (독립 트랙레코드와 충돌 주의) | 중 | ★☆☆ |

**하지 않을 것**: 4h→고빈도 전환(비용 구조 불리·기존 frequency-research 결론 유지),
가격손절 재도입(fng — Kaminski·Lo 근거 유지), 단일 백테스트 성능만 보고 파라미터 추가 튜닝
(P2 인프라 없이 튜닝 횟수만 늘리면 DSR 관점에서 기대 OOS 성과가 오히려 하락).

---

## 1. 방법론

2026-07 기준 웹 리서치로 다음을 조사: (a) 크립토 추세추종·평균회귀 최신 논문(arXiv/피어리뷰),
(b) 레짐 분류 방법론, (c) 백테스트 과적합 통제, (d) 파생상품·온체인 피처 예측력 실증,
(e) 재사용 가능한 오픈소스. 각 후보는 **현재 코드의 구체 지점**에 매핑하고, 기존
live·backtest 패리티 원칙(공유 순수함수)을 유지하는 방향으로만 제안한다.

현재 시스템에서 이미 논문 근거가 반영된 부분(변경 불필요 확인):
- 래칫 트레일링 스톱 ATR×2.5 — [arXiv 2602.11708](https://arxiv.org/html/2602.11708v1) plateau [2.0, 3.5] 내
- 현물 gross ~70% 상한 — 동일 논문
- fng 가격손절 제거 + 시간손절 — Kaminski·Lo, Alvarez 계열과 일치
- MA200 구조 게이트 — Faber(2007), Moskowitz et al.(2012) TSMOM
- FNG 역발산 자체 — 2023-25 실증들이 buy-and-hold 대비 우위 확인
  ([Bitcoin Magazine 백테스트](https://bitcoinmagazine.com/markets/how-a-bitcoin-fear-and-greed-index-trading-strategy-beats-buy-and-hold-investing) 등)

---

## 2. 개선 후보 상세

### P1. 통계적 점프모델(Statistical Jump Model) 레짐 분류 — 최우선

**현재**: `regime.py:classify_regime()` — 4개 지표(return_24h/72h, bb_width, EMA 정렬)의
하드코딩 AND 규칙. `unknown` 상태가 자주 발생해 매크로 오버레이 폴백에 의존하고,
경계 진동(whipsaw) 시 레짐이 4h마다 뒤집힐 수 있다. 레짐은 6개 알고 전부의 공유 게이트라
여기서의 오분류는 전 알고 성과에 전이된다 (vix_rsi v26 히스테리시스도 근본적으로는
레짐/신호 경계 진동 문제의 증상 치료).

**근거**:
- [Cortese, Kolm, Lindström (2023) "What drives cryptocurrency returns? A sparse statistical jump model approach"](https://link.springer.com/article/10.1007/s42521-023-00085-x) (Digital Finance, 피어리뷰) — 크립토 수익률에 3-state(bull/neutral/bear) SJM이 최적. 피처 선택+파라미터 추정+상태 분류를 동시 수행.
- [Shu & Mulvey (2024) "Downside Risk Reduction Using Regime-Switching Signals: A Statistical Jump Model Approach"](https://arxiv.org/html/2402.05272v2) — 점프 페널티가 상태 전환에 명시적 비용을 부과해 **HMM 대비 전환 빈도가 낮고 안정적** → 거래비용 절감·whipsaw 억제. 하락 리스크 축소 실증.
- JM은 HMM과 달리 다변량 피처셋 통합이 자연스러움 — 현재 이미 수집 중인 피처(FNG, VIX,
  funding z, breadth, stablecoin z, taker z)를 그대로 입력으로 활용 가능.

**오픈소스**: [`jumpmodels`](https://github.com/Yizhan-Oliver-Shu/jump-models) (Shu·Mulvey 저자 구현, PyPI, sklearn 호환 API). 순수 Python이라 EC2 의존성 부담 낮음.

**제안 설계** (검증 후 채택):
1. 일간 피처(이미 parquet에 있음)로 3-state SJM을 학습 → `regimeRaw`에 `sjm_state` 필드 추가
   (risk_overlay.py 산출 경로 재사용, None→graceful 원칙 유지).
2. arena에서는 **섀도우 필드**로 먼저 수집만 하고(라이브 게이트 미적용), 기존 rule 레짐과의
   불일치율·불일치 구간 성과 차이를 30일+ 축적 후 비교.
3. 승격 시 `_regime_state()` 폴백 체인에 SJM을 추가 (로컬 4h → SJM → 오버레이 순).
- 점프 페널티(λ)는 유일한 핵심 하이퍼파라미터 — P2의 DSR/CPCV로 선택해 과적합 방지.

**기대효과**: 레짐 오분류·whipsaw 감소는 전 알고 공통 개선. Shu·Mulvey에서 레짐 신호 기반
자산배분이 MaxDD 대폭 축소 실증. 아레나 최대 약점(하락장 역추세 롱 손실)에 직접 대응.

---

### P2. 검증 인프라: Deflated Sharpe Ratio · PBO · CPCV — 모든 후속 튜닝의 전제

**현재**: wf-v1 walk-forward(500/120/6 embargo)와 macro 백필 백테스트가 있으나,
**시도 횟수를 반영한 통계 보정이 없다**. v22 fng 튜닝(ts/mh 그리드), v26 vix_rsi 튜닝처럼
파라미터 탐색이 반복될수록 selection bias가 누적된다 — plateau 중앙값 채택은 좋은 휴리스틱이지만
정량 보정은 아니다.

**근거**:
- [Bailey & López de Prado — "The Deflated Sharpe Ratio"](https://www.researchgate.net/publication/286121118_The_Deflated_Sharpe_Ratio_Correcting_for_Selection_Bias_Backtest_Overfitting_and_Non-Normality) — 시도 횟수·비정규성 보정 후 Sharpe 유의성 검정.
- [Arian, Norouzi, Seco (2024) "Backtest overfitting in the machine learning era"](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110) — 합성 통제 환경에서 **CPCV가 walk-forward·K-fold 대비 PBO(백테스트 과적합 확률)와 DSR 통계 모두 우수**.
- [arXiv 2512.12924 "Interpretable Hypothesis-Driven Trading: A Rigorous Walk-Forward Validation Framework"](https://arxiv.org/html/2512.12924v1) — 가설 주도 + 엄격한 WF 검증 프레임 최신 사례.

**제안**:
1. `scripts/analysis/`에 검증 유틸 추가: 튜닝 그리드 결과 → DSR·PBO 산출 리포트.
   (오픈소스 참고: Hudson & Thames mlfinlab 계열, [mlfinpy](https://mlfinpy.readthedocs.io/en/latest/Labelling.html) — 구현은 수식 기준 자체 작성이 가벼움)
2. 신규 파라미터 채택 기준을 명문화: "plateau 중앙값 + DSR > 0.95 신뢰 + PBO < 0.2" 등.
3. wf-v1에 CPCV 모드 추가 검토 (기존 embargo 설계 재사용).

**기대효과**: 직접 수익 창출이 아니라 **미래의 과적합 손실 방지**. 튜닝 사이클이 v22→v26처럼
계속되는 프로젝트 특성상 누적 기대값이 가장 큰 투자.

---

### P3. 변동성 추정기 개선 — 6봉 realized vol은 너무 노이지

**현재**: `combined_position_weight()`의 `realized_vol_24h` = **직전 6봉(24h)** 로그수익률
표준편차. 표본 6개의 표준편차는 추정 분산이 극도로 커서, 사이징이 최근 몇 봉의 우연에
좌우된다 (저변동 착시 → 과대 사이징 → 다음 봉 손실 확대).

**근거**:
- [Moreira & Muir (2017) "Volatility-Managed Portfolios"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2659431) (JF) — 변동성 타깃의 원 근거. 단, 효과는 변동성 **예측 품질**에 의존.
- [크립토 모멘텀 변동성 관리 실증 (FMPM 2025)](https://link.springer.com/article/10.1007/s11408-025-00474-9) — 변동성 관리가 크립토 모멘텀 크래시 완화에 유효.
- [Cederburg et al. "On the performance of volatility-managed portfolios"](https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X) (JFE) — 나이브 구현은 효과가 불안정하다는 반증 → 추정기 품질이 관건이라는 방증.
- 표준 관행: EWMA(RiskMetrics λ≈0.94) 또는 단기/중기 블렌드가 소표본 표준편차보다 안정적.

**제안** (순수함수 1개 추가·플래그 게이트, live/backtest 패리티 용이):
1. `indicators.py`에 EWMA 변동성(또는 6봉/30봉 블렌드 `max(short, λ·long)`) 추가.
2. 백테스트로 기존 6봉 방식과 A/B: 종가자산·MaxDD·사이징 분포(가중치 히스토그램) 비교.
3. 보수 원칙: **max(단기, 블렌드)** 로 축소 방향 우선 적용하면 무회귀에 가깝게 도입 가능.

**기대효과**: 거래당 위험 1.5% 균질화의 실제 달성도 향상. MaxDD 축소 예상. 코드량 대비
효율 최상급.

---

### P4. 메타라벨링 — 6개 알고의 진입 신호에 2차 확률 필터

**현재**: 각 알고는 규칙 통과 시 무조건 진입(사이징만 변동성/리스크 타깃). 진입 후 결과와
진입 시점 피처(`signal_reason.inputs`에 이미 16+ 피처 저장 중)의 관계를 학습하는 레이어가 없다.

**근거**:
- [Singh & Joubert "Does Meta-Labeling Add to Signal Efficacy?"](https://hudsonthames.org/wp-content/uploads/2022/04/Does-Meta-Labeling-Add-to-Signal-Efficacy.pdf) — 1차 신호 위에 "이 신호가 맞을 확률"을 예측하는 2차 모델 → 정밀도 향상·저신뢰 거래 필터링·확률 기반 사이징.
- 라벨링은 고정수평선보다 [triple barrier / trend-scanning](https://grokipedia.com/page/Triple-barrier_labeling)이 우수 — [최근 비교 실증](https://www.mql5.com/en/articles/19253)에서 trend-scanning이 Sharpe +37% 개선, 고정 수평선은 일관되게 열화.
- 아레나는 이미 트레일링/시간손절 구조라 triple barrier 라벨과 자연 정합 (배리어 = 실제 청산 규칙).

**현실 제약(중요)**: 라이브 트레이드 표본이 아직 적다(알고당 수십 건). ML 2차 모델의
정직한 학습에는 수백 건+ 필요 →
1. **지금**: macro 백필 백테스트로 라벨 데이터셋 생성 파이프라인만 구축 (트레이드 → 피처 + triple-barrier 라벨).
2. **중기**: 로지스틱 회귀 수준의 저용량 모델로 시작 (피처 5~8개, CPCV 검증) — v23/v26에서
   수동으로 발견한 패턴("MACD hist 악화 중 진입이 손실 집중")이 바로 메타라벨링이 자동으로
   찾아야 할 종류의 규칙이며, 이미 2건이 수동 검증됐다는 것 자체가 이 방향의 유효성 증거.
3. **채택 형태**: 확률 < 임계 시 진입 보류(veto)부터. 확률 비례 사이징은 그 다음 단계.

**기대효과**: 승률·정밀도 개선. 단 표본·과적합 리스크가 커서 P1~P3 이후 착수 권장.

---

### P5. 거래소 넷플로우 피처 — 기존 TODO의 근거 보강 및 우선순위 승격

**현재**: `sources/exchange_outflow.py` 스캐폴딩만 존재 (CLAUDE.md 다음 작업 1번).
API 제공자 미결정 상태로 정체.

**근거 (신규)**:
- [arXiv 2411.06327 "Return and Volatility Forecasting Using On-Chain Flows in Cryptocurrency Markets"](https://arxiv.org/pdf/2411.06327) — **USDT 거래소 순유입이 BTC·ETH 수익률을 다구간에서 양(+)으로 예측** (buy-side liquidity 지표). BTC 자체 유출입보다 스테이블코인 유입의 예측력이 명확.
- 이는 현재 `stablecoin_supply_zscore`(공급 증가율)와 다른 신호 — 공급은 발행량, 넷플로우는
  **거래소로의 이동**(실제 매수 대기 자금). 상호 보완적.

**제안**:
1. 구현 우선순위를 "BTC 거래소 유출"보다 **"스테이블코인 거래소 순유입"** 으로 조정
   (논문 실증이 더 강한 쪽). 무료 소스 검토: DefiLlama(이미 사용 중), Glassnode 무료 티어 한계 확인.
2. regimeRaw에 `stablecoin_exchange_netflow_z` 추가 (lag1, 롤링 z — 기존 패턴 그대로).
3. 1차 활용: multi_factor·fng_contrarian의 **양방향** 신호 — 유입 급증 시 veto 해제 조건 완화
   / 유출 급증 시 veto. 백테스트 검증 후 임계 결정.

---

### P6. 시간대 시즌럴리티 게이트 — 소형·저위험

**현재**: 4h 봉마다 균일하게 진입 판정. 시간대(UTC hour/요일) 정보 미사용.

**근거**:
- [Concretum Group "Seasonality in Bitcoin Intraday Trend Trading" (2018–2025)](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/) — **"Monday Asia Open Effect"**: 일요일 저녁(NY)~월요일 아시아 개장 구간에 추세추종 성과가 뚜렷하게 집중.
- [Intraday and daily dynamics of cryptocurrency (2024, ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S1059056024006506) — US 장중 시간대에 유동성·스프레드 최적, 21:00–23:00 UTC 수익 집중.
- 주말: 거래량·유동성 저하 → 슬리피지 비용 상승 구간.

**제안** (순수함수 + parameters 플래그, 코드량 최소):
1. 우선 **진단만**: 기존 라이브·백테스트 트레이드를 진입 UTC hour·요일별로 성과 분해하는
   분석 스크립트 (`scripts/analysis/`). 데이터는 이미 전부 있음.
2. 유의미한 패턴 확인 시(예: 주말 진입 열위) 알고별 진입 허용 시간창 게이트를 백테스트 검증.
3. 주의: 시즌럴리티는 소멸(arbitraged away) 리스크가 커서 **약한 사이징 조정**(예: 열위
   시간대 ×0.7)이 hard veto보다 강건.

---

### P7. FNG 지속기간 피처 — fng_contrarian 품질 게이트 보강

**현재**: FNG 스냅샷 값(<30)만 사용. 공포가 **며칠째인지**는 미사용.

**근거**: [실증 리뷰](https://www.ainvest.com/news/navigating-crypto-fear-greed-index-strategic-entry-points-fear-dominated-market-2601/)들에서 **지속된 극단 공포(예: 15 미만 30일+)가 이후 6–12개월 강세를 선행**하는 패턴이 사이클마다 반복. 단발 공포(뉴스 쇼크)와 소진된 공포(캐피출레이션 후)는 평균회귀 품질이 다르다 — 현재 v23 안정화 게이트(MACD hist 반등)와 같은 문제의식의 일간 버전.

**제안**: parquet에 `fng_days_below_30`(연속 일수) 파생 컬럼 추가 → regimeRaw 노출 →
fng_contrarian에서 "지속일수 ≥ N일 시 사이징 상향 / 1일차는 표준" 형태의 소프트 게이트를
백테스트 검증. FNG 히스토리는 이미 전량 보유라 수집 작업 없음.

---

### P8. (섀도우 전용) MAB 자본 배분 메타레이어 — 장기

**현재**: 알고별 독립 $1,000 경쟁 (portfolio-risk-v2의 제품 핵심 = 투명 독립 트랙레코드).

**근거**: [Strategy Selection Using Multi-Armed Bandit Algorithms in Financial Markets](https://www.researchgate.net/publication/385097222_Strategy_Selection_Using_Multi-Armed_Bandit_Algorithms_in_Financial_Markets), [Bandit Networks for Portfolio Optimization (arXiv 2410.04217)](https://arxiv.org/html/2410.04217v2) — 온라인 학습으로 성과 좋은 전략에 자본을 동적 이동.

**주의**: 독립 트랙레코드 원칙과 정면 충돌하므로 **라이브 계정에는 적용하지 않는다**.
"6개 알고를 부분 배분하는 가상 메타 포트폴리오"를 7번째 섀도우 트랙으로만 운영 —
제품 관점에서 "당신이 이 대시보드를 보고 자본을 배분했다면"이라는 스토리 소재이자,
향후 실계좌 전환 시의 배분 로직 사전 검증.

---

## 3. 로드맵

```
Phase A (즉시, 코드량 소 · 무회귀 우선)
  A1. P6-진단: 시간대/요일 성과 분해 스크립트 (데이터 보유, 분석만)
  A2. P2: DSR·PBO 유틸 + 파라미터 채택 기준 명문화
  A3. P3: EWMA/블렌드 변동성 백테스트 A/B

Phase B (2~4주 지평)
  B1. P1: jumpmodels로 SJM 오프라인 학습 → regimeRaw 섀도우 필드 배선
  B2. P7: fng_days_below_30 파생 + 백테스트
  B3. P5: 스테이블코인 거래소 넷플로우 소스 조사 → 구현
  B4. P4-준비: macro 백필 백테스트 → triple-barrier 라벨 데이터셋 파이프라인

Phase C (30일+ 섀도우 축적 후 판단)
  C1. SJM 레짐 라이브 승격 여부 (불일치 구간 성과 비교)
  C2. P4: 저용량 메타라벨 모델 (로지스틱) + CPCV 검증
  C3. P6: 시즌럴리티 소프트 사이징 게이트
  C4. P8: MAB 메타 포트폴리오 섀도우 트랙
```

각 단계 공통 채택 기준: (1) macro 백필 백테스트에서 대상 알고 개선 + 타 알고 무회귀,
(2) Phase A2 이후로는 DSR/PBO 통과, (3) None→graceful (새 피처 미수집 시 기존 동작 유지),
(4) live·backtest 공유 순수함수 패리티.

---

## 4. 참고 문헌 / 오픈소스 전체 목록

**레짐 분류**
- Cortese, Kolm, Lindström (2023), *What drives cryptocurrency returns? A sparse statistical jump model approach*, Digital Finance — https://link.springer.com/article/10.1007/s42521-023-00085-x
- Shu, Mulvey (2024), *Downside Risk Reduction Using Regime-Switching Signals: A Statistical Jump Model Approach* — https://arxiv.org/html/2402.05272v2
- `jumpmodels` 패키지 — https://github.com/Yizhan-Oliver-Shu/jump-models
- *Dynamic Factor Allocation Leveraging Regime-Switching Signals* — https://arxiv.org/pdf/2410.14841

**검증/과적합**
- Bailey, López de Prado, *The Deflated Sharpe Ratio* — https://www.researchgate.net/publication/286121118
- Arian, Norouzi, Seco (2024), *Backtest overfitting in the machine learning era* — https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110
- *Interpretable Hypothesis-Driven Trading* (2025) — https://arxiv.org/html/2512.12924v1
- mlfinpy (라벨링·CPCV 구현 참고) — https://mlfinpy.readthedocs.io/en/latest/Labelling.html

**사이징/변동성**
- Moreira, Muir (2017), *Volatility-Managed Portfolios*, JF — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2659431
- Cederburg et al., *On the performance of volatility-managed portfolios*, JFE — https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X
- *Cryptocurrency momentum has (not) its moments* (FMPM 2025) — https://link.springer.com/article/10.1007/s11408-025-00474-9
- *Systematic Trend-Following with Adaptive Portfolio Construction* — https://arxiv.org/html/2602.11708v1 (현행 트레일링 스톱·70% 상한의 근거, 재확인)

**메타라벨링**
- Singh, Joubert, *Does Meta-Labeling Add to Signal Efficacy?* — https://hudsonthames.org/wp-content/uploads/2022/04/Does-Meta-Labeling-Add-to-Signal-Efficacy.pdf
- Triple-barrier labeling 개요 — https://grokipedia.com/page/Triple-barrier_labeling
- 라벨링 방법 비교 실증 (trend-scanning 우위) — https://www.mql5.com/en/articles/19253

**피처(온체인/파생/센티먼트)**
- *Return and Volatility Forecasting Using On-Chain Flows in Cryptocurrency Markets* — https://arxiv.org/pdf/2411.06327
- BIS WP 1270, *Stablecoins and safe asset prices* — https://www.bis.org/publ/work1270.pdf
- FNG 역발산 백테스트 — https://bitcoinmagazine.com/markets/how-a-bitcoin-fear-and-greed-index-trading-strategy-beats-buy-and-hold-investing

**시즌럴리티**
- Concretum Group, *Seasonality in Bitcoin Intraday Trend Trading* — https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/
- *Intraday and daily dynamics of cryptocurrency* (2024) — https://www.sciencedirect.com/science/article/pii/S1059056024006506
- *Turn-of-the-candle effect in bitcoin returns* — https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/

**자본 배분**
- *Strategy Selection Using Multi-Armed Bandit Algorithms in Financial Markets* — https://www.researchgate.net/publication/385097222
- *Improving Portfolio Optimization Results with Bandit Networks* — https://arxiv.org/html/2410.04217v2

**도구**
- vectorbt (대규모 파라미터 스윕 스크리닝용) — https://vectorbt.dev/
- NautilusTrader (실행 충실도 참고) — https://github.com/nautechsystems/nautilus_trader
