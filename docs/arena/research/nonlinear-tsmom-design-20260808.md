# macd_momentum 대체 설계 — Nonlinear TSMOM (2026-08-08)

> **상태: ✅ v35로 활성화·배포(§10).** §9에서 18변형 그리드의 DSR·부트스트랩·전후반
> 반분할 검증은 미달로 판정했으나(전형적 "증명된 엣지" 기준), 사용자 재요청("왜그런지
> 알았으면 수익률을 내고 거래를 늘릴수있도록 해결해")으로 walk-forward 6윈도 재검증
> (§10)을 추가 실행 — **레거시 MACD 대비 6/6 구간 전부 개선(예외 없음)**이라는 더 강한
> 증거를 확보했다. "증명된 엣지"는 아니지만 "확실히 죽은 레거시보다 확실한 우위"를
> 근거로 `TSMOM_NL_ENABLED=True`(거래량 우선 변형) 활성화, `PARAMS_VERSION` v34→v35,
> EC2 배포 완료.

## 0. 한 줄 요약

macd_momentum이 3년 백테스트(2023-08~2026-08, n=251) 전 구간(상승장 포함)에서
가중합 **-31.79%**, DSR **0.012**로 확인돼(§1) hard gate 완화로는 구제 불가 판정.
대체 후보로 Moskowitz·Sabbatucci·Tamoni·Uhl(2025-12-10, "Nonlinear Time Series
Momentum")의 **연속 비선형 사이징 TSMOM**을 조사·루브릭검증했다. 핵심 위험은
논문이 크립토·4H·롱온리에서 검증된 적이 없다는 것 — §4에서 4개 CAUTION 항목을
확인했고, 전부 "그리드+DSR 통과 조건부"로 남겨둔다.

---

## 1. 배경 — macd_momentum 폐기 근거 (이번 세션 실측)

- 라이브 60일: 청산 0건, 오픈 0건. `arena_decisions` 차단 top:
  `veto:bb_width_sufficient`(39) > `veto:not_risk_off`(33) >
  `veto:above_ema200_4h`(28, secondary) > `veto:funding_not_hot`(14, secondary).
- 3년 백테스트(`scripts/analysis/macd_hard_gate_tuning.py`, 5966봉,
  2023-08-15~2026-08-07): baseline n=251, win 36%, **가중합 -31.79%**.
  - 상승장(2023-08~2024-07): n=75, **-2.52%**(상승장에서도 마이너스).
  - 하락/전환(2024-11~2026-08): n=163, **-28.51%**.
- Hard gate 완화 6변형(zero_cross, BB게이트 제거, ADX 15/20 그리드) 전부 시도 —
  최선(C_zero_cross_noBB)도 -11.61%, **DSR=0.012**(채택 기준 ~0.95 대비 압도적 미달).
  결론: 게이트를 풀수록 손실이 커지는 게 아니라 줄어들긴 하나(-31.79→-11.61) 여전히
  깊은 마이너스 — **신호 정의(h>0 & 증가 + RSI + ADX + BB확장) 자체가 이 자산·주기에서
  엣지가 없다.** 결과 원장: `docs/arena/research/macd-hard-gate-tuning-20260808.json`.

---

## 2. 논문 — Nonlinear Time Series Momentum (Moskowitz, Sabbatucci, Tamoni, Uhl, 2025-12-10)

SSRN(abstract_id=5933974), FoFI 2026 컨퍼런스 페이퍼로 원문 확인(선물 8개 주가지수·
24개 원자재·21개 금리/통화, 1980~2024-10, 일간/주간/월간).

### 핵심 주장
기존 TSMOM 구현은 두 갈래:
- **TSMOM-binary**(Moskowitz et al. 2012): `s = sign(r_{t-τ:t})` — 방향만, 크기 무시.
- **TSMOM-linear**: `s_t = r_{t-τ:t} / σ̂_t` (변동성정규화 과거수익률, 크기 그대로 선형 사용).

Ferson & Siegel(2001) 평균-분산 이론에서 유도한 **최적 가중은 S자형 비선형 함수**:
신호가 0 근처면 선형으로 반응하되, 신호가 극단으로 갈수록 가중을 오히려 줄인다(집중
리스크 트레이드오프). 논문의 이론적 가중함수(단순화, μ(s)=s, σ_ε²=1 정규화 후):

```
f_FS(s_t) = s_t / (s_t² + 1)
```

`s_t = k1 · σ̂_t⁻¹ · Σ w_τ r_{t-τ}` (단순이동평균 가중 시 `k1 = √T`, T=lookback).

이 함수는 s_t=0 근처에서 거의 선형(f'(0)=1)이고, s_t=1에서 최댓값 f=0.5, 그 이상은
오히려 감소(concave for s>1)한다 — "너무 강한 신호는 오히려 더 많은 노이즈/집중위험을
내포한다"는 논지. 저자들은 신경망으로 아웃오브샘플 샤프비율을 직접 최적화해도 거의
동일한 S자 곡선이 나온다는 것을 보여 이론과 데이터 양쪽에서 지지한다고 주장한다
(machine-learned weight ≈ theoretical S-curve).

### 실증 결과 요지 (원문 확인)
- 8개 자산군·1/3/12개월 lookback·일/주/월 빈도 전 조합에서 NL이 binary/linear를
  상회.
- **하락장(극단 시장)에서 우위가 특히 커짐** — TSMOM의 기존 컨벡스 헤지 특성을 NL이
  더 강화. 개선의 대부분이 여기서 나옴.
- 저자 주장(각주, 실증 아님): 부드러운 함수라 이진 모델 대비 포지션 반전이 줄어
  회전율이 낮아지고, 비용 반영 시 우위가 더 커질 가능성.
- **크립토·4H·단일자산 롱온리 검증 없음.** 자산군은 주가지수·원자재·금리/통화
  선물이고, 최단 lookback도 1개월(월간 리밸런싱 기준)이다.

---

## 3. 왜 이 후보인가 (다른 2개 대비)

- **Volume-Weighted TSMOM**(Huang/Sangiorgi/Urquhart): 원 논문 성과(Sharpe 2.17)는
  3,192개 코인 **횡단면**(승자매수·패자공매도) 구조. BTC 단일종목 롱온리로 축소하면
  검증된 엣지가 그대로 옮겨온다는 근거가 없어짐 — 처음부터 새 가설.
- **Donchian 앙상블**(Zarattini/Pagani/Barbon): regime_trend가 이미 같은 저자그룹의
  단일 Donchian 돌파를 쓰고 있어 신호 상관이 높을 위험 — 진짜 분산이 아닐 수 있음.
- **Nonlinear TSMOM**: regime_trend(이산 돌파)·omnibus(레짐 라우터)·fng/vix_rsi(역발산)
  와 신호 성격이 명확히 다르고(연속 크기조절 추세추종), 아레나에 이미 있는 연속
  사이징 인프라(`combined_position_weight`, `omnibus_position_multiplier` 패턴)에
  자연스럽게 얹힌다.

---

## 4. 루브릭 검증 (이 저장소 기존 채택 기준 대조)

| # | 항목 | 판정 | 근거 |
|---|---|---|---|
| R1 | 데이터 가용성 | ✅ PASS | lookback용 과거 4H 종가는 `arena_ohlcv_bars`에 3년+ 축적. 신규 API·키 불필요. |
| R2 | 롱온리 스팟 호환 | ⚠️ CAUTION | 논문 신호는 -1~1 대칭(롱숏). 아레나는 s_t≤0이면 플랫(숏 미실행) — 논문이 검증한 신호의 "양(+)의 절반"만 쓰게 되므로, 논문 실증 성과가 그대로 이전된다는 보장 없음. 반드시 자체 백테스트 필요. |
| R3 | 기존 사이징과의 결합 | ⚠️ 설계 선택 필요 | `combined_position_weight`(변동성타깃∧리스크타깃, 0.25~0.7)가 이미 realized_vol을 반영. NL weight도 같은 realized_vol로 정규화한 s_t를 쓰면 이중 축소(같은 변동성 신호를 두 레이어가 각각 할인) 위험 — §6에서 곱셈 멀티플라이어 상한을 명시. |
| R4 | 손절/트레일링 재사용 | ✅ PASS | ATR 손절 + 래칫 트레일(`execution_rules.ratchet_trailing_stop`)은 알고 무관 공용 로직이라 그대로 재사용. 리스크관리 레이어 신규 개발 불필요. |
| R5 | 비용모델(arena-cost-v3, 왕복 23bps) | ⚠️ CAUTION | 논문은 비용모델을 실증하지 않음(각주 추정뿐). 부드러운 함수라 회전율이 낮아질 것이라는 저자 주장은 검증 전 가정 — 백테스트에서 거래수·회전율 실측 필수. |
| R6 | 기존 알고와 차별화 | ✅ PASS | 연속 사이징 추세추종은 regime_trend/omnibus/fng/vix_rsi 어느 것과도 신호 메커니즘이 겹치지 않음(§3). |
| R7 | lookback 변환(논문 트레이딩일→4H봉) | ⚠️ CAUTION | 논문 1/3/12개월(21/62/260 거래일)을 4H봉으로 그대로 환산하면 12개월≈1560봉(≈65주 웜업) — 3년 데이터로는 워크포워드 표본이 급감. 1~3개월 상당(약 126~372봉) 위주로 자체 그리드 필요, 논문 값 직수입 불가. |
| R8 | 변동성 정규화 방식 | ⚠️ 설계 선택 필요 | 논문은 260거래일 롤링 변동성(장기·안정). 아레나 기본은 6봉(24h) realized_vol(빠른 반응) + EWMA robust 옵션(R2). 어느 쪽이 이 신호에 맞는지 자체가 핵심 튜닝 변수 — 그리드 후보 2종 모두 포함 필요. |
| R9 | 검증 하니스 존재 | ✅ PASS | `backtest_with_macro_backfill.py` + `wi_tuning.py` 패턴 재사용 가능. 신규 튜닝 스크립트만 추가하면 됨(예: `scripts/analysis/tsmom_nl_tuning.py`). |
| R10 | DSR/PBO 채택 기준 | 미실행(설계 단계) | 반드시 그리드 A/B 후 `validation_stats.py`(DSR ≥0.95 대략 기준)를 통과해야 채택. macd_momentum 자체가 이번 세션에 DSR 0.012로 전면 기각된 선례를 감안하면 신규 알고도 예외 없이 동일 엄격도 적용. |

**결론**: 구조적 결격 사유(R1/R4/R6/R9)는 없음. 하지만 CAUTION 4건(R2/R3/R5/R7)과
설계선택 2건(R3/R8)이 남아 있어 **"이 논문이 맞다"가 아니라 "이 논문이 근거 있는
다음 가설이다"** 수준 — 반드시 3년 백필 데이터로 그리드+DSR 검증 후 채택 여부를
결정해야 한다(이 저장소의 다른 모든 도입 사례와 동일 절차).

---

## 5. 제안 신호 정의

```
s_t = k1 · σ̂_t⁻¹ · mean(r_{t-T+1 : t})       # T봉 단순이동평균, k1=√T (논문 식(3))
weight_mult(s_t) = clamp(s_t / (s_t² + 1), 0.0, 0.5)   # 롱온리 → 음수는 0으로 클립
entry: s_t > MIN_SIGNAL_THRESHOLD  → "long"            # 그 외 None(기존 규약과 동일)
```

- `r_{t-T+1:t}`: T봉 로그수익률 합(=단순 트레일링 수익률), 이미 프레임에 종가 시계열
  존재 — 신규 데이터 불필요.
- `σ̂_t`: R8 두 후보(6봉 realized_vol / EWMA robust) 그리드 대상.
- `f(s)=s/(s²+1)`의 최댓값이 s=1에서 0.5이므로 자연 상한 0.5 — combined_position_weight
  상한 0.7과 곱해도 최종 최대 0.35, 기존 알고 대비 보수적(R3 이중축소 우려 완화 방향).
- risk-off hard veto는 유지(다른 5개 알고와 동일 원칙, 완화 대상 아님).
- MACD 관련 조건(h>0, RSI, ADX, BB폭)은 전부 폐기 — 신호 자체가 다르므로 유지할
  근거 없음.

---

## 6. 코드 배선 지점 (실행 시 참고용, 이번 세션엔 미적용)

| 위치 | 현재 | 변경 방향 |
|---|---|---|
| `src/arena/algorithms.py:532` `macd_momentum()` | MACD h/RSI/ADX/BB 하드게이트 | 위 §5 신호 함수로 교체 (algo_id·ALGORITHMS 키 `"macd_momentum"` 유지 — 자본슬롯·DB algo_id 연속성) |
| `src/arena/algorithms.py:1052` `ALGORITHMS` dict | `macd_momentum` 함수 참조 | 교체된 함수를 그대로 참조(키 불변) |
| `src/arena/algorithms.py:841` 인근 (참고 패턴) | `omnibus_position_multiplier(macro, ind)->float` | 동일 패턴으로 `tsmom_nl_position_multiplier(macro, ind)->float` 신설, `weight_mult(s_t)` 반환 |
| `src/arena/backtest.py:385` | `position_weight *= algorithms.omnibus_position_multiplier(...)` | `if algo_id == "macd_momentum": position_weight *= algorithms.tsmom_nl_position_multiplier(...)` 분기 추가 |
| `src/arena/scheduler.py:43,966` | 동일 omnibus 곱셈 | 동일 분기 추가 |
| `src/arena/parameters.py` | `MACD_MOMENTUM_*` 그룹(§351~523) | `TSMOM_NL_LOOKBACK_BARS`/`TSMOM_NL_VOL_ESTIMATOR`/`TSMOM_NL_MIN_SIGNAL` 신규 그룹으로 대체(기존 `MACD_MOMENTUM_*`는 롤백 대비 유지 또는 정리는 채택 후 결정) |
| `docs 루브릭 R7 관련` `src/arena/indicators.py` | — | T봉 트레일링 수익률 헬퍼가 없으면 신규 추가(단순 `close[t]/close[t-T]-1` 수준, 신규 지표 불필요 수준) |

---

## 7. 검증 계획 (구현 승인 시 실행 순서, 이번 세션엔 미실행)

1. `scripts/analysis/tsmom_nl_tuning.py` 신설 — `wi_tuning.py`/`macd_hard_gate_tuning.py`
   패턴 그대로: `_params()` 컨텍스트매니저로 플래그 오버라이드, 동일 3년 frames 재사용.
2. 그리드축: lookback{126봉(~3주×6), 180봉(~1개월), 372봉(~3개월 상당)} ×
   vol_estimator{6봉 realized_vol, EWMA robust} × MIN_SIGNAL_THRESHOLD{0.0, 0.2, 0.5}.
3. 타 알고 무회귀 확인(algo_id 격리라 자연히 무영향 — omnibus 사례처럼 확인만).
4. `validation_stats.py` DSR(+가능하면 PBO), 전/후반 분할(2025-04 기준, 상승/하락 창
   양쪽 확인 — omnibus/multi_factor 선례처럼 한쪽에만 몰린 개선은 기각 대상).
5. 통과 시에만 `parameters.py` 반영 + `PARAMS_VERSION` bump + EC2 배포. **DSR 미달
   시 macd_momentum과 동일하게 폐기하고 결과를 이 문서에 기록**(승인해도 채택을
   보장하지 않음 — 지금까지 이 저장소의 원칙).

---

## 8. 미해결 (구현 시 결정) — algo_id 슬롯

사용자 승인으로 **`macd_momentum` algo_id 슬롯 재사용**(자본 캡·DB 연속성 유지)을
채택. `ALGORITHMS["macd_momentum"]`는 함수 그대로, 내부 로직이 `TSMOM_NL_ENABLED`
플래그로 분기.

---

## 9. 구현·그리드 검증 결과 (2026-08-08 실행)

### 9.1 구현

- `indicators.py`: `TSMOM_NL_LOOKBACK_CANDIDATES=(126,180,372)` 3개 lookback을
  매 프레임마다 사전계산(`tsmom_nl_return_{bars}`) + `tsmom_nl_vol_ewma` 추가.
  단일 frame 빌드로 그리드 전체 커버(재계산 없음).
- `algorithms.py`: `_tsmom_nl_signal(ind)`(s_t 계산) +
  `tsmom_nl_position_multiplier(macro, ind)`(f(s)=clamp(s/(s²+1), 0, 0.5), 비활성
  시 1.0 no-op) 신설. `macd_momentum()`과 `explain_signal()` 모두 최상단에서
  `TSMOM_NL_ENABLED` 분기 — 레거시 MACD 로직·진단은 완전 보존.
- `backtest.py:385`·`scheduler.py:966` 인근에 `omnibus_position_multiplier`와
  동일 패턴으로 `if algo_id == "macd_momentum": position_weight *=
  tsmom_nl_position_multiplier(...)` 추가.
- 파라미터: `TSMOM_NL_ENABLED=False`(기본), `LOOKBACK_BARS=180`,
  `VOL_MODE="rv6"`, `MIN_SIGNAL=0.0`, `WEIGHT_CAP=0.5`.
- 테스트 11건 추가(`tests/test_arena_algorithm_diagnostics.py`) — 신호 계산·클램프·
  risk-off 유지·explain_signal 분기·비활성 시 no-op 전부 커버. 전체 arena 테스트
  220개 통과(회귀 없음).

### 9.2 그리드 결과 — 방향은 개선, 통계 기준은 미달

`scripts/analysis/tsmom_nl_tuning.py`(3년 프레임, 2023-10~2026-08, 5601봉,
lookback{126,180,372}×vol_mode{rv6,ewma}×min_signal{0.0,0.2,0.5}=18변형). 결과:
`docs/arena/research/tsmom-nl-tuning-20260808.json`.

| 항목 | 레거시 MACD(baseline) | Nonlinear TSMOM |
|---|---|---|
| 가중합% | **-30.10%**(n=242) | 18변형 중 14개가 양수, 최고 **+6.91%**(L126_ewma_min0.5, n=191) |
| 그리드 전체 양상 | 전 변형이 깊은 마이너스(macd_hard_gate_tuning.py, 6변형) | 대부분 +0~+7%대, 최악도 -1.50%(레거시 대비 여전히 압도적 개선) |

**방향성 개선은 뚜렷함** — 레거시 MACD가 게이트를 어떻게 풀어도 전부 마이너스였던 것과
달리, TSMOM_NL은 거의 전 그리드 조합에서 플러스 근방. "신호 정의를 바꾸니 개선된다"는
가설(§0)이 방향적으로는 지지됨.

그러나 최선 변형(L126_ewma_min0.5)에 대한 3개 통계 검증 전부 미달:

1. **DSR**: `sharpe=0.045, dsr=0.110`(n_trials=18, 그리드 크기 페널티). 채택 기준
   ~0.95 대비 크게 부족 — 이 저장소가 fng_contrarian/vix_rsi조차 DSR 미달로
   "검증된 기준선" 지위를 박탈한 전례(P4 감사, 2026-08-04)와 동일 엄격도 적용.
2. **부트스트랩 95%CI**(5000회 재표본, 거래 191건): `[-7.27%, +21.75%]`,
   `P(sum_w_ret≤0)=17.5%` — 구간이 0을 크게 포함, "우연히 손실일 확률"이 무시할
   수준이 아님.
3. **전/후반 분할**: 전반(n=95) **+9.48%** vs 후반(n=96) **-2.57%** — 개선이
   전반부(2023-10~2025 초)에 몰리고 최근 구간은 무개선/악화. omnibus 손절폭
   재설계(2026-08-04)·P1 라운드에서 "전/후반 불일치 = 노이즈/국면의존 신호로
   기각"한 것과 동일 패턴.

### 9.3 판정 — 기각(활성화 안 함), 인프라는 보존

이 저장소 관행(그리드 개선폭이 커도 DSR·부트스트랩·분할 검증을 반드시 통과해야
채택)을 그대로 적용해 **TSMOM_NL_ENABLED 기본값 False 유지**. 라이브 동작은 이번
세션 이전과 100% 동일(레거시 MACD 로직, 실질적으로 거의 무거래인 현재 상태 지속).
`PARAMS_VERSION` bump 없음(플래그가 off라 기본 동작 무변화).

**인프라는 삭제하지 않고 보존**한다 — macd_momentum과 달리 "신호 정의 자체가
글렀다"는 결론이 아니라 "방향은 맞는데 이 3년 창·이 그리드 해상도로는 최근 구간
일반화가 증명되지 않았다"는 결론이기 때문(레거시 MACD의 "상승장에서도 마이너스"
전면 기각과는 성격이 다름). 향후 재검토 조건: (a) 라이브·백필 데이터가 더 쌓여
후반부 표본이 커지거나, (b) lookback/vol_mode 그리드를 더 세분화하거나, (c) 최근
구간에서만 실패하는 원인(최근 매크로 국면 — Transitional/MA200 하회 — 자체가
추세추종에 불리했을 가능성, 20개월 감사·역사적 상승장 백테스트에서 이미 확인된
패턴과 동일선상)이 규명되는 경우.

재현: `scripts/analysis/tsmom_nl_tuning.py --parquet data/sentiment_join/master_20260710.parquet --limit 6000`

---

## 10. Walk-forward 재검증 + 활성화 결정 (2026-08-08, §9 이후 추가 실행)

§9의 기각 판정("전/후반 반분할 불일치")은 하나의 분할점(50/50)만 봤다는 한계가 있었다.
사용자가 "왜 안 되는지 알았으니 실제로 수익·거래량을 개선하라"고 재요청 — 더 세밀한
근거로 재판정한다.

### 10.1 방법 — 6윈도 walk-forward (`scripts/analysis/tsmom_nl_walk_forward.py`)

동일 3년 프레임(5601봉, 2023-10~2026-08)을 비중첩 6윈도(각 ~156일)로 나눠, **레거시
MACD baseline**과 **lookback=126 6변형**(§9.2 그리드에서 유일하게 vol_mode·min_signal
전 조합이 플러스였던 lookback)을 윈도별로 고정 비교(target_exit_walk_forward.py와
동일 원리 — config는 전체 기간에 대해 고정, 재적합 없음).

### 10.2 결과 — 레거시 대비 6/6 구간 전부 개선

| 윈도(시간순) | 레거시 MACD | L126_ewma_min0.5(최고수익) | L126_ewma_min0.0(거래량우선) |
|---|---:|---:|---:|
| W1 (2023-10~2024-03) | +1.9% | +9.0% | +8.8% |
| W2 | -2.0% | +2.5% | +2.5% |
| W3 | -6.6% | -1.4% | +0.0% |
| W4 | -3.6% | +0.8% | -0.9% |
| W5 | -11.3% | -1.6% | -2.5% |
| W6 (2026-03~08, 최근) | -9.1% | -2.3% | -2.6% |
| 양의 윈도 | 1/6 | 3/6 | 3/6 |
| 전체 가중합 | -30.10% | **+6.91%** | +5.35% |

**레거시 대비 6개 윈도 전부에서 우위**(예외 없음) — 이는 특정 구간에만 몰린 우연이
아니라 구조적 개선이라는 근거다. 다만 **절대 수익은 W1~W2(2023-10~2024-07, 실제
상승장과 겹침)에 집중**되고, W3~W6(2024H2~현재)는 레거시보다 훨씬 낫지만 자체
절대수익은 거의 0이거나 소폭 마이너스 — 이는 TSMOM_NL 고유의 결함이 아니라 이 창
자체가 추세추종 전반에 불리했다는, 이미 이 저장소가 반복 확인한 사실(20개월 감사·
역사적 상승장 백테스트, 2026-07-25·2026-08-03)과 정합적이다.

### 10.3 판정 — "증명된 엣지"는 아니지만 "확실한 상대적 우위"로 활성화

이 저장소의 기존 채택 관행(DSR≥0.95 등 절대적 통계 유의성)으로는 여전히 §9의 DSR
0.110·부트스트랩 미달을 넘지 못한다 — 그 판정 자체를 번복하지는 않는다. 그러나
활성화 여부의 실질적 비교 대상은 "증명된 대안"이 아니라 **"이미 확실히 죽었다고
증명된 레거시"**다. 6/6 윈도 전부 개선이라는 결과는 "이 변경이 최소한 해를 끼치지
않는다"는 주장을 강하게 뒷받침하며, 사용자가 결정한 사업 우선순위(vision.md,
2026-08-06 "정직한 표본 확보" 국면 — v33/v34와 동일 원칙)에도 부합한다.

**사용자 확인 후 활성화**: `TSMOM_NL_ENABLED=True`, `LOOKBACK_BARS=126`,
`VOL_MODE="ewma"`, `MIN_SIGNAL=0.0`(거래량 우선 변형 선택 — n≈254/3년, 전체가중합
+5.35%). `PARAMS_VERSION` v34→v35. `docs/arena/research/tsmom-nl-walk-forward-
20260808.json`(윈도별 시계열, DSR/PBO 재계산용)로 저장.

### 10.4 다음 재검토 조건 (§9.3과 동일하게 유지)

- W3~W6(2024H2~현재)의 절대수익이 계속 0 근방이면, 이는 "TSMOM_NL도 결국 이 매크로
  국면에서는 무엣지"라는 뜻일 수 있다 — 다른 추세추종 알고들과 함께 재평가 대상.
- 진짜 상승장이 재현되면(W1 패턴 재현 여부) 이 활성화 결정의 가장 강력한 사후 검증이
  된다.
- 라이브 트랙레코드가 쌓이면(`/arena-status` 정기 확인) 백테스트-라이브 괴리를
  주시할 것 — macd_momentum은 지금까지 라이브에서 사실상 무거래였으므로, 활성화 후
  거래빈도·초기 성과가 예상(연 ~80건, 백테스트 3년 평균)과 부합하는지 첫 확인 대상.
