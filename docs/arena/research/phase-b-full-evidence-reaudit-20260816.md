# Phase B 숏 후보 전체 재감사 — DSR 단일기준의 오적용 확인 (2026-08-16)

## 배경

사용자가 Phase B 1순환 "6알고 전부 기각"(2026-08-15) 결론에 세 가지를 지적했다:

1. 백테스트 구간이 하락장인데도 숏이 유의미하지 않았다는 게 이상하다.
2. 실제로 하려는 건 "무지성 숏"이 아니라 데이터로 롱/숏을 동적으로 선택하는
   건데, Phase B가 그 가설을 검증한 게 맞는지 이해가 안 된다.
3. 기각 기준 자체가 현물(그리드 탐색) 기준을 그대로 가져다 쓴 거 아니냐 —
   "선물인데 롱만 치는 게 말이 안 된다."

같은 날 저녁 [증거기준 프레임워크](evidence-criteria-framework-20260816.md)가
DSR은 "대규모 그리드 탐색 승자 선정용"이고, Phase B처럼 알고당 사전에 1~2개
사양만 정해놓고 도는 단일가설 검증에는 PSR+MinTRL이 맞는 도구라는 걸 이미
정립했었다. 하지만 그 재적용은 `vix_rsi`(ETH) 한 셀에만 하고 나머지 34셀은
"DSR 미달=기각" 상태로 방치돼 있었다 — 이게 지적 3번의 실체다.

## 실행

`scripts/analysis/phase_b_full_evidence_reaudit.py`(신규) — Phase B가 이미
확정한 6개 알고 × 3자산 × 2변형 = 36셀 전부를 그리드 탐색 없이 그대로
재실행하고, 셀마다 PSR·MinTRL(필요 최소 표본길이)·검출가능 최소SR을 계산해
"SR 자체가 음수(방향이 나쁨)" vs "SR은 양수인데 표본이 모자라 판정 불가" vs
"검정력 충분·판정 가능"으로 재분류했다. 코드·파라미터 변경 없음, 순수
재분석(사전 사양 재실행 + 통계 재해석).

**1차 실행 버그 발견·수정**: `macd_momentum` 6셀이 전부 SR=0.000·sum%=0.00%로
나와 재확인한 결과, 원본 `macd_momentum_short_backtest.py`가 TSMOM_NL 사이징의
음수클립 해제 몽키패치(`algorithms.tsmom_nl_position_multiplier = ..._abs`)를
`main()` 안에서만 적용하는데 이 재감사 스크립트가 그 함수를 직접 임포트해서만
쓰다 보니 몽키패치가 누락돼 모든 숏 포지션이 사이징 0으로 클립돼 있었다(=
포지션은 열렸지만 비중이 0이라 손익도 0). 재감사 스크립트에도 동일 몽키패치를
추가해 재실행 — "재검증 도구 자체도 검증해야 한다"는 걸 다시 확인한 사례.

## 결과 — 36셀 재분류

| 진단 | 셀 수 | 의미 |
|---|---:|---|
| SR음수(방향자체가 나쁨) | **22** | 표본과 무관하게 방향이 확실히 나쁨 — 기각 타당 |
| 검정력부족(판정불가) | **12** | SR은 양수인데 표본이 모자라 "엣지 없음"이라 말할 수 없음 — **원 문서가 "기각"으로 잘못 표기** |
| 검정력충분·판정가능 | **2** | `vix_rsi`/ETH(veto유지·veto제거) — 유일하게 제대로 검증된 통과 |

알고별 분포:

| 알고 | SR음수 | 판정불가 | 판정가능 | 최선 셀 |
|---|---:|---:|---:|---|
| macd_momentum | 1 | 5 | 0 | ETH veto제거 SR+0.080 n=112 (2.8x 더 필요) |
| regime_trend | 5 | 1 | 0 | SOL strict n=10 (1395x — 사실상 무의미) |
| multi_factor | 3 | 3 | 0 | BTC/ETH/SOL direction_soft 전부 양수, 15~33x 더 필요 |
| vix_rsi | 3 | 1 | **2** | **ETH 통과**, SOL veto유지 근접(2.8x) |
| fng_contrarian | 4 | 2 | 0 | SOL 양쪽 변형 양수, 1.9x/3.4x 더 필요 |
| omnibus | 6 | 0 | 0 | 전부 확실히 음수 |

전체 원시 데이터: `docs/arena/research/phase-b-full-evidence-reaudit-20260816.json`

## 지적 1 — "하락장인데 유의미하지 않다"에 대한 답

백테스트 구간(2025-04-16~2026-07-11)의 실제 buy&hold: **BTC -23.75%, ETH
+12.36%, SOL -39.27%**. 균일한 하락장이 아니었다 — BTC/SOL은 확실한 하락,
ETH는 오히려 상승. 그래서:

- `omnibus`(추세추종형 숏, STRUCTURAL_DOWN)는 BTC(-23.75%)·SOL(-39.27%) 같은
  **실제 하락장에서도 6셀 전부 확실히 SR 음수**다 — 이건 표본 문제가 아니라
  진짜 나쁨. 하락장에서 추세추종 숏이 안 먹히는 건 이상한 게 아니라 문헌에
  반복 보고되는 현상(모멘텀 크래시 — 급락 후 반등 시 숏이 정확히 최악의
  타이밍에 청산됨, 문헌은 이미 검토됨). "하락장인데 숏이 안 먹혔다"는 관찰이
  틀린 게 아니라, **추세추종 방식의 숏은 원래 하락장에서도 잘 안 먹힌다는 게
  이미 8/15 문헌조사의 핵심 결론이었다.**
- 반대로 `vix_rsi`(역발산형 숏, 과열 되돌림을 노림)는 ETH(+12.36%, 상승장)에서
  통과했다 — 상승장 안의 조정 국면을 잡아내는 거라 전체 추세 방향과 무관하게
  작동할 수 있는 메커니즘이라는 게 결과로도 확인된다.

즉 "하락장 유무"보다 **전략 유형(추세추종형 숏 vs 역발산형 숏)**이 훨씬 더
결정적이었다.

## 지적 2 — "동적 롱/숏 선택 아니었다"에 대한 답 (미해결로 남김)

이 재감사도 원 설계(`strategy_fns={algo_id: 숏전용함수}`)를 그대로 재실행한
것이라 이 문제는 **해소되지 않았다**. Phase B는 "이 알고가 기간 내내
숏미러로만 행동했다면"을 테스트했지 "평소 롱, 조건 맞을 때만 숏 추가"하는
실제 라이브 배선(동적 선택기)을 조인 백테스트로 검증한 게 아니다. 표본이
작았던 이유(n=5~171, 대부분 100 미만)의 상당 부분이 여기서 온다 — 숏 조건만
따로 떼어놓고 보니 발화 빈도 자체가 낮았던 것. 진짜 동적 시스템을 조인
백테스트로 돌리면 표본이 늘어날 여지가 있으나, 이번 재감사 스코프 밖이다.

## 지적 3 — "기각 기준이 못미덥다"에 대한 답

**맞았다.** 36셀 중 12셀(33%)이 "SR 음수라 기각"이 아니라 "표본 부족이라
판정 자체가 불가능"이었는데 원 문서(§8~13)는 전부 "❌기각"으로 기록했다.
특히 `multi_factor`(direction_soft, 3자산 전부 SR 양수)와
`macd_momentum`(veto제거, 3자산 전부 SR 양수)은 방향성 자체는 일관되게
좋았는데 n이 10~112라 검정력이 안 나온 것뿐이다 — "엣지가 없다"가 아니라
"몰랐다"가 정확한 진단이다.

## 다음 단계 후보 (미결정, 사용자 확인 필요)

1. **문서 정정만**: §8~13의 "❌기각" 표기를 12셀에 한해 "판정보류(증거부족)"로
   정정 — 코드/배포 변경 없음, 기록의 정확성만 개선.
2. **근접 후보 라이브 관찰**: 지적 2에서 나온 "동적 조인 백테스트가 답이 아닐
   수도 있다"는 점과, vision.md의 "정직한 표본 확보" 원칙에 따라 — 배수가
   낮은 근접 후보(macd_momentum ETH/SOL veto제거 2.8x/5.3x, vix_rsi SOL
   veto유지 2.8x, fng_contrarian SOL 1.9x/3.4x)를 meridian(D019)과 같은
   방식으로 사전 DSR 게이트 없이 페이퍼캐피털로 라이브 배선하고 e-value
   순차검정으로 축적 관찰한다.
3. **동적 조인 백테스트 구현**: 지적 2를 정면으로 풀기 위해 "롱 조건 유지 +
   숏 조건 추가"를 한 백테스트 실행에서 같이 도는 진짜 combined 함수를
   작성해 재검증한다(표본이 늘어날 가능성, 다만 구현 비용 있음).
4. **전부 보류**: 지금 결과로는 어느 쪽도 결정적이지 않으므로 아무것도
   바꾸지 않고 선물 트랙은 계속 vix_rsi(ETH)+meridian만 숏 참여로 유지한다.

## 재현

```bash
.venv/bin/python3 scripts/analysis/phase_b_full_evidence_reaudit.py
```

## 구현 — 근접 후보 라이브 배선 (arena-params-v41, 2026-08-16 같은 세션 후속)

사용자가 "근접 후보 라이브 배선(권장)"을 선택 — meridian(D019)과 동일하게
사전 DSR 게이트 없이 페이퍼캐피털로 실거래 배선하고 표본을 축적한다. 승격 대상:

- `macd_momentum`: BTC/ETH/SOL-PERP 전부(3자산 전부 SR 양수, veto제거 변형).
- `fng_contrarian`: SOL-PERP만(SOL만 SR 양수, BTC/ETH는 SR음수라 제외).
- `vix_rsi`: SOL-PERP 추가(기존 ETH 확정승격 D017과 별개 트랙).

`multi_factor`(15~33배 부족, 3자산 다 필요표본이 큼)·`regime_trend`(1395배,
사실상 무의미)는 이번엔 승격하지 않음 — 표본 부족 정도가 근접이라 부르기엔
너무 컸다.

**구현**: `algorithms.py`에 `macd_momentum_short`(§8 veto제거 설계)·
`fng_contrarian_short`(§13 veto유지 설계)·`tsmom_nl_position_multiplier_abs`
(숏 사이징, 음수클립 없는 abs 버전) 신규. `short_signals.PERP_SHORT_ALGORITHMS`에
둘 다 등록. `parameters.py`의 `PERP_SHORT_ENABLED_TRACKS`·`ALGORITHM_TRACK_SCOPE`
양쪽에 승격 트랙 추가(v39가 막았던 "숏 못 쓰는 spot 복제본" 문제가 이 트랙들만
해소됐으므로).

**direction-blind 결함 실제 수정**(Phase B §13이 실측했지만 "도달 불가능한 경로"라
방치했던 것 — 이번에 fng_contrarian_short를 실제로 배선하면서 도달 가능해져
방치할 수 없었음): v22 물타기(`FNG_CONTRARIAN_SCALE_IN_ENABLED`)·P-A
목표가익절(`FNG_TARGET_EXIT_ENABLED`)·`PRICE_STOP_DISABLED_ALGOS` 가격손절 면제
세 메커니즘 전부 `algo_id`로만 게이팅되고 `direction`을 안 봐서, 숏에 적용되면
(1) 사이징이 롱 전용 트랜치로 잘못 계산되고 (2) 목표가가 진입가 "위"에 잡혀
즉시 손실 확정되고 (3) 가격손절까지 면제돼 무방비 노출되는 3중 결함이었다.
`backtest.py`·`scheduler.py`·`stream.py` 세 파일 전부에 `direction=="long"`
게이팅을 추가해 숏은 표준 ATR손절+래칫트레일링+시간손절만 받도록 분리했다.

신규 테스트 25건(`test_arena_macd_momentum_short.py` 9·
`test_arena_fng_contrarian_short.py` 8·`test_arena_fng_short_direction_gating.py`
3 — 사이징·가격손절 정상작동·목표가익절 버그 회귀방지 각 1건씩·
`test_arena_meridian.py`/`test_arena_vix_rsi_short.py` 스코프 갱신 포함) +
기존 테스트 갱신 4건, arena 362개 전체 통과. `PARAMS_VERSION` v40→v41.

롤백: `PERP_SHORT_ENABLED_TRACKS`에서 macd_momentum 3개+fng_contrarian SOL+
vix_rsi SOL 제거, `ALGORITHM_TRACK_SCOPE`에서 확장분 제거(v39/v37 상태로
복귀). direction 게이팅 수정 자체는 숏 미사용 시에도 무해한 방어적 수정이라
되돌릴 필요 없음.
