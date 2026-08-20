# 신규 알고 후보 — Riptide: 선물 프리미엄 지수 플립 역발산 (2026-08-20)

## 배경

사용자가 파생상품 매매기법("펀딩비 극단 양수→음수 플립을 추세반전에 베팅") 질문 후,
"이미 검증한 거 반복하지 말고 유의미한 신규 테스트"를 요청. 이 저장소가 이미 검증한
`Undertow`(2026-08-14 기각, `funding_zscore<=-1.5` 정적 레벨 임계값)와 정보구조가
다른 가설을 선별:

- Undertow: "현재 레벨이 극단적으로 음수인가"(상태) — 기각됨.
- Riptide(신규): "최근 극단 양수였다가 지금 막 음수로 전환됐는가"(디레버리징 이벤트) —
  레벨이 아니라 전환(flip) 자체를 탐지. 문헌상 캡추레이션 마커는 상태보다 이벤트에
  가깝다는 게 사용자 질문의 원 기법 설명과도 일치.
- 데이터원도 다름: `funding_zscore`는 8h 정산 funding rate의 **BTC공유** 30일 롤링
  z-score(2026-08-01 검증: ETH corr=0.476·SOL corr=0.082로 자산고유성 낮음, 기존
  6알고가 이미 veto로 쓰는 값)인 반면, **premium index**(마크가격 대비 무기한선물
  프리미엄, 연속 측정치이자 funding rate의 원천 산출 재료)는 `market_structure.py`가
  이미 수집은 하면서도(`arena_mark_price_bars`) 주 신호·veto 어디에도 쓴 적이 없는
  데이터(전수 grep 확인) — 자산별로 직접 Binance에서 가져와 계산해 자산고유성도 자동
  확보됨.

## 방법론

`new_algo_candidates_backtest.py`(Wellspring/Undertow/Chorus)와 동일 원칙:
`backtest.run_replay(strategy_fns=...)` 오버라이드만(`ALGORITHMS`/live 배선 무변경),
단일 사전 사양(그리드 아님, DSR `n_trials=1`), 부트스트랩 95%CI(가중수익, 3000회),
전/후반 분할. macro 백필은 `master_20260710.parquet`(2025-04-16~2026-07-10, 446일,
`new_algo_candidates_backtest.py`와 동일 창이라 직접 비교 가능) 재사용.

**신호(Riptide)**: `premium_index_zscore_max_7d >= 2.0`(트레일링 7일 중 최고치가
2-시그마 이상 극단 과열) AND `premium_index_zscore <= 0.0`(오늘은 평균 이하로 전환) →
롱. risk-off 제외. 임계값은 관례대로(2-시그마 "극단", 0 "평균 이하 전환") 사전 설계값,
백테스트 결과를 보고 조정하지 않음.

premium index는 `/fapi/v1/premiumIndexKlines`(전체 히스토리 지원, 2026-08-11 카탈로그
감사에서 이미 확인됨)에서 자산별 일별 종가를 직접 가져와 `funding_zscore_asset_native
_backtest.py`와 동일 컨벤션(30일 롤링, `shift(1)`로 lookahead 방지)으로 z-score 계산.

## 구현 중 발견한 배선 버그(수정)

`backtest._macro_signal_from_snapshot()`이 `regimeRaw`에서 **명시적으로 화이트리스트된
필드만** `macro` dict로 전달하는 구조라(P3 `fng_days_below_30` 추가 때와 동일 패턴),
신규 필드를 `regimeRaw`에 overlay해도 전달이 안 돼 첫 실행에서 3자산 전부 `n=0`(거래
없음)이 나왔음. `premium_index_zscore`/`premium_index_zscore_max_7d` 2개 필드를 이
화이트리스트에 추가(그레이스풀 `raw.get()`, 기본값 None — 라이브 `scheduler._fetch_macro`
는 아직 이 필드를 안 채우므로 실거래 영향 없음, arena 테스트 408개 전부 통과 확인).

## 결과

| 자산 | n | win% | sum_w% | PF | 부트스트랩95%CI | 전/후반 | DSR |
|---|---:|---:|---:|---:|---|---|---:|
| BTC | 55 | 41.8 | -10.68 | 0.65 | [-23.51%, +2.45%] | -10.18/-0.50 | 0.122 |
| ETH | 28 | 35.7 | +2.57 | 1.09 | [-8.63%, +14.51%] | +4.41/-1.85 | 0.565 |
| SOL | 22 | 31.8 | -3.58 | 0.68 | [-12.30%, +5.65%] | -2.41/-1.17 | 0.256 |

3자산 합계 -11.69%. BTC/SOL은 명확히 순손실(PF<1)이고, ETH만 근소 플러스(PF 1.09)지만
부트스트랩 CI가 0을 크게 포함하고 전/후반 분할에서 부호가 뒤집힘(+4.41%→-1.85%) — 잡음과
구분 불가. DSR 전부 0.95 기준선에 크게 미달(최고 0.565).

## 결론

**❌ 채택하지 않음.** Undertow(같은 데이터 계열, 정적 레벨)와 마찬가지로 이 프로젝트가
반복 확인한 패턴 — 단일 사전사양에서 이 정도로 DSR 미달·CI가 0 포함이면 그리드 튜닝으로
살아날 가능성은 낮다고 판단, 추가 탐색 진행 안 함. **레버리지 포지셔닝 계열 정보원
(funding_zscore 레벨·premium index 플립) 둘 다 이 기간·이 자산군에서 방향 예측력이
없다는 근거가 하나 더 쌓임** — veto로는 유효했던 정보가 주 신호로 승격하면 엣지가
없다는 2026-08-14 결론(Wellspring/Undertow/Chorus)과 일관된 패턴 재확인.

`backtest.py`의 화이트리스트 확장(2개 필드, 그레이스풀 기본 None)은 되돌리지 않음 —
무해하고 향후 재사용 가능. 재사용 산출물: `scripts/analysis/premium_flip_candidate
_backtest.py`(자산별 premium index 직접조회 + z-score/flip 계산 템플릿, 다른 premium
index 기반 가설에도 재사용 가능).
