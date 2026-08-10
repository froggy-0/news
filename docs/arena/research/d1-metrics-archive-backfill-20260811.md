# D1 실행 — futures/um/daily/metrics 아카이브 백필·교차검증·A/B (2026-08-11)

[binance-data-catalog-audit-20260811.md](binance-data-catalog-audit-20260811.md) D1의 후속
실행. 권고 순서(§6) 그대로 진행: **교차검증 → 백필 → A/B**. 결론부터: **taker(WI-10)는
아카이브로 재현 불가능함이 확정됐고, LSR·OI는 완벽히 백필 가능하지만 실제 백테스트 A/B에서
아무 개선도 없었다(3개 알고 무변화, 1개 알고는 악화)** — 채택하지 않는다.

## 1. 교차검증 — 결정적 발견

REST `/futures/data/*?period=4h`(최근 30일만 지원)와 아카이브 5분 데이터를 4h로 리샘플한 값을
같은 96개 봉(2026-07-25~08-10)에서 직접 대조. **처음 시도는 타임스탬프 정렬을 반대로 가정해
전부 어긋나 보이는 오탐이 있었다** — REST의 `timestamp`는 4h 구간의 "여는 시각"이 아니라
"닫히는 시각"이었다(정정 후 재검증).

정렬 수정 후 4개 아카이브 컬럼 × 4개 REST 엔드포인트 전수 대조:

| 아카이브 컬럼 | 가장 가까운 REST 필드 | mean\|Δ\| |
|---|---|---|
| `count_long_short_ratio` | `globalLongShortAccountRatio.longShortRatio` | **0.00018** ✅ |
| `count_toptrader_long_short_ratio` | `topLongShortAccountRatio.longShortRatio` | **0.00016** ✅ |
| `sum_toptrader_long_short_ratio` | `topLongShortPositionRatio.longShortRatio` | **0.00003** ✅ |
| `sum_open_interest_value` | `openInterestHist.sumOpenInterestValue` | **0.0000%** ✅ |
| `sum_taker_long_short_vol_ratio` | *(4개 전부와 대조, 최선조차)* | **0.53~0.83** ❌ |

LSR(글로벌·탑트레이더 계정·포지션) 3종과 OI는 사실상 완벽히 일치한다. **`sum_taker_long_short_vol_ratio`(WI-10이 필요로 하는 `taker_ratio_4h`, REST `takerlongshortRatio.buySellRatio`
와 동일 정의로 추정했던 컬럼)는 4개 REST 엔드포인트 어느 것과도 매칭되지 않았다** — 방향조차
자주 뒤집힌다(예: 아카이브 2.50 vs 라이브 0.49, 매수우위↔매도우위 반전). Binance가 이 daily
metrics 파일 안에 taker 비율을 다른 집계 방식(원본 5분 buyVol/sellVol을 알 수 없는 방식으로
재가공)으로 넣어둔 것으로 보이며, 원시 buyVol/sellVol이 파일에 없어 역산도 불가능하다.

**결론**: 카탈로그 감사(2026-08-11) 시점에 "WI-10을 이 아카이브로 백필 가능"이라고 쓴 CLAUDE.md
항목은 **틀렸다** — 정정 필요(§4). WI-10(`TAKER_CONFIRM_4H_ENABLED`)은 여전히 라이브 전용이며
백테스트 검증 수단이 없다.

## 2. 백필

검증된 3개 컬럼(LSR 글로벌계정 + OI)만 사용해 BTC 2025-01-01~2026-08-09(19개월, 5분→4h
리샘플, 3,516봉)를 백필. `scripts/analysis/metrics_archive_features.py`:
- `long_short_ratio_zscore_4h`: `count_long_short_ratio`의 30일/180봉 롤링 z(15일/90봉 최소,
  `risk_overlay._last_rolling_zscore`와 동일 규약).
- `oi_change_7d_4h`: `sum_open_interest_value`의 7일(42봉) 변화율. 가격과의 다이버전스 판정은
  프레임의 실제 종가 시리즈와 결합해야 하므로 오버레이 단계(`lsr_oi_backfill_tuning.py`)에서
  완성.

⚠️ 정렬 함정 하나 더 있었음: `arena_ohlcv_bars.close_time`은 4h 경계의 -1초(예:
`23:59:59`)로 저장되는데 아카이브 리샘플은 정확한 경계(`00:00:00`)를 쓴다 — 처음 실행 시
매칭 0/1966으로 완전히 실패했고, `+1초` 보정 후 1963~1921/1966(99~98%)로 정상화됐다.
(정렬 버그가 이번 세션에서만 두 번 나왔다는 것 자체가 4h 경계 정렬이 이 프로젝트에서
반복적으로 밟는 지뢰라는 뜻 — 다음에 유사 작업을 할 때는 이 문서를 먼저 참조할 것.)

## 3. A/B — 결과: 채택하지 않음

`scripts/analysis/lsr_oi_backfill_tuning.py`: baseline(기존 sentiment_join 일간 lag1 z, macro
백필 표준 경로)과 variant(각 프레임의 `long_short_ratio_zscore`/`oi_divergence_flag`만 아카이브
4h 값으로 덮어씀, 다른 macro 키는 그대로) 두 프레임셋으로 동일 `backtest.run_replay` 실행.
`ReplayFrame`이 frozen dataclass라 `dataclasses.replace`로 새 macro dict를 가진 프레임을
만들어 baseline은 전혀 건드리지 않았다.

프레임 1966개(2025-09-16~2026-08-10, ~11개월, `master_20260710.parquet` 워밍업 이후 구간).

| 알고 | baseline sum_w_ret | variant sum_w_ret | Δ | 판정 |
|---|---|---|---|---|
| `regime_trend` | -11.64% | -11.64% | 0.00 | 무변화 |
| `macd_momentum` | -5.61% | -5.61% | 0.00 | 무변화 |
| `multi_factor` | -1.76% | **-3.06%** | **-1.31** | ❌ 악화 |
| `omnibus` | -4.58% | -4.58% | 0.00 | 무변화 |
| `fng_contrarian`/`vix_rsi`(대상 아님) | — | — | 0.00 | 무회귀 확인(OK) |

`regime_trend`(WI-1/v33 secondary vote 8개 중 5)와 `macd_momentum`(secondary vote 6개 중
3~4)의 LSR/OI 부차조건은 **daily lag1과 4h 아카이브 사이에 진입 판정이 단 한 번도 갈리지
않았다** — 이 ~11개월 창에서는 해상도 차이가 실질적 영향이 없었다는 뜻. `omnibus`의
UP_TREND `_lsr_crowded` hard veto도 동일. `multi_factor`(`_lsr_crowded` hard veto)만
결과가 바뀌었고, 방향은 **악화**(승률 44.7%→42.6%, 가중합 -1.76%→-3.06%) — 더 촘촘한(빠른)
LSR 신호가 daily-smoothed 버전보다 나쁜 타이밍에 veto를 발동시킨다는 뜻으로 해석된다.

DSR은 참고용(변형 2개뿐이라 통계적으로 약함, `n_trials=2`)이지만 전 알고에서 `best=baseline`
으로 일관됐다.

## 4. 결론 및 CLAUDE.md 정정

- **채택하지 않음.** 코드·파라미터 변경 없음, `PARAMS_VERSION` bump 없음, 배포 없음.
- **WI-10은 여전히 막혀 있다** — "D1으로 검증 가능해진다"던 카탈로그 감사·CLAUDE.md의 원래
  주장은 taker 컬럼 자체가 다른 정의였다는 게 밝혀지며 무효화됐다. WI-10을 실제로 풀려면
  라이브 축적(현재도 진행 중, `market_structure.py`가 매 4h 사이클마다 캐시)을 기다리거나
  다른 taker 데이터 소스를 찾아야 한다.
- **LSR/OI는 데이터로는 완전히 백필 가능**(거의 완벽한 정의 일치)하지만, 실제로 백테스트
  결과를 바꾸지 않거나(3/4) 악화(1/4)시켰다 — "데이터 해상도가 게이트 품질의 병목이었다"는
  가설이 이 창에서 반증됐다. 재시도 시 새로운 근거(다른 기간·다른 알고) 없이는 무의미.
- 이 조사로 얻은 재사용 가능한 산출물: `scripts/analysis/metrics_archive_features.py`
  (다운로드·캐시·리샘플·검증된 3컬럼 z-score 유틸리티, taker 제외)와
  `scripts/analysis/lsr_oi_backfill_tuning.py`(frozen-dataclass macro 오버레이 A/B 패턴,
  다른 아카이브 피처 검증에도 재사용 가능한 템플릿).

**CLAUDE.md 정정 필요 사항**: 2026-08-11 카탈로그 감사 커밋의 D1 서술 중 "WI-10 및 3게이트가
검증 수단 없음으로 묶여있던 근본 원인이 이 30일 제한이었고 아카이브가 그 구멍을 메움"은
taker에 대해서는 틀렸다(§1) — LSR/OI에 대해서만 맞고, 그마저도 A/B에서 무효과/악화로
확정됐다(§3). 아래 CLAUDE.md 항목에 이 실행 결과를 반영한다.
