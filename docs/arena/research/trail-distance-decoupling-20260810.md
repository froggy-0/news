# 트레일링 거리 분리(TRAIL_DISTANCE_MULT_BY_ALGO) — 설계·검증·기각 (2026-08-10)

## 배경

`/arena-status` 세션에서 "실거래가 4시간 주기에 갇혀있다"는 사용자 지적을 계기로 두 갈래로
분해했다: ① 진입·flat_signal 판정 자체가 4h봉 지표에 묶여 있음(미탐사, 1h 원본 데이터
자체가 없어 착수 전), ② 익절·청산의 실시간 반응성(1분틱 인프라는 이미 있음 — omnibus
target_exit·전 알고 트레일링스탑이 이미 라이브에서 1분틱으로 동작). 사용자가 ②부터
개선을 요청.

## 진단 (데이터로 확인된 사실)

BTC 청산거래(2026-08-10 시점) 중 MFE(보유중 최대유리이동)가 진입 시 손절거리(=현재
`trail_distance`)보다 작은 비율:

```
vix_rsi:      5/7  (71%)
multi_factor: 10/11 (91%)
```

`ratchet_trailing_stop()`은 `trail_distance`(=진입 시 손절거리 그대로)를 그대로 재사용해
`S_t = max(S_{t-1}, P_t − trail_distance)`로 래칫한다. MFE가 이 거리에 못 미치면 래칫이
이론상으론 아주 조금 움직여도 여전히 진입가 아래(손실구간)에 머물러 **이익을 전혀 잠그지
못한다** — 예: risk 3.0%인데 MFE 0.5%면 최고점에서도 래칫 스톱은 진입가 대비 −2.5%.

## 설계

Tier2(`TARGET_EXIT_ATR_MULT_BY_ALGO`, 전량 익절)는 "어디서 전량 청산할지" ATR 배수를
그리드 핏해 PBO 0.877~0.921로 기각됐다(과최적화). 이번 설계는 다른 실패모드를 피하려 함:
손절폭(리스크 관리, `stop_loss_price`)은 그대로 두고 **트레일링 거리만** 독립적으로 좁혀
래칫이 더 촘촘히 반응하게 한다 — 자유도 1개(배수), 상단을 캡하지 않아 "승자를 일찍
자르는" 부작용도 이론상 없음.

구현(전부 기본값 무효과, 하위호환):
- `parameters.TRAIL_DISTANCE_MULT_BY_ALGO: dict[str, float] = {}` (빈 dict=off)
- `execution_rules.trail_distance_from_stop(open_price, stop_loss_price, mult=1.0)` —
  `mult` 인자 추가(기본 1.0 = 기존 동작과 완전 동일)
- `backtest.py`/`positions.py` 두 호출부에서 `TRAIL_DISTANCE_MULT_BY_ALGO.get(algo_id, 1.0)`
  로 조회해 전달 (live·backtest 동일 배선)
- 그리드 하니스: `scripts/analysis/trail_distance_tuning.py` (exit_tuning.py 패턴 재사용)

## 그리드 결과 (단일 프레임, 2025-09~2026-08, macro 백필)

```
vix_rsi (baseline sum_w=-0.99%, 포착률-54%):
  mult 0.7~0.3 전부 sum_w 악화 또는 미미(-0.02~+0.04%p 수준 잡음), 포착률 -31~-64% 계속 음수
  mult 0.2: sum_w -8.10%(최악)

multi_factor (baseline sum_w=-1.76%, 포착률-56%):
  mult 낮출수록 단조 악화: 0.7→-3.14%, 0.5→-2.61%, 0.3→-8.86%, 0.2→-10.33%
  거래수도 47→86건으로 폭증(잦은 스톱아웃 후 재진입) — 포착률 개선 없이 회전만 증가
```

타알고 교차영향 없음(격리 확인 — 동일 프레임에서 대상 알고 외 5개 알고 거래열이
mult 변경 전후 완전히 동일함을 직접 대조 확인, `open_time` 시퀀스 100% 일치).

## 기각 사유

**전 구간·양쪽 알고 모두 개선 없음 — 트레일 거리를 좁힐수록 대체로 더 나빠진다.**
`_ratchet_sim_position()`이 봉 **종가** 기준으로만 래칫하는데(look-ahead 방지, 스톱
트리거 체크 이후 1회), 좁은 트레일 거리는 4h봉 단위의 정상적인 노이즈(고점 대비 되돌림)에도
쉽게 걸려 조기 손절되는 전형적 "트레일링스탑 휩소" 실패모드로 보인다 — 이익을 가끔
잠그는 이득보다 조기 스톱아웃으로 손실이 늘어나는 비용이 더 크다.

⚠️ **vix_rsi는 애초에 이 실험 대상이 아니었어야 함** — 2026-07-21 P2(1분 정밀화,
`docs/arena/research/arena-status-review-20260721.md#9`)에서 vix_rsi의 4h 기반 MFE
포착률 음수는 **해상도 아티팩트**(1분 재계산 시 −7%→+51%)로 이미 판정돼 exit-tuning
대상에서 제외(재시도 금지)된 알고다. 이번 세션에서 그 결론을 놓치고 재시도한 것 — 결과도
당연히 무의미(고칠 실제 문제가 없었음). multi_factor는 1분에서도 누출이 실재(−91%)로
재확인된 알고라 이번 실험 자체는 유효한 시도였으나, 이 특정 메커니즘(트레일 거리 좁히기)은
기각.

**남은 불확실성**: 이 그리드는 backtest의 봉 종가 기준 래칫으로 계산됐다. 라이브는
1분틱으로 연속 래칫하므로(휩소를 유발하는 "종가만 보고 판단"이라는 제약이 없음),
백테스트가 좁은 트레일의 휩소 리스크를 과대평가했을 가능성을 완전히 배제할 순 없다
(vix_rsi의 4h 진단 자체가 아티팩트였던 선례와 유사한 종류의 우려). 다만 이번 결과는
단일 지점이 아니라 mult 0.7~0.2 전 구간에서 **단조** 악화라 대체로 우연이 아닐 가능성이
높고, 1분 event-driven 백테스트를 새로 구축하는 것은 이 세션 범위를 크게 넘는 작업이라
보류. **채택하지 않음** — 재시도하려면 1분 해상도 시뮬레이션(새 인프라 필요)이나 완전히
다른 메커니즘(부분 익절 등)이 필요.

## 상태

- `TRAIL_DISTANCE_MULT_BY_ALGO`는 빈 dict(off) 유지, `PARAMS_VERSION` 변경 없음(라이브
  무영향).
- 배선(`execution_rules.trail_distance_from_stop`의 `mult` 인자, `backtest.py`/
  `positions.py` 조회부)은 하위호환·무효과라 재사용 가능하도록 코드에 보존
  (`TARGET_EXIT_ATR_MULT_BY_ALGO`와 동일 관례). 신규 테스트 1건
  (`test_trail_distance_from_stop_mult_scales_distance_default_unchanged`), arena
  221개 테스트 통과.
- 재현: `scripts/analysis/trail_distance_tuning.py --algo multi_factor`
