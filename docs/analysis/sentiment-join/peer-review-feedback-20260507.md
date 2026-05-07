# Peer Review 피드백 — Sovereign Index & Regime Signal

**수신일**: 2026-05-07  
**대응 커밋**: `feat/pca-oos-track-a` (2026-05-07)  
**대상**: `sovereign-regime-signal-baseline-20260507.md` 및 관련 파이프라인  
**상태**: 부분 해소 (1-2, 1-5, 1-6 구현 완료 / 1-1, 1-3, 1-4 잔여)

### 2026-05-07 대응 요약

| 항목 | 상태 | 구현 내용 |
|---|---|---|
| 1-5 PCA loading 해석 | ✅ 완료 | `_interpret_pca_loadings()` → `sovereignIndex.pcInterpretation` 필드, 패널 표시 |
| 1-6 OOS 분할 | ✅ 완료 | `compute_today_score_oos()` expanding window, `todayScoreMethod: "oos_expanding"` |
| 1-2 Baseline 비교 (Track A) | ✅ 완료 | `sovereign_gauge_60_long` predictor 추가, `trackAWfAvgHitRate` 패널 노출 |
| 1-1 Bootstrap CI | ⏳ 잔여 | 기존 구현(`evaluate_baseline` bootstrap) 있음, permutation test 미구현 |
| 1-3 Granger 절차 | ⏳ 잔여 | 문서화 필요 |
| 1-4 CryptoBERT 대안 | ⏳ 잔여 | 중기 로드맵 유지 |

---

## 1. 보완 요구사항

### 1-1. 통계적 파워 부족 (T+7 Hit Rate)

- Full 지수의 **23일 표본**으로 산출한 T+7 Hit Rate 65–68%는 통계적 파워가 매우 약하다.
- 현재 한계로 인지하고 있으나, **부트스트랩 신뢰구간** 또는 **무작위 순열 기반 유의성 검정(permutation test)**이 제시되어 있지 않다.
- → 대응: bootstrap CI 및 permutation test 추가 구현 필요

### 1-2. Baseline 비교 누락

- "F&G 단독 지수", "단순 모멘텀", "감성 없는 PCA" 등과 비교해야 하이브리드 지수의 한계 이상의 부가가치를 입증할 수 있다.
- 현재 Track B(vol_regime_v2)는 baseline 비교가 있으나, **Track A(Sovereign Sentiment Gauge) 자체의 baseline 비교가 없다**.
- → 대응: `eval_voting_rules.py` 확장 또는 별도 비교 스크립트 작성

### 1-3. Granger 인과성 검정 절차 세부사항 누락

- **stationarity 처리** (차분 또는 로그 변환), **lag 길이 선택 기준** (AIC/BIC), **다중검정 보정** 등이 명시되지 않았다.
- 향후 Granger 검정 진행 시(`hybrid_index.py` + Track A/B 상관관계) 절차를 문서화해야 한다.
- → 대응: 검정 실행 시 전처리 절차 및 파라미터 선택 근거를 문서에 포함

### 1-4. FinBERT 도메인 미스매치 — 대안 검토 없음

- FinBERT의 crypto 도메인 미스매치를 한계로만 기록하고, **CryptoBERT** 또는 **도메인 특화 fine-tuning** 같은 대안 검토가 없다.
- → 대응: 비교 실험 계획 수립 (단기 우선순위는 낮으나 중기 로드맵에 포함)

### 1-5. PCA 첫 주성분 Loading 해석 불완전

- `sovereign-regime-signal-baseline-20260507.md` 섹션 2에 PC1 loadings 표가 있으나, **경제적 해석이 명시적으로 기술되지 않았다**.
- "하이브리드 지수의 의미"가 블랙박스로 남아 있음.
- → 대응: Top loading 3–5개의 부호·크기를 바탕으로 한 문장 해석 추가
  - 현재 로딩 기준 잠정 해석: "PC1은 BTC 시장의 낙관적 분위기(fng↑, news_sentiment↑)와 낮은 공포(vix↓, long_short_ratio↓)가 결합될수록 높아지는 '위험 선호' 복합 지표"

### 1-6. In-sample / Out-of-sample 분할 미기술

- Hit Rate 65–68%가 **walk-forward 결과인지 in-sample fit인지** 확인 불가.
- 현재 `_minmax_score()` 스케일링이 전체 히스토리 min/max 사용 → 룩어헤드 바이어스 가능성 이미 인지됨.
- → 대응: 데이터 분할 방식을 명시하고 walk-forward 검증 여부를 문서에 기재

---

## 2. 미답 질문 목록

> 향후 답변 작성 또는 구현으로 해소해야 할 질문들

| # | 질문 | 관련 보완사항 | 우선순위 |
|---|---|---|---|
| Q1 | T+7 Hit Rate 65–68%는 어떤 baseline 대비인가? F&G 단독 또는 단순 5일 모멘텀과 비교 시 McNemar 검정 또는 bootstrap CI로 우위가 유의한가? | 1-1, 1-2 | 높음 |
| Q2 | Granger 인과성 검정에서 stationarity는 어떻게 확보했는가? 가격 → 차분 수익률, 감성 → 원시값 사용 여부 및 정확한 변환 절차 | 1-3 | 높음 |
| Q3 | PCA 첫 주성분에서 각 피처(news_sentiment, F&G, btc_return, funding_rate, vix, usdkrw_return)의 loading 분포는? Core 하이브리드 지수의 경제적 의미를 한 문장으로 설명한다면? | 1-5 | 중간 |
| Q4 | Winsorize(0.01~0.99 capping) 도입 시 2022년 5월 Luna 사태 같은 진짜 시장 충격 신호까지 절단할 위험을 어떻게 다룰 계획인가? | — | 중간 |
| Q5 | Hit Rate 65–68%가 walk-forward 검증 결과인지, in-sample fit 수치인지? 365일 표본의 in-sample / out-of-sample split 구성은? | 1-6 | 높음 |
| Q6 | 단기 트레이딩 보조지표 활용 결론에서, 실제 백테스팅 시 거래비용·슬리피지 반영 후 alpha가 유의한지 확인할 계획이 있는가? | — | 중간 |

---

## 3. 대응 로드맵 (우선순위 순)

### 단기 (2주 이내)

- [x] **Q5 해소**: `compute_today_score_oos()` expanding window 구현. 파이프라인 다음 실행부터 `todayScoreMethod: "oos_expanding"` 기록. 관련 파일: `hybrid_index.py`, `pipeline.py`
- [x] **1-5 해소**: `_interpret_pca_loadings()` → `sovereignIndex.pcInterpretation` 필드 추가. 패널에 "PC1: fng·뉴스감성 강세, 롱숏비 완화 주도의 위험선호 복합 지수" 표시. 관련 파일: `frontend_artifact.py`, `SovereignIndexPanel.tsx`
- [x] **Q1 부분 해소**: `sovereign_gauge_60_long` predictor 추가 (`baselines.py`, `statistical_tests.py`). Track A vs always_up/btc_momo_20d 비교 자동 산출. `trackAWfAvgHitRate`(55.8%, 13 folds) 패널 노출
- [ ] **Q1 완전 해소**: permutation test 미구현 — McNemar 또는 bootstrap pair test 추가 필요
- [ ] **Q2 해소**: Granger 검정 전처리 절차(차분, lag AIC/BIC, 다중검정 보정) 문서화

### 중기 (30–60일)

- [ ] **Q4 해소**: outlier capping 정책 재검토 — `outlier-policy-review-20260424.md` 업데이트
- [ ] **Q6 해소**: 비용·슬리피지 반영 백테스팅 추가 (`vol_regime_v2_cost_sensitivity.py` 확장)
- [ ] **1-4 해소**: CryptoBERT 비교 실험 계획 수립 및 feature-roadmap 반영

---

## 4. 관련 파일

| 파일 | 관련 사항 |
|---|---|
| `docs/analysis/sentiment-join/sovereign-regime-signal-baseline-20260507.md` | 피드백 대상 기준점 문서 |
| `docs/analysis/sentiment-join/outlier-policy-review-20260424.md` | Q4 winsorize 정책 |
| `src/morning_brief/analysis/sentiment_join/hybrid_index.py` | PCA loading 해석 (Q3) |
| `scripts/analysis/eval_voting_rules.py` | baseline 비교 확장 필요 (Q1) |
| `scripts/analysis/vol_regime_v2_cost_sensitivity.py` | 거래비용 반영 백테스팅 (Q6) |
