# 구현 계획 W1~W8 — 수익률 개선 우선순위의 코드베이스 기반 상세 설계 (2026-07-15)

> **성격**: [return-improvement-priorities-20260715](return-improvement-priorities-20260715.md)의
> 즉시 구현 가능 항목(P0~P4, P6-b, P7)을 실제 코드 앵커 기준으로 설계한 실행 문서.
> 계획 조사 과정에서 **W2(omnibus 사이징 패리티 버그)를 신규 발견**해 추가했다.
> **W1·W2는 구현·검증 완료(2026-07-15, 아래 §W1/§W2 결과 참고), W3~W8은 아직 미구현** —
> 각 항목은 이 문서의 설계·검증 절차대로 개별 사이클로 진행한다.

## 공통 컨벤션 (전 항목 적용)

- 신규 동작은 `parameters.py` 플래그/dict 기본 off(빈 dict) — 검증 통과 후에만 값 채움.
- live·backtest 패리티: 같은 순수함수를 양쪽에서 호출 (`execution_rules`/`algorithms` 패턴).
- None→graceful: macro 필드 부재 시 기존 동작 유지.
- 채택 게이트: 그리드 → `walk_forward_validate.py` 패턴 6윈도 → `validation_stats.py` DSR/PBO.
  구조적 버그 수정(W2)은 DSR 불요(경제·논리 근거 우선).
- 라이브 반영 시 `PARAMS_VERSION` bump + [deploy-runbook](../operations/deploy-runbook.md) +
  배포 후 `paper_positions.params_version` 실제 라벨 확인(v25·v29 재발 이력).
- 커밋 전 `.venv/bin/python3 -m ruff check` + `pytest tests/test_arena_*.py`.

## 의존성·실행 순서

```
W1 비용 정합 ──┬──> W5 FNG 지속기간 A/B     (기울지 않은 하니스 필요)
W2 omnibus 패리티 ─┴──> W6 unknown 조이기 A/B  (동일)
W3 성과 회계 ──> W4 MFE 1m 정밀화            (현행 버전 필터 재사용)
W7 프로세스 방어 · W8 파킹 회계 — 독립, 병행 가능
```

---

## W1. 백테스트 비용 정합 — 기본값을 라이브 비용 모델과 일치 (P1, 공수 소)

### 현재 상태
- `src/arena/backtest.py:72-74` — `BacktestSettings` 기본값:
  `fee_bps=parameters.FEE_BPS(5.0)`, `slippage_bps=0.0`, `spread_bps_round_trip=0.0`
  → 왕복 비용 `2*(fee+slip)+spread` (`backtest.py:512`) = **10bps**.
- 정답은 이미 코드에 있음: `src/arena/frequency.py:235` —
  `_add_costs(LIVE_4H_PROFILE_ID, [("base", FEE_BPS, 1.0, 1.0, 0.0), ...])`
  = base 시나리오 왕복 **13bps** (fee 5/leg + slip 1/leg + spread 1 RT, arena-cost-v2와 일치).
- CLI 경로(`backtest.py:1455-1505`)는 cost scenario를 주입하지만, **분석 하니스 13곳이
  전부 bare `BacktestSettings()`로 호출** — wi_tuning.py:62, exit_tuning.py:125,
  fng_optimize.py:86, walk_forward_validate.py:104, ab_trailing_stop.py:62,
  backtest_with_macro_backfill.py:139·153, arena_status.py:466,
  target_exit_tuning.py:123, target_exit_walk_forward.py:113·118,
  backtest_report.py:88·103(주간 저장 백테스트도 동일!).

### 변경 설계
`backtest.py:73-74` 기본값 수정 (한 곳 수정으로 13곳 호출부 전부 정합):

```python
slippage_bps: float = 1.0            # base cost scenario(frequency.py)와 일치 — live 왕복 13bps
spread_bps_round_trip: float = 1.0
```

- 대안(기각): 하니스마다 cost scenario 주입 — 하니스가 늘 때마다 누락 재발. 기본값
  수정이 안전. `funding_buffer_bps_per_8h=0.0` 유지(현물 funding 0, 비용 모델과 일치).
- CLI 경로는 시나리오 값으로 덮어쓰므로 무영향(base 시나리오면 동일 값).

### 검증
1. `pytest tests/test_arena_backtest*.py` — 비용 10bps를 가정한 assert가 있으면 13bps로 갱신.
2. **회전 증가형 채택 2건 재검증** (결론 뒤집힘 여부가 이 항목의 본론):
   - P-A fng 목표배수: `walk_forward_validate.py --windows 6 --target fng_contrarian`
     (atr2.0 현행 vs atr1.0 vs off config 추가) — atr2.0 우위 유지 확인.
   - WI-7 omnibus target on/off: `wi_tuning.py` 패턴으로 `OMNIBUS_TARGET_EXIT_ENABLED` A/B.
     ⚠️ W2와 상호작용 — **W2 수정 후 함께 재실행**해야 진짜 결론.
3. 뒤집히는 항목이 있으면 해당 플래그 되돌림 + `PARAMS_VERSION` bump(별도 사이클).

### 완료 기준
기본값 13bps + 테스트 통과 + 재검증 2건 결론 문서화(유지 or 번복).

### ✅ 결과 (2026-07-15, W2와 함께 구현·검증)
- `backtest.py:73-74` 기본값을 `slippage_bps=1.0`·`spread_bps_round_trip=1.0`으로 수정
  (설계안 그대로) — 13곳 하니스 전부 자동 정합.
- 기존 테스트 중 기본값(10bps) 가정 2건 발견·수정: `test_arena_backtest.py`
  (`test_backtest_stop_loss_uses_intrabar_ohlc_and_live_cost_rule`, ret_pct -0.026→-0.0263),
  `test_arena_vnext_shadow.py`(`test_backtest_includes_funding_in_net_return`, trading_cost_pct
  0.001→0.0013·ret_pct 0.008→0.0077). 전 arena 테스트(133건) 통과, ruff 통과.
- **재검증 2건 결과 (13bps + W2 사이징 수정 동시 적용, master_20260710.parquet)**:
  ```
  P-A fng 목표배수:  OFF n=41 win=54% sum_w=+0.61  |  ON(atr2.0, 현행) n=51 win=59% sum_w=+2.45
    → ON 우위 유지 확인 (atr1.0/1.5는 wi_tuning.py 재실행에서도 atr2.0보다 열위, 결론 불변)
  WI-7 omnibus 목표가: OFF n=89 win=57% sum_w=-2.59  |  ON(atr1.0, 현행) n=97 win=62% sum_w=-1.43
    → ON 우위 유지 확인(Δ+1.15, W2 사이징 버그 수정 후에도 결론 불변)
  ```
- **결론: 두 채택 모두 번복 없음** — `PARAMS_VERSION` bump 불필요(파라미터 값 변경이 아니라
  분석 하니스 기본값 수정이므로 라이브 배포 대상도 아님, 백테스트 도구 전용 변경).
- `wi_tuning.py` 재실행 결과 `docs/arena/research/wi-tuning-results.json` 자동 갱신(13bps 기준).

---

## W2. omnibus 사이징 라이브/백테스트 패리티 버그 수정 (신규 발견, 공수 소) ⚡W1과 동시

### 현재 상태 (버그)
- 라이브: `scheduler.py:923-925` — omnibus 진입 시
  `position_weight *= omnibus_position_multiplier(macro, ind)` (UP=1.0/RANGE=0.40/REBOUND=0.25,
  `algorithms.py:707-723`).
- 백테스트: `backtest.py:_open_position()`(340~) — **이 multiplier를 적용하지 않음**
  (`grep omnibus_position_multiplier src/arena/backtest.py` → 0건). combined weight(0.25~0.7)
  그대로 사용.
- **영향**: 백테스트 omnibus 가중수익(`ret×weight`)이 RANGE 2.5배·REBOUND 4배 과대(이익·손실
  모두). WI-7 채택 근거(-6.24→-4.57)의 절대값이 부풀려져 있었음. 양쪽 arm이 같은 왜곡이라
  방향(Δ)은 유지됐을 가능성이 높지만 재확인 필요. 향후 모든 omnibus A/B 왜곡 원천.

### 변경 설계
`backtest.py:_open_position()` — combined weight 계산 블록(358-370) 직후, fng 분기(352-356)
바깥의 else 경로에만:

```python
if algo_id == "omnibus":
    position_weight *= algorithms.omnibus_position_multiplier(macro, frame.indicators)
```

scheduler와 동일 순수함수·동일 입력(macro, indicators) — 패리티 확보. 구조적 버그
수정이므로 DSR 게이트 불요.

**권장 리팩터(W5·W6 대비)**: multiplier 적용 지점이 scheduler·backtest 2곳으로 늘어나므로,
`algorithms.entry_size_multiplier(algo_id, macro, ind) -> float` 공용 함수 하나로 묶어
양쪽이 1줄씩만 호출하게 할 것 — W5(fng 지속기간)·W6(unknown 조이기) multiplier가 같은
지점에 쌓일 예정이라 패리티 지점을 1곳으로 고정하는 가치가 큼. 초기 구현은 내부에서
`omnibus_position_multiplier`만 호출.

### 검증
1. 백테스트 재실행 후 omnibus 트레이드의 `position_weight`가 RANGE/REBOUND 진입에서
   0.40/0.25배로 줄었는지 trade 레벨 확인(진입 시 `signal_reason` 또는 params_snapshot으로
   레짐 구분).
2. WI-7 on/off Δ 재계산(W1의 13bps와 함께) — Δ 부호 유지 확인. 뒤집히면
   `OMNIBUS_TARGET_EXIT_ENABLED` 재검토.
3. `pytest tests/test_arena_backtest*.py`.

### 완료 기준
백테스트 omnibus weight가 라이브와 일치 + WI-7 재검증 결론 문서화.

### ✅ 결과 (2026-07-15)
- `backtest.py:_open_position()`의 combined-weight `else` 분기 안에 설계안 그대로 1줄 추가.
  `entry_size_multiplier()` 공용 리팩터는 **하지 않음** — 설계 문서의 fallback 그대로
  "초기 구현은 omnibus_position_multiplier만 직접 호출"을 채택(W5·W6 착수 시 함수가
  실제로 필요해지는 시점에 리팩터, 지금은 최소 변경으로 리스크 축소).
- 신규 회귀 테스트 `tests/test_arena_backtest.py::test_omnibus_range_entry_applies_live_size_multiplier`
  추가 — RANGE 진입 시나리오로 `position_weight == 0.10`(combined 0.25 × RANGE배수 0.40)
  고정 검증. **수정 전 코드에 되돌려 실행해 실제로 실패(0.25)하는 것 확인 후 커밋** — 진짜
  회귀 테스트임을 확인.
- W1 결과에 병기한 대로 WI-7 on/off Δ 부호 유지 확인(+1.15, 번복 없음).

---

## W3. 성과 회계 분리 — 현행 버전 트랙레코드 (P0, 공수 소)

### 현재 상태
- `scripts/analysis/arena_status.py` — `_closed_trades()`(84)가 전 기간 청산 거래 로드,
  `_agg()`(170)로 섹션2 집계, `_mfe_mae()`(201)로 섹션3. params_version별 표는 이미
  존재하나 **메인 표·MFE가 전 버전 혼합** — 누적 -15.4%의 92%가 v14~v24 구버전 유산인데
  현행 로직 평가에 섞여 들어감(Tier2 기각 캠페인의 MFE 표본에도 구버전 포함됐었음).

### 변경 설계
1. `arena_status.py` 상단에 상수:
   ```python
   # 현행 로스터 기준 버전 — WI-1/7(v28)·P-A(v29) 등 구조 변경 이전 거래는 legacy로 분리.
   CURRENT_ROSTER_MIN_PARAMS = 26
   ```
   파서: `params_version` "arena-params-vNN" → `int(NN) >= CURRENT_ROSTER_MIN_PARAMS`.
   (경계 조정 논쟁 방지를 위해 상수 주석에 근거 명시. v26 = vix_rsi 히스테리시스 이후.)
2. 섹션2: 기존 전체 표 유지 + 바로 아래 "**현행(v26+) 서브테이블**" 추가(동일 `_agg` 재사용,
   필터만). 헤더 요약 2줄: `전체 누적 -15.4% (24건) | 현행 v26+ -1.3% (8건)` 형식.
3. 섹션3 MFE: 현행 버전 필터 행을 알고별로 병기 — 이후 청산 관련 판단은 이 행만 사용.
4. (선택, 별도) 대시보드 `arena/index.html` 거래 로그에 params_version 뱃지 — 프론트 작업,
   이번 범위 제외.
5. `.claude/skills/arena-status/SKILL.md` 출력 형태 절에 "현행 버전 우선 해석" 1줄 추가
   (스킬 유지보수 규약).

### 검증
실행해서 v26+ 소계가 params_version별 표 합산과 일치하는지 대조(현재 기준 8건 ≈ -1.3%).

### 완료 기준
`/arena-status` 출력에 전체/현행 분리 표기 + SKILL.md 갱신.

---

## W4. MFE/MAE 1m 정밀화 — 청산 스레드 진위 판정 (P2, 공수 소)

### 현재 상태
- 진단 소스가 4h봉 high/low(`arena_status.py:_mfe_mae`, `exit_tuning.py:_mfe_capture`) —
  이 진단이 Tier1·Tier2 두 캠페인을 발동시켰고 둘 다 기각. 4h high는 "실제로 잡을 수
  있었던 이익"을 과대평가할 수 있음(스파이크 후 즉시 반락).
- 1분 데이터 존재: `arena_realtime_feature_bars` — `data_lake.py:716` upsert,
  `window_start`·`last_price` 컬럼 확인(`replay_realtime_risk_gate.py:168`이 동일 컬럼 fetch).
  1분 윈도 집계(`realtime_market.py:flush`, 82~), 2.5만행+.

### 변경 설계
신규 스크립트 `scripts/analysis/mfe_1m.py` (arena_status 비대화 방지, 읽기 전용):
1. 대상: `paper_positions` closed + W3의 `CURRENT_ROSTER_MIN_PARAMS` 필터(임포트 재사용).
2. 거래별: `arena_realtime_feature_bars`에서 `window_start ∈ [open_time, close_time]`
   구간 `last_price` 시계열 로드 →
   `MFE_1m = max(price)/open_price − 1`, `MAE_1m = min/open − 1`,
   `포착률_1m = ret_pct / MFE_1m` (MFE > 0.3% 거래만, arena_status와 동일 정의).
3. 출력: 알고별 `n | MFE_4h | MFE_1m | 포착률_4h | 포착률_1m | 1m커버리지%` 비교표.
4. **커버리지 가드**: 수집기 재시작 갭 등으로 1m 윈도가 빈 구간 존재 —
   `커버리지 = 실제 윈도 수 / 예상 윈도 수(hold_hours×60)`, **<80% 거래는 제외**하고
   제외 건수 표기.
5. 해석 주의를 출력에 박제: `last_price`는 1분 윈도 종가 계열이라 4h high보다 보수적 —
   그러나 "1분 안에 반응해 잡을 수 있었던 가격"이라는 정의가 목적(실행 가능 이익)에
   더 정합.

### 판정 분기 (스크립트 출력 하단에 명시)
- 포착률_1m이 0 근처 이상(4h 대비 대폭 개선) → **청산 개선 스레드 종결 선언** —
  arena-exit-tuning SKILL.md에 종결 사유 추가, 이후 개선은 진입 품질(W5·W6)로 집중.
- 1m에서도 명확히 음수 → 그때 1m 근거로 청산 메커니즘 재설계(별도 설계 문서, 지금 범위 아님).

### 완료 기준
비교표 산출 + 판정 분기 중 하나 선택·문서 기록.

---

## W5. FNG 지속기간 피처 `fng_days_below_30` (P3, 공수 소~중) — W1·W2 선행 필수

### 근거
공포 1일차(뉴스 쇼크, 추가 하락 여지) vs N일 지속(매도 소진)의 평균회귀 품질 차이.
fng_contrarian은 현행 최다 진입 알고. 데이터는 parquet에 전량 보유 — 수집 작업 없음.

### 데이터 흐름 (전 구간 앵커)
```
risk_overlay.py (산출) → regimeRaw
  ├─ live:     scheduler._fetch_macro (scheduler.py:91) → macro dict
  └─ backtest: backtest_with_macro_backfill.build_macro_rows(:37)
               → backtest._macro_signal_from_snapshot (backtest.py:1043)
→ algorithms.py 사이징/게이트 → parameters.py 플래그
```

### 변경 설계
1. **산출** — `src/morning_brief/analysis/sentiment_join/risk_overlay.py`:
   fng 소스는 `df["fng_value"]`(line 163). `compute_regime_state()`의 regimeRaw
   dict(line ~231)에 추가:
   ```python
   "fng_days_below_30": _fng_streak_below(df.get("fng_value"), threshold=30.0),
   ```
   `_fng_streak_below`: 시계열 끝에서 역방향으로 `< threshold` 연속 일수(마지막 값이
   임계 이상이면 0). **lag 불요** — FNG는 발표 즉시 가용, 기존 `fng` 필드와 동일 취급
   (누수 아님). 결측일은 스트릭 중단으로 처리(보수적).
2. **backtest 백필**: `build_macro_rows`가 `compute_regime_state(window)`를 그대로 쓰므로
   자동 포함. `backtest.py:_macro_signal_from_snapshot`(1043)에 매핑 1줄 추가.
3. **live 매핑**: `scheduler.py:_fetch_macro` regimeRaw 매핑 블록(~133)에
   `"fng_days_below_30": raw.get("fng_days_below_30")` 추가.
4. **알고 배선** — 두 변형을 A/B (권장: 사이징형):
   - **사이징형(권장)**: fng는 `FNG_CONTRARIAN_PRICE_TRANCHES[0][1]`(0.15) 고정 사이징
     (`scheduler.py:911`, `backtest.py:354`)이므로 combined weight 경로가 아님 —
     **트랜치 가중을 균일 스케일**하는 헬퍼 `algorithms.fng_duration_scale(macro) -> float`
     (1일차 `FNG_DAY1_SIZE_MULT=0.5`, 2일+ 1.0, 필드 None이면 1.0):
     - live: `scheduler.py:911` `position_weight = tranche[0][1] * scale`
     - 물타기 추가 트랜치: `execution_rules.pending_price_tranches` 호출부에 동일 scale
       전달(라이브 `positions.maybe_scale_in_fng_price` + backtest
       `_maybe_scale_in_fng_sim`(:401) 양쪽) — **누적 비중 상한(VOL_WEIGHT_MAX) 로직이
       스케일 후 가중 기준으로 일관되는지 확인 필수**.
   - 게이트형: `fng_contrarian()`(algorithms.py:316)의 `fng < FNG_LONG_BELOW` 분기에
     `fng_days_below_30 >= FNG_DURATION_MIN_DAYS` 조건 추가. 거래수 급감 위험(WI-4 전례:
     거래 붕괴 → 검증 불능) — A/B에서 거래수 먼저 확인.
5. **파라미터**: `FNG_DURATION_FEATURE_ENABLED=False`(기본 off),
   `FNG_DURATION_MODE="sizing"|"gate"`, `FNG_DAY1_SIZE_MULT=0.5`, `FNG_DURATION_MIN_DAYS=2`.
6. **⚠️ R2 반영 지연**: regimeRaw 신규 필드는 morning-brief 파이프라인 재실행 후 R2
   latest.json에 반영 — 그 전 라이브는 None→scale 1.0 (기존 컨벤션, 무회귀).

### 검증 (13bps 하니스에서 — W1·W2 병합 후)
1. wi_tuning 패턴 A/B 스크립트(`FNG_DURATION_*` 오버라이드): 사이징 0.5/0.3 × 게이트
   N∈{2,3,5} 그리드 — fng sum_w·MFE·거래수 + 타알고 무회귀.
2. WF 6윈도(`walk_forward_validate.py`에 config 추가) → `validation_stats.py` DSR/PBO.
3. 통과 시: 플래그 on + `PARAMS_VERSION` bump + 배포 + 라벨 확인.

### 완료 기준
A/B·WF·DSR/PBO 결과 문서화(채택 or 기각 — 기각도 §0 목록에 등재).

---

## W6. unknown 레짐 사이징 조이기 (P4, 공수 소) — W1·W2 선행 필수

### 근거
라이브 손실 진입 레짐: fng 8건 중 unknown 5, vix_rsi 5건 중 unknown 4 (arena-status 섹션6).
백테스트 M-2에서 macd 손실 전원 unknown 진입. 게이트 **완화**는 금지(M-1)지만 **조이기**는
미검증. ⚠️ unknown이 전체 봉의 40%(M-2) — 게이트형은 거래 반토막이므로 **사이징형만** 설계.
⚠️ vix_rsi는 구조 필터 추가가 항상 악화였던 전례(WI-5 기각) — 알고별 독립 A/B, 기각 시 그
알고는 접는다.

### 변경 설계
1. `parameters.py`:
   ```python
   # unknown 레짐 진입 사이징 축소 — 기본 빈 dict(off). 검증 통과 알고만 항목 추가.
   UNKNOWN_REGIME_SIZE_MULT_BY_ALGO: dict[str, float] = {}
   ```
   (`TIME_STOP_HOURS_BY_ALGO`·`TARGET_EXIT_ATR_MULT_BY_ALGO`와 동일 범용 dict 컨벤션.)
2. `algorithms.py`: 순수함수
   ```python
   def unknown_regime_size_mult(algo_id: str, macro: dict) -> float:
       if macro.get("arena_regime_state") != "unknown":
           return 1.0
       return parameters.UNKNOWN_REGIME_SIZE_MULT_BY_ALGO.get(algo_id, 1.0)
   ```
3. 적용 지점: **W2에서 만든 `entry_size_multiplier()` 내부에 합성** — scheduler·backtest
   호출부 변경 없음(패리티 지점 1곳 유지). fng는 트랜치 경로(W5와 동일 지점)에도 적용.
4. 진단 가시성: `signal_reason.diagnostics`에 `size_mults: {...}` 기록(사후 분석용).

### 검증
알고별 독립 A/B: `{"fng_contrarian": 0.5}` / `{"vix_rsi": 0.5}` / `{"multi_factor": 0.5}`
각각 단독 → sum_w·MaxDD·거래수(사이징형이라 불변이어야 정상) → WF → DSR/PBO.
부수 효과: 이 A/B의 unknown 구간 성과 데이터는 SJM 승격 판단(M-3)의 "unknown 회피 가치"
정량 근거로 재사용.

### 완료 기준
알고별 채택/기각 문서화. 채택분만 dict에 등재 + PARAMS_VERSION bump.

---

## W7. 프로세스 방어 — PARAMS_VERSION 훅 + 주간 헬스체크 (P7, 공수 소, 독립)

### (a) PARAMS_VERSION pre-commit 체크
- 현재: `.pre-commit-config.yaml`에 local repo(ruff-format·ruff-check)만 존재. v25·v29
  두 차례 bump 누락으로 전후비교 오염.
- 설계: `scripts/hooks/check_params_version.py` + local hook 추가 —
  staged diff에 `src/arena/parameters.py`가 있고, 대문자 상수 할당 라인이 변경됐는데
  `PARAMS_VERSION` 라인은 미변경이면 exit 1 (메시지: "파라미터 변경 감지 —
  PARAMS_VERSION bump 필요. 의도적 생략이면 --no-verify").
  구현: `git diff --cached -U0 src/arena/parameters.py` 파싱, `^[+-][A-Z_]+\s*[:=]` 매치.
- 커밋메시지 대조 방식(commit-msg 훅)은 메시지에 버전을 안 쓰는 커밋을 못 잡으므로
  diff 기반 채택. 오탐(주석만 수정 등)은 --no-verify로 우회 가능하게 설계.

### (b) 주간 헬스체크 (로그가 아닌 실산출물 기반)
- 근거: "connected 로그 = 정상" 가정이 WI-9 59시간 무음 사망을 놓침. 산출물 카운트 기반
  체크 필요.
- 설계: `scripts/analysis/arena_health.py` (읽기 전용) — 체크 4종, 이상 시 exit 1:
  1. `arena_runs` 최근 24h 행 존재 (스케줄러 생존).
  2. 최신 `paper_positions.params_version` == `parameters.PARAMS_VERSION` (라벨 드리프트).
  3. `arena_macro_snapshots` 최신 `stale_hours < 48` (R2 파이프라인 생존).
  4. `arena_liquidation_bars` 카운트 — 현재 0건은 알려진 상태(warning만, P1-3 종결 전까지).
- 실행 채널 (결정 1개): **GH Actions 주간 cron 권장** — Supabase secrets가 이미 Actions에
  존재(fill-signal-outcomes 워크플로우), 실패 시 GH 알림 무료. 대안: EC2 systemd timer +
  `slack_notify.notify_error`(slack_notify.py:492) 재사용 — Slack 웹훅이 이미 배선돼 있어
  알림 품질은 이쪽이 위. **둘 중 택1은 착수 시 결정**(기본 권장: GH Actions).

### 완료 기준
(a) parameters.py 상수 변경 커밋에서 훅 발동 확인. (b) 주 1회 자동 실행 + 인위적 이상
(버전 라벨 불일치) 주입 테스트로 알림 확인.

---

## W8. 스테이블 파킹 회계 — 백테스트 회계부터 (P6-b, 선택, 공수 소)

### 근거
롱온리 현물의 하락장 이론적 최선 = 현금 0%. flat 기간 자본에 스테이블 파킹 수익(연 4~5%)을
부여하면 "쉬는 것"이 성과로 계상 — 실거래 전환 시 실제 가능한 구조라 페이퍼 회계로도 정당.

### 변경 설계 (백테스트만 — 대시보드 표기는 제품 결정 후 별도)
1. `BacktestSettings`에 `idle_yield_apr: float = 0.0` (기본 0 = 무변화).
2. 프레임 루프 equity 갱신 지점(`backtest.py:965-` for algo_id 블록)에서 포지션 없는
   알고에 4h분 복리: `equity *= 1 + apr × (4/(24×365))`. 부분 노출(weight<1)은 1차 구현에서
   무시(포지션 있으면 0) — 단순성 우선, 필요 시 `(1−weight)` 비례는 후속.
3. **트랙레코드 순수성**: `metrics`에 `idle_yield_contrib_pct` 별도 필드로 분리 기록 —
   알고 알파와 파킹 수익을 합산만 하면 알고 비교가 오염되므로 분리 표기 필수.
### 검증
apr=0.045로 176일 백테스트 → 노출률 낮은 알고(vix_rsi 11%, omnibus 7%)의
idle_yield_contrib ≈ 4.5%×(1−노출률)×기간비율 근사치와 일치 확인.

### 완료 기준
백테스트 metrics에 분리 계상 + 벤치마크 비교 시 주석. 대시보드 반영은 사용자 결정 대기.

---

## 착수 체크리스트 (사이클당 1항목)

```
[x] W1+W2 — 구현·테스트·재검증 완료 (2026-07-15). PARAMS_VERSION bump 불필요.
[ ] W3 → 실행 결과로 현행 트랙레코드 기준선 기록
[ ] W4 → 청산 스레드 종결 or 재설계 판정
[ ] W5 A/B (13bps 하니스) → 채택/기각
[ ] W6 A/B (알고별 독립)  → 채택/기각
[ ] W7-a 훅 · W7-b 헬스체크 (채널 결정 1개)
[ ] W8 (선택)
```

관련: [return-improvement-priorities-20260715](return-improvement-priorities-20260715.md),
[big-candle-no-pnl-diagnosis-20260715](big-candle-no-pnl-diagnosis-20260715.md),
[arena-exit-tuning SKILL](../../../.claude/skills/arena-exit-tuning/SKILL.md)
