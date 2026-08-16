# meridian perp 3자산 상관관계 진단·수정 (2026-08-16)

## 배경

사용자 질문("선물 기준으로 가장 심각한 알고리즘 하나")에 답하며 라이브 DB(`paper_positions`,
perp 트랙 시작 2026-08-15)를 직접 조회한 결과, `meridian`의 BTC/ETH/SOL perp 포지션 3건이
전부 `active_leg=reversion`(FNG<30 하나)으로 **같은 4h봉에 동시 진입**한 것을 확인했다.
`_meridian_active_leg()`의 역발산 leg가 FNG/VIX라는 자산 무관 매크로 트리거만 보고 발화해,
아레나의 "자산×알고 독립" 설계 원칙(포트폴리오 리스크 v2)이 meridian에서는 사실상 깨져
있다는 게 핵심 문제였다.

## 1차 시도 — 역발산 leg 모멘텀 안정화 게이트 (기각 아님, 부분 채택)

`fng_contrarian`/`vix_rsi`가 실제 진입함수에서 쓰는 `_momentum_not_worsening()`
(macd_hist 직전봉 대비 개선 확인)을 meridian 역발산 leg에도 적용 — 원래 설계문서가
"핵심조건만 재사용"하며 이 조건을 빠뜨렸던 것을 바로잡는 취지였다.

20개월 macro 백필(`master_20260710.parquet`, BTC/ETH/SOL) 백테스트 결과:

| | BTC n(rev/trend) | ETH n(rev/trend) | SOL n(rev/trend) | BTC sum_w | ETH sum_w | SOL sum_w |
|---|---|---|---|---|---|---|
| 게이트 off | 309(162/147) | 295(156/139) | 304(162/142) | -18.80% | -35.87% | -15.57% |
| 게이트 on | 296(145/151) | 295(139/156) | 298(143/155) | -13.12% | -17.85% | -21.36% |

동시진입(reversion leg, 2자산+ 같은 4h봉): **27.1%→28.7% — 거의 그대로.** FNG/VIX가
자산 무관 트리거인 데다, 실제 시장 공포 국면에서는 여러 자산의 모멘텀도 대개 같이
움직여 자산별 게이트로는 차별화가 안 된다. BTC/ETH는 개선, SOL은 악화(혼재) — 일관성
회복·칼받기 방지 목적으로는 유효하지만 **상관관계 완화라는 원래 목표는 달성 못함.**
→ 필터 자체는 채택(`MERIDIAN_REVERSION_STABILIZATION_ENABLED=True`), 상관관계는 별도
메커니즘 필요하다고 결론.

## 2차 시도 — leg별 동시진입 상관캡 (채택)

`_meridian_concurrent_leg_count()`(scheduler.py) — 새 포지션을 열기 직전, 같은 leg로
이미 열려 있는 "다른" perp 트랙 수를 세어 캡 이상이면 신규 진입을 차단.

사후 시뮬레이션(`scripts/analysis/meridian_reversion_correlation_check.py`
`_simulate_concurrency_cap`, 모멘텀게이트 on 거래셋에 시간순 그리디 필터 적용 —
독립 백테스트 3건을 사후 병합하는 근사치이지 진짜 조인 백테스트는 아님):

| leg | cap | n_total | sum_w_total% | 동시진입 |
|---|---|---|---|---|
| reversion | off | 889 | -52.33 | 90/314 (28.7%) |
| reversion | 2 | 807 | -38.73 | 63/282 (22.3%) |
| reversion | **1** | 673 | **-20.94** | **0/211 (0.0%)** |
| trend | off | 889 | -52.33 | 59/396 (14.9%) |
| trend | 2 | 833 | -54.88 | 51/355 (14.4%) |
| trend | 1 | 687 | -53.14 | 0/260 (0.0%) |

`reversion` leg는 cap=1이 cap=2보다 두 지표(상관·손익) 모두에서 명백히 우세 —
trade-off가 아니라 양쪽 다 개선(동시진입 완전 제거 + 손실 60% 축소, 거래수는
889→673로 -24%). `trend` leg는 애초에 동시진입률이 낮고(가격 기반이라 매크로보다
덜 상관) 캡을 걸어도 손익 개선이 없어(-52.33→-53.14, 사실상 무변화) 캡 대상에서
제외.

**채택**: `MERIDIAN_LEG_CONCURRENCY_CAP_BY_LEG = {"reversion": 1, "short": 1}`
(short은 실거래 표본 0건이라 직접검증은 못했으나 reversion과 신호 성격이 같아
선제 적용), `trend`는 무제한 유지. `PARAMS_VERSION` v39→v40.

## 한계·주의

- 사후 시뮬레이션은 독립적으로 계산된 3자산 백테스트 결과를 시간순으로 사후 필터링한
  근사치다. 실제 조인 백테스트(3자산을 한 calendar loop로 동시 재생하며 상태 공유)는
  아니다 — 방향성 판단에는 충분하나 정밀한 채택 기준(DSR/PBO)은 적용하지 않았다.
- 라이브에서 동시 tie(같은 사이클, 같은 open_time)가 나면 어느 트랙이 "먼저" 열리는지는
  `ALGORITHM_TRACK_SCOPE["meridian"]`(frozenset) 순회 순서에 의존 — 결정적이지 않을 수
  있다. 캡이 "누군가 하나는 막는다"는 보장이지 "특정 자산을 우선한다"는 보장은 아니다.
- short 캡은 실거래 미검증(표본 0건) — 라이브 관찰 후 재확인 필요.

## 재현

```bash
.venv/bin/python3 scripts/analysis/meridian_reversion_correlation_check.py \
    --parquet data/sentiment_join/master_20260710.parquet
```
