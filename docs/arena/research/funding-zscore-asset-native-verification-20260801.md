# ETH/SOL 자산고유 funding_zscore 재검증 — 2026-08-01

## 배경

2026-07-31 세션에서 ETH/SOL 라이브 shadow에 자산고유 funding/LSR 롤링 z-score
(`src/arena/futures_baseline.py`)를 구현·배포했다. 이때 "검증하고 적용할래?"라는
질문이 남았다: 지금까지 ETH/SOL **백테스트**(`backtest_with_macro_backfill.py`)는
BTC parquet에서 재구성한 `regimeRaw`를 3자산이 그대로 공유해왔는데(Track A/B 설계
§3.1의 의도된 원칙), 이는 (a) 설계상 결정이기도 했지만 (b) 실제로는 "ETH/SOL 자산고유
funding 히스토리를 과거로 되짚어 백테스트할 수 있는가"가 당시 미확인이었기 때문이기도
했다. 라이브가 이미 자산고유 값을 쓰고 있으니, 백테스트도 자산고유로 재검증하면 결론이
달라지는지 확인이 필요했다.

**핵심 사실관계**: Binance `/fapi/v1/fundingRate`는 심볼 무관하게 전체 히스토리를
보존한다(OI/LSR과 달리 30일 제한 없음 — 2026-07-31 세션에서 이미 실측 확인). 따라서
ETH/SOL도 BTC와 동일 방법론(`join.py`의 `funding_rate_zscore_30d`: 일별 3건 합산 →
`shift(1).rolling(30, min_periods=20)` 평균/표준편차)으로 자산고유 z-score를 재구성해
과거 시점 백테스트에 넣는 것이 원리적으로 가능함을 이번에 실행으로 확인했다.

## 1단계 — 상관관계·베토 판정 일치율 확인

`scripts/analysis/funding_zscore_asset_native_verify.py` (기간 2025-01-16~2026-07-10,
516일 비교 가능):

| 심볼 | BTC-공유 대비 상관계수 | funding_hot 베토 발동일(BTC/자산고유/둘다) | 판정 일치율 |
|---|---|---|---|
| ETHUSDT | 0.476 | 49 / 37 / 16 | 89.5% |
| SOLUSDT | **0.082**(사실상 무상관) | 49 / 29 / 7 | 87.6% |

SOL은 BTC 펀딩비와 거의 상관이 없다 — "일치율 87.6%"는 두 시리즈 모두 대부분의 날에
조용하기 때문에 생기는 착시(기저율 효과)이고, 실제로 베토가 발동하는 소수 날짜만 보면
BTC-공유 49일 중 자산고유와 겹치는 건 7일뿐(14%)이다. 즉 지금까지 SOL 백테스트는 SOL과
사실상 무관한 신호로 진입을 막아왔다는 뜻이다.

## 2단계 — 실제 백테스트 영향 확인 (핵심 질문)

`scripts/analysis/funding_zscore_asset_native_backtest.py` — macro_rows의
`regimeRaw.funding_zscore`만 자산고유 값으로 치환(다른 macro 필드는 그대로, OI 기반
`oi_divergence_flag`는 30일 제한으로 애초에 자산고유 백필 불가능이라 미변경)하고
동일 데이터로 A/B 실행.

**ETHUSDT** (상관 0.476):

| algo | BTC공유 n/win%/sum_w | 자산고유 n/win%/sum_w |
|---|---|---|
| multi_factor | 38/42.1%/+2.02% | 37/40.5%/**+3.52%** |
| omnibus | 107/54.2%/-5.90% | 111/56.8%/**-4.09%** |
| regime_trend | 5/60.0%/-0.80% | 5/80.0%/-0.05%(n=5, 표본 무의미) |
| macd_momentum·vix_rsi·fng_contrarian | 거의 무변화 | 거의 무변화 |

**SOLUSDT** (상관 0.082, 가장 극단적 케이스):

| algo | BTC공유 n/win%/sum_w | 자산고유 n/win%/sum_w |
|---|---|---|
| multi_factor | 43/51.2%/+10.11% | 45/48.9%/+9.93%(거의 동일) |
| omnibus | 98/48.0%/-8.39% | 102/50.0%/-7.06%(소폭 개선) |
| regime_trend | 14/50.0%/+0.49% | 13/46.2%/+0.11%(n=13, 표본 무의미) |
| macd_momentum·vix_rsi·fng_contrarian | 완전 무변화 | 완전 무변화 |

## 결론

**상관관계가 사실상 0(SOL)이어도 백테스트 결과는 거의 안 바뀐다.** 이유:
funding_hot 베토는 전체 관측일의 ~9.5%에서만 발동하고, 그마저도 진입 결정을 좌우하는
여러 조건(레짐·MA200·LSR 과밀·taker 확인·낙폭 등) 중 하나일 뿐이라 단독으로 결과를
지배하지 못한다. 거래 수 변화도 미미(ETH 241→243, SOL 247→252)하다.

**이는 2026-07-31 D-verdict(cross-asset-verdict-20260731.md, 6개 알고 전부 §5.2
실패)의 견고성을 뒷받침한다** — 그 결론이 "BTC 펀딩 데이터를 잘못 공유해서 생긴
아티팩트"가 아니라 실제 구조적 결과임을 재확인한 것.

## 결정

- ❌ **자산고유 funding_zscore를 백테스트 파이프라인(`backtest_with_macro_backfill.py`)에
  정식 배선하지 않음** — 영향이 무시할 만한 수준이라 복잡도 대비 이득이 없음. 스크립트
  (`funding_zscore_asset_native_verify.py`/`funding_zscore_asset_native_backtest.py`)는
  재현 가능하도록 보존.
- ✅ **라이브 shadow는 그대로 유지** — `futures_baseline.py`가 이미 자산고유 값을 계산 중이고
  (2026-07-31 배포), 이건 백테스트와 무관하게 라이브 정확도 관점에서 올바른 방향이라 변경 없음.
- 이로써 2026-07-31 "검증하고 적용할래?" 질문이 최종 종결됨 — funding 부분은 검증 완료,
  적용(백테스트 배선)은 근거 부족으로 보류. LSR/OI는 애초에 Binance 30일 제한으로 검증
  자체가 불가능(기존 확인 사항 재확인, 변경 없음).

## 재현

```bash
.venv/bin/python3 scripts/analysis/funding_zscore_asset_native_verify.py \
    --parquet data/sentiment_join/master_20260710.parquet
.venv/bin/python3 scripts/analysis/funding_zscore_asset_native_backtest.py \
    --symbol ETHUSDT --parquet data/sentiment_join/master_20260710.parquet
.venv/bin/python3 scripts/analysis/funding_zscore_asset_native_backtest.py \
    --symbol SOLUSDT --parquet data/sentiment_join/master_20260710.parquet
```
