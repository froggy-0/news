# "장대양봉인데 왜 수익률이 이런가" 진단 + 개선 계획 (2026-07-15)

> **질문**: 2026-07-14 12:00 UTC 4h봉이 +3.02%(62,845→64,744, 고가 64,966) 급등했는데
> 아레나 수익률은 왜 이 모양인가?
> **답**: 두 가지 별개 문제가 섞여 있다.
> 1) **그 캔들 자체는 참여 자격이 없었다** — 6개 알고 전부 게이트가 정상 작동해 의도적으로
>    쉬었고(레짐 분류기가 이 급등을 "약세장 내 숏스퀴즈성 반등"으로 정확히 판별), 이는
>    설계대로다.
> 2) **누적 수익률이 저조한 진짜 원인은 청산 품질** — 거래가 있었던 4개 알고 전부 MFE
>    포착률이 마이너스(이익이 났다가 도로 흘림). 이건 실제 개선 여지가 있고, 이미 설계는
>    있지만 아직 구현 안 된 상태다.

---

## 1. 그 캔들에 왜 아무도 안 탔나

### 1a. 캔들 자체 확인

| open_time (UTC) | O | H | L | C | 변화율 |
|---|---|---|---|---|---|
| 2026-07-14 08:00 | 62,561 | 62,923 | 62,500 | 62,845 | +0.45% |
| **2026-07-14 12:00** | **62,845** | **64,966** | 62,781 | **64,744** | **+3.02%** |
| 2026-07-14 16:00 | 64,744 | 64,897 | 64,232 | 64,570 | -0.27% |
| 2026-07-14 20:00 | 64,570 | 65,100 | 64,420 | 65,044 | +0.73% |

### 1b. 같은 시각 6개 알고 전부 skip (arena_decisions, 2026-07-14T12:05 UTC)

| 알고 | action | skipped_reason |
|---|---|---|
| regime_trend | flat_skip | `veto:bullish_regime` |
| fng_contrarian | flat_skip | `veto:not_risk_off` |
| vix_rsi | flat_skip | `veto:not_risk_off` |
| macd_momentum | flat_skip | `veto:not_risk_off` |
| multi_factor | flat_skip | `veto:not_risk_off` |
| omnibus | flat_skip | `veto:oversold_rebound_1of4votes` |

**해석**: 4h 로컬 레짐 분류기(`classify_regime()`)가 그 순간 시장을 **bull_trend가 아닌
risk-off/stress 계열**로 판정했다. 즉 규칙 그대로: `regime_trend`는 bull_trend가 아니라서
막히고, `fng/vix_rsi/macd/multi_factor`는 "risk-off가 아닐 것"을 요구하는데 오히려
risk-off라서 막혔다.

### 1c. 이 판정이 근거 없는 게 아니라는 증거 (같은 시각 macro, arena_macro_snapshots)

```
sjm_state: sjm_bear          ← 구조 레짐 모델도 여전히 약세로 판정
btc_above_ma200: 0.0         ← 200일선 하회
btc_drawdown_90d: -21.0%     ← 90일 낙폭 지속
breadth_up_ratio: 0.1        ← 상위10 알트 중 10%만 동반 상승(광범위 참여 아님)
taker_imbalance_zscore: -1.30 ← 테이커 순매도 우위(가격은 올랐는데 공격적 매수 우위가 아님)
long_short_ratio_zscore: -0.98 ← 숏 비중 평소보다 높음
oi_divergence_flag: 1        ← OI-가격 방향 불일치(레버리지 캐리 신뢰 낮음)
fng: 22 (극단적 공포)
```

**종합**: 가격은 3% 튀었지만 (a) 광범위 참여 부족(breadth 10%), (b) 공격적 매수가 아닌
순매도 우위(taker imbalance 음수), (c) 90일 하락추세·200일선 하회 지속. 전형적인
**약세장 내 숏커버링/데드캣 반등** 프로파일이다. 추세추종 알고(regime_trend,
macd_momentum)가 이런 캔들 하나로 진입했다면 오히려 칼받기였을 가능성이 높다.

### 1d. 이미 검증된 결론 (재작업 불필요)

[regime-macd-diagnosis-20260711.md](regime-macd-diagnosis-20260711.md)에서 동일 병목을
이미 진단했고, 게이트를 완화하는 A/B는 **전부 기각**됐다(승률·sum_w 전 변형 악화). 결론은
"무거래 = 정상 동작"이며, 유일한 구조적 개선 경로는 레짐 분류기 자체를 SJM으로 교체/앙상블
하는 M-3(진행 중, 판단일 2026-08-10). **지금 게이트 임계값을 다시 튜닝하는 것은 하지
않는다** — 표본 부족 상태에서의 재시도는 과적합만 만든다는 것이 이미 A/B로 확인됨.

---

## 2. 그럼 왜 누적 수익률 자체가 안 좋은가 (진짜 개선 여지)

`/arena-status` 결과 (2026-06-20~, 총 24건 청산):

| algo | n | win% | 가중합% | 기대값%/T | PF | MFE포착률 |
|---|---|---|---|---|---|---|
| regime_trend | 0 | - | 0 | 0 | - | - (무거래, 정상) |
| macd_momentum | 0 | - | 0 | 0 | - | - (무거래, 정상) |
| fng_contrarian | 8 | 25% | **-7.02** | -0.84 | 0.34 | **-37%** |
| vix_rsi | 5 | 20% | **-3.99** | -1.12 | 0.10 | **-34%** |
| multi_factor | 6 | 33% | **-4.40** | -0.92 | 0.09 | **-92%** |
| omnibus | 5 | 60% | +0.03 | +0.17 | 1.97 | +10%(참고: WI-7 적용 후 그나마 양호) |
| **buy&hold** | - | - | **+0.36%** | - | - | - |

**헤드라인**: 거래가 있었던 4개 알고 전부 MFE 포착률이 마이너스다. 이는 "한때 이익이던
포지션이 청산 시점엔 손실 또는 미미한 수익으로 끝났다"는 뜻 — 진입 방향은 맞았는데(MFE>0),
청산이 그 이익을 지키지 못하고 있다. 승률·PF가 낮은 것도 결국 같은 원인의 다른 증상이다.
buy&hold(+0.36%)조차 못 이기는 이유가 "시장을 못 읽어서"가 아니라 "이익을 흘려서"라는 뜻.

이 진단은 이미 [`arena-exit-tuning` 스킬](../../../.claude/skills/arena-exit-tuning/SKILL.md)
문서에 정량화돼 있다:

- **Tier 1 실측 완료** (`scripts/analysis/exit_tuning.py`, 시간배리어 그리드,
  코드 변경 없음): `vix_rsi`·`multi_factor`는 `TIME_STOP_HOURS`/`MIN_HOLD` 전 조합에서
  포착률이 **개선되지 않음**(-29~-92% 그대로 또는 악화). 이유: 시간 배리어는 "언제 접을지"만
  정할 뿐 "이익 난 순간을 붙잡는" 메커니즘이 아니기 때문 — 예측된 결과.
- **Tier 2 (미구현)**: `fng_contrarian`·`omnibus`만 목표가 익절(상단 배리어)이 있고
  `vix_rsi`·`multi_factor`·`regime_trend`·`macd_momentum`은 한 번도 이익목표 배리어를
  가져본 적이 없다. Triple-Barrier(Lopez de Prado) 관점에서 6개 알고 중 4개가 배리어를
  불균등하게만 갖춘 상태.

---

## 3. 개선 계획

### (A) "캔들 안 탄 것" — 액션 없음, 모니터링만

- 게이트 재튜닝 금지(1d 근거). regime-macd-diagnosis M-3(SJM 섀도우, 판단일 2026-08-10)이
  유일한 구조적 개선 경로 — 그때까지 대기.
- M-5 프로세스 유지: regime_trend/macd_momentum이 실제로 bull_trend 진입에 성공하면
  첫 5거래를 즉시 리뷰(진입 레짐 라벨·MFE 포착률·close_reason 대조).

### (B) MFE 포착률 마이너스 — **지금 실행 가능, 우선순위 1순위**

`vix_rsi`·`multi_factor`에 Tier 2(범용 목표가 익절)를 구현한다. 설계는
[arena-exit-tuning §Tier 2](../../../.claude/skills/arena-exit-tuning/SKILL.md)에 이미
있음 — 신규 설계 불필요, 구현만 남음:

1. `parameters.py`: `TARGET_EXIT_ATR_MULT_BY_ALGO: dict[str, float] = {}` (기존
   `TIME_STOP_HOURS_BY_ALGO`와 동일한 dict 패턴, 신규 알고는 항목 추가만).
2. `algorithms.py`: `atr_target_price(direction, entry_price, atr, mult) -> float` 공용
   순수함수 신설(fng/omnibus 기존 구현은 물타기·평단 재계산 복잡도 때문에 그대로 두고,
   vix_rsi·multi_factor만 신규 공용 경로 사용 — 무리한 리팩터보다 위험 최소화 우선).
3. `backtest.py` `_open_position()` + 메인 루프의 omnibus 전용 목표가 체결 블록을
   `algo_id == "omnibus"` 조건 제거하고 `position.target_price is not None` 조건으로 일반화.
4. live `stream.py` 1m 틱 경로도 동일 로직 일반화(패리티 유지).
5. `execution_rules.target_exit_triggered()`는 이미 순수함수라 재사용만.

**검증 절차** (기존 컨벤션 그대로): ATR 배수 2.0~3.0×에서 시작해 그리드 →
`walk_forward_validate.py` 롤링 윈도 → `validation_stats.py` DSR/PBO → 대상 알고
MFE 포착률·sum_w 개선 + 타 알고 무회귀 확인 → 통과 시 `PARAMS_VERSION` bump 후 배포.
⚠️ 목표가를 너무 타이트하게 잡으면 포착률은 오르지만 payoff가 무너져 기대값이 오히려
나빠질 수 있음 — sum_w·expectancy·payoff를 함께 확인할 것.

**표본 경고**: 현재 n=5~6건으로 매우 작다. 방향 가설로 다루고, 파라미터 확정은 반드시
위 검증 절차를 통과한 뒤에만.

### (B-1) 구현 완료 (2026-07-15) — Tier2 배선

`TARGET_EXIT_ATR_MULT_BY_ALGO` dict 패턴으로 위 5단계 전부 배선 완료(기본 빈 dict라
**현재 라이브 동작 변화 없음**):

| 파일 | 변경 |
|---|---|
| `parameters.py` | `GENERIC_TARGET_EXIT_ENABLED`(스위치) + `TARGET_EXIT_ATR_MULT_BY_ALGO: dict = {}` |
| `algorithms.py` | `atr_target_price(direction, entry_price, atr, mult)` 공용 순수함수 신설 |
| `backtest.py` | `SimPosition.target_price` 필드 + `_open_position()` 산출 + 메인 루프 청산 블록(omnibus/fng 블록과 동일 위치, `target_exit_triggered` 재사용) |
| `scheduler.py` | 진입 시 `signal_reason["target_price"]` 고정 저장 |
| `stream.py` | 1m 틱에서 목표가 도달 시 `close_reason="target_exit"` 청산(트레일링 체크보다 먼저) |
| `scripts/analysis/target_exit_tuning.py` | Tier2 전용 ATR배수 그리드 스크립트(exit_tuning.py 패턴 재사용, MFE 포착률 동시 출력) |

**초기 그리드 결과** (fresh macro, `master_20260710.parquet`, 1966봉, 단일 프레임 — 과적합 가능):

```
vix_rsi:      baseline n=20 win65% sum_w=+5.89 cap=-25%  |  atr1.5~3.0 전부 cap -24~-25%(변화 미미)
multi_factor: baseline n=65 win49% sum_w=+1.42 cap=-17%  |  atr1.5 n=70 win53% sum_w=+1.59 cap=-12%(방향 개선)
                                                              atr2.5 n=67 win48% sum_w=+0.05 cap=-22%(악화)
```

**해석**: 메커니즘 자체(배선)는 정상 동작 확인(타알고 sum_w 무변화로 격리 확인됨, mult에
따라 n·승률이 실제로 바뀜). 그러나 신호는 아직 결론을 낼 만큼 깨끗하지 않다 —
`vix_rsi`는 사실상 무효과(포착률 그대로), `multi_factor`는 atr1.5에서만 방향성 개선이고
atr2.5는 오히려 악화(비단조). 단일 프레임 그리드만으로는 채택 불가 → 아래 walk-forward로
검증했다.

### (B-2) Walk-forward + DSR/PBO 검증 (2026-07-15) — **결론: 기각**

신규 스크립트 `scripts/analysis/target_exit_walk_forward.py`(walk_forward_validate.py와
동일 원리를 `TARGET_EXIT_ATR_MULT_BY_ALGO` 일반 알고에 적용 — 기존 스크립트는 fng 전용
하드코딩이라 재사용 불가)로 6개 비중첩 윈도 검증 + `EquityPoint.realized_ret_pct`(프레임별
정렬 시계열, config 무관 항상 길이=frame수라 CSCV 요구사항 충족 — 트레이드 단위 배열은
config마다 체결수가 달라 정렬이 깨져서 부적합) 기반 DSR/PBO 계산.

```
vix_rsi (6윈도):
  baseline  평균+0.98 표준편차0.97 양의윈도4/6  (n동일: 4,1,7,0,5,3 — 전 config 거래수 불변)
  atr1.5~3.0 전부 양의윈도 4/6 그대로, 평균은 baseline 이하이거나 오차범위 내 동일
  → 목표가가 멀리 있어 거의 발동 안 함(체결 수 불변) + 발동 시 오히려 이익을 조기 캡

multi_factor (6윈도):
  전 config(baseline·atr1.5~3.0) 양의윈도 2/6로 동일, 평균 -0.05~+0.23(잡음 수준)
  → 단일 프레임에서 보였던 atr1.5 개선은 특정 구간에 몰린 결과, 6윈도 분해하면 재현 안 됨

DSR/PBO (validation_stats.py):
  vix_rsi:      best=atr2.5  DSR=0.580(<0.95 기준 미달)  PBO=0.877(≤0.2 기준 대폭 초과)
  multi_factor: best=atr3.0  DSR=0.178(<0.95 기준 미달)  PBO=0.921(≤0.2 기준 대폭 초과)
```

**결론**: 두 알고 모두 walk-forward 양의윈도 비율 개선 없음 + DSR·PBO 둘 다 기준 대폭
미달(PBO 0.88·0.92는 "그리드에서 고른 최선 config가 OOS에서 중앙값 이하로 떨어질 확률"이
88~92%라는 뜻 — 사실상 순수 잡음과 구분 불가). **`TARGET_EXIT_ATR_MULT_BY_ALGO`를
vix_rsi·multi_factor에 채우지 않는다.** 배선 코드는 기본 빈 dict로 유지(신규 알고나
다른 청산 메커니즘 재검토 시 재사용 가능하도록 코드는 남겨둠 — WI-4/5/6 "off 유지"와
동일 컨벤션).

**왜 실패했는지**: ATR 기반 목표가는 omnibus RANGE/REBOUND(평균회귀 진입, 목표가 도달이
논리적 종료점)·fng_contrarian(동일 논리 + 물타기 평단 재계산)에는 이론적으로 맞았지만,
`vix_rsi`(외생 매크로 필터, 추세 성분 있음)·`multi_factor`(레짐 필수화 이후 사실상
레짐 추종에 가까움)는 "정해진 반등 폭"을 가정할 이론적 근거가 약하다 — 이 두 알고의
MFE 포착률 문제는 **profit-target이 아니라 다른 메커니즘**(예: 손절/트레일 거리 자체
재검토, 혹은 애초에 표본 5~6건으로 청산 문제를 단정하기엔 이르다는 가능성)으로 접근해야
한다. 이번 검증으로 "Tier2 = vix_rsi·multi_factor 해법"이라는 가설 자체가 기각됨.

### (C) 실행 순서 요약

```
완료          Tier 2 배선(코드) — parameters/algorithms/backtest/scheduler/stream 전부. 기본 off.
완료·기각     Tier 2 ATR 목표가(vix_rsi·multi_factor) walk-forward+DSR/PBO 전멸(PBO 0.88·0.92)
              → 배포 안 함, 코드는 off 상태로 보존(재사용 가능)
다음 후보     vix_rsi·multi_factor MFE 포착률 문제는 profit-target 외 다른 접근 필요
              (손절/트레일 거리 재검토 또는 표본 축적 후 재진단) — 미착수
대기          M-3 SJM 섀도우 판단 (2026-08-10) — regime_trend/macd 무거래 문제의 유일 구조적 해법
프로세스      M-5 첫 5거래 리뷰 (강세장 진입 발생 시)
금지          게이트 완화 재튜닝 (A/B 전멸 확인됨, regime-macd-diagnosis 참조)
              Tier2 ATR 목표가 재튜닝(값만 바꿔서 재시도) — 이번 검증으로 가설 자체가 기각됨
```

---

관련 문서: [regime-macd-diagnosis-20260711](regime-macd-diagnosis-20260711.md),
[arena-exit-tuning 스킬](../../../.claude/skills/arena-exit-tuning/SKILL.md),
[remaining-improvements-20260710](remaining-improvements-20260710.md)
