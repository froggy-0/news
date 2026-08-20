# 레버리지·물타기/피라미딩·숏 판단 리뷰 + macd_momentum 숏 결함수정 (2026-08-20)

## 배경

`/arena-status` 세션(어제 상승장 분석) 직후 사용자 요청: "거래 로직 관점에서 더 볼 게
있나 — 롱/숏 판단, 선물 레버리지 여부, 물타기 여부를 문헌·오픈소스 근거로 분석해줘."
세 축을 순서대로 검증했다. 결과: **레버리지·피라미딩 둘 다 데이터가 명확히 반대**(1x
유지, 피라미딩 미채택 확정)였고, 조사 과정에서 실제 결함 하나(macd_momentum 숏 사이징)
를 발견해 v45로 수정·배포했다.

## 1. macd_momentum 숏 사이징 결함 — 발견 및 수정 (arena-params-v45)

### 발견

2026-08-19 라이브 숏 청산 10건을 실측한 결과 `position_weight` 분포:

```
[0.000, 0.015, 0.018, 0.024, 0.060, 0.063, 0.085, 0.092, 0.252, 0.296]
```

8/10건이 `<0.10`(1건은 정확히 0.000) — 슬롯·표본만 소모하고 손익 기여가 없는
"유령 거래". 원인: v41이 macd_momentum 숏을 승격하면서 롱의
`TSMOM_NL_MIN_SIGNAL=0.0`(v35 "거래량 우선" 선택)을 그대로 재사용 — 사이징
`f(s)=|s|/(s²+1)`가 `s→0`에서 함께 0에 수렴하는데, 진입 임계값이 0이라 `s`가 아주
작아도(예: -0.02) 숏이 열림.

### 임계값 선정

3자산 macro 백필 실측(`scripts/analysis/short_min_signal_tuning.py`, 후보
{0.0,0.05,...,0.5}) 결과 **sum_w·DSR은 후보 구간 전체에서 노이즈 수준 차이**(전부
부트스트랩 95%CI가 0 포함) — 즉 이 축은 알파 레버가 아니다. 대신 최소 실현
position_weight가 후보값에 따라 어떻게 바뀌는지를 봤다:

| min_signal | 최소 weight(오름차순 10개 중 최솟값) | 유령거래(w<0.10) 비율 |
|---|---|---|
| 0.3 | 0.069 | — |
| 0.4 | 0.088 | 17/174 (9.8%) |
| **0.5** | **0.101** | **0/164 (0%)** |

0.5가 최소 position_weight를 구조적으로 ≈0.10 이상 보장하는 첫 지점 — **파라미터
fit(수익 최적화)이 아니라 "경제적으로 의미있는 최소 배분 보장"이라는 구조적 근거로
채택**(CLAUDE.md 원칙: "구조적 버그 수정은 DSR 낮아도 채택 가능").

### 부수 발견: 진단 필드도 깨져 있었음

`explain_signal(algo_id, macro, ind)`가 `direction` 인자 없이 항상 `ALGORITHMS[algo_id]`
(롱 함수)만 재평가 — 숏 거래의 `signal_reason.diagnostics`도 롱 조건으로 계산되고
`tsmom_nl_weight_mult`가 항상 `0.0`으로 기록됐다(라이브 숏 10건 전수 확인, 실제
사이징과 무관한 진단 전용 결함). `explain_signal`에 `direction: str | None = None`
매개변수를 추가해 `direction="short"`일 때 `_explain_macd_momentum_short()`(신규
헬퍼)로 분기하도록 수정, `scheduler._signal_reason`이 `signal`을 그대로 넘기도록 배선.

### 구현

- `parameters.TSMOM_NL_SHORT_MIN_SIGNAL = 0.5`(신규, 롱의 `TSMOM_NL_MIN_SIGNAL=0.0`은
  무변경).
- `algorithms.macd_momentum_short()`: `s < -TSMOM_NL_MIN_SIGNAL` → `s <
  -TSMOM_NL_SHORT_MIN_SIGNAL`.
- `algorithms.explain_signal()`: `direction` 매개변수 추가, `_explain_macd_momentum_short()`
  신규.
- `scheduler._signal_reason()`: `explain_signal(algo_id, macro, ind, direction=signal)`.
- `PARAMS_VERSION` v44→v45. 신규 테스트 8건(`test_arena_macd_momentum_short.py` 6·
  `test_arena_scheduler_perp.py` 1·버전 하드코딩 1).

## 2. 레버리지 — Kelly 기준 역산, 1x 유지 확정

`scripts/analysis/kelly_leverage_diagnosis.py` — 실제 라이브 수익분포에서
`f* = μ/σ²`(거래당 로그성장 최대화 비율)를 역산 + 부트스트랩 95%CI.

| 대상 | n | SR/거래 | f* 점추정 | f* 95%CI |
|---|---|---|---|---|
| 전체 풀링 | 125 | +0.096 | 5.07 | **[-5.6, +12.2]** |
| 롱 | 115 | +0.145 | 7.54 | **[-2.0, +14.8]** |
| 숏 | 10 | -1.134 | -135 | **[-431, -66]** |

**모든 그룹의 CI가 0을 포함** — f*를 추정할 수 없다는 뜻이고, 추정 못 하는 양에
레버리지를 걸 근거는 없다. 관측 SR(0.07~0.15)이 MDE_SR(최소검출가능SR,
0.15~0.69)보다 작아 애초에 검출력 자체가 부족한 상태(2026-08-16 증거기준
프레임워크의 결론과 일치 — "어떤 알고도 통계적으로 증명된 양의 Sharpe 없음").
레버리지는 알파를 만들지 않고 μ·σ를 같은 배수로 늘리므로, **1x 유지가 근거 있는
선택**임을 재확인. 코드·파라미터 변경 없음(현행 유지가 곧 결론).

## 3. 물타기 vs 피라미딩 — 배치가 문헌과 정반대, 인프라 구현·진검증·기각

### 문제의식

코드 감사 결과 스케일인 메커니즘은 **`fng_contrarian`(평균회귀)의 물타기 하나뿐**이고
추세계열(`regime_trend`/`macd_momentum`/`meridian` 추세leg)엔 사이징을 키우는 장치가
없었다. 문헌 통설(피라미딩=추세·돌파 적합, 물타기=평균회귀 적합, 예:
[turtletrader.com](https://www.turtletrader.com/average-up/))과 **정반대 배치**.

### 1차: 사후 시뮬레이션 (방향성 확인용, 채택 근거 아님)

`scripts/analysis/pyramiding_feasibility.py` — 청산 시점을 baseline 그대로 고정하고
진입 트랜치만 추가(진입가 ±0.5d/1.0d, d=|진입가−초기손절가|). 결과: 추세계열
단조개선(macd_momentum Δ+6.11%p, multi_factor Δ+8.38%p), 평균회귀형(omnibus) 단조악화
— 방향은 문헌과 일치했으나 **부트스트랩95%CI가 전부 0 포함**, 자산별 불일치(multi_factor
개선분 대부분이 SOL 단독)라 결론으로 못 씀. "사후 시뮬은 실제 엔진 재시뮬레이션이
아니라는 한계"를 명시하고 정식 구현 필요성만 확인.

### 2차: 인프라 구현 — src/에 정식 배선, 기본 off

물타기 함수(`execution_rules.pending_price_tranches`/`fill_price_tranches`)의 방향
일반화판 신설:
- `execution_rules.pending_pyramid_tranches()` / `fill_pyramid_tranches()` — direction
  매개변수로 롱(상승 유리)·숏(하락 유리) 모두 지원.
- `parameters.PYRAMID_UP_ENABLED_ALGOS: frozenset[str] = frozenset()`(기본 off) +
  `PYRAMID_UP_LEVELS = ((0.5, 0.15), (1.0, 0.15))`.
- `backtest.SimPosition`에 `pyramid_ref_price`/`pyramid_filled_count` 필드, `_open_position`
  초기화, `_maybe_pyramid_up_sim()` 헬퍼, 두 hold 분기(spot/perp)에 배선.
- **핵심 설계 확인(단위테스트로 증명)**: `ratchet_trailing_stop`은 절대 `trail_distance`
  만 참조하고 평단·비중과 무관 — 피라미딩이 청산 메커니즘에 영향을 주지 않는다
  (`test_pyramid_up_does_not_change_trailing_stop_distance`, on/off 동일 프레임에서
  청산가 정확히 일치 확인).
- 신규 테스트 10건(`test_arena_execution_rules.py` 6 + `test_arena_backtest.py` 4).

### 3차: 진짜 백테스트 엔진 A/B — 명확히 기각

`scripts/analysis/pyramiding_true_backtest_ab.py` — `PYRAMID_UP_ENABLED_ALGOS`를 실제
프로세스에서 토글해 `backtest.run_replay()`(실제 엔진, 청산도 진짜 재시뮬레이션)로
3자산 A/B. **사후 시뮬과 정반대 결과**:

| algo | off | on | Δ |
|---|---|---|---|
| macd_momentum | -13.17% | **-27.02%** | -13.86%p |
| regime_trend | -4.33% | -4.33% | 0.00%p(트랜치 미도달) |
| omnibus | -12.20% | -12.05% | +0.15%p(사실상 무변화) |
| multi_factor | -3.37% | **-10.38%** | -7.01%p |
| **4알고 합계** | **-33.07%** | **-53.78%** | **-20.71%p** |

**원인**: `risk.evaluate_open()`의 알고별 드로다운 킬스위치(`ALGO_MAX_DRAWDOWN_KILL_PCT`)
가 `position_weight × ret_pct`로 누적 드로다운을 추적하는데, 피라미딩이 포지션을
키우면 개별 거래의 실현 손익 변동폭이 커져 **킬스위치가 baseline과 다른 시점에
발동** → 이후 쿨다운·거래 시퀀스 전체가 원본과 갈라짐(거래 건수도 소폭 상이: BTC
macd_momentum 74→73건 등). 사후 시뮬은 거래를 독립적으로 재계산해 이 경로 의존성을
전혀 포착하지 못했다 — **"청산 메커니즘은 안 바뀐다"는 확인은 맞았지만, "리스크
상태 머신과의 상호작용"이라는 별개 경로로 해를 끼쳤다.**

### 결론

❌ **미채택 확정** — `PYRAMID_UP_ENABLED_ALGOS` 기본 빈 frozenset(off) 유지, 라이브
미배선. 사후 시뮬의 낙관적 신호는 방법론적 한계(리스크 상태머신 미반영)로 인한
착시였음이 진짜 엔진 검증으로 확인됨. 인프라는 재사용 가능하게 보존(Tier2 등과 동일
관행) — 재시도하려면 사이징 축소(피라미딩 시 킬스위치 임계값도 비례 완화 등) 같은
별도 설계가 필요하나, 이번 세션 범위 밖.

## 4. 문헌·오픈소스 서베이 (참고, 코드 변경 없음)

- **펀딩비 캐리 구조**: [BIS Crypto carry](https://www.bis.org/publ/work1087.pdf) ·
  [Perpetual Futures Pricing (Ackerer, 2026, Mathematical Finance)](https://onlinelibrary.wiley.com/doi/10.1111/mafi.70018) ·
  [Funding Rate Mechanism (Zhang, 2026)](https://papers.ssrn.com/sol3/Delivery.cfm/6185958.pdf?abstractid=6185958&mirid=1) —
  전부 "펀딩이 롱→숏 이전"이라는 구조적 사실을 다루지 방향 예측력을 주장하지 않음.
  `funding_carry`(v43)가 이미 문헌이 지지하는 형태.
- **오픈소스**: [Freqtrade](https://github.com/freqtrade/freqtrade)의 Edge 사이징은
  개념적으로 `combined_position_weight`와 동일. 대체할 신규 기법 없음.
  [NautilusTrader](https://nautilustrader.io/)의 나노초 이벤트 드리븐 체결 시뮬은
  2026-08-10 트레일링 실험의 "봉종가 래칫이 휩소를 과대평가했을 가능성" 미해결
  꼬리에 이론적으로 유용하나, `mfe_1m_backtest.py`+1m 아카이브로 훨씬 싸게 접근
  가능해 도입 불필요.
- 숏 방향성 판단(거울반전·GJR-GARCH·모멘텀크래시 사이징) 자체는 이미
  [Phase B](spot-to-perp-phase-b-short-entry-design-20260815.md)에서 전수 검증됐고
  이번 세션은 그 결론을 재확인만 함(재작업 없음).

## 롤백

- v45(숏 결함수정): `TSMOM_NL_SHORT_MIN_SIGNAL`을 `0.0`으로(v41 상태 복귀). direction
  진단 수정은 되돌릴 필요 없음(하위호환, 부작용 없음).
- 피라미딩: 애초에 기본 off라 롤백 대상 아님.
