# Paper Trading Arena 외부 구조 리뷰 — 2026-07-25

## 1. 총평

현재 Arena는 “BTC 4H 현물 long/flat 알고리즘 6개를 과최적화 방어 하에 운영하는 실험장”으로는 꽤 엄격하게 관리되고 있지만, “하락장에서도 반등 기회를 선별해 양의 수익을 보탠다”는 목표를 달성했다고 보기는 아직 이르다. 숏을 쓰지 않는다는 사실 자체는 이 목표와 모순되지 않는다. 하락 추세 안에도 과매도 해소·숏커버·유동성 충격 복원에 따른 반등이 있고, long/flat은 그중 일부를 먹고 나머지 시간에는 현금으로 방어할 수 있다. 다만 가능한 목표는 상승장과 대칭적인 수익 극대화가 아니라, “하락장 전체 구간에서 큰 손실을 피하면서 반복되는 반등 거래의 순기대값을 양수로 만든다”는 비대칭 목표다. 실제 코드는 omnibus의 `DOWN_TREND → OVERSOLD_REBOUND` 경로와 0.25배 사이징·ATR 목표가로 이 철학을 이미 구현하고 있다(src/arena/algorithms.py:705, src/arena/algorithms.py:755, src/arena/algorithms.py:768, src/arena/algorithms.py:787). 그러나 2026-07-25 07:24 UTC `arena_status.py --since-version arena-params-v30` 기준 전체 청산 37건과 현행 v30 14건만으로는 이 경로가 하락장에서 실제 양의 기대값인지 분리 검증할 수 없다. 현재 시스템은 방향은 맞지만, “하락장 반등 포착 능력”을 독립 성과축으로 입증하지 못한 상태다.

## 2. 동의하는 기존 결론

### 2.1 롱온리 구조에서 regime_trend/macd_momentum 무거래는 대체로 정상이다

`regime_trend`는 강세 레짐, Donchian 돌파, ADX, EMA 정렬, RSI, 펀딩, ETF, EMA200, 테이커, 볼륨, LSR, OI 조건을 모두 요구한다(src/arena/algorithms.py:318). `macd_momentum`도 risk-off, 펀딩, ETF, EMA, MA200, LSR, OI, BB폭, RSI, ADX를 통과해야 한다(src/arena/algorithms.py:472). 2026-07-24 게이트 진단에서 `regime_trend`는 1966봉 중 long 신호 7개(0.4%), `macd_momentum`은 4개(0.2%)에 불과했다(docs/arena/research/gate-block-rates-20260724.md:6, docs/arena/research/gate-block-rates-20260724.md:41). 이건 “알고가 죽었다”기보다, 하락/전환 국면에서 롱 추세추종이 쉴 수밖에 없는 설계의 귀결이다.

다만 “정상”과 “목표 달성”은 다르다. 이 두 추세 알고가 쉬는 동안 omnibus·fng_contrarian 같은 평균회귀 계열이 하락장 반등을 실제로 수익화하는지가 별도로 증명돼야 한다.

### 2.2 비용 정합과 omnibus 사이징 패리티를 먼저 잡은 순서는 타당했다

W1/W2 문서는 백테스트 기본 비용 10bps가 라이브 13bps와 달랐고, omnibus RANGE/REBOUND 사이징 multiplier가 live에만 적용되고 backtest에는 없던 문제를 지적했다(docs/arena/research/implementation-plan-w-series-20260715.md:18, docs/arena/research/implementation-plan-w-series-20260715.md:90). 이건 파라미터 튜닝 이전에 반드시 고쳐야 하는 판단 인프라 문제다. 이 순서는 맞았다.

### 2.3 WI-1 multi_factor 레짐 필수화는 구조적으로 맞는 수정이다

`multi_factor`는 기존 5중4 구조에서 방향성 레짐이 선택 조건이면 FNG/VIX/RSI/펀딩만으로 조용한 하락장 롱이 가능했다. 현재 코드는 `MULTI_FACTOR_REGIME_REQUIRED=True`이고, bullish 또는 sideways 레짐을 먼저 요구한 뒤 나머지 팩터 득표를 본다(src/arena/algorithms.py:519). 이건 “조용한 하락장에서 방향성 없는 롱”이라는 명확한 설계 결함을 제거한 것이며, 단순 튜닝이 아니라 구조 수정이다.

### 2.4 vix_rsi/multi_factor에 단순 ATR 목표가를 붙이는 가설 기각은 대체로 타당하다

Tier2 문서는 vix_rsi와 multi_factor에 ATR 목표가를 붙인 뒤 walk-forward와 DSR/PBO로 검증했고, vix_rsi PBO 0.877, multi_factor PBO 0.921로 기각했다(docs/arena/research/big-candle-no-pnl-diagnosis-20260715.md:165). 코드상 범용 목표가 배선은 빈 dict이면 무효과인 구조로 남아 있다(src/arena/parameters.py:340). “평균회귀 진입의 논리적 종료점”이 명확한 omnibus/fng와 달리, vix_rsi·multi_factor는 고정 ATR 캡이 이론적으로 약하다. 이 가설의 기각은 납득된다.

### 2.5 P4 unknown 사이징 완화 기각은 “그 특정 처방”에 대해서는 타당하다

코드는 local 4H 레짐이 unknown이면 유효 레짐 판단에서 macro overlay로 폴백한다(src/arena/algorithms.py:31). 그리고 unknown 완화는 진입 veto가 아니라 `UNKNOWN_REGIME_SIZE_MULT_BY_ALGO`에 등록된 경우에만 사이징을 줄이는 구조다(src/arena/algorithms.py:63, src/arena/parameters.py:357). 11개월 백필에서 unknown 진입이 순양 기여였고 사이징 축소가 손익만 깎았다면, “unknown이면 일괄 사이즈 축소”는 잘못된 처방이다. 이 결론에는 동의한다.

## 3. 반박/재검토가 필요한 기존 결론

### 3.1 “파라미터 튜닝 레버가 소진됐다”는 말은 너무 넓다

문서상 여러 A/B가 기각된 것은 사실이다. 하지만 대부분은 이미 정한 알고리즘 family 안에서 임계값·시간·목표가·사이징을 바꾼 것이다. 따라서 더 정확한 결론은 “현재 6개 롱온리 룰셋 안에서, 기존 피처와 기존 진입 철학을 유지한 채 소규모 파라미터만 바꾸는 레버는 상당히 소진됐다”이다. “수익 개선 여지가 소진됐다”는 결론은 과하다.

특히 2026-07-24 gate-block 결과는 일부 조건이 dead weight 후보일 수 있음을 다시 보여준다. 예를 들어 macd_momentum의 `macd_hist_positive`, `rsi_below_long_max`, `bb_width_sufficient` near-miss는 이후 평균수익이 각각 +0.51%, +0.22%, +0.17%였다(docs/arena/research/gate-block-rates-20260724.md:62). multi_factor의 breadth/ETF/LSR veto near-miss도 양수다(docs/arena/research/gate-block-rates-20260724.md:94). 이 숫자만으로 바로 바꾸면 안 되지만, “재시도 금지” 딱지로 닫기에는 근거가 너무 거칠다.

### 3.2 DSR/PBO 게이트는 방향은 맞지만 적용 방식은 과잉 확신을 만든다

`validation_stats.py`는 DSR과 CSCV PBO를 구현한다. DSR은 선택된 best config의 return 배열과 n_trials로 계산하고(scripts/analysis/validation_stats.py:43), PBO는 config별 동일 길이 시계열을 요구한다(scripts/analysis/validation_stats.py:93). 방향은 맞다. 문제는 이 도구가 “소표본에서 보수적이어야 한다”는 목적과 “기각 결론을 확정적으로 말한다”는 문서 톤 사이에서 혼용된다는 점이다.

소표본 live n=1~14는 DSR/PBO를 적용할 수 없어서 백필 11개월에 의존한다. 그런데 백필은 현재 라이브 국면과 분포가 다를 수 있고, macro parquet forward-fill/stale 이력도 문서화되어 있다(CLAUDE.md:226). 이 경우 PBO ≤0.2를 통과하지 못했다고 해서 “영구 재시도 금지”는 과하다. 더 적절한 판정은 “현재 백필 검증 창과 이 그리드에서는 채택 불가”다.

### 3.3 레짐 분류기는 병목일 가능성이 높다. 사이징 완화 실패가 분류기 정상성을 증명하지 않는다

`classify_regime()`는 strict_v1 고정이고(src/arena/regime.py:49), 실제 판정은 24h/72h 수익률, BB폭, EMA fast/slow, ATR extreme, sideways 폭 조건에 거의 전부 의존한다(src/arena/regime.py:71, src/arena/regime.py:133). `market_features`에서는 funding과 OI를 snapshot에 넣지만 판정에 쓰지 않는다(src/arena/regime.py:79). macro regime도 snapshot에만 들어가고 strict 판정에는 쓰이지 않는다(src/arena/regime.py:81). 즉 이 분류기는 “시장 상태를 다층적으로 분류”한다기보다 “단기 수익률·EMA·BB폭으로 이름표를 붙이는 룰”에 가깝다.

omnibus는 이 한계를 알고 있어서 local unknown이면 별도 2of3 relaxed 계산으로 다시 분류한다(src/arena/algorithms.py:604). 이건 역설적으로 main classifier가 너무 많은 구간을 unknown/transition으로 남긴다는 증거다. P4 unknown 사이징 완화가 실패했다는 사실은 “unknown인 거래도 11개월 평균으로는 수익 기여였다”는 뜻이지, “분류기가 충분히 정밀하다”는 뜻이 아니다.

### 3.4 “청산 튜닝이 소진됐으니 문제는 진입이다”는 논리 비약이다

MFE 진단은 아직 애매하다. 4H 기준으로는 fng/vix/multi_factor의 포착률이 낮고, 2026-07-25 실측에서도 fng -3%, vix -29%, multi_factor -111%로 나쁘다. 하지만 1m 재진단에서 vix_rsi는 4H 아티팩트였다는 결론이 문서화되어 있고(CLAUDE.md:281), fng와 multi_factor만 1m에서도 누출이 재확인됐다는 상태다. 따라서 “청산 전반 소진”이 아니라 “단순 시간배리어와 단순 ATR 목표가는 소진, 알고별로 원인이 다름”이 맞다.

특히 multi_factor는 최근 현행 v30 4건에서 -1.64%로 다시 나빠졌고, trailing_stop 4건·flat_signal 6건이 섞여 있다(2026-07-25 arena_status 실행 결과). 이건 진입 품질, stop distance, flat signal timing, 레짐 필터가 모두 얽힌 문제다. ATR 목표가 하나가 실패했다고 청산 레이어를 닫으면 안 된다.

### 3.5 `sleeves.py`는 아직 하락장 반등 전략의 검증 장치가 아니다

실제 `SHADOW_SLEEVES`에는 `trend_core` 하나만 등록되어 있다(src/arena/sleeves.py:148). 이 sleeve는 `algorithms.regime_trend()`를 감싼 비용 인식 추세 코어일 뿐이고(src/arena/sleeves.py:101), 하락장 반등을 독립된 성과 단위로 추적하지 않는다. 반등 로직은 현재 omnibus 내부의 한 하위 상태로 묻혀 있어, 전체 omnibus 손익만 보면 UP_TREND·RANGE·OVERSOLD_REBOUND 중 무엇이 돈을 벌었는지 알 수 없다. 따라서 sleeves의 방향성은 쓸 만하지만, 현재 구현은 숏 없이 반등을 먹는다는 목표를 검증하는 답이 아니다. 별도의 숏 sleeve가 필요한 것이 아니라, 하락장 반등 가설을 다른 레짐 손익과 분리해 shadow 검증할 연구 단위가 필요하다.

## 4. 가장 중요한 구조적 갭 Top 3

### Top 1. 목표 문장과 측정 기준이 불명확하다

실행 구조가 현물 long/flat인 것은 의도와 맞다(src/arena/parameters.py:45). 문제는 “하락장에서도 안정 고수익”이 상승장과 같은 절대수익을 뜻하는지, 하락장 전체 기간의 양수 수익을 뜻하는지, 아니면 반등 이벤트들의 양의 기대값과 낮은 낙폭을 뜻하는지 정의되어 있지 않다는 점이다. 숏 없이도 세 번째 목표는 충분히 가능하고, 두 번째도 반등 빈도와 크기가 충분하면 가능하다. 반면 첫 번째는 long/flat의 노출 기회가 제한되므로 현실성이 낮다.

현재 보고는 알고별 전체 손익 중심이라 `OVERSOLD_REBOUND`만의 거래수, 순손익, 승률, profit factor, 보유시간, 최대 연속손실, 반등 capture ratio를 보여주지 않는다. 이 상태에서는 방향이 맞는지조차 판정할 수 없다.

예상 임팩트: 가장 크다. 목표와 평가축을 바로 세우면 “하락장에서 쉬는 것”과 “반등 포착에 실패한 것”을 구분할 수 있다.

### Top 2. 레짐 분류기가 너무 단순하고, unknown/transition의 의미가 불명확하다

strict_v1은 단기 return 부호와 EMA 정렬, BB폭을 AND로 묶는다(src/arena/regime.py:133). sideways와 trend 모두 같은 `REGIME_TREND_BB_WIDTH_MIN = 3.5`, `REGIME_SIDEWAYS_BB_WIDTH_MAX = 3.5` 경계에 걸려 있다(src/arena/parameters.py:427). 분류기가 macro/futures/breadth/stablecoin을 직접 활용하지 않기 때문에, “가격 구조”, “유동성”, “포지셔닝”, “공포/리스크오프”가 하나의 레짐 확률로 통합되지 않는다.

예상 임팩트: 큼. 단순 사이징 조정이 아니라, 진입 가능 universe 자체를 바꾸는 상위 의사결정 품질 문제다.

### Top 3. 검증 체계는 엄격하지만, “기각의 해석”이 지나치게 확정적이다

PBO/DSR는 좋은 방어막이다. 그러나 결과 해석이 “이 그리드/이 기간에서 채택 불가”를 넘어 “재시도 금지/구조 결함 아님”으로 자주 확장된다. 특히 live 표본은 극소이고, 백필 기간은 최근 live 국면과 다를 수 있다. 이 상황에서 강한 통계 게이트는 채택 기준으로는 적절하지만, 연구 방향을 닫는 근거로는 과하다.

예상 임팩트: 중~큼. 과최적화는 막지만, 진짜 regime-conditional edge까지 버릴 수 있다.

## 5. 다음에 시도해볼 만한 방향

### 5.1 “하락장 반등 포착”을 독립 목표로 정의

왜 지금까지 안 했는지: 하락장 대응이 전체 Arena의 방어 성과와 omnibus 총손익 안에 섞여 있었고, “하락장 수익”이라는 표현도 손실 회피와 반등 수익을 구분하지 않았다.

왜 지금은 해볼 가치가 있는지: 숏 없이도 하락장 반등을 먹겠다는 의도는 합리적이다. 다만 성패는 하락장 전체 benchmark 대비 방어력, 반등 거래 순손익, 실제 반등 대비 capture ratio, 거래가 없던 기간의 기회비용으로 나눠 봐야 한다. 이 기준이 있어야 “반등을 다 못 잡아도 괜찮다”는 허용 범위와 최소 성공 조건을 정할 수 있다.

### 5.2 레짐 분류기를 독립 연구 대상으로 격상

왜 지금까지 안 했는지: 게이트/청산/사이징 쪽에서 빠르게 고칠 수 있는 레버가 많았고, SJM 같은 상위 레짐 모델은 shadow 판단 대기 대상으로 남아 있었다.

왜 지금은 해볼 가치가 있는지: 반등 롱의 핵심은 “하락장이냐”보다 “급락 진행 중이냐, 매도 압력이 둔화된 반등 가능 구간이냐”를 구분하는 것이다. local strict classifier는 features를 거의 쓰지 않고 funding/OI/macro는 snapshot에만 둔다(src/arena/regime.py:79). unknown 사이징 완화 실패는 “unknown이 나쁘다”가 아니라 “unknown이라는 라벨이 정보량이 낮다”로 읽는 편이 더 타당하다. 다음 연구는 unknown 비율 축소 자체보다, 분류 결과와 `PANIC_DROP`·`OVERSOLD_REBOUND` 구분이 이후 1~3개 4H봉의 return/vol/drawdown을 실제로 분리하는지 검증하는 쪽이어야 한다.

### 5.3 gate near-miss를 “즉시 완화”가 아니라 “후보 발굴”로 재사용

왜 지금까지 안 했는지: gate 완화 실험들이 많이 기각되어, 재튜닝 자체에 피로도가 쌓였다.

왜 지금은 해볼 가치가 있는지: 2026-07-24 near-miss raw는 일부 조건이 dead weight일 가능성을 보여준다. 예를 들어 multi_factor의 breadth veto near-miss 93건 평균 +0.87%는 무시하기 어렵다(docs/arena/research/gate-block-rates-20260724.md:94). 물론 단일 near-miss 평균은 selection bias가 강하므로 바로 완화하면 안 된다. 하지만 “조건별 veto의 정보가 시간/레짐에 따라 달라지는지”를 보는 연구 후보로는 가치가 있다.

### 5.4 청산은 알고별로 분리해서 다시 해석

왜 지금까지 안 했는지: MFE 포착률이라는 공통 진단이 너무 강한 신호처럼 보였고, target_exit라는 공통 메커니즘이 자연스러운 첫 시도였다.

왜 지금은 해볼 가치가 있는지: 단순 ATR target_exit는 기각됐지만, fng는 profit target이 실제 활성화되어 있고(src/arena/parameters.py:240), vix_rsi는 1m에서 4H MFE 아티팩트가 확인됐고, multi_factor는 flat/trailing/레짐 전환 문제가 섞여 있다. 이제는 “청산 공통 튜닝”이 아니라 알고별 failure mode 분해가 필요하다.

### 5.5 스테이블/현금 수익 회계를 먼저 shadow로 붙여 현실적 바닥 수익률을 측정

왜 지금까지 안 했는지: 페이퍼트레이딩 시스템의 주 관심이 BTC 방향성 알고였고, 현금 수익은 부차적 회계처럼 보였을 가능성이 높다.

왜 지금은 해볼 가치가 있는지: 하락장에서 flat이 최선인 구조라면, flat 기간의 수익률이 0인지, 현실적 stable yield인지가 제품 목표와 사용자 인식에 영향을 준다. 숏보다 리스크/제품 충돌이 작고, “롱온리 방어 시스템”의 현실 성과를 더 정확히 보여준다.

### 5.6 하락장 반등 로직을 omnibus 총성과에서 분리해 검증

왜 지금까지 안 했는지: omnibus는 UP_TREND·RANGE·DOWN_TREND를 한 라우터로 묶는 것이 목적이었고, 최근 검증도 전체 omnibus의 수익 개선 여부를 중심으로 진행됐다.

왜 지금은 해볼 가치가 있는지: 현재 `OVERSOLD_REBOUND`는 RSI, BB 위치, MACD 개선, 24시간 낙폭 중 3개를 요구하고(src/arena/algorithms.py:659), 급락은 `PANIC_DROP`으로 차단하며, 진입 크기도 0.25배로 제한한다(src/arena/algorithms.py:768). 방향은 이론적으로 일관된다. 그러나 전체 omnibus가 플러스라는 사실만으로 이 하위 경로가 플러스라고 말할 수 없다. 이 경로만 분리했을 때 비용 후 기대값이 양수인지, 손실이 급락 재개 구간에 집중되는지부터 확인해야 한다. 여기서 음수라면 숏 부재가 아니라 반등 식별력이 문제다.

## 6. 불확실/검증 불가 항목

- Supabase 원자료는 `arena_status.py`로 현재 요약을 직접 조회했지만, 사용자가 언급한 별도 SQL 명령은 프롬프트에 포함되어 있지 않았다. 따라서 paper_positions 원시 row 전체를 별도 SQL로 재집계하지는 않았다.
- EC2 live 코드와 로컬 checkout이 완전히 동일한지는 이번 요청 범위상 배포/원격 파일 diff를 수행하지 않았다. 로컬 저장소 기준으로만 코드 패리티를 평가했다.
- 1m MFE 최신 재실행은 하지 않았다. 이번 리뷰에서는 기존 문서와 코드 구조, 그리고 `arena_status.py` 현재 출력만 사용했다.
- DSR/PBO 구현의 수식 자체를 외부 논문 원문과 대조하지는 않았다. 코드 레벨에서는 일반적인 DSR/CSCV 형태를 따르지만, return series 선택과 sample-size 해석이 더 중요하다고 판단했다.
- 현재 조회 결과만으로는 omnibus 거래를 UP_TREND/RANGE/OVERSOLD_REBOUND별로 분해하지 못했다. 따라서 “하락장 반등 로직이 실제로 수익인가”는 이번 리뷰에서 검증 불가다.

## 결론

기존 기각 결론 상당수는 “그 처방을 지금 켜면 안 된다”는 의미에서는 맞다. 하지만 “그래서 더 할 것이 없다”는 결론은 틀렸다. 숏 없이 하락장 반등을 먹겠다는 방향은 현실적이며, 현재 omnibus 설계도 그 방향과 정합적이다. 다만 상승장과 같은 수익을 기대해서는 안 되고, 목표는 “모든 반등 포착”이 아니라 “급락 지속 구간을 피하면서 선택한 반등 거래의 비용 후 기대값을 양수로 유지”하는 것으로 정의해야 한다. 가장 큰 문제는 숏 부재가 아니라 반등 성과가 총성과에 묻혀 있는 측정 구조, 단순한 레짐·급락/소진 판별, 그리고 기각 결과의 과도한 일반화다. 다음 우선순위는 WI류 미세 튜닝이 아니라 `OVERSOLD_REBOUND` 경로의 독립 귀속 검증과 레짐 분류력 평가다.
