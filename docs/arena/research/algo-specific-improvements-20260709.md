# 6개 알고리즘 특화 진단 & 개선 계획 (2026-07-09)

> **성격**: 알고별 상세 진단 문서 (코드 수정 없음). 라이브 트랙레코드(Supabase paper_positions,
> 2026-06-19~07-09)와 macro 백필 백테스트 결과, 알고별 특화 리서치를 결합해
> "파라미터 조정 수준인지 / 매매 방식 자체 수정이 필요한지 / 추가 수집 지표가 필요한지"를
> 알고마다 판정한다. 상위 문서: [return-optimization-research-20260709.md](return-optimization-research-20260709.md)

---

## 0. 라이브 성과 스냅샷 (2026-07-09 조회, closed 기준)

| 알고 | 거래 | 승률 | 평균수익 | 가중합산 | 평균보유 | 판정 |
|---|---|---|---|---|---|---|
| omnibus | 3 | 66.7% | +0.38% | +0.06% | 8.4h | ✅ 유일 순플러스 |
| multi_factor | 1 | 0% | -2.69% | -2.69% | 10.3h | ⚠️ 표본 부족 |
| vix_rsi | 4 | 25% | -1.36% | -3.92% | 13.0h | ❌ 주 손실원 2 |
| fng_contrarian | 6 | 16.7% | -1.41% | -7.09% | 45.1h | ❌ 주 손실원 1 |
| **regime_trend** | **0** | — | — | — | — | 💤 3주간 무거래 |
| **macd_momentum** | **0** | — | — | — | — | 💤 3주간 무거래 |

open 포지션 4건 (multi_factor·vix_rsi·fng·omnibus) — 전부 2026-07-08 하락 구간 진입
(MACD hist 전부 음수: -114~-248, RSI 46~50). **롱온리 6개가 하락장에서 동시에 딥매수 중**.

⚠️ 통계 주의: 알고당 n≤6은 유의성 없음. 라이브는 "방향 확인"용이고 판단 근거는
macro 백필 백테스트(6~11개월)와 결합한다. 또한 fng의 stop_loss/trailing_stop 청산 2건은
v22(가격손절 제거, 06-26) **이전** 트레이드 — 라이브 표본에 파라미터 버전이 섞여 있다.

---

## 1. regime_trend — 추세추종 코어

### 현재 로직
강세 레짐 + Donchian20 돌파 + ADX≥20 + EMA 정배열 + RSI<70 + 펀딩/ETF/EMA200/테이커/LSR/OI
**11개 조건 전부 AND**. 청산: flat 신호(레짐/조건 이탈) + 래칫 트레일링.

### 진단
- **3주 무거래는 "정상 동작"** — long/flat 추세추종이 하락장에서 노는 건 설계 의도.
  문제는 강세장이 왔을 때다:
- **조건 중복**: bull_trend 레짐이 이미 return24h/72h>0 + bb_width≥3.5 + EMA 정배열을
  요구하는데, 진입이 다시 EMA 정배열 + ADX + Donchian을 겹쳐 요구. 11-AND는 각 조건이
  독립 확률 0.8이어도 결합 통과율 ~8.6%.
- **돌파 시점 RSI 딜레마**: 20봉 신고가 돌파 순간의 RSI는 통상 60~75 — RSI<70과 자주 충돌.
- **볼륨 미사용**: 돌파 확인의 표준인 거래량 필터가 없다. klines에서 volume을 받아오지만
  지표로 안 쓴다 ([TrendSpider](https://trendspider.com/learning-center/donchian-channel-trading-strategies/),
  [LuxAlgo](https://www.luxalgo.com/blog/donchian-channels-breakout-and-trend-following-strategy/) —
  돌파봉 볼륨 > 20봉 평균×1.5가 가짜 돌파 필터의 정석).
- 테이커 확인이 **일간 lag1** z-score — 4h 돌파 트리거의 확인용으론 하루 늦다.
  arena-features-v8이 이미 4h `taker_buy_sell_ratio`를 수집 중인데 알고 게이트에 미연결.

### 개선안 (우선순위)
1. **[분석만, 즉시] 조건별 차단률 진단** — `explain_signal`/roster_diagnostics가 이미
   조건별 통과/실패를 기록 중. 백테스트 11개월에서 "돌파는 떴는데 무엇이 막았나"를 집계해
   어느 AND가 dead weight인지 정량화. 이것 없이 조건을 빼는 것은 금물.
2. **볼륨 확인 추가 + 중복 조건 정리 교환** — 돌파봉 상대볼륨(vs 20봉 평균) 게이트를 넣는
   대신, 진단에서 중복으로 판명된 조건(예: bull 레짐과 겹치는 EMA 정배열)을 완화하는
   교환을 백테스트. 목표: 통과율은 유지·상향하며 진입 품질 개선.
3. **테이커 확인을 4h 데이터로 교체** — 일간 lag1 → 로컬 4h taker_buy_sell_ratio
   (이미 수집, market_structure v8). 지연 제거 + macro 의존 축소.
4. **듀얼 Donchian(20/50) 검토** — fast/slow 채널 정렬 시에만 진입 (다중 타임프레임 확인).

### 매매 방식 자체 수정 필요? — **아니오**
long/flat 추세추종 코어는 유지. 단 "강세장 진입 기회를 11-AND가 얼마나 흘리는지"를
반드시 사전 정량화해 둘 것 (강세장이 시작된 뒤에 고치면 늦다).

### 추가 바이낸스 지표
- **kline volume (이미 수집, 미사용)** — 신규 수집 비용 0. 최우선.
- 4h takerlongshortRatio (이미 수집) — 게이트 연결만 필요.

---

## 2. fng_contrarian — 공포 역발산

### 현재 로직
FNG<30 + risk-off 아님 + 90일 낙폭≤-10% + breadth/stablecoin veto + MACD hist 개선(v23)
→ 가격 트랜치 물타기(0/-3/-6% → 0.15/0.25/0.30), 가격손절 없음, 시간손절 72h, min_hold 48h.
청산: FNG≥30 복귀 flat 또는 time_stop.

### 진단 (라이브 6건 상세)
- **flat_signal 청산 4건 평균 -0.52%**: v22 진단("조기 FNG-중립 flat이 손실 주범")이
  라이브에서도 재현 중. FNG가 30을 살짝 회복하는 시점은 통상 반등 초입 — 거기서 팔면
  물타기로 낮춘 평단의 이점을 못 살린다. 백테스트에서 time_stop 만기보유 승률 86% vs
  flat 청산 36%였는데, **청산 임계 자체는 여전히 진입 임계(30)와 동일**하다.
- stop/trailing -3.2% 2건은 v22 이전 트레이드 (현재는 비활성 — 문제 아님).
- 구조적 하락장에서 FNG<30이 수 주 지속되면 "공포 역발산"이 아니라 "하락 추종 물타기"가
  된다 — 낙폭 게이트(-10%)만으로는 이 구분이 안 됨.

### 개선안 (우선순위)
1. **청산 히스테리시스 (vix_rsi v26과 동일 메커니즘)** — 진입 FNG<30 / 청산 FNG≥45~50
   (중립 복귀 확인)으로 분리. v26에서 이미 검증된 패턴의 이식이라 리스크 낮음.
   백테스트 그리드(청산 임계 40/45/50/55) + DSR 검증. **기대효과 최상**.
2. **FNG 지속기간 피처** — `fng_days_below_30` 연속일수. 실증상
   [지속된 극단 공포가 이후 강세를 선행](https://www.ainvest.com/news/navigating-crypto-fear-greed-index-strategic-entry-points-fear-dominated-market-2601/)
   — 공포 1일차(뉴스 쇼크)와 소진 국면(N일 지속+안정화)을 구분해 사이징 차등.
3. **청산 캐스케이드(강제청산) 확인** — 역발산 진입의 가장 강한 트리거는 "매도 소진"이고,
   그 직접 증거는 **롱 청산 폭발 후 소강**이다
   ([Kingfisher: liquidation + CVD 결합](https://thekingfisher.io/blogs/liquidation_maps_cvd)).
   현재 v23 MACD hist 프록시보다 직접적. → 신규 수집 필요(아래).
4. 트랜치 -3/-6%가 90일 낙폭 규모와 무관하게 고정 — ATR 배수 기반 동적 트랜치 검토(후순위).

### 매매 방식 자체 수정 필요? — **부분 (청산만)**
진입·물타기·시간손절 구조는 근거가 탄탄(유지). **청산 임계 분리가 미완성 상태** —
v22가 보유기간만 늘렸고 청산 트리거(FNG≥30)는 그대로라 반쪽 수정이었다.

### 추가 바이낸스 지표
- **forceOrder(강제청산) 스트림** — REST 폐지, websocket 전용 → `stream.py`에 구독 추가
  가능. 4h 롱청산 총액 z-score → "캐피출레이션 후 소강" 확인 피처. **이 알고에 가장
  가치 있는 신규 데이터**.
- spot vs perp **CVD 다이버전스** (가격 신저가 + CVD 고저점 상승 = 매도 흡수) —
  aggTrade 기반, realtime 수집기 확장.

---

## 3. vix_rsi — 외생 매크로 필터

### 현재 로직
VIX<q40×1.05 + RSI<50 + risk-off 아님 + breadth/stablecoin veto + MACD hist 개선(v26)
→ 롱. 청산: RSI≥60 또는 VIX≥q40×1.15 (v26 히스테리시스). MA200 게이트 없음.

### 진단
- **엣지 자체가 의심되는 유일한 알고**. v26 수정 전 백테스트 11개월 -10.71%(6알고 중 최악),
  수정 후에도 **-0.57%** — 수정은 손실 축소지 수익 창출이 아니다. 라이브 4건 25% 승률.
- 논리 구조 문제: "주식시장 VIX calm + BTC RSI<50"은 하락 추세에서 상시 성립한다.
  RSI<50은 과매도 반전 신호가 아니라 단순 약세 상태 — **"딥"이 아니라 "하락 중"을 사는 조건**.
- MA200 게이트를 "외생 신호라 방향성 무관" 논리로 제외했지만, 백테스트 손실은 하락
  구간에 집중 — 이론이 데이터와 충돌하면 데이터 우선.
- 근본 의문: 주식 VIX가 BTC 4h 진입에 갖는 정보량. 크립토 자체 내재변동성(Deribit DVOL)이
  더 직접적인 대체재.

### 개선안 (우선순위)
1. **[즉시, 백테스트만] 일간 MA200 게이트 추가 A/B** — macd/omnibus v24와 동일 패턴.
   이것으로도 음수 탈출 실패 시 2번으로.
2. **트리거 재정의: RSI<50 → RSI 과매도 회복 크로스** — "RSI<50인 상태"(상태 조건)가 아니라
   "RSI가 30~35를 하향 후 상향 돌파"(이벤트 조건)로 변경. 평균회귀 진입을 상태 매수에서
   반전 확인 매수로 바꾸는 것 — v26 안정화 게이트의 논리적 완결판.
3. **VIX → DVOL(크립토 내재변동성) 대체 연구** — Deribit 공개 API. "BTC 옵션시장이 calm +
   과매도 반전" 조합이 주식 VIX보다 자산 정합성 높음. regimeRaw에 dvol 필드 추가 검토.
4. **위 전부 실패 시 은퇴/교체 후보 1순위** — 6슬롯 중 유일하게 "고쳐서 살릴 근거"가
   백테스트에 없다. 교체 후보: 금리/DXY 매크로 게이트 + BTC 기술 트리거 조합, 또는
   basis(현선물 스프레드) 기반 캐리 신호 (이미 수집 중인 데이터).

### 매매 방식 자체 수정 필요? — **예 (트리거 재정의 또는 은퇴)**
파라미터 미세조정 단계는 v26으로 끝났다. 다음 단계는 구조 변경이어야 한다.

### 추가 바이낸스 지표
- 바이낸스 외: **Deribit DVOL** (BTC 내재변동성 지수). 바이낸스 내: 없음 — 이 알고의
  문제는 데이터가 아니라 트리거 논리다.

---

## 4. macd_momentum — 모멘텀

### 현재 로직
MACD hist>0 + hist 증가 + RSI<65 + BB폭≥3.5 + ADX≥18, veto: risk-off/펀딩/ETF/4h EMA200/
일간 MA200(v24)/LSR/OI. 청산: flat + 트레일링.

### 진단
- 3주 무거래 — regime_trend와 동일하게 하락장 정상 동작. 그러나 **백테스트도 v24 후
  -1.06%로 음수** — 대기 중인 알고가 강세장에서 벌 거라는 증거가 약하다.
- **regime_trend와 역할 중복**: 두 알고 모두 "확립된 상승 모멘텀 확인 후 진입"이라
  같은 구간에서 같이 진입/휴면. 6슬롯 다양화 관점에서 낭비.
- hist>0 AND hist 증가는 **늦은 진입** — MACD 라인이 시그널을 이미 상회하고 가속까지
  확인한 시점은 통상 상승 중반. 여기에 RSI<65 상한이 걸려 진입 창이 더 좁아짐.

### 개선안 (우선순위)
1. **트리거를 "hist 0선 상향 돌파 이벤트"로 재정의** — 현재의 "hist>0 상태 + 증가"
   대신 "hist가 음→양 전환한 봉"(모멘텀 반전 초기)을 잡는 것으로 백테스트 A/B.
   진입이 빨라지면 RSI<65 충돌도 자연 해소. regime_trend(돌파=추세 중기)와
   시간축 차별화(전환=추세 초기)가 생겨 중복 해소.
2. **볼륨/CVD 확인 결합** — 모멘텀 전환의 진위 필터
   ([CVD 정렬 시 돌파 신뢰도 상승](https://www.backquant.com/learn/cvd)). regime_trend와
   공유 인프라.
3. 진단 스크립트로 v24 이후 잔여 손실 -1.06%의 발생 구간 분해 (어떤 레짐에서 잃는지).

### 매매 방식 자체 수정 필요? — **예 (트리거 시점 재정의)**
"이미 강한 모멘텀"이 아니라 "모멘텀 전환"을 잡는 알고로 정체성을 옮기는 것이
포트폴리오 관점(중복 해소)과 단독 성과 관점 모두에서 유리할 가능성. 백테스트로 결정.

### 추가 바이낸스 지표
- kline volume (이미 수집) / CVD (신규, fng와 공유).

---

## 5. multi_factor — 복합 투표

### 현재 로직
veto(risk-off/ETF/LSR/breadth/stablecoin) 통과 후 5팩터 중 **4개 이상**:
① 강세레짐 ② FNG<60 ③ VIX calm ④ RSI<55 ⑤ 펀딩 미과열. 청산: flat + 트레일링.

### 진단 — **구조적 결함 발견 (고신뢰)**
- **방향성 팩터가 선택 사항**: ②~⑤는 방향성이 아니라 "과열 아님" 조건들이다. 조용한
  하락장에서는 FNG<60 ✓, VIX calm ✓, RSI<55 ✓, 펀딩 미과열 ✓ — **강세레짐 없이 4표
  충족**해 진입한다. 라이브 유일 거래가 정확히 이 패턴: 07-08 하락 구간(RSI 50,
  hist -114) 진입 → 현재 보유 중. 이전 -2.69% 트레일링 청산도 동일 패턴 추정.
- 즉 "5중 4 투표"의 실질은 "강세장에서 사거나, **아니면 조용한 하락장에서 사거나**".
- 백테스트 +0.74%로 유일 순플러스였지만, 이 결함이 수정되면 더 좋아질 여지가 크다
  (하락장 진입분만 제거).

### 개선안 (우선순위)
1. **①(강세레짐)을 필수 조건으로 승격 + 나머지 4중 3 투표** — 최소 변경으로 결함 제거.
   백테스트 A/B는 형식적 확인 수준(논리적으로 명백).
   변형안: ① 필수가 너무 조이면 "①=강세 또는 중립(sideways), bear류만 배제" 중간안.
2. 팩터 가중 투표(레짐 2표) — 1번의 대안, 동일 효과.
3. (후순위) 팩터 추가 검토: stablecoin/breadth를 veto에서 투표 팩터로 이동 — 투표 정보량
   증가 vs 거래빈도 감소 트레이드오프를 백테스트로.

### 매매 방식 자체 수정 필요? — **아니오 (투표 구조 1곳만 수정)**
설계 자체는 건전. 결함은 국소적이고 수정 명확.

### 추가 바이낸스 지표 — 불필요 (기존 데이터로 충분)

---

## 6. omnibus — 전천후 라우터

### 현재 로직
5-state 라우팅: UP_TREND(눌림목, ×1.0) / RANGE(하단 회귀, ×0.40) / DOWN_TREND→
OVERSOLD_REBOUND(3/4 투표, ×0.25) / RISK_OFF·TRANSITION(없음).

### 진단
- **라이브 최고 성적** (3건, 66.7%, 전부 flat 청산, 평균 8.4h) — 라우터 설계가 하락·횡보장
  대응이라는 존재 이유를 실증 중. 백테스트 -2.05%(v24 후)와의 괴리는 백테스트 구간
  (하락 지배적)과 v24 게이트 반영 시점 차이로 추정 — 재실행으로 확인 필요.
- 개선 여지는 **청산의 정밀화**: RANGE/REBOUND는 명확한 목표가가 있는 평균회귀인데
  청산이 "flat 신호 대기"(다음 4h 재평가) — 평균회귀의 정석 청산(BB 중앙선 도달)보다 둔탁.
- REBOUND 사이즈 ×0.25는 보수적으로 타당하나, 승리 시 이익도 ×0.25 — 반등 확인
  강도에 따른 차등(투표 3/4 vs 4/4)이 없다.

### 개선안 (우선순위)
1. **RANGE/REBOUND 목표가 청산 추가** — BB 중앙선(RANGE) / BB 중앙~상단(REBOUND) 도달 시
   익절. 4h 봉 종가 대기보다 빠른 회전 + 평균회귀 이론 정합
   (Bollinger 2002). live는 stream.py 1m 틱으로 목표가 감시(기존 트랜치 감시와 동일 패턴).
2. **REBOUND 투표 강도 차등 사이징** — 3/4표 ×0.25, 4/4표 ×0.35~0.40 백테스트.
3. **REBOUND에 청산 캐스케이드 확인 결합** — fng와 공유 (forceOrder 스트림).
4. TRANSITION 상태 빈도 진단 — 지나치게 자주 TRANSITION이면 기회 유실. 진단 로그 집계.

### 매매 방식 자체 수정 필요? — **아니오 (청산 정밀화만)**
6개 중 가장 건강. 손대는 순서도 마지막이어야 한다(잘 되는 것 먼저 만지지 말 것).

### 추가 바이낸스 지표
- forceOrder 스트림 (fng와 공유), kline volume (반등봉 볼륨 확인).

---

## 7. 종합: 신규 수집 지표 우선순위 (전 알고 공통)

| 순위 | 지표 | 수집 방법 | 비용 | 수혜 알고 |
|---|---|---|---|---|
| 1 | **kline volume 지표화** (상대볼륨 z) | 이미 수신 중 — indicators.py 계산만 | 0 | regime_trend, macd, omnibus |
| 2 | **4h taker ratio 게이트 연결** | 이미 수집(v8) — 알고 배선만 | 0 | regime_trend |
| 3 | **forceOrder 청산 스트림** | stream.py websocket 구독 추가 | 중 | fng, omnibus(REBOUND) |
| 4 | **CVD (spot/perp)** | aggTrade 집계 — realtime 수집기 확장 | 중 | macd, regime_trend, fng |
| 5 | **Deribit DVOL** | 외부 공개 API, 일간이면 충분 | 소 | vix_rsi (대체 연구) |

1·2번은 **수집 비용 제로** — 이미 서버에 도착하는 데이터를 안 쓰고 있는 것부터 해소.

## 8. 실행 순서 제안

```
1주차:  multi_factor 투표 구조 수정 백테스트 (결함 명확, 최소 변경, 기대효과 큼)
        fng 청산 히스테리시스 그리드 백테스트 (v26 패턴 이식)
        regime_trend/macd 조건별 차단률 진단 스크립트 (분석만)
2주차:  volume 지표화 + regime_trend 볼륨 게이트 백테스트
        vix_rsi MA200 게이트 A/B → 실패 시 RSI 크로스 트리거 재정의 실험
3주차~: macd 0선 크로스 트리거 재정의 백테스트
        omnibus 목표가 청산 (stream.py 확장과 함께)
        forceOrder 스트림 수집 시작 (지표는 축적 후)
```

채택 기준은 상위 문서와 동일: 백테스트 개선 + 타 알고 무회귀 + DSR/PBO 통과 +
None→graceful + live/backtest 패리티.

---

## 참고 (알고별 특화분)

- Donchian 가짜돌파 필터·볼륨 확인 — https://trendspider.com/learning-center/donchian-channel-trading-strategies/ , https://www.luxalgo.com/blog/donchian-channels-breakout-and-trend-following-strategy/
- Liquidation map + CVD 결합 — https://thekingfisher.io/blogs/liquidation_maps_cvd
- CVD 개요·다이버전스 — https://www.backquant.com/learn/cvd
- 파생 지표 종합 (OI·펀딩·청산·CVD) — https://medium.com/@cryptocreddy/comprehensive-guide-to-crypto-futures-indicators-f88d7da0c1b5
- FNG 지속기간 실증 — https://www.ainvest.com/news/navigating-crypto-fear-greed-index-strategic-entry-points-fear-dominated-market-2601/
- 공통 방법론(SJM 레짐·DSR/PBO·메타라벨링·변동성 추정) — return-optimization-research-20260709.md
