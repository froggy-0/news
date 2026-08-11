# D2 실행 — BVOL(크립토 IV)로 VIX 대체 A/B (2026-08-11)

[binance-data-catalog-audit-20260811.md](binance-data-catalog-audit-20260811.md) D2의 후속
실행. `vix_rsi`·`multi_factor`(f3)가 읽는 `macro['vix_now']`/`['vix_q40']`을 주식 VIX(FRED
VIXCLS, 일간·미국 장중만 갱신)에서 BVOL(바이낸스 옵션 내재변동성, 24/7, 2023-06-20~)로
바꿨을 때 백테스트 성과가 개선되는지 탐색했다.

**결론: 채택하지 않음 — BVOL 대체는 두 알고 모두 뚜렷이 악화시킨다.** "24/7 크립토 자산에
주식장 지표를 쓰는 구조적 불일치"라는 가설 자체가 이 데이터로 반증됐다.

## 1. 구현

- `scripts/analysis/bvol_archive.py`: BVOL 일간 아카이브(1초 해상도 파일의 일간 마지막
  관측치만 캐시) 다운로드 + `risk_overlay.py`의 vix_q40 정의(90일 롤링·최소 30일·40th
  percentile)를 그대로 재사용한 `vix_now`/`vix_q40` 대응 컬럼 산출(lag1 — 프로젝트 표준
  daily macro 관례).
- 다운로드 속도 이슈: 초기 전체 커버리지(2023-06-20~2026-08-09, 1147일) 순차 다운로드가
  13분에 198개(전체의 17%)로 너무 느려 중단 — 실제 A/B에 필요한 범위(백테스트 프레임
  워밍업 100일 포함 ~430일)만, 6개 구간으로 나눠 병렬 다운로드로 전환해 완료.
- `scripts/analysis/bvol_backfill_tuning.py`: master_20260710.parquet 표준 macro 백필(D1/D3와
  동일 11개월 창, 1966프레임) + BVOL overlay(`dataclasses.replace`, baseline 무변형, D1/D3와
  동일 패턴). BVOL 커버리지 1837/1966(93%, 워밍업 구간 일부 90일 롤링 미달로 제외).

## 2. 결과

| 알고 | baseline(VIX) | variant(BVOL) | Δ | DSR best |
|---|---|---|---|---|
| `vix_rsi` | n=40, win 42%, -0.99% | n=41, win 39%, **-4.25%** | **-3.26** | baseline 0.322 |
| `multi_factor` | n=47, win 45%, -1.76% | n=50, win 42%, **-3.92%** | **-2.16** | baseline 0.167 |

비대상 알고(regime_trend·macd_momentum·omnibus·fng_contrarian) 전부 Δ0.0000 — vix_now/
vix_q40을 안 읽는 알고들은 정확히 무변화(오버레이 격리 확인).

## 3. 해석

- 두 알고 모두 승률·가중수익 둘 다 악화 — 방향이 뒤섞이지 않고 일관되게 나쁘다. DSR은
  낮지만(n_trials=2라 통계적으로 약함) 두 조합 모두 `best=baseline`으로 일치.
- "크립토는 24/7인데 VIX는 미국 장중에만 갱신된다"는 구조적 불일치가 실제로 있다는 것과,
  "그래서 크립토 네이티브 IV로 바꾸면 낫다"는 것은 별개 명제였다 — 후자는 반증됐다. 가능한
  해석: BVOL의 옵션시장 IV가 VIX보다 변동성이 크고(옵션시장 자체가 얕음) 노이즈가 많아
  `vix_q40` 임계값 통과/미통과 판정이 VIX보다 불안정해졌을 가능성. 이 세션에서는 원인
  분해까지는 하지 않음(채택 안 하는 결론에 추가 조사 투입 안 함).
- 라이브 배선 결정(BVOL은 T+1 아카이브 전용, eapi markIV는 산출식이 달라 패리티 파손)은
  애초에 이 결과로 인해 **논의할 필요 자체가 없어졌다** — 백테스트에서 이미 진다.

## 4. 결론

- 코드·파라미터 변경 없음, PARAMS_VERSION 무변경, 배포 없음.
- **BVOL을 VIX 대체로 채택하지 않는다.** D2 스레드 종결 — 재시도 조건: 새로운 근거(다른
  BVOL 집계 방식, 예컨대 일중 평균이나 다른 percentile 정의) 없이는 무의미.
- 재사용 산출물: `bvol_archive.py`(BVOL 다운로드·vix_q40 동형 산출), `bvol_backfill_tuning.py`
  (macro 오버레이 A/B 템플릿).
