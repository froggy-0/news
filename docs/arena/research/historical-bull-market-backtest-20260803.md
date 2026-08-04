# 실제 역사적 상승장(2023-08~2024-07) 백테스트 — "상승장 미검증" 질문에 답 (2026-08-03)

> **결론: "상승장이 오면 될 것"이라는 기대는 반증됐다 — BTC뿐 아니라 ETH/SOL도.**
> 2023-2024 실제 랠리 전체(BTC +126.97%·ETH +78.77%·SOL +687.86% buy&hold)를
> 3자산 전부 백테스트한 결과, 6알고 합산 포착률이 **BTC +1.6% / ETH −9.7% / SOL
> +4.2%**로 전부 5% 미만이거나 마이너스였다(§5.1). 원인은 "상승장이 없어서"가
> 아니라 **`regime_trend`의 진입조건이 7개 AND로 묶여있어 역대급 랠리에서도 신호가
> bar의 0.55%에서만 발화**하는 구조적 문제(§3).
>
> BTC 단독 검증(§1~§4)에서 시작해 ETH/SOL 자체 상승장까지 확장(§5.1) — "ETH/SOL은
> 아직 상승장 검증이 안 됐을 뿐"이라는 낙관적 해석의 근거가 사라졌다. 재현: §6.

---

## 0. 배경

`priority-analysis-20260725.md` §3.6이 20개월(2024-11~2026-07, buy&hold −16.29%)
재확인에서 남긴 미결 질문:

> "상승장이든 하락장이든"이라는 목표는 여전히 **상승장 쪽이 미검증**이다. 이 창은
> 순하락장이라, 추세추종 알고들의 무엣지가 "설계 결함"인지 "이 창에 상승국면이
> 없어서"인지 이 데이터만으로는 못 가른다.

세션 중 "그럼 상승장 올 때까지 손 놓고 기다리자는 거냐"는 질문이 나왔다. 답은
**"미래를 기다릴 필요 없이, 이미 일어난 상승장(2023-10~2024-03 BTC ETF 승인 랠리)까지
백테스트 창을 과거로 확장하면 지금 바로 검증 가능하다"**였다 — ETH/SOL 자산을
옆으로 늘리는 것(세션 중 실측: BTC-ETH-SOL 4H 수익률 상관계수 0.78~0.82, "상승국면
비율"도 46.8%/43.9%/42.7%로 거의 동일 — 상관된 자산을 추가해봤자 같은 하락장을
3번 반복 관측할 뿐 새 레짐 표본은 생기지 않음)과 달리, 시간을 뒤로 늘리는 건
실제로 다른 레짐 정보를 준다.

---

## 1. 데이터 준비

### 1.1 BTC 4H OHLCV 백필
`scripts/analysis/backfill_ohlcv_symbol.py --symbol BTCUSDT --start 2023-05-01 --end 2024-07-31`
— `arena_ohlcv_bars`에 **2,749행 upsert**(기존 2024-11~ 데이터와 별도 구간, 충돌 없음).

### 1.2 매크로 재구성 (FNG + funding, VIX 제외)
- **FNG**: `fetch_fng(lookback_days=1200)` — Alternative.me, 458일 전부 결측 없음.
- **Funding rate**: `_fetch_funding_rate_history()` — Binance, 458일 일별 집계,
  `funding_rate_zscore_30d` 직접 계산(join.py와 동일 공식).
- **VIX**: ⚠️ **제외** — 로컬 `FRED_API_KEY` 미설정. `vix_rsi`는 이번 검증에서
  테스트 불가(macro.vix_now=None → 신호 자체가 안 뜸). `_funding_hot`/`_oi_diverged`/
  `_etf_outflow_heavy`/`_lsr_crowded`/`_taker_confirms` 등 veto 함수 코드 확인 결과
  **미수집(None) 시 전부 "차단 안 함"으로 안전하게 처리**됨(`algorithms.py` 실측
  확인) — 즉 데이터 없음이 오차단으로 잘못 해석되는 버그는 없음.
- **로컬 레짐(`arena_regime_state`)**: R2/VIX와 무관하게 4H 가격·지표만으로 매
  bar `regime.classify_regime_variant()`가 독립 계산 — 이 부분은 데이터 공백 영향
  전혀 없음(트렌드 알고 게이팅의 핵심 축).

`risk_overlay.compute_regime_state()`를 일별 워크포워드(과거 창만 보는 `.iloc[:i+1]`
방식, `build_macro_rows()`와 동일 원칙)로 호출해 363일치 macro_rows 생성
(2023-08-04~2024-07-31, 95일 워밍업 후).

---

## 2. 백테스트 결과

`backtest.load_frames_from_supabase(symbol='BTCUSDT', from_date=2023-08-04,
to_date=2024-07-31, macro_rows=...)` + `backtest.run_replay()` — 실제 라이브 코드
경로 그대로(전략 로직 변경 없음, 읽기 전용).

| algo | n | win% | 가중합% | PF | 주요 청산사유 |
|---|---:|---:|---:|---:|---|
| multi_factor | 42 | 52.4 | **+5.47** | 1.63 | flat_signal 41 |
| fng_contrarian | 5 | 80.0 | +2.17 | 3.77 | target_exit 3 (표본 극소) |
| macd_momentum | 64 | 46.9 | +0.33 | 1.07 | flat_signal 64 (사실상 breakeven) |
| **regime_trend** | **11** | 54.5 | **−1.18** | **0.63** | flat_signal 11 |
| omnibus | 123 | 52.8 | **−4.79** | 0.76 | flat 88 / target 25 / stop 7 |
| **6알고 합산** | 245 | | **+2.00%** | | |
| **buy&hold(BTC)** | | | **+126.97%** | | |

frames=2172(2023-08-04~2024-07-30), fng macro 커버리지 2166/2172(99.7%).

**핵심**: 역대급 상승장(+127%)을 줬는데도 6알고 합산은 **+2%** — buy&hold 대비
**−125%p**. "이 창이 하락장이라 추세추종이 기회가 없었다"는 가설이 반증됐다.
상승장을 실제로 줬는데도 압도적으로 못 벌었다.

---

## 3. 원인 분해 — `regime_trend` 조건별 진단

`algorithms.explain_signal("regime_trend", ...)`를 매 bar 재현해 실패 조건을 집계.

```
총 bar: 2172
arena_regime_state 분포: unknown 35.7% / sideways 22.2% / bull_trend 20.4% /
                        bear_trend 13.4% / stress 8.2%
raw_signal='long' 발화 bar: 12건 (0.55%)

조건별 실패 횟수(막힌 이유 랭킹):
  donchian_breakout    2059건 (94.8%)  ← 압도적 1위
  bullish_regime       1717건 (79.1%)
  ema_aligned_up       1239건 (57.0%)
  above_ema200_4h        597건 (27.5%)
  adx_trending           489건 (22.5%)
  funding_not_hot        258건 (11.9%)
  rsi_below_long_max     227건 (10.5%)
```

**로컬 레짐 분류기는 정상이다** — 역대급 랠리 구간의 20.4%를 정확히 `bull_trend`로
잡았다(터무니없이 낮지 않음, "레짐 라벨이 방향은 맞게 찍는다"는 §3.5 기존 확인과
정합). 문제는 그 다음 — **`bullish_regime` AND `donchian_breakout` AND
`ema_aligned_up` AND `adx_trending` AND `above_ema200_4h` AND `funding_not_hot`
AND `rsi_below_long_max`, 7개 조건을 전부 동시에 만족**해야 신호가 뜬다.

각 조건이 개별로는 20~90%대 통과율이어도 **전부 곱하면 지수적으로 줄어든다** —
Donchian20 상단 돌파 자체가 정의상 "최근 20봉 신고가 경신"이라는 저빈도 이벤트라
(이건 원래 그래야 정상 — 돌파는 드물게 일어나야 함), 여기에 6개 조건을 추가로
AND 걸면 역대급 랠리에서도 12번밖에 안 열린다.

**"상승장이 없어서 기회가 없었다"가 아니라 "상승장을 줘도 문이 거의 안 열리는"
과잉 필터링 문제다.**

`omnibus`(n=123, −4.79%)는 반대로 가장 많이 거래하고 가장 많이 잃었다 — 별도
원인 분해가 필요한 후속 과제(§7).

---

## 4. 통계적 주의사항

- **단일 역사적 창**: 2023-10~2024-03 ETF 랠리 단 1회 관측. 다른 상승장
  (2020-2021, 2019 등)으로 확장 검증 전까지 "상승장 전체에 대한 일반화"는 아니다.
- **표본 크기**: `fng_contrarian` n=5, `regime_trend` n=11 — 개별 PF는 참고용,
  통계적 확정 아님(순열검정·부트스트랩 미실시, 시간 제약상 이번 라운드는
  스크리닝 목적).
- **VIX 결측**: `vix_rsi` 전혀 테스트 못함. `FRED_API_KEY` 확보 시 재실행 필요.
- **OI/LSR/ETF흐름/breadth/stablecoin 전부 None**: Binance OI·LSR은 30일
  보존 한계로 2023년 데이터 자체가 존재하지 않음(구조적 한계, 재수집 불가).
  ETF흐름은 2024-01 전엔 상품 자체가 없었음(정상적 결측). breadth·stablecoin은
  이번 라운드에서 재현 우선순위상 생략 — 필요시 추가 가능.
- 이 결측들이 결과를 유리하게 왜곡했을 리스크는 낮다(§1.2에서 확인한 대로
  None→미차단이 기본값이라, 없으면 오히려 진입이 "더 쉬워지는" 방향).

---

## 5. ETH/SOL 크로스에셋 질문과의 관계 — 별개 축

이번 검증은 **"BTC에서 이 알고들이 상승장 자체에서 작동하는가"**를 묻는다. 다른
문서(`cross-asset-verdict-20260731.md`)의 **"BTC 규칙이 ETH/SOL로 전이되는가"**와는
직교하는 질문이다.

| 질문 | 검증 상태 |
|---|---|
| BTC 규칙이 BTC 상승장에서 작동하는가 | **✅ 이번에 검증 — 답: 잘 작동 안 함(§2/§3)** |
| BTC 규칙이 ETH/SOL로 전이되는가(임의 레짐) | ✅ 기존 검증(D분기, 하락장 창) |
| BTC 규칙이 ETH/SOL **상승장**에서 작동하는가 | **✅ 이번에 검증(§5.1) — 답: BTC보다 더 안 좋음** |

세 번째 칸을 §5.1에서 채웠다 — 결과는 기대와 반대였다.

### 5.1 ETH/SOL 자체 역사적 상승장(2023-08~2024-07) 백테스트

같은 macro_rows(FNG+funding, Track A/B 원칙대로 자산 공유 — 자산고유 funding은
`funding-zscore-asset-native-verification-20260801.md`에서 이미 "효과 무시할 수준"으로
확인됨), 같은 방법론으로 ETHUSDT·SOLUSDT 4H(2023-05~2024-07)를 백필(`arena_ohlcv_bars`
upsert, 각 2,749행)해 동일 창을 재현. 로컬 `arena_regime_state`는 자산별로 독립
계산(멀티자산 shadow 설계와 동일 원칙).

| 자산 | buy&hold | 6알고 합산 | 거래수 | 포착률(합산/buy&hold) |
|---|---:|---:|---:|---:|
| BTC | +126.97% | +2.00% | 245 | **+1.6%** |
| ETH | **+78.77%** | **−7.65%** | 256 | **−9.7%** |
| SOL | **+687.86%** | +29.09% | 326 | **+4.2%** |

**3자산 전부 실제 상승분의 5% 미만만 포착하거나 아예 마이너스다.** §2~§3의 발견이
BTC만의 우연이 아니라 **구조적으로 3자산에 재현되는 패턴**임이 확인됐다.

알고별(ETH/SOL) 상세:

| algo | ETH n/PF/sum% | SOL n/PF/sum% |
|---|---|---|
| fng_contrarian | 6 / 5.97 / +1.85 | 6 / 207.49(n극소, 과대해석 금지) / +4.31 |
| macd_momentum | 73 / 0.86 / −2.89 | 97 / 1.46 / +11.57 |
| multi_factor | 40 / **0.70** / −3.62 | 57 / 1.41 / +9.16 |
| omnibus | 126 / 0.75 / −4.15 | 144 / 1.13 / −0.11 |
| regime_trend | 11 / 1.33 / +1.16 | 22 / 1.75 / +4.16 |

**ETH가 유독 나쁘다** — BTC/SOL에서 PF>1이던 `multi_factor`(1.63/1.41)가 ETH에서만
0.70으로 뒤집힌다. `macd_momentum`도 BTC 1.07(사실상 breakeven)·SOL 1.46(양호)
대비 ETH만 0.86(손실). 원인은 미분해(§7 후속과제) — ETH의 이 구간 가격 패턴이
BTC/SOL보다 되돌림이 잦고 지속상승 구간이 짧았을 가능성이 있으나 확인 안 됨.

`regime_trend`는 3자산 모두 PF>1(0.63→1.33→1.75)로 BTC 결과와 방향이 다르지만
n=11/11/22로 전부 소표본 — 통계적 확정 아님.

### 5.2 결론

"ETH/SOL 매매 시작"의 근거가 되려면 이 칸이 좋게 나와야 했는데, **오히려 BTC보다
나쁘게(ETH 포착률 −9.7%) 나왔다.** 원래 우려("BTC조차 상승장에서 신통치 않음")가
더 짙어졌다 — 상승장을 줘도 3자산 다 비슷하게 못 번다는 것까지 확인됐으므로,
"ETH/SOL은 아직 상승장 검증이 안 됐을 뿐"이라는 낙관적 해석의 근거가 사라졌다.

---

## 6. 재현

```bash
# 1) BTC/ETH/SOL 역사적 4H OHLCV 백필 (arena_ohlcv_bars에 upsert, 기존 데이터와 충돌 없음)
.venv/bin/python3 scripts/analysis/backfill_ohlcv_symbol.py \
    --symbol BTCUSDT --start 2023-05-01 --end 2024-07-31
.venv/bin/python3 scripts/analysis/backfill_ohlcv_symbol.py \
    --symbol ETHUSDT --start 2023-05-01 --end 2024-07-31
.venv/bin/python3 scripts/analysis/backfill_ohlcv_symbol.py \
    --symbol SOLUSDT --start 2023-05-01 --end 2024-07-31

# 2) FNG + funding 히스토리 fetch → daily macro dataframe
#    (fetch_fng, futures._fetch_funding_rate_history 재사용 — 임시 스크립트,
#     이 문서 §1.2 명세로 재작성 가능). BTC 소스로 계산, 3자산 공유(Track A/B 원칙).

# 3) risk_overlay.compute_regime_state() 워크포워드 → macro_rows (3자산 공용)

# 4) backtest.load_frames_from_supabase(symbol='BTCUSDT'|'ETHUSDT'|'SOLUSDT',
#      from_date=2023-08-04, to_date=2024-07-31, macro_rows=...)
#    + backtest.run_replay() → §2/§5.1 결과표 (심볼별 실행, 로컬 레짐은 자산별 독립계산)

# 5) algorithms.explain_signal() 재현 루프 → §3 조건별 실패 집계
```

⚠️ **정리 상태**: 1단계(OHLCV 백필, BTC/ETH/SOL 각 2,749행)는 `arena_ohlcv_bars`에
영구 반영됨(재현·후속 분석에 유리해 보존, 기존 2024-11~ 데이터와 별도 구간이라
충돌 없음). 2~5단계 스크립트는 `/tmp/bullval/`에 임시로 작성했던 것으로 세션 종료
시 사라짐 — 재실행 필요 시 위 명세로 재작성.

---

## 7. 다음 단계 (미착수, 사용자 결정 필요)

1. **`omnibus` 원인 분해** — 3자산 전부(BTC n=123·ETH n=126·SOL n=144)로 가장
   많이 거래했는데 셋 다 저조(−4.79%/−4.15%/−0.11%). `regime_trend`와 달리
   과소거래가 아니라 **품질 나쁜 과다거래**로 보여 다른 진단이 필요.
2. **ETH 유독 부진 원인 분해** — §5.1에서 새로 발견. `multi_factor`·`macd_momentum`이
   BTC/SOL에선 PF>1인데 ETH에서만 PF<1로 뒤집힘. 이 구간 ETH 가격 패턴(되돌림
   빈도·지속상승 길이)이 BTC/SOL과 다른지 확인 필요.
3. **FRED_API_KEY 확보 후 VIX 포함 재실행** — `vix_rsi` 검증 공백 해소(3자산 공통).
4. **다른 역사적 상승장으로 확장** — 2020-2021 랠리 등, 표본을 1개 창에서 늘려
   일반화 가능성 확인(지금은 3자산×1개 창).
5. ~~ETH/SOL 자체 상승장 구간 백테스트~~ — **완료(§5.1)**. 결과: BTC보다 나쁨.
6. **진입조건 완화 실험** — `donchian_breakout`(94.8% 차단) 단독이 병목이므로,
   이 조건만 완화했을 때 신호율·수익률이 어떻게 바뀌는지 A/B. 단, 과거
   `WI-4`(볼륨확인 추가)가 거래수 11→5로 오히려 붕괴시킨 선례가 있어(교차 참조:
   CLAUDE.md) 조건 변경은 신중한 walk-forward 검증 필요.
