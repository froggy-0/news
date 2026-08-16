# 동적 롱/숏 결합 백테스트 — 지적 2 해소 결과 (2026-08-16)

## 배경

지적 2("무지성 숏이 아니라 동적 선택 아니냐")에 답하기 위해 Phase B의 격리
숏전용 테스트 대신, 실제 라이브 배선(`short_signals.resolve()`가 매 사이클
롱함수·숏함수를 둘 다 평가해 동적 합성)을 그대로 재현한 결합 백테스트를
실행했다(`scripts/analysis/joint_long_short_backtest.py`). 롱·숏 핵심조건이
구조적으로 상호배타임을 코드로 확인해(문턱값이 겹치지 않음 — macd_momentum
s>0/s<0, fng_contrarian FNG<30/FNG>70, vix_rsi vix_now<임계/>=같은임계)
`resolved = long_signal or short_signal` 단순 결합이 `resolve()`의 비충돌
분기와 동치임을 검증한 뒤 진행했다(스크립트 docstring 참조).

## 결과 — 결합하면 대부분 악화, 일부는 순손실로 반전

| 조합 | long_only | short_only(Phase B) | **combined(실제 라이브)** |
|---|---:|---:|---:|
| macd_momentum/BTC | -3.56%(DSR0.231) | +4.01%(DSR0.783) | +2.28%(DSR0.623) |
| macd_momentum/ETH | -1.45%(DSR0.377) | +6.16%(DSR0.835) | +4.35%(DSR0.704) |
| macd_momentum/SOL | -5.50%(DSR0.136) | +3.77%(DSR0.762) | **-1.02%(DSR0.447)** |
| fng_contrarian/SOL | -17.97%(DSR0.052) | +2.23%(DSR0.634) | **-15.74%(DSR0.112)** |
| vix_rsi/SOL | -0.03%(DSR0.498) | +5.37%(DSR0.838) | +4.51%(DSR0.686) |
| **vix_rsi/ETH**(D017 확정승격) | -10.36%(DSR0.068) | **+11.09%(PSR0.970·MinTRL충족)** | **-0.50%(DSR0.478)** |

**핵심 발견**: 6개 조합 전부 `long_only`가 확실히 음수다(이 알고들이 perp에서
롱온리로는 원래 안 좋다는 v39의 원 판단과 일치). 문제는 `combined`가
`short_only`보다 6개 중 6개 전부 나쁘고, 그중 3개(macd/SOL·fng/SOL·**vix_rsi/ETH**)는
순양(+)에서 순손실로 반전됐다는 것 — 알고가 롱·숏을 같은 슬롯에서 공유하다
보니, 확실히 나쁜 롱 쪽이 자본회전(트레이드 기회)을 잠식해 좋은 숏 쪽의
기여를 희석시키거나 완전히 뒤집는다.

**가장 심각한 사례**: `vix_rsi/ETH`는 Phase B 전 과정에서 유일하게 엄밀한
채택기준(PSR≥0.95·MinTRL충족)을 통과해 **오늘 낮에 이미 확정 승격**(D017
경로, v37)한 알고인데, 결합 백테스트에서는 DSR 0.970→0.478로 추락하고
부호까지 반전(+11.09%→-0.50%)된다. **즉 오늘 아침의 "확정 승격" 판정 자체가
지적 2와 동일한 사각지대(격리 숏만 검증, 결합 효과 미검증)에 있었다** —
이번 재검증으로 처음 드러남.

## 해석

- 숏 신호 자체의 통계적 성질(PSR·DSR)은 격리 테스트가 정확히 측정했다 —
  문제는 신호 품질이 아니라 **"같은 알고 슬롯이 롱·숏을 공유"하는 구조**다.
  롱이 이 알고들에겐 이미 확인된 손실 유발원인데, 결합 배선이 그 손실
  기회를 그대로 살려둔 채 숏만 얹은 셈이라 순효과가 희석되거나 반전된다.
- `_combined()` 래퍼는 `resolve()`와 동치임을 코드로 검증했으므로(위 배경
  참조), 이 격차는 백테스트 방법론 문제가 아니라 **지금 라이브에 배선된
  실제 로직의 성질**이다 — 즉 지금 EC2에서 실제로 이렇게 동작 중이다.

## 다음 단계 (사용자 결정 필요, 코드 변경 전)

이 발견은 오늘 배포한 v41(macd_momentum·fng_contrarian SOL) **및 이미
살아있던 v37(vix_rsi ETH)** 둘 다에 해당한다. 후보:

1. **숏 전용으로 좁히기(롱 차단)** — 이 트랙들에서 롱 신호를 무시하고 숏만
   실행하도록 배선 변경(`resolve()`에 `long_enabled` 플래그 추가 또는 track
   scope에서 롱 차단). short_only 통계를 그대로 보존.
2. **전면 롤백** — v37/v41 승격을 전부 되돌리고 해당 트랙을 무배선(perp
   미참여) 또는 스코프 재검토.
3. **표본 확대 관찰** — 페이퍼캐피털이라 즉시 손실은 없으니 combined 상태로
   더 관찰(단, vix_rsi/ETH는 이미 확정승격 근거가 무너진 상태라 관찰만으론
   근거 회복 안 됨 — 표본이 지금 이 백테스트 결론을 뒤집을 근거는 없음).

코드·파라미터 변경 없음(진단만).

## 재현

```bash
.venv/bin/python3 scripts/analysis/joint_long_short_backtest.py
```

## 구현 — 숏 전용 트랙 전환 (arena-params-v42, 같은 세션 후속)

사용자가 "이 트랙들을 숏 전용으로 전환(권장)" 선택. `short_signals.resolve()`에
`long_enabled: bool = True` 매개변수 추가 — False면 알고의 기존 롱함수가
"long"을 반환해도 무시하고 숏 신호만 실행한다. `parameters.
PERP_LONG_BLOCKED_TRACKS`(신규, `PERP_SHORT_ENABLED_TRACKS`와 동일한 6개
트랙)와 `perp_long_enabled()` 헬퍼로 게이팅, `scheduler.py`의 `resolve()`
호출부에 배선. 신호 함수·`PERP_SHORT_ENABLED_TRACKS`·`ALGORITHM_TRACK_SCOPE`는
무변경 — 진입 스코프 자체는 유지하고 방향만 숏으로 제한한다.

이 조치의 기대 효과는 위 표의 `short_only` 열을 그대로 복원하는 것과
수학적으로 동치다(롱을 차단하면 결합 신호가 곧 숏 신호이므로) — 별도
재백테스트 없이 검증 가능.

**라이브 현황 확인**: 배포 직전 조회한 6개 트랙의 오픈 포지션 중 4건이
차단 전 롱(fng_contrarian/SOL, macd_momentum/SOL, vix_rsi/ETH, vix_rsi/SOL —
전부 v41 이전인 2026-08-15에 열린 레거시)이었다. 롱 차단은 신규 진입만
막고 기존 포지션 관리 로직(손절·트레일링·flat청산)엔 영향이 없으므로,
이 레거시 롱들은 다음 사이클부터 알고가 더 이상 롱 신호를 못 내
정상적인 flat_signal 경로로 청산되고 재진입하지 않는다 — 별도 처리 불필요
(v39 스코프 변경 때와 달리 "고아 포지션" 문제가 아니라 의도된 청산).

신규 테스트 6건(`test_arena_short_signals.py` 2·`test_arena_perp_policy.py` 2·
버전 하드코딩 1 등) 포함 arena 366개 통과, ruff clean. `PARAMS_VERSION`
v41→v42. 롤백: `PERP_LONG_BLOCKED_TRACKS`를 빈 frozenset으로.
