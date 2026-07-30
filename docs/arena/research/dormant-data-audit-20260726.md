# 미탐색 데이터 전수 감사 — 2026-07-26

## 목적과 방법

지금까지의 아레나 분석은 `paper_positions`·`arena_decisions`·`arena_macro_snapshots`·
`arena_ohlcv_bars` 등 핵심 테이블에 집중돼 있었다. 이 문서는 **한 번도 조회하지 않은
나머지 데이터**를 전수 훑어, 모호하지 않고 결정적인(decisive) 개선점이 나올 때까지
반복 조사한 결과다.

**조사 방법**: 코드베이스에서 `.table("...")` 호출을 전수 grep해 실제 존재하는
Supabase 테이블 30개를 확정 → 각 테이블의 row count·최신성 조회 → 지금까지 분석에서
전혀 언급되지 않은 테이블 우선 순위로 내용 검사 → 이상 신호 발견 시 근본원인까지 코드
레벨로 추적 → 정량 검증.

```
arena_backtest_equity_curve   arena_backtest_risk_events    arena_backtest_runs
arena_backtest_trades         arena_backtest_validation_*   arena_basis_snapshots
arena_decisions*              arena_execution_gates         arena_execution_quality
arena_feature_registry        arena_funding_rates           arena_indicator_*
arena_liquidation_bars        arena_macro_snapshots*        arena_mark_price_bars
arena_market_feature_snapshots arena_ohlcv_bars*            arena_open_interest_snapshots
arena_parent_orders           arena_realtime_*              arena_risk_events
arena_run_ohlcv_bars          arena_runs                    arena_shadow_decisions
arena_strategy_versions       arena_walk_forward_splits     paper_positions*
```
(*표시 = 기존 분석에서 이미 다룬 테이블. 이 문서는 나머지 26개 중심.)

---

## 핵심 발견 (결정적): 섀도우 실행품질 게이트가 가동 이래 100% 거부 — 구조적 오검량

### 요약

`src/arena/execution_gate.py`의 `evaluate_execution_gate()`(섀도우 전용, 실거래 미적용)가
신호가 존재했던 **168/168 사이클(100%)**에서 `no_trade`를 반환했다. 예외 없음.
`arena_execution_gates`(1,551행) 테이블 전수 조회로 확인 — 이 게이트가 살아있던 전체
기간(2026-06-19~) 단 한 번도 "허용"을 낸 적이 없다.

| 구분 | 값 |
|---|---|
| 현행 6알고 신호 존재 사이클 | 168 |
| `decision == "no_trade"` | **168 (100.0%)** |
| `decision != "no_trade"` (허용) | **0** |
| 사유: `expected_return_below_cost_floor` | 159 (94.6%) |
| 사유: `risk_daily_loss_limit`/`risk_max_long_positions` | 9 (5.4%, 구 portfolio-risk-v1 캡 시절) |

**교차검증**: `arena_parent_orders`/`arena_execution_quality`(더 상세한 TCA 섀도우
로그, 47행)를 실제 체결된 `paper_positions` 38건과 타임스탬프로 조인 — **38/38 전부**
동일하게 `expected_return_below_cost_floor`로 거부 판정. 즉 지금까지 시스템이 실제로
연 모든 포지션은, 이 섀도우 게이트 기준으로는 "비용 대비 기대수익 미달"로 매번 걸렸을
거래다.

### 근본 원인 (코드 레벨 확인)

`src/arena/execution_gate.py:141-142`:
```python
elif expected_return < expected_cost * policy.ecr_multiple:
    reject_reason = "expected_return_below_cost_floor"
```
`ecr_multiple = 3.0`(`parameters.py:443`) — 기대수익이 왕복비용의 3배는 돼야 통과.

**문제는 `expected_return` 계산 자체다** (`execution_gate.py:83-88`):
```python
def _price_edge_bps(signal, indicators, close):
    macd_hist = abs(indicators.get("macd_hist") or 0.0)
    atr = indicators.get("atr") or 0.0
    edge_price = max(macd_hist, atr * parameters.MACD_ATR_THRESHOLD_MULTIPLE)  # ×0.10
    return edge_price / close * 10_000.0
```
`MACD_ATR_THRESHOLD_MULTIPLE = 0.10`(`parameters.py:392`) — **ATR의 10%** 를 "기대수익"
프록시로 쓴다. BTC 4H ATR이 보통 종가의 0.8~1.6%인 걸 감안하면, 이 프록시는 구조적으로
**8~16bps 안팎**밖에 안 나온다. 반면 `expected_cost`는 스프레드/슬리피지 실측치를 반영해
정상적으로도 최소 10~50bps, 오더북이 얇게 잡히는 순간엔 100~730bps까지 튄다
(실측: `docs/arena/research/priority-analysis-20260725.md` 등에서 다룬 진짜 전략 로직과
무관한 별도 계산). 3배 곱하면 요구선이 **30~2190bps** — `expected_return`(7~55bps 실측
범위)이 이 요구선을 넘을 가능성이 수학적으로 거의 없다. 실측 47건 전부가 이 부등식을
만족 못 한 것도 우연이 아니라 **파라미터 조합이 애초에 통과 불가능하게 설계**됐기 때문이다.

실측 샘플(전량, `arena_parent_orders.decision_snapshot.gate_decision`):

| algo | expected_return(bps) | expected_cost(bps) | 요구선(×3) | 결과 |
|---|---:|---:|---:|---|
| fng_contrarian | 16.8 | 16.4 | 49.3 | FAIL |
| omnibus | 55.0 | 730.0 | 2190.0 | FAIL |
| multi_factor | 10.5 | 278.7 | 836.1 | FAIL |
| ...(전체 47건) | 7.7~55.0 | 16.4~730.0 | 49.3~2190.0 | **전부 FAIL** |

두 번째 문제(부차적, 같은 방향으로 악화시킴): `expected_cost`가 실시간 오더북 스냅샷의
**상위 20레벨**만으로 10bps 밴드 내 깊이를 추정한다(`execution_gate.py`의
`_depth_score`/`expected_cost_bps`, feature_snapshot 원자료의 `depth_asks` 리스트 길이
20 확인). BTCUSDT 현물은 세계에서 가장 유동성이 깊은 페어 중 하나인데, 얕은 상위 20레벨만
보고 슬리피지를 추정하면 실제보다 훨씬 나쁜 비용으로 과대추정될 수 있다(실측
`depth_score: 0.0027`인 샘플 확인 — $100만 기준 대비 0.27%만 잡힘). 이게 `expected_cost`
쪽의 비정상적 스파이크(최대 730bps)의 유력한 원인으로 보인다.

### 이게 왜 "결정적"이고 왜 지금까지 안 보였나

- **결정적인 이유**: 판단에 모호함이 없다. 168/168, 47/47 — 소표본 노이즈나 해석 여지가
  아니라 수학적으로 통과 불가능한 임계값 조합이다.
- **왜 안 보였나**: 이 서브시스템은 **섀도우 전용**(`mode: "shadow"`, 실거래 무영향)이라
  대시보드·`arena_status.py`·기존 모든 분석 스크립트가 참조하지 않는 테이블
  (`arena_execution_gates`/`arena_execution_quality`/`arena_parent_orders`)에만
  기록돼 왔다. `docs/arena/research/realtime-execution-gate-v1.md`에 설계 문서는
  있지만, **가동 후 실측 검증 기록이 없다** — 만들고 나서 한 번도 되짚어보지 않은
  전형적인 "구현은 했지만 검증 루프가 없는" 케이스.

### 임팩트

- **현재**: 무해하다. 섀도우 전용이라 실거래·리스크·자본에 영향 없음.
- **잠재적 위험**: 이 시스템의 로드맵([return-optimization-research-20260709.md] 등)은
  섀도우 검증 후 "승격"하는 패턴을 반복 사용한다(SJM, trend_core sleeve 등도 동일 패턴).
  만약 이 실행품질 게이트를 같은 방식으로 "검증 후 실거래에 연결"한다면, **현재 파라미터
  그대로는 모든 거래가 즉시 차단된다** — 이 오검량을 모르고 승격하면 시스템이 조용히
  멈춘다.
- **부차 영향**: `arena_execution_quality.expected_cost_bps`를 신뢰할 만한 실비용
  추정치로 오인해 다른 분석(TCA, 비용 민감도)에 재사용하면 잘못된 결론으로 이어질 수
  있다.

### 적용 완료 (2026-07-26 후속)

`src/arena/execution_gate.py`의 `_price_edge_bps()`를 `_expected_return_bps()`로
교체 — 알고별 실제 목표가 메커니즘을 우선 사용하도록 배선:
1. `omnibus` → `algorithms.omnibus_target_price(macro, ind, close)` 실거리
2. `fng_contrarian` → `algorithms.fng_target_pct(ind, close)` 실거리
3. `TARGET_EXIT_ATR_MULT_BY_ALGO`에 등록된 알고 → 해당 ATR mult
4. 나머지(regime_trend·macd_momentum 등 트레일링 전용) → `max(|macd_hist|,
   ATR×OMNIBUS_REBOUND_TARGET_ATR_MULT(1.0))` 폴백(기존 macd_hist 비교 구조는 유지,
   ATR 배수만 0.10→1.0으로 현실화)

`evaluate_execution_gate()`에 `macro` 파라미터 추가, `scheduler.py` 3개 호출부 배선.
`tests/test_arena_execution_gate.py`(10건)·전체 arena 테스트(150건) 통과.

**재시뮬레이션 검증**: `arena_decisions` 신호 존재 195사이클을 신규 로직으로 재평가 →
거부율 **100%→22.1%**(43/195, 나머지 152건은 통과). 남은 22.1% 거부는 `expected_cost`가
실제로 크게 튄(오더북 얕음) 케이스로, 정상적인 필터링으로 보인다(2번 항목은 여전히
개선 여지 있음, 아래 참조).

미해결(다음 대상):
1. 오더북 깊이 추정을 상위 20레벨 한정에서 실제 10bps 가격밴드까지 페이지네이션하거나,
   최소한 얕은 스냅샷일 때의 폴백 로직을 점검 — `expected_cost_bps`가 여전히 가끔
   과대추정될 수 있음.
2. 이 게이트를 승격 후보로 검토하기 전에, 반드시 `docs/arena/research/`에 "가동 후
   실측 거부율" 같은 헬스체크를 루틴화(예: 월 1회 `arena_execution_gates` allow-rate
   점검) — 이번처럼 5주간 아무도 안 본 채로 방치되는 것 방지.
3. `ENABLE_ARENA_EXECUTION_GATE_LIVE=False` 계속 확인(EC2 env 변수 확인 완료, override
   없음) — 섀도우 상태 유지, 실거래 무영향.

---

## 부차 발견 1: SJM(통계적 점프모델) 섀도우 — 아직 판단 이르나 관찰 포인트 있음

`src/morning_brief/analysis/sentiment_join/risk_overlay.py:129 _compute_sjm_state()` —
JumpModel(n=2, penalty=15)로 bull/bear 2상태 분류, 섀도우 전용(`sjm_state`),
"30일 관찰 후 rule-based 레짐 대비 비교로 승격 여부 결정" 설계.

- `arena_macro_snapshots` 전수 조회 결과 **최초 등장 2026-07-14** — 오늘(2026-07-26)
  기준 12일차, **아직 30일 미달**. 승격 판단은 이르다.
- 지금까지 **100% `sjm_bear`** — 상태 변화가 전혀 없어 rule-based 분류기(`unknown`·
  `sideways`·`bull_trend` 등 다변화됨)와의 판별력 비교 자체가 아직 불가능(분산 없는
  신호는 비교 대상이 못 됨).
- **결정적이지 않음** — 표본기간 미달 + 변동 없음이라 이번 문서의 "결정적 발견" 기준을
  충족하지 못한다. 30일(2026-08-13 전후) 도달 후 재확인 필요. 액션: 없음(관찰 지속).

## 부차 발견 2: `arena_shadow_decisions`(trend_core sleeve) — 이미 알려진 한계 재확인

`sleeves.py`의 `trend_core_v1`이 자체 레짐 분류기(`reason.regime_reason.rule`)를 쓰는데
샘플 확인 결과 `"no_rule_matched"` → `regime: "unknown"` → `action: "shadow_flat"`가
반복. 기존 `external-review-verdict-20260725.md`에서 이미 "sleeves.py는 검증장치로
불충분"이라 지적한 것과 정합적 — 새로운 결정적 사실은 아니고 기존 결론의 재확인.

## 조사했으나 특이사항 없음(참고용)

- `arena_liquidation_bars`: 0행 — 기존 WI-9 진단(네트워크 차단 추정)과 일치, 새 정보 없음.
- `arena_backtest_validation_checks/runs`: 각 12행/1행, 2026-06-19 이후 갱신 없음 —
  일회성 검증 도구로 보이며 방치 자체는 특이사항 아님(원포인트 체크 용도).
- `arena_funding_rates`/`arena_open_interest_snapshots`/`arena_mark_price_bars`/
  `arena_basis_snapshots`: 정상 수집 중(4H 주기), 현재 각 알고 게이트에서 이미 활용
  중인 파생 지표(funding_zscore, oi_divergence_flag 등)의 원천 데이터 — 별도 이상 없음.
- `arena_realtime_risk_events`/`arena_realtime_risk_states`/`arena_realtime_feature_bars`:
  1분 단위로 매우 활발히 수집 중(각 2~5만 행) — `mfe_1m.py` 등 기존 분석에서 이미 활용됨.

---

## 결론

가장 사소해 보였던 두 테이블(`arena_execution_quality` 47행, `arena_parent_orders`
47행 — 핵심 테이블 대비 1/10 이하 규모)이 시스템 전체에서 가장 결정적인 미발견 문제를
담고 있었다. **섀도우 실행품질 게이트는 가동 후 5주간 단 한 번도 거래를 허용한 적이
없으며, 원인은 실제 시장 상황이 아니라 파라미터 미스매치(`MACD_ATR_THRESHOLD_MULTIPLE=0.10`
vs `ecr_multiple=3.0`)다.** 현재는 섀도우 전용이라 무해하지만, 검증 없이 승격되면
시스템을 조용히 정지시킬 수 있는 잠복 결함이었다.
