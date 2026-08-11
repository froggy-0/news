# D3 실행 — futures/cm/daily/liquidationSnapshot 백필·A/B (2026-08-11)

[binance-data-catalog-audit-20260811.md](binance-data-catalog-audit-20260811.md) D3의 후속
실행(§6 권고 순서: D1 다음 항목). 2026-08-10에 배선한 `_liquidation_exhaustion_sufficient()`
게이트(`LIQUIDATION_EXHAUSTION_GATE_ENABLED=False`, fng_contrarian·omnibus DOWN_TREND 레그)
는 그때까지 검증 데이터가 전무했다 — COIN-M(cm) 아카이브(BTC/ETH/SOL,
2023-06-25~2024-10-14)로 역사적 상승장 창(2023-08-04~2024-07-31)에서 처음 검증했다.

**결론: 채택하지 않음, `LIQUIDATION_EXHAUSTION_GATE_ENABLED=False` 유지.** 이 세션은 D3 문서
§4가 명시한 대로 "게이트를 끄는 근거를 찾는 반증 목적"으로 설계됐고, 결과가 정확히 그 근거를
제공한다 — `fng_contrarian`은 전 임계값·전 자산에서 게이트가 baseline보다 나쁘고,
`omnibus`(DOWN_TREND 레그)는 명목상 개선되지만 거래수가 90%까지 붕괴하고 DSR이 사실상 0(노이즈
구분 불가)이라 신뢰할 수 없다.

## 1. 구현

- `scripts/analysis/liquidation_cm_archive.py`: cm 아카이브 다운로드(캐시) + 4h 버킷 집계.
  side 규약은 `liquidation_stream._Bucket`과 동일(SELL=롱청산, BUY=숏청산). **notional 계산
  버그를 구현 중 발견·수정**: 처음엔 `average_price × last_fill_quantity`를 썼는데, COIN-M
  계약은 가격과 무관한 고정 USD 단위(`dapi/v1/exchangeInfo` 실측: BTCUSD_PERP=100,
  ETHUSD_PERP=10, SOLUSD_PERP=10)라 이 방식은 구간 내 가격추세(2023-08 ~$29k→2024-07
  ~$65k)를 그대로 z-score에 섞어 넣는다(BTC 5일 샘플에서 총 청산액이 $9.7B로 비현실적으로
  나와 발견 — 수정 후 $15M로 정상화). `last_fill_quantity × 고정계약단위`로 수정.
- `compute_4h_features()`: `liquidation_features.liquidation_snapshot()`의 청크 기반 정의
  (24h 트레일링 합의 30개 비중첩 24h 청크 대비 z-score)를 벡터화(24h 트레일링 합 시퀀스를
  6봉 간격으로 스트라이드하면 수학적으로 동일). **자체검증**: 실제 데이터에서 순수함수와
  스팟체크 20~40포인트 대조 — 백필 대상 구간(2023-08-04 이후, 워밍업 40일 확보된 구간)에서는
  `maxdiff=0`(부동소수점 오차 수준). 아카이브 시작 직후 30일 이내(워밍업 부족 구간, 대상 밖)
  에서만 두 구현이 갈렸는데, 원인은 "데이터 이전 기간=진짜 0"(순수함수) vs "데이터 이전
  기간=결측"(초기 벡터화 reindex)의 정의 차이 — 대상 구간엔 영향 없어 그대로 둠.
- `scripts/analysis/liquidation_cm_backfill_tuning.py`: p2_edge_cost_audit.py의 상승장
  FNG+funding macro 재구성(`build_bull_macro_rows`)과 BTC/ETH/SOL 프레임 빌더를 재사용,
  `dataclasses.replace`로 각 프레임의 macro에 `liq_asymmetry_24h`/`liq_intensity_zscore_24h`만
  오버레이(다른 macro 키·baseline 프레임은 무변형, D1의 `lsr_oi_backfill_tuning.py`와 동일
  패턴). 청산 커버리지: 3자산 프레임의 94~99%(BTC 2154/2172, ETH 2155/2172, SOL 2062/2172).

## 2. 결과

`LIQUIDATION_EXHAUSTION_MAX_ASYMMETRY` ∈ {0.3, 0.5, 0.7} (기존 코드의 0.5 placeholder
좌우 그리드) × 3자산, `fng_contrarian`(핵심조건 뒤 hard gate) vs `omnibus` DOWN_TREND 레그만
필터(`algorithms.omnibus_regime_for`로 사후 분류, 2026-08-04 omnibus-stop-distance-design과
동일 레그 태깅 기법).

### fng_contrarian — 전 임계값·전 자산에서 baseline이 우세

| 자산 | thresh | n(base→var) | sum_w_ret(base→var) | Δ |
|---|---|---|---|---|
| BTC | 0.3/0.5/0.7 | 5→5 | +2.07→+1.99/+1.17/+2.07 | -0.08/-0.90/0.00 |
| ETH | 0.3/0.5/0.7 | 6→5 | +1.74→+0.79/+1.09/+1.14 | -0.95/-0.65/-0.60 |
| SOL | 0.3/0.5/0.7 | 6→5 | +4.14→+1.88/+1.98/+1.98 | -2.26/-2.16/-2.16 |

**포트폴리오 합산**: baseline n=17 win=76% sum_w_ret=+7.95% → 전 임계값에서 n=15,
sum_w_ret +4.23~+5.19%(Δ -2.77~-3.72). `best=baseline` DSR 0.973(n_trials=3) 전 그리드
일관. 게이트가 걸러낸 2건이 하필 큰 승리 거래였다는 뜻 — 표본이 17건뿐이라 개별 거래
민감도가 크지만, 방향이 3개 임계값·3개 자산 9개 조합 전부에서 한 번도 뒤집히지 않았다.

### omnibus DOWN_TREND — 명목상 개선이지만 거래 붕괴 + DSR≈0

| 자산 | thresh | n(base→var) | win%(base→var) | sum_w_ret(base→var) | Δ |
|---|---|---|---|---|---|
| BTC | 0.3 | 88→9 | 61→44 | -1.75→-0.65 | +1.09 |
| BTC | 0.7 | 88→45 | 61→62 | -1.75→-1.12 | +0.62 |
| ETH | 0.3 | 107→13 | 51→15 | -4.79→-1.31 | +3.48 |
| SOL | 0.5 | 108→8 | 66→75 | -0.17→+0.17 | +0.35 |

**포트폴리오 합산**: baseline n=303 win=59% sum_w_ret=-6.71% → thresh 0.3/0.5/0.7에서
n=27/47/96, sum_w_ret -2.25/-2.82/-2.71%(Δ+3.89~+4.45). 얼핏 개선처럼 보이지만:

1. **거래수 91%(thresh=0.3)~68%(thresh=0.7) 붕괴** — 게이트가 "품질 낮은 거래만 골라서
   막는" 것이 아니라 표본 자체를 거의 없애고 있다.
2. **승률이 오히려 떨어지는 조합이 다수**(ETH thresh=0.3: 51%→15%, BTC thresh=0.3: 61%→44%)
   — 진짜 "매도 소진 확인" 필터라면 승률이 올라가야 하는데, 정반대 방향이 절반 가까이
   나온다. 이는 필터가 청산 관측치의 실제 품질 신호가 아니라 표본을 줄이는 것 자체로
   분산을 낮춰 우연히 평균을 개선시키고 있다는 강한 정황이다.
3. **DSR 0.000/0.002/0.018**(n_trials=3) — 기준 0.95는커녕 사실상 0. WI-4(`거래 11→5 붕괴·
   DSR 0.003`, 2026-07-09 기각)와 동일한 실패 패턴: 표본을 극단적으로 줄이는 필터는 겉보기
   개선이 대부분 노이즈다.

## 3. 결론 — 채택하지 않음, 게이트 off 유지

- `fng_contrarian`: 게이트가 일관되게 손해 → 켤 근거 없음(원래도 없었지만 이번에 명시적
  반증 확보).
- `omnibus` DOWN_TREND: 명목 수익 개선은 있으나 거래붕괴+승률역행+DSR≈0 조합이 전형적인
  과최적화/표본축소 아티팩트 — **채택 기준(D3 §4 한계 3: 상승장에서조차 뚜렷이 나빠지면
  명확한 기각)의 반대 극단이지만, "뚜렷이 개선"도 DSR이 뒷받침 못 하면 채택 사유가 안 된다.
  이 결과 하나로는 게이트를 켤 근거가 되지 않는다.**
- **`LIQUIDATION_EXHAUSTION_GATE_ENABLED=False` 그대로 유지.** 코드·파라미터 변경 없음,
  `PARAMS_VERSION` bump 없음, 배포 없음.
- 재사용 가능한 산출물: `liquidation_cm_archive.py`(cm 다운로드·4h 버킷·벡터화 피처, D3의
  다른 시도나 향후 라이브 청산 데이터 30일+ 축적 후 대조군으로 재사용 가능),
  `liquidation_cm_backfill_tuning.py`(프레임 macro 오버레이 A/B 템플릿, D1과 동일 패턴).
- 이 세션에서 확정된 한계(그대로 유효): cm≠um 규모차, 2024-10-14 이후 데이터 없음(하락장
  검증 불가) — 재시도하려면 라이브 축적(WI-9, 2026-08-10부터 실제 가동)이 하락장 구간의
  진짜 um 데이터를 쌓아줄 때까지 기다리는 게 유일한 다음 경로다.
