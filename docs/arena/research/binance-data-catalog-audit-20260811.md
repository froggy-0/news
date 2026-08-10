# 바이낸스 공개 데이터 전수 감사 — spot / futures(um·cm) / option (2026-08-11)

## 0. 한 줄 결론

**아레나가 안 쓰고 있는 바이낸스 공개 데이터가 5종 있고, 그중 2종은 지금 아레나의 가장 큰
구조적 제약(“라이브로만 모아서 백테스트를 못 한다”)을 직접 해소한다.** 그리고 2026-08-10
세션의 “청산 데이터 백필 불가 확정” 결론은 **부분적으로 틀렸다** — COIN-M(cm) 아카이브에는
2023-06-25~2024-10-14 구간 청산 이력이 실재한다(§5 정정).

| # | 발견 | 왜 중요한가 | 우선순위 |
|---|---|---|---|
| **D1** | `futures/um/daily/metrics` — 선물 포지셔닝 5분봉, BTC 2020-09~현재 | arena-features-v8이 **라이브로만** 모으던 4개 피처 전부 6년치 백필 가능 (REST는 30일 제한, 실측 확인) | **P1** |
| **D2** | `option/daily/BVOLIndex` — 크립토 네이티브 내재변동성, 2023-06~현재 | `vix_rsi`가 쓰는 주식 VIX(FRED)의 크립토 직결 대체·보완 후보 | P3 |
| **D3** | `futures/cm/daily/liquidationSnapshot` — BTC/ETH/SOL USD_PERP, 2023-06~2024-10 | 어제 켠 청산 소진 게이트를 **상승장 창에서** 검증 가능(원래 불가로 판정했던 것) | P2 |
| **D4** | `futures/um/daily/bookDepth` — 밴드별 호가 깊이, 2023-01~현재 | 실행게이트(현재 shadow·히스토리 0)의 히스토리 백테스트 | P5 |
| **D5** | `spot/*/klines` 1m·1s — 2017-08(1m)/2020-08(1s)~현재 | P2 MFE 1분 정밀화를 **라이브 구간(2026-07~)이 아니라 전 백테스트 구간**으로 확장 | P4 |

---

## 1. 조사 방법 (재현 가능)

세 가지를 각각 **실측**했다. 문서 읽기만으로 판단하지 않았다 — WI-9(“지역차단” 오판정)의
교훈대로, “있다고 쓰여 있다”와 “실제로 파일이 있다”는 다르기 때문.

1. **버킷 트리 탐색**: `data.binance.vision`은 S3 REST GET Bucket(v1) 형식으로 익명 리스팅이
   된다. `delimiter=/`로 데이터 타입 트리를, `marker` 페이지네이션으로 전체 키를 수집.
   ⚠️ `max-keys` 상한이 1000이라 페이지네이션을 안 하면 **“마지막 파일”을 오판한다**(실제로
   1차 조사 때 BVOLIndex가 2024-11에서 끝나는 것처럼 보였으나, 페이지네이션하니 2026-08-09까지
   있었음).
2. **샘플 실다운로드**: 각 데이터셋 1일치를 실제로 받아 압축 해제 → 컬럼·행수·용량 확인.
3. **REST 대조**: 같은 데이터를 REST API가 히스토리로 주는지 직접 호출해 확인(§3).

재현 스크립트: [`scripts/analysis/binance_archive_catalog.py`](../../../scripts/analysis/binance_archive_catalog.py)

```bash
.venv/bin/python3 scripts/analysis/binance_archive_catalog.py tree data/futures/um/daily/
.venv/bin/python3 scripts/analysis/binance_archive_catalog.py range data/futures/um/daily/metrics/BTCUSDT/
.venv/bin/python3 scripts/analysis/binance_archive_catalog.py sample \
    data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-08-08.zip
```

---

## 2. 전체 카탈로그 (2026-08-11 실측)

### 2.1 spot (`data/spot/{daily,monthly}/`)

| 데이터 타입 | 해상도 | 커버리지(BTCUSDT) | 아레나 현황 |
|---|---|---|---|
| `klines` | 1s, 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d | 1m: 2017-08~2026-07(월간), 1s: 2020-08~2026-08-09(일간) | **4h만 사용**(`arena_ohlcv_bars`). 1m/1s 미사용 → **D5** |
| `trades` | 체결 단위 | 전 구간 | 미사용 (필요 없음 — aggTrades/klines로 충분) |
| `aggTrades` | 집계 체결 | 전 구간 | 미사용 |

현물 아카이브는 이 3종이 전부다. **주문흐름·호가·포지셔닝류는 현물엔 아예 없다** — 그래서
아레나가 현물 롱온리인데도 선물 데이터를 참조하는 현재 구조가 (데이터 가용성 측면에선)
필연적이다.

### 2.2 futures / USDT-M (`data/futures/um/`)

| 데이터 타입 | daily | monthly | 커버리지(BTCUSDT) | 아레나 현황 |
|---|---|---|---|---|
| `klines` | ✅ | ✅ | 2019-09~ | 미사용(현물 klines 사용) |
| `aggTrades` / `trades` | ✅ | ✅ | 2019-09~ | 미사용 |
| **`metrics`** | ✅ | ❌ | **2020-09-01~2026-08-09** | **미사용 → D1** |
| **`bookDepth`** | ✅ | ❌ | **2023-01-01~2026-08-09** | **미사용 → D4** |
| `bookTicker` | ✅ | ✅ | 2020~ | 미사용(최우선호가 tick) |
| `fundingRate` | ❌ | ✅ | 2020-01~2026-07 | REST로 이미 접근 가능(§3) |
| `premiumIndexKlines` | ✅ | ✅ | 2020-01~2026-07 | REST로 이미 접근 가능 |
| `markPriceKlines` | ✅ | ✅ | 2020~ | REST로 이미 접근 가능 |
| `indexPriceKlines` | ✅ | ✅ | 2020~ | 미사용 |
| `liquidationSnapshot` | ❌ | ❌ | **없음** | — (§5) |

ETH/SOL 커버리지: `metrics` 둘 다 2021-12-01~2026-08-09(n=1713), `bookDepth` 둘 다
2023-01-01~2026-08-09.

### 2.3 futures / COIN-M (`data/futures/cm/`)

USDT-M과 데이터 타입이 같고 **`liquidationSnapshot`이 하나 더 있다**(daily만).

| 심볼 | 파일 수 | 첫 파일 | 마지막 파일 |
|---|---|---|---|
| `BTCUSD_PERP` | 472 | 2023-06-25 | **2024-10-14** |
| `ETHUSD_PERP` | 474 | 2023-06-25 | **2024-10-14** |
| `SOLUSD_PERP` | 455 | 2023-06-25 | **2024-10-14** |

2024-10-14 이후 발행이 끊겼다. 이건 arXiv:2607.27070이 “바이낸스가 유의미한 해상도로 청산
데이터를 더 이상 공개하지 않아 대리변수로 우회했다”고 쓴 것과 정확히 일치하는 시점이다.

### 2.4 option (`data/option/daily/`)

| 데이터 타입 | 심볼 | 커버리지 | 판정 |
|---|---|---|---|
| **`BVOLIndex`** | `BTCBVOLUSDT`, `ETHBVOLUSDT` | **2023-06-20~2026-08-09** (n=1121, 끊김 없음) | **살아있음 → D2** |
| `EOHSummary` | BTC/ETH/BNB/XRP/DOGE USDT | 2023-05-18~**2023-10-23** (n=147) | **死** — 3년 전 중단, 사용 불가 |

SOL BVOL은 없다(BTC·ETH만). 단 옵션 자체는 SOLUSDT 언더라잉이 상장돼 있어 라이브 markIV는
얻을 수 있다(§4 D2).

---

## 3. REST vs 아카이브 — 무엇이 어디에만 있는가 (실측)

이번 감사의 **가장 실질적인 발견**은 이 표다. 바이낸스 선물 REST는 두 계열로 갈리는데,
아레나가 쓰는 피처들이 하필 히스토리가 막힌 쪽에 몰려 있다.

| 엔드포인트 | 과거 `startTime` | 실측 결과 |
|---|---|---|
| `/fapi/v1/fundingRate` | ✅ 지원 | 2023-01-01 요청 → 정상 반환 |
| `/fapi/v1/premiumIndexKlines` | ✅ 지원 | 2023-01-01 요청 → 정상 반환 |
| `/fapi/v1/markPriceKlines` | ✅ 지원 | (동일 계열) |
| **`/futures/data/openInterestHist`** | ❌ | `{"code":-1130,"msg":"parameter 'startTime' is invalid."}` |
| **`/futures/data/globalLongShortAccountRatio`** | ❌ | 동일 `-1130` |
| **`/futures/data/topLongShortAccountRatio`** | ❌ | 동일 (30일 제한) |
| **`/futures/data/topLongShortPositionRatio`** | ❌ | 동일 |
| **`/futures/data/takerlongshortRatio`** | ❌ | 동일 |

`src/arena/market_structure.py:20-28`이 참조하는 5개 `/futures/data/*` 경로가 **전부 30일
제한**이다. 즉 **arena-features-v8에서 추가한 선물 sentiment overlay(4개 비율 피처)와
`oi_divergence_flag`는 REST만으로는 원리적으로 백테스트가 불가능**했고, 지금까지 그 상태였다.
`metrics` 아카이브(D1)가 정확히 이 구멍을 메운다.

---

## 4. 발견 상세

### D1. `futures/um/daily/metrics` — 선물 포지셔닝 5분봉 (P1)

```csv
create_time,symbol,sum_open_interest,sum_open_interest_value,
count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,
count_long_short_ratio,sum_taker_long_short_vol_ratio
2026-08-08 00:00:00,BTCUSDT,106964.058,6940865634.40,1.17050042,1.53817300,1.10263350,0.57838100
```

- **해상도** 5분(288행/일), **용량** 압축 ~11KB/일 → BTC+ETH+SOL 전 구간 합계 **약 60MB**.
  (이 문서의 모든 후보 중 압도적으로 싸다.)
- **커버리지** BTC 2020-09-01~, ETH/SOL 2021-12-01~, 전부 어제까지 최신.

**아레나 피처와의 1:1 매핑** (`market_structure.build_market_features` 기준):

| 아카이브 컬럼 | 아레나 라이브 수집 | 현재 백테스트 가용성 |
|---|---|---|
| `count_long_short_ratio` | `globalLongShortAccountRatio` → `global_account_ls_ratio` | ❌ 없음 |
| `count_toptrader_long_short_ratio` | `topLongShortAccountRatio` → `top_account_ls_ratio` | ❌ 없음 |
| `sum_toptrader_long_short_ratio` | `topLongShortPositionRatio` → `top_position_ls_ratio` | ❌ 없음 |
| `sum_taker_long_short_vol_ratio` | `takerlongshortRatio` → `taker_buy_sell_ratio` | ❌ 없음 |
| `sum_open_interest(_value)` | `openInterestHist` → `oi_divergence_flag` | ❌ 없음 |

**이게 풀어주는 것**:
- `_lsr_crowded`(LSR z≥2.0 veto), `_taker_confirms`(돌파 주문흐름 확인), `_oi_diverged`
  (OI-가격 7일 불일치 veto) — **세 게이트 전부 지금까지 백테스트에서 검증된 적이 없다.**
  현재 백테스트는 morning-brief parquet의 일간 lag1 z값(`long_short_ratio_zscore`,
  `taker_imbalance_zscore`)에 의존하는데, 그건 파케이가 끝나는 2026-05-01 이후 forward-fill이고
  4h 해상도가 아니다.
- WI-10(`TAKER_CONFIRM_4H_ENABLED`)이 “live 전용 개선이라 검증 수단이 없어 보류”로 2026-07-09
  이후 **1년 넘게 묶여 있던 유일한 이유가 바로 이 데이터 부재**다. D1을 넣으면 검증 가능해진다.
- 5분 해상도라 4h 봉 경계에 정확히 맞춰 재표본화 가능(`frequency.py` 규약과 정합).

**한계**: `/futures/data/*` 라이브 값과 아카이브 값의 정의가 동일한지는 겹치는 최근 30일 구간에서
**교차검증이 필요**하다(반드시 먼저 할 것 — 라이브/백테스트 패리티는 이 프로젝트에서 이미 두 번
버그가 났던 지점이다: omnibus 사이징(W2), depth limit(2026-07-30)).

### D2. `option/daily/BVOLIndex` — 크립토 네이티브 내재변동성 (P3)

```csv
calc_time,symbol,base_asset,quote_asset,index_value
1786147200000,BTCBVOLUSDT,BTCBVOL,USDT,35.7571
```

- **해상도 1초**(86,400행/일), 압축 389KB/일 → BTC+ETH 전 구간 **약 870MB**(4h로 다운샘플하면 무의미하게 작아짐).
- **커버리지** 2023-06-20~2026-08-09, BTC·ETH만(SOL 없음).
- `index_value`는 연율화 % IV(위 샘플 35.76 = 35.76%). VIX와 개념적으로 직접 비교 가능.

**왜 흥미로운가**: `vix_rsi`는 **주식시장 VIX**(FRED VIXCLS, 일간, 발표지연)를 외생 매크로
필터로 쓴다. 크립토 자체의 옵션시장 IV는 (a) 같은 자산군이고 (b) 일간이 아니라 초 단위고
(c) 주말에도 산출된다 — 크립토는 24/7인데 VIX는 미국 장중에만 갱신된다는 구조적 불일치가
지금 `vix_rsi`에 내장돼 있다.

**라이브 가용성 (실측)**: BVOL 지수 자체는 **공개 실시간 엔드포인트가 없다.**
- `eapi/v1/index?underlying=BTCBVOLUSDT` → `-1128 Invalid underlying`
- `api/v3/ticker/price?symbol=BTCBVOLUSDT` → `-1121 Invalid symbol` (BVOL 토큰은 상장폐지됨)
- 즉 **아카이브 일간 파일(T+1)이 유일한 경로**. 다만 아레나 macro는 이미 일간·lag1 + 48h stale
  허용 구조라 이 지연은 규격 내다.
- 대안(라이브): `eapi/v1/mark`가 옵션별 `markIV`를 실시간 제공한다(실측: BTC 532개 계약,
  BNB/SOL/XRP/DOGE + XAU/XAG/CL/BZ 언더라잉까지 총 1522개). ATM·30일 만기 보간으로 자체
  IV 지수를 만들 수 있지만, **BVOL 아카이브와 산출식이 다르므로 히스토리와 라이브를 섞으면
  패리티가 깨진다.** 둘 중 하나로 통일해야 한다.

### D3. `futures/cm/daily/liquidationSnapshot` — 청산 이력 (P2, 정정 사항)

```csv
time,side,order_type,time_in_force,original_quantity,price,average_price,order_status,
last_fill_quantity,accumulated_fill_quantity
1709598391022,SELL,LIMIT,IOC,1,67934.2,68203.4,FILLED,1,1
```

- 개별 강제청산 주문 단위(2024-03-05 BTCUSD_PERP: 1,344건/일), 압축 ~13KB/일 → 3심볼 전 구간
  **약 18MB**.
- `side=SELL`이 롱 청산, `BUY`가 숏 청산 — 어제 구현한 `liquidation_stream._Bucket.add()`와
  **부호 규약이 동일**하다. 4h 버킷 집계로 `arena_liquidation_bars`와 같은 스키마를 만들 수 있다.

**이게 풀어주는 것**: 2026-08-10에 배선한 `_liquidation_exhaustion_sufficient()` 게이트는
“데이터가 없어 백테스트 배선을 의도적으로 안 만들었다”고 기록해 뒀다. 이제 **2023-06~2024-10
구간(= 역사적 상승장 백테스트 창 2023-08~2024-07을 완전히 포함)**에서는 그리드 검증이 가능하다.

**한계 (중요)**:
1. **코인마진(cm) ≠ 우리가 라이브로 모으는 USDT마진(um).** 규모가 훨씬 작고 참여자 구성이
   다르다. 시장 전체 캐스케이드는 공유하므로 *방향·타이밍*은 상관되지만 *금액 수준*은
   다르다 → `liquidation_intensity_zscore`처럼 **자기 히스토리 대비 z-score로 쓰는 설계는
   호환되고**, 절대 USD 임계값은 호환되지 않는다. (다행히 어제 구현한 게이트는
   `liq_asymmetry_24h`라는 **비율** 기반이라 이 문제에 덜 취약하다.)
2. **2024-10-14에서 끊긴다** → 하락장 창(2024-11~2026-07)에는 데이터가 0. 즉 이 프로젝트가
   관행적으로 요구하는 **전/후반 분할 검증을 상승장 창 내부에서만** 할 수 있다. 이건 약한 검증이다.
3. 이 두 한계 때문에 D3는 “게이트를 켤 근거”가 아니라 **“게이트를 끌 근거를 찾는 용도”**로
   쓰는 게 정직하다(반증 목적). 상승장 창에서조차 악화시키면 그건 명확한 기각 신호다.

### D4. `futures/um/daily/bookDepth` — 밴드별 호가 깊이 (P5)

```csv
timestamp,percentage,depth,notional
2026-08-08 00:00:01,-5.00,8073.73300000,515478831.14230000
```

- 밴드: **±0.2%, ±1%, ±2%, ±3%, ±4%, ±5%** (12레벨), 스냅샷 간격 ~30초(34,560행/일).
- 압축 554KB/일 → 3심볼 전 구간 **약 2.2GB**.

**한계가 결정적**: 아레나 실행게이트는 **10bps(0.1%) 밴드 깊이**(`depth_10bp_bid/ask_usd`)를
쓰는데 아카이브의 최소 밴드는 **20bps(±0.2%)**다. 즉 직접 대체가 안 되고 밴드를 20bps로
재정의하거나 보간해야 한다. 2026-07-30에 고친 depth 과소추정 버그의 재발 위험이 있는 지점이라
**임계값을 그대로 옮기면 안 된다.**

실행게이트는 아직 shadow 전용(`ENABLE_ARENA_EXECUTION_GATE_LIVE=False`)이므로 이 작업의
기대이익은 낮다 → 우선순위 최하위.

### D5. `spot/*/klines` 1m·1s — 인트라바 정밀화 (P4)

- 1m: 월간 파일, 2017-08~2026-07, ~2.1MB/월 → 3심볼 전 구간 **약 600MB**.
- 1s: 일간 파일, 2020-08~2026-08-09, ~1.7MB/일 → 3심볼 **약 11GB**(권장하지 않음).

**이게 풀어주는 것**:
1. **P2 MFE 1분 정밀화의 구간 확장.** 2026-07-21 §9에서 `arena_realtime_feature_bars`로 1분
   MFE를 재검증해 `vix_rsi`의 4h 진단이 해상도 아티팩트였음을 밝혔는데, 그 테이블은 라이브
   가동 이후만 존재한다(그래서 표본이 작았다). 1m 아카이브를 쓰면 **전 백테스트 구간에서**
   같은 판정을 할 수 있다.
2. **백테스트 체결 현실성.** 현재 백테스트는 손절/목표가를 봉 저가·고가로 판정하고
   래칫 트레일링은 봉 종가로 갱신한다. 2026-08-10 트레일링 거리 실험이 “봉종가 래칫이라
   좁은 트레일의 휩소를 과대평가했을 가능성을 배제 못함”이라는 미해결 꼬리를 남긴 채
   끝났는데 — **1m 데이터가 정확히 그 꼬리를 자를 수 있는 재료다.**

---

## 5. 이전 결론 정정 — “청산 백필 불가 확정”

[liquidation-feature-design-20260810.md](liquidation-feature-design-20260810.md)에 이렇게 적혀 있다:

> **백필 불가 확정** — `data.binance.vision` S3 리스팅 직접 조회 결과 선물 daily/monthly 어느
> 쪽에도 청산 데이터 타입 자체가 없음

**정정**: 이 판정은 **USDT-M(`data/futures/um/`)만 확인**하고 COIN-M(`data/futures/cm/`)을 보지
않은 결과였다. cm에는 `liquidationSnapshot`이 있고 BTC/ETH/SOL USD_PERP 전부
2023-06-25~2024-10-14 구간이 존재한다(§2.3, §4 D3).

**그럼에도 유지되는 부분**:
- USDT-M(우리가 라이브 수집하는 시장)의 청산 이력은 **여전히 공개되지 않는다** — 원래 문서의
  핵심 논지(“우리만의 문제가 아니라 바이낸스가 원천적으로 안 준다”)는 UM에 대해선 그대로 참이다.
- `GET /fapi/v1/forceOrders`가 호출계정 전용이라는 것도 그대로다.
- 2024-10-14 이후는 어느 시장에도 없다 → “오늘부터 원본을 쌓기 시작한다”는 D-day 판단도 유효.

**정정의 실질적 의미**: “검증 자체가 불가능하니 라이브 축적을 기다린다”가 아니라, **“상승장
구간에 한해 지금 반증 시도를 할 수 있다”**로 바뀐다. 게이트를 켜는 근거로는 부족하지만 끄는
근거로는 충분하다(§4 D3 한계 3).

> 방법론 교훈: 하위 디렉터리 한 단계를 안 열어보고 “존재하지 않음”을 확정한 것. WI-9의
> “connected 로그 = 정상” 오판정과 같은 계열의 실수다 — **부재 증명은 탐색 범위를 명시하지
> 않으면 성립하지 않는다.**

---

## 6. 우선순위 권고

| 순위 | 항목 | 근거 | 비용 | 주요 리스크 |
|---|---|---|---|---|
| **P1** | **D1 metrics 백필** | 5개 게이트(`_lsr_crowded`/`_taker_confirms`/`_oi_diverged` + WI-10)가 **한 번도 검증된 적 없음**. 다운로드 60MB로 이 프로젝트에서 가장 비용 대비 효과가 큼 | 낮음 | 라이브/아카이브 정의 불일치 → **최근 30일 겹침 구간 교차검증을 먼저** |
| **P2** | **D3 cm 청산 백필** | 어제 켠 인프라의 유일한 검증 수단. 18MB | 낮음 | cm≠um 규모차, 상승장 창만 커버 → **기각 근거 수집용으로 한정** |
| P3 | D2 BVOL | `vix_rsi`의 주식VIX↔크립토 불일치를 정면으로 다룸 | 중 | 라이브 엔드포인트 없음(T+1) / markIV와 산출식 상이 |
| P4 | D5 1m klines | 트레일링 휩소 과대평가 의혹(2026-08-10 미해결 꼬리) 해소 + MFE 전구간 재판정 | 중(600MB) | 백테스트 실행시간 증가 |
| P5 | D4 bookDepth | 실행게이트가 아직 shadow 전용이라 기대이익 낮음 | 높음(2.2GB) | 10bps↔20bps 밴드 불일치 |
| — | ❌ option `EOHSummary` | 2023-10 중단(3년 전) | — | 사용 불가 |
| — | ❌ spot `trades`/`aggTrades`, futures `bookTicker` | klines/metrics로 충분, 용량만 큼 | — | — |

**권고 실행 순서**: D1 교차검증 → D1 백필 → WI-10 및 3개 게이트 A/B(기존 `wi_tuning.py` 패턴
재사용) → 그 결과를 보고 D3 착수 여부 판단.

---

## 7. 가드레일 (이 데이터를 쓸 때)

- **예측형 청산 신호 금지** — 2026-08-10에 문헌(arXiv:2607.27070)으로 확정한 가드레일 그대로.
  D3로 히스토리가 생겼다고 “캐스케이드 사전예측”으로 확장하지 않는다. 사후확인(backward-looking)
  품질필터 용도만.
- **새 피처 = 새 자유도.** P4 과최적화 감사(2026-08-04)에서 사양탐색 원장
  (`specification-trial-ledger-20260804.json`)을 만든 이유가 이것이다. D1~D5로 만든 변형은
  전부 원장에 기록하고 DSR을 누적 N으로 계산할 것. 데이터가 늘었다고 검정 기준이 느슨해지지 않는다.
- **라이브/백테스트 패리티 우선.** 이 프로젝트에서 실제로 성과를 왜곡한 버그는 전부
  “백테스트에만 있거나 라이브에만 있던 것”이었다(omnibus 사이징 W2, depth limit, 심볼 필터).
  아카이브 피처를 backtest에 넣을 때 **라이브 경로(`scheduler`/`market_structure`)와 같은
  단위·같은 부호·같은 lag인지**를 테스트로 고정할 것.
- **아카이브는 T+1**이다. 라이브 macro 주입 경로를 아카이브로 바꾸면 안 된다(백필 전용).
- 리스팅 시 `max-keys` 1000 상한 + `marker` 페이지네이션을 반드시 쓸 것(§1).

---

## 8. 부록 — 실측 원자료

```
# 데이터 타입 트리 (2026-08-11)
spot/{daily,monthly}/           : klines, trades, aggTrades
futures/um/daily/               : aggTrades, bookDepth, bookTicker, indexPriceKlines,
                                  klines, markPriceKlines, metrics, premiumIndexKlines, trades
futures/um/monthly/             : aggTrades, bookTicker, fundingRate, indexPriceKlines,
                                  klines, markPriceKlines, premiumIndexKlines, trades
futures/cm/daily/               : (um daily와 동일) + liquidationSnapshot
futures/cm/monthly/             : (um monthly와 동일, bookDepth·metrics·liquidationSnapshot 없음)
option/daily/                   : BVOLIndex, EOHSummary

# 커버리지 (marker 페이지네이션 적용)
um/daily/metrics/BTCUSDT/                    n=2169  2020-09-01 ~ 2026-08-09
um/daily/metrics/ETHUSDT/                    n=1713  2021-12-01 ~ 2026-08-09
um/daily/metrics/SOLUSDT/                    n=1713  2021-12-01 ~ 2026-08-09
um/daily/bookDepth/{BTC,ETH,SOL}USDT/    n=1312~1315 2023-01-01 ~ 2026-08-09
um/monthly/fundingRate/BTCUSDT/              n=79    2020-01    ~ 2026-07
cm/daily/liquidationSnapshot/BTCUSD_PERP/    n=472   2023-06-25 ~ 2024-10-14
cm/daily/liquidationSnapshot/ETHUSD_PERP/    n=474   2023-06-25 ~ 2024-10-14
cm/daily/liquidationSnapshot/SOLUSD_PERP/    n=455   2023-06-25 ~ 2024-10-14
option/daily/BVOLIndex/BTCBVOLUSDT/          n=1121  2023-06-20 ~ 2026-08-09
option/daily/BVOLIndex/ETHBVOLUSDT/          n=1121  2023-06-20 ~ 2026-08-09
option/daily/EOHSummary/BTCUSDT/             n=147   2023-05-18 ~ 2023-10-23  (중단)
spot/monthly/klines/BTCUSDT/1m/              n=108   2017-08    ~ 2026-07
spot/daily/klines/SOLUSDT/1s/                n=2190  2020-08-11 ~ 2026-08-09

# 압축 파일 크기 (1개 기준)
metrics 1일           10,778 B
liquidationSnapshot 1일 12,840 B
fundingRate 1개월         914 B
BVOLIndex 1일        388,787 B
bookDepth 1일        554,469 B
spot 1m 1개월      2,112,275 B
spot 1s 1일        1,702,786 B

# REST 히스토리 지원 실측
/fapi/v1/fundingRate?startTime=1672531200000          → 200 OK (데이터 반환)
/fapi/v1/premiumIndexKlines?startTime=1672531200000   → 200 OK
/futures/data/openInterestHist?startTime=1672531200000        → -1130 invalid startTime
/futures/data/globalLongShortAccountRatio?startTime=...       → -1130 invalid startTime

# 옵션 라이브 IV
GET /eapi/v1/mark  → 총 1522개 계약(BTC 532개), 각 계약에 markIV/bidIV/askIV/greeks 포함
GET /eapi/v1/exchangeInfo optionContracts underlying:
    XAGUSDT, BTCUSDT, CLUSDT, ETHUSDT, BZUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, XAUUSDT
BVOL 지수 라이브 엔드포인트: 없음 (eapi -1128 / spot -1121, BVOL 토큰 상장폐지)
```
