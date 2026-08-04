# 진입/보유 분리 — 코드베이스 기반 구현 계획 (2026-08-04)

> **상태: ✅ 구현·검증 완료 (2026-08-04). 판정: 4개 변형 전부 기각, 플래그 비활성 유지.**
> 코드(플래그·분기·테스트·A/B 하니스)는 전부 구현·통과했으나, 실제 A/B 백테스트에서
> 명목상 개선 2건이 통계적 재검증(특이성 비교·부트스트랩)을 통과하지 못해 **활성화하지
> 않기로 결론**. 상세: §6. 인프라는 보존(재사용·후속 알고 확장 가능).
>
> **⚠️ 이 문서의 가장 중요한 내용은 §1이다** — 설계 문서의 의사코드가 실제 코드와
> 다른 지점 5건을 코드 확인으로 찾아 정정했다. §1을 읽지 않고 설계 문서만 보고
> 구현하면 동작하지 않거나 의도와 다르게 동작한다.

---

## 0. 범위

| 포함 | 제외 |
|---|---|
| `regime_trend` 청산 히스테리시스 설계·작업분해 | 구현·커밋·배포 |
| 변형 A(상태 유지) / 변형 B(Donchian 하단) 양쪽 | `macd_momentum`·`omnibus` 확장(후속) |
| 테스트·A/B 검증 계획 | 실제 A/B 실행 |
| 코드 앵커 확정, 설계 오류 정정 | PARAMS_VERSION bump 여부 확정(§7-3) |

---

## 1. 설계 문서 대비 정정사항 (코드 실측) — **필독**

설계 문서 §6이 "구현 시 실제 필드명을 코드에서 재확인해야 한다"고 남긴 항목을 실제로
확인한 결과, **5건의 불일치**를 발견했다.

### 1-1. `ema200` → **`ema_200`** (필드명 오류)
설계 §4.2 의사코드는 `ind.get("ema200")`을 썼으나 실제 키는 **`ema_200`**
(`indicators.py:477`). 그대로 구현하면 항상 `0.0`을 반환해 조건이 무력화된다.

### 1-2. `above_ema200_4h`는 단순 비교가 아니라 **레짐 조건부 게이트**
실제 구현은 `not _below_ema_trend_strict(ind, macro)`(`algorithms.py:150-159`):

```python
def _below_ema_trend_strict(ind, macro) -> bool:
    if macro.get("arena_regime_state") == regime.REGIME_BULL_TREND:
        return False          # ← bull_trend에서는 게이트 자체를 적용 안 함
    return _below_ema_trend(ind)   # close < ema_200
```

**`bull_trend` 레짐에서는 이 조건이 무조건 통과**한다(중복 필터 회피, arena-params-v20).
따라서 보유 조건에 넣어도 강세장에서는 아무 제약이 되지 않는다 — 설계 §4.2가 기대한
"MA200 상회 유지"라는 방어 효과는 **bull_trend 밖에서만** 작동한다. 이 비대칭을
인지하고 넣어야 한다.

### 1-3. `ema_aligned_up`은 **정배열 + 기울기** 2조건
실제: `ema_fast > ema_slow and ema_fast_slope > 0`(`algorithms.py:345`). 설계
의사코드는 `ema_fast > ema_slow`만 썼다. 보유 조건으로 쓸 때 `ema_fast_slope > 0`까지
요구하면 **횡보 구간에서 기울기가 자주 뒤집혀 조기청산이 재발**할 수 있다.
→ 보유 조건에서는 **정배열만 요구하고 기울기는 제외**하는 것을 1차안으로 권장
(진입은 현행 유지). 이것 자체가 A/B 변형 대상(§4-2 변형 A2).

### 1-4. `regime_trend` 진입 조건은 7개가 아니라 **12개**
설계 §2 표는 `explain_signal`이 상승장 창에서 **실제로 실패를 기록한** 7개만 보여준다.
실제 시그널 함수(`algorithms.py:347-360`)와 `explain_signal`(`:1021-1049`)은 12개를
평가한다. 나머지 5개(`etf_outflow_not_heavy`, `taker_confirms`, `volume_confirms`,
`lsr_not_crowded`, `oi_not_diverged`)는 **2023-2024 백테스트 창에서 macro 결측으로
전부 자동통과**했기 때문에 실패 목록에 안 나타난 것이다(ETF는 2024-01 이전 상품
부재, OI/LSR은 Binance 30일 보존 한계 — historical-bull-market-backtest 문서 §4).

**함의**: §2의 "지속확률" 측정은 **12개 중 7개만 관측된 상태**다. 라이브·최근
데이터에서는 나머지 5개도 활성이므로, 이들이 보유 판정에 들어가면 조기청산의
새 원인이 될 수 있다. → **보유 조건에서 5개 전부 제외**(진입 전용)를 기본안으로
하되, `_lsr_crowded`·`_etf_outflow_heavy`는 risk-off류 방어이므로 §4-1의
"즉시청산, 양보 없음" 그룹에 넣을지 별도 판단 필요(§7-1 미결정).

### 1-5. `backtest.py` 호출부가 **2곳**
`exit_hold_override`는 backtest에서 두 번 호출된다:
- **`backtest.py:843`** — spot 경로(`product_decision.should_close` 분기). 현재
  `TARGET_PRODUCT="spot"`이므로 **실제로 타는 경로**.
- **`backtest.py:889`** — 비-spot 경로(`signal is None` 분기, `exit_reason="signal_flat"`).

live는 `scheduler.py:808` 1곳. **테스트는 세 경로 모두 커버해야 패리티가 보장된다.**

---

## 2. 변경 대상 (확정된 코드 앵커)

| # | 파일 | 앵커 | 변경 성격 |
|---|---|---|---|
| A | `src/arena/parameters.py` | `MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED`(:328) 인근 | 플래그 3개 신설 |
| B | `src/arena/algorithms.py` | `exit_hold_override()`(:886), `macd_momentum` 분기(:932) 뒤 | `regime_trend` 분기 추가 |
| C | `tests/test_arena_algorithm_diagnostics.py` | `test_vix_rsi_exit_hold_override_hysteresis`(:172) | 신규 테스트 추가 |
| D | `scripts/analysis/` | `wi_tuning.py` 패턴 | A/B 스크립트 신설 |

**변경 불필요(확인 완료)**:
- `spot_policy.py` — 훅이 이미 호출부에 배선돼 있어 무변경
- `scheduler.py` / `backtest.py` — 호출부 3곳 모두 기존 배선 그대로 사용
- `indicators.py` — `donchian_lower`가 이미 산출됨(`:482`), 변형 B도 신규 지표 불필요

---

## 3. 플래그 설계 (§2-A)

```python
# P1(2026-08-04): regime_trend 청산 히스테리시스 — 진입조건(이벤트 포함)이 곧 보유조건인
#   구조 분리. donchian_breakout 지속확률 30.1%(이벤트)인데 보유 판정에 재사용돼
#   진입 12회 중 9회가 다음 봉에 조기청산(entry-exit-separation-design-20260804.md §2).
#   근거: MOP 2012(JFE) 추세 지속 1~12개월 vs 실측 중앙보유 8h.
REGIME_TREND_EXIT_HYSTERESIS_ENABLED = False
REGIME_TREND_EXIT_MODE = "state"       # "state"(변형A) | "donchian_exit"(변형B)
REGIME_TREND_EXIT_DONCHIAN_PERIOD = 10 # 변형B 전용: 청산용 하단 채널(진입 20 < 청산 10)
```

**기본값 전부 off/현행유지** — 기존 WI 플래그 관례(`VOLUME_CONFIRM_ENABLED=False` 등)와
동일. 플래그가 꺼져 있으면 `exit_hold_override`가 기존과 100% 동일하게 동작해야 한다
(무회귀 테스트 §5-1).

⚠️ **변형 B 주의**: `REGIME_TREND_EXIT_DONCHIAN_PERIOD=10`은 `indicators.compute()`가
산출하는 `donchian_lower`(period=`DONCHIAN_PERIOD`=20)와 **기간이 다르다**. 현재
지표는 20봉 하단만 제공하므로 변형 B는 둘 중 하나를 택해야 한다:
- **B-1(권장·저비용)**: 기존 `donchian_lower`(20봉) 그대로 사용, 신규 파라미터 불필요
- **B-2**: `indicators.compute()`에 `donchian_lower_exit`(10봉) 추가 산출 —
  `indicators.py` 변경 필요, 프레임 재빌드 필요

→ **1차 A/B는 B-1로 진행**(코드 변경 최소). B-1이 유망하면 B-2로 기간 최적화.

---

## 4. `exit_hold_override` 분기 설계 (§2-B)

### 4-1. 공통 골격 (기존 3개 분기와 동일 패턴)

```python
if algo_id == "regime_trend" and parameters.REGIME_TREND_EXIT_HYSTERESIS_ENABLED:
    # 양보 없는 즉시청산 (vix_rsi:897-900, fng:914-915와 동일 원칙)
    if _is_risk_off(_regime_state(macro)):
        return False
    if _breadth_collapsed(macro) or _stablecoin_contracting(macro):
        return False
    # ... 모드별 분기 (4-2 / 4-3)
return False
```

### 4-2. 변형 A — 상태 조건 유지 (`REGIME_TREND_EXIT_MODE == "state"`)

§1-1~§1-4 정정을 반영한 조건 집합:

| 조건 | 보유 판정 포함? | 근거 |
|---|---|---|
| `donchian_breakout` | ❌ **제외** | 지속확률 30.1% = 이벤트(설계 §2) |
| `ema_fast > ema_slow` | ✅ 포함 | 지속확률 87.2%, 추세 골격 |
| `ema_fast_slope > 0` | ⚠️ **A1 제외 / A2 포함** | §1-3 — 조기청산 재발 우려로 A/B 분리 |
| `adx >= ADX_TREND_MIN` | ✅ 포함 | 지속확률 97.9% |
| `not _below_ema_trend_strict` | ✅ 포함 | §1-2 — bull_trend에선 무조건 통과 |
| `rsi < TREND_CORE_RSI_LONG_MAX` | ✅ 포함 | 지속확률 97.8%, 설계 §2.2(효과 작음) |
| `not _funding_hot` | ✅ 포함 | 지속확률 99.2% |
| 나머지 5개(etf/taker/volume/lsr/oi) | ❌ **제외** | §1-4 — 관측 공백 + 진입 전용 성격 |

→ **A1**(기울기 제외)과 **A2**(기울기 포함) 두 변형을 A/B에서 병행.

### 4-3. 변형 B — Donchian 하단 이탈 (`REGIME_TREND_EXIT_MODE == "donchian_exit"`)

```python
close = ind.get("close", 0.0)
dc_lower = ind.get("donchian_lower", 0.0)
if dc_lower <= 0:
    return False          # 지표 미산출 시 기존 동작(즉시청산) 유지 — graceful
return close > dc_lower   # 하단 이탈 전까지 무조건 보유
```

**단순함이 장점**: 상태 조건을 하나도 안 보고 "반대편 채널 이탈"만 본다(터틀 원형,
설계 §4.4-c). 파라미터 수가 최소라 과최적화 위험이 가장 낮다.

### 4-4. 두 변형의 공통 안전장치 (기존 인프라, 변경 불필요)

- **하방**: 래칫 트레일링 스톱(`execution_rules.ratchet_trailing_stop`) — 현재 발동률
  1.2%로 사문화 상태였으나 이 변경으로 실제 작동 여지 생김
- **손절**: ATR 기반 `stop_loss` 그대로
- **보유 상한**: `MIN_HOLD_HOURS["regime_trend"]=12.0`은 **최소** 보유라 상한이 아님.
  → `TIME_STOP_HOURS_BY_ALGO`에 `regime_trend` 항목이 **없다**(현재 `fng_contrarian`
  60h만). 무한 보유 방지 장치가 없으므로 **시간손절 추가 여부는 §7-2 미결정**.

---

## 5. 테스트 계획 (§2-C) — ✅ 완료 (2026-08-04)

`tests/test_arena_algorithm_diagnostics.py:172`의 `test_vix_rsi_exit_hold_override_hysteresis`
패턴을 그대로 따랐다(`monkeypatch.setattr(parameters, ...)` — 파일 내 기존 관례 확인
후 계획의 `_params` contextmanager 대신 채택, §1 수준의 정정).

### 5-1. 무회귀 — ✅
`test_regime_trend_exit_hold_override_disabled_by_default` — 플래그 off 시 항상 False.
전체 arena 테스트 156개(기존 150 + 신규 6) 통과, ruff 통과.

### 5-2. 변형 A 단위 테스트 — ✅
`test_regime_trend_exit_hold_override_variant_a_state_conditions` — 상태조건 전부 참+
donchian 미참조 → hold. EMA역배열/ADX약화/RSI과열/funding과열 각각 → 청산.

### 5-2b. A1/A2 슬로프 분기 — ✅
`test_regime_trend_exit_hold_override_variant_a_slope_ab` — 계획대로 A1/A2 결과가
갈림을 확인(같은 ind에서 슬로프 음전 시 A1=hold, A2=청산).

### 5-3. 변형 B 단위 테스트 — ✅
`test_regime_trend_exit_hold_override_variant_b_donchian_exit` — 하단 위/이탈/미산출
3케이스 전부 계획대로.

### 5-4. 즉시청산 양보 없음 — ✅
`test_regime_trend_exit_hold_override_no_hysteresis_bypass` — risk-off·breadth붕괴·
stablecoin수축 3케이스.

### 5-5. 경로 패리티 (§1-5) — 별도 테스트 미추가, 근거 확인
`exit_hold_override(algo_id, macro, ind)`는 순수함수이고 3개 호출부
(`scheduler.py:808`, `backtest.py:843`, `backtest.py:889`) 전부 동일 시그니처로
직접 호출 — 로직 분기가 호출부에 없다. 기존 `vix_rsi`/`fng_contrarian`/`macd_momentum`
히스테리시스도 함수 단위 테스트만 있고 3경로 통합테스트가 없는 것과 동일 수준 —
**기존 관례와 일관되게 별도 경로별 테스트는 추가하지 않음.** (통합 레벨 검증은 §6의
A/B 백테스트가 backtest.py 경로를 실제로 태우므로 자연히 커버됨.)

---

## 6. A/B 검증 결과 — ✅ 실행 완료 (2026-08-04). **판정: 4개 변형 전부 기각**

### 6-1. 하니스 — ✅
`scripts/analysis/regime_trend_exit_tuning.py` 신설(`wi_tuning.py`의
`@contextmanager _params(**overrides)` 패턴 재사용). `/tmp/bullval/macro_rows.json`
(상승장, 세션 내 보존됨 — 재생성 불필요했음)과 `build_macro_rows(master_20260710.parquet)`
(하락장)을 함께 로드해 5변형(baseline/A1/A2/B1/control) × 2창을 자동 비교.

⚠️ **실행 중 발견한 방법론 버그**: 최초 실행 시 하락장 창을 `from_date`/`to_date` 없이
`limit=2000`만으로 호출했더니 "최신 2000봉"이 의도한 2024-11~2026-07 20개월이 아니라
2025-09~2026-08의 **다른(더 급락한, buy&hold −43.44%) 최근 11개월 창**을 잡았다.
`priority-analysis-20260725.md`/root-cause 문서와 다른 창으로 비교하는 오류였음 —
`--bear-from 2024-11-09 --bear-to 2026-07-25 --bear-limit 4000`으로 명시 고정해
재실행(buy&hold −16.19%, 기존 문서의 −16.29%와 정합 확인 — 재현성 검증 완료).

### 6-2. 실측 결과

**상승장(2023-08-04~2024-07-31, BTC +126.97%)** — frames=2172:

| variant | n | win% | sum_w_ret% | PF | 중앙보유h | 최대보유h | 엣지bp | 엣지/비용 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 11 | 54.5 | −1.18 | 0.63 | 12.0 | 12.0 | −5.2 | −0.95 |
| A1(상태·기울기제외) | 10 | 50.0 | −1.59 | 0.44 | 16.0 | 32.0 | −10.5 | −1.94 |
| A2(상태·기울기포함) | 10 | 50.0 | −1.59 | 0.44 | 16.0 | 32.0 | −10.5 | −1.94 |
| B1(Donchian하단) | 10 | 20.0 | −4.49 | 0.18 | **70.0** | **104.0** | −39.4 | −7.29 |
| control(MIN_HOLD만 24h) | 10 | 50.0 | **+0.07** | **1.10** | 24.0 | 28.0 | +6.1 | **1.14** |

**하락장(2024-11-09~2026-07-25, BTC −16.19%)** — frames=3737:

| variant | n | win% | sum_w_ret% | PF | 엣지/비용 |
|---|---:|---:|---:|---:|---:|
| baseline | 16 | 25.0 | −4.65 | 0.40 | −3.87 |
| A1/A2(동일) | 16 | 37.5 | **−2.09** | 0.65 | −1.20 |
| B1 | 16 | 31.2 | −4.63 | 0.48 | −3.86 |
| control | 16 | 37.5 | −4.62 | 0.45 | −3.84 |

**"양쪽 창 동시 개선"(§6-3 기준2) 자동판정**: A1/A2/B1 **전부 ❌**(상승장 악화 또는
하락장 무변화). `control`은 스크립트의 자동비교 루프 밖이라 수동 계산 필요 — 아래 §6-3.

### 6-3. 통계적 검증 — **표면적 개선 2건 모두 노이즈로 판명**

raw 숫자만 보면 두 가지가 유망해 보였다: (a) 상승장 `control`(+1.25%p, PF 0.63→1.10,
처음으로 손익분기 상회), (b) 하락장 `A1`(+2.56%p). 둘 다 **추가 검증에서 기각**했다:

**(a) 특이성 검증** — "MIN_HOLD 2배 상향"을 다른 5개 알고에도 똑같이 적용:

| algo | baseline | 2×MIN_HOLD | Δ |
|---|---:|---:|---:|
| multi_factor | +5.47% | +11.32% | **+5.86** |
| macd_momentum | +0.33% | +2.27% | +1.93 |
| **regime_trend(대상)** | −1.18% | +0.07% | **+1.25** |
| omnibus | −4.79% | −4.26% | +0.53 |
| fng_contrarian | +2.17% | +1.56% | −0.61 |
| vix_rsi | 0.00% | 0.00% | 0.00 |

`regime_trend`의 개선폭(+1.25)이 6개 알고 중 3위 — **오래 들고 있으면 좋아지는 건
이 상승장 구간의 일반적 시장베타 효과지, regime_trend 설계와 무관.** 오히려
`multi_factor`가 4.7배 더 크게 개선됨.

**(b) 하락장 A1 부트스트랩** — baseline 거래풀 95% CI(5,000회 재표본):
`[−10.80%, +1.68%]`. A1 결과(−2.09%)가 **이 구간 안**에 있음 → baseline 노이즈와
통계적으로 구분 불가.

### 6-4. 최종 판정 — §6-3(구 계획) 기준 적용

| 변형 | 엣지/비용≥1 | 양쪽창 개선 | 노이즈와 구분 | **채택** |
|---|:---:|:---:|:---:|:---:|
| A1 | ❌(둘 다 <1) | ❌ | ❌(하락장 개선이 CI 안) | ❌ |
| A2 | ❌ | ❌ | ❌(A1과 동일 결과) | ❌ |
| B1 | ❌❌(최악) | ❌ | — (개선 자체가 없어 불필요) | ❌ |
| control | 상승장만 ✅ | 형식상 ✅(수치는 미미) | ❌(다른 알고가 더 크게 개선) | ❌ |

**4개 변형 전부 기각.** 가장 근접했던 `control`도 "regime_trend 고유의 개선"이 아니라
"이 특정 상승장 구간의 일반 효과"로 판명돼 채택 근거가 없다.

### 6-5. 부가 관찰 (기각과 별개로 기록할 가치)

- **B1(Donchian 하단 이탈)이 가장 나쁘다** — 상승장에서 중앙보유 70h·최대 104h로
  급등 후 조정까지 다 물고 있다가 손실로 청산되는 패턴. "반대편 채널까지 버틴다"는
  터틀 원형이 이 자산·이 파라미터(20봉)에서는 손절선이 너무 멀다는 뜻 — 더 짧은
  하단 기간(예: 10봉, 원래 계획서 §3의 문헌 원형)으로 재시도할 여지는 남아있으나
  이번 라운드 범위 밖.
- **A1=A2 항상 동일** — `ema_fast_slope>0` 조건이 이 두 창에서 한 번도 결과를 가르지
  않았다. 실질적으로 사문화된 파라미터일 가능성 — 단 표본이 작아(n=10~16) 확정 아님.
- **`regime_trend`는 표본 자체가 극소**(상승장 n=10~11, 하락장 n=16) — 어떤 개선을
  시도해도 통계적 확정이 어려운 알고라는 게 이번 라운드의 메타 결론에 가깝다.

---

## 7. 미결정 사항 — ✅ 착수 결정 완료 (2026-08-04)

1. **`_lsr_crowded`·`_etf_outflow_heavy`를 보유 판정에 넣을지** → **결정: 제외**(1차안
   그대로). 2023-2024 창에서 관측 불가라 백테스트로 판정 못 하므로 A/B 대상에서 뺀다.
   라이브 shadow 관찰 후 별도 판단.
2. **`regime_trend` 시간손절 추가 여부** → **결정: 1차 구현에 추가하지 않음.** 근거
   없는 신규 파라미터 선제 추가는 피한다(트레일링이 이미 하방 방어). A/B에서 변형 B가
   비정상적으로 긴 보유를 만드는지 관찰(§6-4에 보유시간 분포 지표 추가)하고, 문제가
   실측되면 그때 근거를 갖고 추가. **라이브 활성화 전에는 재검토 필수**(무제한 보유는
   운영 리스크).
3. **PARAMS_VERSION bump 여부** → **결정: 구현 단계(플래그 off)에서는 bump 안 함.**
   W1/W2 선례 따름. A/B 통과 후 활성화 시점에만 bump.
4. **DSR의 시행횟수(N) 입력값** → **결정: 이번 라운드는 보류.** P4 감사(별도 과제)와
   연동 필요해 범위 밖. 이번 A/B는 DSR 없이 §6-3의 엣지/비용·양쪽창 통과·순열검정
   3개 기준으로만 판정(허용 가능한 축소 — 표본이 원래 작아 DSR 신뢰도도 낮았을 것).

---

## 8. 리스크

| 리스크 | 완화 |
|---|---|
| 보유 연장이 하락장에서 손실 확대 | 트레일링·손절 유지(§4-4), 하락장 창 필수 통과(§6-2) |
| `regime_trend` n=8~11로 표본 극소 | 순열검정(§6-3), 단독 채택 금지 — `macd_momentum` 확장 결과와 함께 판단 |
| §1-4의 5개 조건이 라이브에서만 활성 | 백테스트 통과해도 **라이브 shadow 관찰 기간** 확보 후 승격 |
| 과최적화(변형 5개 비교) | §7-4의 N 정직 반영, PBO 기준 유지 |

---

## 9. 작업 순서 요약 — 전부 완료, 최종 판정 기각

```
[선결] §7 미결정 4건 판단                        ✅ 완료
   ↓
1. parameters.py 플래그 3개 (기본 off)          ✅ 완료 — §3
2. algorithms.exit_hold_override regime_trend 분기 ✅ 완료 — §4
3. tests 무회귀 + 변형별 단위(6건)               ✅ 완료 — §5 (156개 arena 테스트 전체 통과)
4. scripts/analysis/regime_trend_exit_tuning.py  ✅ 완료 — §6-1
5. 상승장 macro_rows                             ✅ 세션 내 보존, 재생성 불필요
6. A/B 실행 (4변형 × 2창 + 특이성/부트스트랩 검증) ✅ 완료 — §6-2~6-4
   ↓
[판정] 🔴 4개 변형(A1/A2/B1/control) 전부 기각 — §6-4
   근거: 엣지/비용<1(A1/A2/B1) 또는 개선이 통계적으로 다른 원인에 귀속(control),
         A1의 하락장 개선은 baseline 부트스트랩 95%CI 안(노이즈와 구분 불가)
   → 플래그 REGIME_TREND_EXIT_HYSTERESIS_ENABLED=False 유지. 활성화 안 함.
   → PARAMS_VERSION bump 없음(§7-3 결정대로 — 미활성 상태이므로 해당 없음).
   ↓
[코드 처리] 인프라는 보존(Tier2 선례와 동일 — "off 유지, 코드는 재사용 가능하게 보존")
   ↓
[후속 검토 필요] regime_trend는 표본이 구조적으로 작아(§6-5) 이 알고 단독으로는
   추가 개선 시도의 통계적 확정이 어려울 수 있음. macd_momentum(히스테리시스 이미
   구현됨, 플래그만 뒤집으면 됨 — 코드 작업 없이 바로 A/B 가능)으로 먼저 넘어가는
   것을 권장. omnibus는 원인분해(root-cause §7-1) 선행 필요.
```

## 10. 최종 요약 (`regime_trend`)

**코드 변경 사항(전부 커밋 가능 상태, 라이브 동작 무변경)**:
- `src/arena/parameters.py` — 플래그 3개 추가(기본 off)
- `src/arena/algorithms.py` — `exit_hold_override()`에 `regime_trend` 분기 추가
- `tests/test_arena_algorithm_diagnostics.py` — 단위 테스트 6건 추가
- `scripts/analysis/regime_trend_exit_tuning.py` — A/B 하니스 신규(재사용 가능 자산)

**연구 결론**: 설계(§4)와 문헌 근거(§4.4)는 타당했으나, **이 알고(`regime_trend`)의
표본 크기(n=10~16)에서는 어떤 변형도 통계적으로 유의한 개선을 만들지 못했다.**
표면적 개선 2건 모두 재검증(특이성 비교·부트스트랩)에서 걸러졌다 — 이는 root-cause
문서의 P4(과최적화 감사) 우려가 실제로 유효했음을 이번 라운드에서 직접 확인한
것이기도 하다: **명목상 개선이 진짜 엣지인지 노이즈인지는 반드시 재검증해야 한다.**

---

## 11. `macd_momentum` 확장 — ✅ 실행 완료 (2026-08-04). **판정: 기각**

§9의 후속 권고에 따라 진행. `macd_momentum`은 히스테리시스가 **이미 구현돼 있어**
(`algorithms.py:930-941`, `MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED` 플래그만 뒤집으면
됨) 신규 변형 설계가 불필요 — regime_trend보다 작업 범위가 작았다.

### 11-1. 착수 전 지속성 진단 (§2 방법론 재적용)

```
              상승장(2023-08~2024-07)      하락장(2024-11~2026-07)
h>0(레벨)     참인봉1079  지속확률92.0%     참인봉1885  지속확률92.5%
h>h_prev(델타) 참인봉1063  지속확률73.8%     참인봉1870  지속확률75.1%

진입 다음봉 조건이탈 1위: macd_hist_increasing(델타) — 39.5%(상승장)/34.8%(하락장)
  (2위 대비 3배 이상 — 압도적 1위, regime_trend의 donchian_breakout과 동일 패턴)
```

**기존 코드 설계가 이미 옳은 방향이었다** — `exit_hold_override`가 보유판정에서
`h>h_prev`(델타, 저지속성)를 빼고 `h>0`(레벨, 고지속성)만 본다. regime_trend에
새로 설계해 넣은 것과 동일한 원칙을 이 알고는 처음부터 갖고 있었다는 뜻.

### 11-2. A/B 결과 — 그런데도 성적은 나쁘다

`scripts/analysis/macd_momentum_exit_tuning.py` 신설, 동일 2창 실행:

**상승장(BTC +126.97%)**:

| variant | n | win% | sum_w_ret% | PF | 중앙보유h | 최대보유h | 엣지/비용 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 64 | 46.9 | +0.33 | 1.07 | 8.0 | 20.0 | 1.09 |
| hysteresis | 51 | 35.3 | **−4.36** | 0.85 | **24.0** | **120.0** | −0.57 |

**하락장(BTC −16.19%)**:

| variant | n | win% | sum_w_ret% | PF | 중앙보유h | 최대보유h | 엣지/비용 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 47 | 42.6 | −0.19 | 0.89 | 8.0 | 20.0 | 0.93 |
| hysteresis | 33 | 45.5 | +0.60 | 0.96 | 28.0 | 156.0 | 1.30 |

**상승장에서 뚜렷하게 악화**(+0.33%→−4.36%p, 최대보유가 20h→120h로 6배 폭증 —
히스토그램이 결국 되돌리는 전체 사이클을 다 물고 있다가 손실 확정). 하락장은
명목상 개선(+0.79%p)했으나:

### 11-3. 통계적 검증 — 양쪽 다 기각

- **부트스트랩**: 상승장 hysteresis(−4.36%)는 baseline 95%CI [−7.65,+9.10] **안**
  (악화조차 노이즈와 구분 안 됨). 하락장 hysteresis(+0.60%)도 baseline 95%CI
  [−7.53,+7.86] **안**.
- **특이성**: 하락장에서 "MIN_HOLD만 2배" control이 **+2.66%p**로 히스테리시스
  (+0.79%p)의 3.4배. 상승장에서는 방향까지 갈린다 — control은 **+1.93%p 개선**하는데
  히스테리시스는 **−4.69%p 악화**. 같은 "더 오래 들고 있기"인데 정확히 어떻게
  청산 타이밍을 잡느냐(고정 시간 vs "h>0 동안 무기한")에 따라 정반대 결과.

### 11-4. 해석 — regime_trend와 다른 실패 양상

이벤트/상태 분리 원칙(§2/§11-1)은 진단으로서는 맞았다. 그런데 "상태 조건이
지속되는 동안 무기한 보유"라는 **처방**이 문제다 — MACD 히스토그램은 결국
평균회귀하는 오실레이터라, `h>0`이 92% 지속된다는 건 "한 봉 뒤에도 대개 참"이라는
뜻이지 "긴 사이클 내내 참"이라는 뜻이 아니다. 실제로 최대보유가 120h/156h까지
늘어난 사례들이 전체 성적을 깎았다 — **상한 없는 히스테리시스가 오실레이터형
지표에는 부적합**하다는 뜻으로 해석된다(regime_trend의 EMA/ADX 같은 준-단조 상태
지표와의 차이).

**판정: 기각.** 플래그 `MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED`는 `False` 유지
(기존과 동일 — 이번 라운드는 활성화 여부를 재확인한 것, 코드 변경 없음).

### 11-5. 다음 알고 권고 재검토

당초 순서(regime_trend → macd_momentum → omnibus)에서 **2연속 기각**이 나왔다.
공통점: 둘 다 추세·모멘텀형이고 표본이 작지 않음(macd n=47~64)에도 히스테리시스
연장이 도움이 안 됐다 — "청산을 늦추면 나아진다"는 전제 자체가 이 두 알고 유형에는
안 맞을 가능성. `omnibus`로 넘어가기 전에 **root-cause 문서 §7-1(omnibus 원인분해)이
먼저 필요**하다는 우선순위가 이 결과로 강화됨 — 같은 처방(히스테리시스)을 세 번째
알고에 기계적으로 반복하기보다, omnibus는 원인부터 다시 진단하는 쪽을 권장.

---

## 12. `omnibus` 원인분해 — ✅ 완료 (2026-08-04). **판정: 이 문서의 처방 대상 아님**

root-cause 문서 §7-1(omnibus 원인분해)을 §11-5 권고에 따라 수행. **결론: regime_trend·
macd_momentum과 겉증상(flat_signal 지배)은 같지만 근본원인이 다르다 — 이벤트/상태
분리로는 해결되지 않고, 별도 갈래(손절폭)의 문제다.**

### 12-1. 레짐/신호 지속성 — 앞의 두 알고와 다른 패턴

| | 지속확률 | 진입 다음봉 신호 유지 |
|---|---:|---:|
| regime_trend `donchian_breakout` | 30.1%(이벤트) | 9/12(75%) 단일조건이 지배적으로 소멸시킴 |
| macd_momentum `h>h_prev` | 74%(델타) | 51/129(39.5%) 단일조건이 1위로 소멸시킴 |
| **omnibus 레짐(UP/RANGE/DOWN)** | **72~84%(상태에 가까움)** | **51~55%(거의 동전던지기, 분산됨)** |

omnibus의 레짐 분류 자체는 이벤트가 아니라 이미 상태에 가깝다(72~84% 지속). 진입
신호가 다음 봉에 사라지는 비율도 51~55%로, **어느 한 조건이 지배적으로 죽이는
패턴이 아니라 여러 조건에 걸쳐 분산**돼 있다 — "이 조건 하나만 보유판정에서 빼면
된다"는 regime_trend/macd_momentum식 명확한 처방이 성립하지 않는다.

### 12-2. 레그별·청산사유별 분해 — 진짜 손실원은 다른 곳

**서브레그별(3레그 전부 PF<1)**:

| leg | 상승장 n/PF/sum% | 하락장 n/PF/sum% |
|---|---|---|
| UP_TREND | 41 / 0.84 / −2.21 | 55 / 0.89 / −2.99 |
| RANGE | 23 / **0.31** / −1.49 | 27 / 0.47 / −1.62 |
| DOWN_TREND(REBOUND) | 59 / 0.82 / −1.09 | 134 / 0.88 / −2.05 |

**청산사유별(양쪽 창 공통 패턴)**:

| exit_reason | 비중 | 평균수익 | 성격 |
|---|---:|---:|---|
| flat_signal | 65~72% | **−0.07~−0.19%**(거의 0) | 많지만 얕음 |
| target_exit | 20~24% | **+1.34~+1.41%** | 잘 작동(WI-7 재확인) |
| **stop_loss** | 6~7% | **−3.55~−3.75%** | **적지만 깊음** |
| **trailing_stop** | 2~4% | **−3.37~−3.70%** | **적지만 깊음** |

`flat_signal`이 건수는 압도적이지만 건당 손실은 거의 0에 가깝다. **실제 손실을
만드는 건 소수(9~11%)의 `stop_loss`/`trailing_stop`인데 건당 −3.4~−3.75%로
`target_exit`의 이익(+1.4%)을 몇 배로 상쇄한다.** 이는 청산 *타이밍*(언제 나가나)이
아니라 청산 *가격*(손절이 얼마나 타이트한가)의 문제 — 이 문서(§4)의 진단 대상인
"이벤트를 상태로 오용"과는 다른 층위.

### 12-3. 기존 선례와의 정합성

`CLAUDE.md` 기록: omnibus REBOUND 레그에서 이미 "가격손절 제외+시간손절"(이 문서의
히스테리시스와 유사한 접근)을 시도한 바 있음 — 전체는 개선(−6.71→−4.69%)됐으나
**전/후반 분할 검증에서 개선이 전반부에만 몰리고 후반 10개월은 무개선**이라
채택하지 않음(2026-07-25). 이번 §12-1/12-2 진단이 그 이유를 설명한다 — 애초에
omnibus의 문제가 청산 타이밍이 아니라 손절폭이었다면, 타이밍을 만지는 시도가
불안정한 결과를 내는 게 당연하다.

### 12-4. 판정 — 이 문서의 범위 밖, 별도 스레드로 분리

**regime_trend·macd_momentum에 썼던 처방(exit_hold_override 히스테리시스)을
omnibus에 세 번째로 기계적으로 적용하지 않는다.** 근거: (1) 진단이 다른 패턴을
가리킴(§12-1), (2) 유사 시도가 이미 한 번 불안정한 결과로 기각된 전례(§12-3),
(3) 2연속 기각 이후 세 번째 기계적 반복은 근거보다 관성에 가까움.

**후속 과제로 분리 제안(이 문서·이 세션 범위 밖)**: 손절폭(`ATR_MULTIPLE`,
`STOP_LOSS_MIN_PCT`/`MAX_PCT`) 튜닝, 특히 RANGE 레그(PF 0.31로 최악)의 손절 로직
재검토. 새 진단 문서로 시작해야 함 — 이 문서의 이벤트/상태 분리 프레임은 이
문제에 적용되지 않는다.

---

## 13. P1 라운드 종합 (2026-08-04 종료)

| 알고 | 처방 | 결과 |
|---|---|---|
| `regime_trend` | 신규 구현(A1/A2/B1) | ❌ 기각 — 개선 2건 모두 재검증 탈락 |
| `macd_momentum` | 기존 구현 활성화만 | ❌ 기각 — 상승장 악화, 하락장은 노이즈 |
| `omnibus` | (처방 시도 안 함) | 원인 자체가 다름 — 손절폭 문제로 재분류, 별도 스레드 |
| `omnibus`(후속) | DOWN_TREND 레그 국소 손절 재설계(변형X) | ❌ 기각 — [omnibus-stop-distance-design-20260804.md §8](omnibus-stop-distance-design-20260804.md) |

**이 라운드의 실질적 산출물은 "채택된 개선"이 아니라 "제거된 가설"이다.** 세
알고 모두에서 "청산을 진입조건과 분리/지연하면 나아질 것"이라는 root-cause
문서(P1)의 핵심 가설을 실측으로 검증했고, regime_trend·macd_momentum에서는
기각됐으며 omnibus에서는 애초에 적용 대상이 아님이 밝혀졌다. `flat_signal`
지배 현상 자체(root-cause §2.2)는 여전히 사실이지만, **그 해법이 "보유 조건
재정의"라는 이번 가설은 3개 알고 전부에서 기각**됐다 — root-cause 문서의 P1을
이것으로 종결하고, 남은 레버(P2 엣지/비용을 다른 방식으로 올리는 법, P4 과최적화
감사, 그리고 이번에 새로 발견된 omnibus 손절폭 문제)로 넘어가야 한다.

**omnibus 손절폭 후속(2026-08-04, 같은 세션)도 기각.** §12가 재분류한
"DOWN_TREND 레그 국소 손절 재설계"(변형X: 가격손절 제외+시간손절, fng_contrarian
v22 원칙의 레그 단위 재적용)를 실제 구현·검증까지 진행했으나 부트스트랩 CI
탈락 + 상승장 전/후반 불일치 재발로 기각됨(상세: omnibus-stop-distance-design
§8). 특이성 체크는 완전 통과해 레그 격리 메커니즘 자체의 정확성은 확인됐고,
그 결과 2026-07-25 실패의 "레그 혼합" 원인 가설이 반증되었다는 새 사실이
확보됨 — DOWN_TREND 레그 손실의 원인은 손절 스위치가 아니라 레그 자체의
기간별 비정상성(non-stationarity)일 가능성이 더 높다. **P1 라운드 최종 전적:
청산 타이밍/손절폭 조정 계열 가설 4건 전부 기각(0/4)** — "청산 정책 조정"으로
는 접근 가능한 레버가 이 세션 기준 소진됐다고 봐야 한다.

## 관련 문서
- [entry-exit-separation-design-20260804.md](entry-exit-separation-design-20260804.md) — 설계·문헌근거(이 문서가 구현으로 번역)
- [root-cause-diagnosis-where-to-look-20260803.md](root-cause-diagnosis-where-to-look-20260803.md) — P1 진단, 엣지/비용 기준
- [historical-bull-market-backtest-20260803.md](historical-bull-market-backtest-20260803.md) — §6-2 상승장 데이터 재현 명세
