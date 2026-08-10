# 청산 데이터 백필 가능성 + 문헌 기반 활용 설계 (2026-08-10)

## 1. 백필 가능성 — 확인 결과: 불가능

> ⚠️ **2026-08-11 정정**: 이 절의 결론은 **부분적으로 틀렸다.** 아래 조사는 USDT-M
> (`data/futures/um/`)만 확인하고 COIN-M(`data/futures/cm/`)을 열어보지 않았다. cm에는
> `liquidationSnapshot`이 존재하며 BTC/ETH/SOL USD_PERP 전부 **2023-06-25~2024-10-14**
> 구간이 있다(개별 청산 주문 단위, side/price/qty 포함, 3심볼 합 ~18MB).
> 따라서 **역사적 상승장 창(2023-08~2024-07)에 한해 백필·검증이 가능하다.**
> 아래 논지 중 "USDT-M에는 없다"·"forceOrders는 계정 전용"·"2024-10-14 이후는 어디에도 없다"는
> 그대로 유효하다. 상세·한계(cm≠um 규모차, 하락장 창 미커버)는
> [binance-data-catalog-audit-20260811](binance-data-catalog-audit-20260811.md) §4 D3·§5 참조.

Binance 공식 대용량 히스토리 아카이브(`data.binance.vision`, `binance-public-data` 저장소)를
S3 리스팅 API로 직접 조회:

```
data/futures/um/daily/   → aggTrades, bookDepth, bookTicker, indexPriceKlines, klines,
                             markPriceKlines, metrics, premiumIndexKlines, trades
data/futures/um/monthly/ → aggTrades, bookTicker, fundingRate, indexPriceKlines, klines,
                             markPriceKlines, premiumIndexKlines, trades
```

**`liquidationSnapshot`(또는 유사 명칭)류는 daily·monthly 어느 쪽에도 존재하지 않는다.**
`GET /fapi/v1/forceOrders`(REST) 역시 호출 계정 자신의 청산만 반환(시장 전체 아님, 문서
확인). 즉 바이낸스는 **시장 전체 청산의 과거 이력을 어떤 경로로도 공개하지 않는다** —
지금(2026-08-10) 살린 WS가 유일한 채널이고, 그 이전 데이터는 원천적으로 존재하지 않는다
(우리가 수집을 안 한 게 아니라 애초에 받을 방법이 없었음).

**참고로 이건 우리만의 문제가 아니다** — 아래 §2의 2026년 논문(정확히 바이낸스 BTCUSDT
대상)도 "leverage variables are proxies for a liquidation state we cannot observe... data
no longer published by Binance at usable resolution"라고 명시한다. 최신 학술 연구조차 원본
청산 마이크로구조 데이터에 접근 못 해 대리변수(OI, L/S ratio, taker 비율)로 우회하고 있다.
반대로 우리가 지금 막 살린 WS는 **개별 이벤트(가격·수량·방향·시각) 원본**이라, 오히려
이 논문 저자들이 쓴 5분 집계 대리변수보다 해상도가 높다. "늦었다"기보다 "이제부터는 남들도
못 가진 원본 데이터를 실시간으로 쌓기 시작한 것"에 가깝다.

## 2. 문헌 리뷰

### [arXiv:2102.04591](https://arxiv.org/abs/2102.04591) — "Liquidation, Leverage and Optimal Margin in Bitcoin Futures Markets"
BitMEX 무기한선물 데이터로 GEV(generalized extreme value) 이론을 적용해 꼬리분포를 모델링.
- **일일 강제청산율**: 롱 3.51%, 숏 1.89% (비대칭 — 크립토의 구조적 롱 편향과 정합).
- 청산되는 트레이더의 평균 레버리지 **60배**.
- 정규분포 가정은 최적 마진을 심하게 과소추정 — 꼬리위험이 훨씬 두껍다.
- ⚠️ 가격예측이 아니라 **거래소 마진 설계** 논문 — "청산량으로 향후 가격을 예측한다"는
  주장은 하지 않는다. 다만 "청산은 일상적으로 발생하는 현상이고 그 규모가 상당하다"는
  베이스라인 감(예: 4h 버킷당 몇 % 수준이 '평범'하고 몇 %가 '이례적'인지 캘리브레이션
  기준)을 준다.

### [arXiv:2607.27070](https://arxiv.org/html/2607.27070) — "Where does the criticality live? Early-warning signals are event-heterogeneous across seven crypto-perpetual liquidation cascades" (2026)
**바이낸스 USDⓈ-M BTCUSDT, 2022~2025년 7개 대형 캐스케이드**를 1분 가격·5분
레버리지/주문흐름 지표로 정밀 분석 — 우리 상황과 거의 동일한 대상.
- **핵심 결론(부정적)**: "No variable is event-invariant" — 가격 자기상관은 7개 중 5개
  이벤트에서만 신호를 보였고, 뉴스 충격형 2개(관세 발표 등)에서는 완전히 사라짐. 롤링
  분산은 "크립토 시장은 변동성 군집이 일상"이라 거의 항상 상승 추세라 오탐이 심해
  "보편적으로 신뢰 불가"로 결론.
- **유일하게 살아남은 신호**: taker 주문흐름 분산의 **압축(감소)**이 6/7 이벤트에서
  캐스케이드 발생에 선행(Fisher 결합 p≈5×10⁻⁶) — 그러나 저자들 스스로 "개별 이벤트
  경보로 쓰기엔 너무 약함"(2/6은 귀무분포와 겹침)이라 명시.
- **저자들의 명시적 경고**: "단일 거래소·단일 변수 조기경보 주장은 설계상 취약하다."
  2025-10 사례에서 인샘플로는 레버리지/흐름 신호가 유효해 보였지만 아웃오브샘플에서
  뒤집혔음 — 정확히 아레나가 DSR/PBO로 늘 걸러내는 실패모드(그리드 핏이 표본 밖에서
  무너짐)와 같은 현상.
- **결론적 권고**: 캐스케이드 "예측"(사전 경보)이 아니라 "메커니즘 자체에서 유도된 상태
  변수"와 "집단 상관구조"를 보라고 제안.

## 3. 시사점 — 아레나에 어떻게 적용할까

두 논문 모두 **"청산 데이터로 캐스케이드를 사전 예측"하는 건 학술적으로도 아직 신뢰
가능한 해법이 없다**는 쪽으로 수렴한다(가장 직접적으로 관련된 2607.27070이 명시적으로
그렇게 결론). 이건 애초에 이 코드베이스가 노리던 것과도 다르다 — `liquidation_stream.py`
docstring이 이미 밝히듯 목표는 "**매도 소진(캐피출레이션) 직접 증거**"(사후 확인용
게이트)이지 "캐스케이드가 언제 올지 예측"(사전 경보)이 아니다. 이 구분이 중요하다:

| | 캐스케이드 사전예측 (논문이 회의적인 것) | 소진 사후확인 (아레나가 원래 노리던 것) |
|---|---|---|
| 질문 | "곧 청산 캐스케이드가 온다" | "방금 청산 캐스케이드가 지나갔다" |
| 시점 | forward-looking | backward-looking (관측 시점=이미 일어난 사실) |
| 난이도 | 높음(논문이 반증) | 낮음(단순 롤링 합계로 관측 가능) |
| 아레나 용도 | (해당 없음, 안 쓸 것) | fng_contrarian/omnibus REBOUND 진입 시 "바닥 다지는 중인가" 품질필터 |

즉 논문들의 회의론은 우리 원래 설계 방향과 충돌하지 않는다 — **오히려 "예측형 신호로
확장하지 말라"는 명확한 가드레일**을 준다. 후자(사후확인)만 하면 된다.

## 4. 제안 설계 (구현은 데이터 축적 후 — 지금은 설계만)

### 특징 후보 (전부 순수 관측치, 예측 아님)
- `liq_long_usd_24h` / `liq_short_usd_24h`: 최근 24h(6버킷) 롱/숏 청산 합계(USD).
- `liq_asymmetry_24h = (long-short)/(long+short)`: 방향성(+1=롱청산 지배=투매 우세).
- `liq_intensity_zscore`: 위 합계의 롤링 z-score(참고 베이스라인: §2 BitMEX 연구의 일일
  3.51%/1.89% — 우리 표본으로 재계산 필요, 문헌값을 그대로 이식하지 않음).

### 사용 방식 (제안, 미확정)
- fng_contrarian/omnibus REBOUND의 **진입 품질필터**(N-of-M 투표의 추가 항목 후보) —
  "낙폭은 충분한데 아직 롱 청산이 안 잦아들었다"(`liq_asymmetry_24h`가 여전히 롱청산
  우세) 상황에서 진입 보류하는 veto 후보. **방향 예측이나 사이징 확대에는 쓰지 않는다**
  — §3의 가드레일.
- 절대 하지 말 것: taker 분산 압축 같은 정교한 조기경보 신호를 자체 재현하려는 시도
  (2607.27070이 이미 "단일 거래소로는 취약"이라고 반증했고, 우리는 그 논문보다 표본이
  훨씬 적을 것).

### Go/No-Go 게이트 (착수 조건)
1. **최소 표본**: "N일"이 아니라 **실제 대형 청산 이벤트가 여러 건 관측**될 것 — 참고
   문헌(2607.27070)은 3년치에서 7개 이벤트를 썼다. 우리는 그렇게 오래 못 기다리지만,
   최소 눈에 띄는 청산 스파이크가 5건 이상 쌓이기 전엔 그리드/튜닝 착수하지 않는다
   (n=1~2로 그리드하면 P4 과최적화 감사가 이미 경고한 함정 그대로 재현).
2. **검증**: 문헌이 그럴듯하다고 코드에 바로 반영하지 않는다 — 기존 컨벤션(그리드→
   walk-forward→DSR/PBO) 그대로 통과해야 채택. 논문의 회의론을 감안하면 오히려
   **채택 기준을 더 보수적으로**(예: veto 전용, 사이징/방향 신호로 확장 금지) 유지.
3. **재확인 시점**: `arena_liquidation_bars`에 유의미한 스파이크가 쌓였는지
   `/arena-status` 또는 별도 스크립트로 주기적 확인(월 1회 정도면 충분 — 매일 확인할
   실익 없음, 캐스케이드 자체가 저빈도 이벤트).

## 5. 결론

- 백필: USDT-M은 불가능(바이낸스가 원천적으로 미공개, 우리만의 문제 아님). **단 COIN-M은
  2023-06-25~2024-10-14 구간 가능 — 2026-08-11 정정, §1 상단 박스 참조.**
- 문헌: "예측형 신호"는 최신 연구도 신뢰 못 함 → 그 방향은 아예 안 감. "사후 소진확인"은
  원래 설계 그대로 유효, 문헌이 방향을 바꾸진 않지만 **가드레일(veto 전용, 보수적 검증)**
  을 명확히 함.
- 다음 액션은 청산 이벤트가 몇 건 쌓인 뒤 §4 게이트 조건 충족 시 그리드 착수.

## 6. 구현 완료 (2026-08-10, 같은 세션 후속)

위 설계를 코드로 배선(게이트는 기본 off, §4 조건 충족 전까지 라이브 무영향):

- **멀티자산 수집**: `liquidation_stream.py`를 BTC 단일 심볼에서 BTC/ETH/SOL 콤바인드
  스트림(`/market/stream?streams=btcusdt@forceOrder/ethusdt@forceOrder/solusdt@forceOrder`)
  으로 확장. 심볼별 독립 4h 버킷(`dict[symbol, _Bucket]`), 콤바인드 래퍼(`{"stream":...,
  "data":{...}}`)·raw 단일스트림 포맷 둘 다 파싱하는 `parse_force_order_frame()` 순수함수로
  분리(테스트 용이).
- **피처 계산**: `liquidation_features.py`(신규) — `recent_liquidation_totals`·
  `liquidation_asymmetry`·`liquidation_intensity_zscore`(고정 시간격자 청크 기반, 데이터
  없는 구간=진짜 0으로 자연 반영)·`liquidation_snapshot`(macro 주입용) 전부 순수함수.
- **DB 읽기**: `data_lake.fetch_liquidation_bars(symbol, since)` 추가(그레이스풀 실패 처리,
  `fetch_latest_realtime_risk_state`와 동일 패턴).
- **macro 주입**: `scheduler._run_cycle()`에 심볼별(`profile.symbol`) 청산 스냅샷 주입 —
  `taker_ratio_4h`(WI-10)와 동일한 위치·패턴, 조회 실패해도 사이클 무영향.
- **veto 배선**(기본 off, `parameters.LIQUIDATION_EXHAUSTION_GATE_ENABLED=False`):
  `algorithms._liquidation_exhaustion_sufficient(macro)` — `fng_contrarian`(핵심조건 뒤)과
  `omnibus`의 DOWN_TREND/OVERSOLD_REBOUND 레그에만 배선(설계 §4 스코프 그대로, UP_TREND/
  RANGE 레그·타 4개 알고는 완전히 무관 — 테스트로 격리 확인). 진입 결정 함수·`explain_signal`
  진단 함수 양쪽에 동일하게 반영(diagnostics에서 `liquidation_exhaustion_sufficient` 조건
  확인 가능).
- **테스트**: `test_arena_liquidation_features.py`(7건)·`test_arena_liquidation_stream.py`
  (6건)·`test_arena_algorithm_diagnostics.py` 추가 6건 — 게이트 off 시 무변화, on 시 정확한
  차단/통과, 레그 격리(UP_TREND 무관) 전부 확인. arena 239개 테스트 통과.
- **배포**: EC2 rsync+재시작 완료. 라이브 로그로 3심볼 동시 연결(`symbols=('BTCUSDT',
  'ETHUSDT', 'SOLUSDT')`) 및 스케줄러의 심볼별 `arena_liquidation_bars` 조회(BTCUSDT/
  ETHUSDT/SOLUSDT 각각 200 OK) 확인. 재시작 직전 구버전(BTC 단일)이 실제로 첫 유효 데이터를
  이미 적재한 것도 확인(`2026-08-10T12:00:00 long=$576900(30) short=$51670(5)`).
- **의도적으로 안 한 것**: `backtest.py` 배선은 보류 — 실데이터가 지금 막 쌓이기 시작해
  백테스트할 과거 청산 이력 자체가 없음(§1). 실제 그리드/검증 시점(§4 게이트 충족 후)에
  백테스트 배선과 검증을 함께 진행하는 게 낫다(다른 rejected 실험들처럼 미리 만들어놓고
  안 쓰는 코드를 최소화). `PARAMS_VERSION` bump 없음 — 게이트가 전부 off라 라이브 신호에
  변화 없는 순수 인프라 변경.
