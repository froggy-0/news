# Meridian — 리서치 종합 롱/숏 알고 설계 (2026-08-15, 설계안·미구현)

**상태**: 설계만, 코드 변경 없음. 사용자 제안("롱도 정확히 말하면 엣지없다 — 지금까지
테스트한 것들 모두 조합하고 관련 논문들 총집합해서, 롱/숏 판단이 가능한 로직만 구현해
실제 페이퍼트레이딩하며 개선해보자")에 대한 구체 설계.

## 0. 배경 — 왜 이 방향이 합리적인가

`docs/arena/product/vision.md`의 2026-08-06 전략 전환("엣지 정밀화 → 정직한 표본
확보")이 이미 롱 쪽에서 검증한 원칙을 이번엔 롱+숏 통합 신규 알고에 처음부터
적용하는 것. 이 프로젝트가 반복 확인한 사실:

- **DSR≥0.95 사전검증 기준을 통과한 알고는 지금까지 하나도 없다.** 롱도 예외가
  아니다 — P4 과최적화 감사(2026-08-04)가 사양탐색 횟수를 정확히 반영한 뒤,
  `fng_contrarian`(DSR 0.099)·`vix_rsi`(DSR 0.134) 둘 다 "검증된 성공 기준선"에서
  강등됐다. 20개월 재확인(2026-07-25)도 역발산 2개만 PF>1이고 추세·모멘텀 4개는
  전부 PF<1 — 이 창 자체가 순하락장이라 "설계결함 vs 상승장 미도래" 미분리.
  숏(Phase B, 2026-08-15)도 6개 알고 거울반전 전부 기각, 문헌기반 재해석·모멘텀
  고유변동성 사이징까지 추가 시도했으나 전부 실패
  ([spot-to-perp-phase-b-short-entry-design-20260815.md](spot-to-perp-phase-b-short-entry-design-20260815.md) §8~§17).
- 반대로 **"증명보다 표본"** 원칙을 적용한 시도는 실제로 개선을 만들었다:
  v33/v34(2026-08-06~07, 진입조건 unanimous AND → N-of-M 투표 완화)는 그리드
  검증 없이 설계값으로 배포했고 회귀 없이 거래량이 늘었다. TSMOM_NL(v35,
  2026-08-08)도 "증명된 엣지"가 아니라 "확실히 죽은 레거시보다 확실한 우위"
  근거로 활성화됐다 — 이 프로젝트에서 이미 통용되는 채택 기준의 선례다.
- **로드맵 KPI 자체가 승률이 아니라 포지션 1,000건 누적**(vision.md Phase 1).
  지금 필요한 건 사전 통계적 확신이 아니라 정직하게 라벨링된 표본이다.

이 문서는 이 원칙을 신규 알고 하나에 처음부터 적용한다 — "검증된 엣지"라고
주장하지 않고, "지금까지의 모든 리서치를 반영한 최선의 추정"이라고 명시적으로
라벨링한 채 페이퍼트레이딩으로 개선한다.

## 1. 리서치 종합 — 무엇을 로직에 반영하는가

### 1-1. 롱 — 살아남은 두 계열만 채택

이 프로젝트가 실제로 시도한 롱 신호는 크게 두 계열로 수렴한다. 둘 다 "증명된
엣지"는 아니지만, 상대적으로 반증되지 않은/개선을 만든 계열이다.

| 계열 | 근거 | 대표 조건 |
| --- | --- | --- |
| **추세추종(연속 사이징)** | TSMOM_NL(Moskowitz·Sabbatucci·Tamoni·Uhl 2025) — walk-forward 6/6 구간 레거시 대비 전부 개선(절대엣지는 미증명, DSR 0.110). [설계](nonlinear-tsmom-design-20260808.md) | `s = T봉누적수익률/(√T·σ̂)`, 진입 `s > 0`, 사이징 `f(s)=s/(s²+1)` |
| **역발산(평균회귀)** | 20개월 재확인에서 유일하게 PF>1(`fng_contrarian` 1.37·`vix_rsi` 1.44) — DSR은 미달이지만 다른 4개(추세·모멘텀)보다는 일관되게 덜 나쁨. [2026-07-25 종합](priority-analysis-20260725.md) | FNG<30 또는 (VIX<q40 ∧ RSI<50), risk-off 제외 |

**채택하지 않는 것**: 규칙기반 다중필터 AND(구 macd_momentum 레거시, DSR 0.012로
완전기각) — 되풀이하지 않는다. `multi_factor`류 5팩터 투표도 채택하지 않는다
(2026-07-30 재검증에서 횡보 허용이 근본 문제로 확인돼 강한 배제 규칙이 필요했고,
이는 "종합"보다 "알고 고유 특화"에 가까워 이 신규 알고의 취지와 안 맞음).

### 1-2. 숏 — 추세미러 배제, 역발산-fade만 채택

Phase B 1·2순환의 핵심 결론을 그대로 반영한다.

- **추세추종 숏(하락 미러)은 명시적으로 배제한다.** 근거가 세 겹이다:
  1. Phase B 1순환 — `regime_trend`·`macd_momentum`·`omnibus` 숏 미러 전부 명확히
     기각(DSR<0.6, CI 전부 0 포함).
  2. Daniel & Moskowitz(2016, *JFE*) "Momentum Crashes" — 과거 루저를 숏할 때
     급반등 시 베타가 옵션처럼 치솟아 최악의 타이밍에 손실이 집중.
  3. Man Group/AIMA 독립 실증 — 트렌드추종 숏은 자산군 무관하게 구조적으로
     손실(-2.0%) vs 롱 이익(+0.9%).
  4. 이 프로젝트 자체 진단(§3-2, 2026-08-15) — 모멘텀 고유 변동성 사이징을
     추가해도 DSR이 원리적으로 개선 안 됨(사이징은 진입 시점 자체를 못 바꿈).
- **역발산-fade(탐욕 매도)만 약하게 채택한다.** `vix_rsi`(ETH) veto유지가 6개
  알고 중 유일하게 채택선 근접(DSR 0.934, CI 하한 -0.37%) — Chen, Hong & Stein
  (2001, *JFE*) "Forecasting Crashes"(직전 수익률 양(+)일수록 음의 왜도가 커짐,
  "정점은 천천히 붕괴는 빠르게")와 방향이 일치. FNG>70(극단적 탐욕) 또는 RSI
  과열을 fade하는 신호만 숏 후보로 쓴다 — 신저가 돌파·역배열 같은 추세 조건은
  숏에서 완전히 배제.
- **GJR-GARCH 진단(§3-1, 2026-08-15)의 함의**: 이 표본에서 레버리지 효과(방향
  무관)가 통계적으로 유의하지 않았다 — "크립토라 변동성 비대칭이 특별히 있다"는
  전제로 게이트를 설계하지 않는다(예: 숏 진입 시 변동성 필터를 추가로 얹지
  않음, 이미 반증된 축).

### 1-3. 공통 인프라 — 반증된 것 재발명하지 않기

| 항목 | 채택 여부 | 근거 |
| --- | --- | --- |
| 레짐 게이트(risk-off 항상 배제) | ✅ 채택 | 6개 알고 전부에서 hard veto로 일관 유지, 예외 없이 안전장치 |
| 추세 leg는 bull_trend만, 역발산 leg는 레짐 무관 | ✅ 채택 | multi_factor 2026-07-30 재검증(횡보 허용이 손실 6/7건 집중) — 추세성 신호는 방향성 레짐 확인 필요, 역발산은 정의상 하락장에서 발화해야 함 |
| 진입 조건 N-of-M 완화(unanimous AND 지양) | ✅ 채택(단, 이 알고는 애초에 조건 수가 적어 대상 아님) | v33/v34 — 과잉 AND가 표본 자체를 죽인다는 반복 확인 |
| 청산: flat_signal + ATR손절 + 래칫 트레일링 | ✅ 채택(추세 leg) | 표준 인프라, 별도 개선 시도 안 함(아래) |
| 청산: 가격손절 제외 + 시간손절(72h) | ✅ 채택(역발산 leg) | fng_contrarian v22 — 평균회귀는 가격손절이 독, 검증됨 |
| 진입/청산 조건 분리(1회성 이벤트 재검사 방지) | ❌ 신규 시도 안 함 | 2026-08-04 root-cause 처방(P1) — regime_trend/macd_momentum 3변형 전부 기각, "청산 타이밍 재설계"가 반증됨 |
| 트레일링 거리만 독립 축소 | ❌ 신규 시도 안 함 | 2026-08-10 — mult 좁힐수록 단조 악화(휩소), 기각 |
| 청산 시 profit-target(ATR 배수 익절) | ⚠️ 조건부 — omnibus WI-7류만 참고, 신규 그리드 안 함 | Tier2(2026-07-15) PBO 0.877~0.921로 전멸, 단 fng v22/P-A는 정반대로 성공 — **알고 고유 사양이라 이 신규 알고에선 그리드 재탐색하지 않고 v22 방식(시간손절)만 재사용** |
| 청산 사유 분해 후 재조정 | ❌ 신규 시도 안 함 | vix_rsi 진단(2026-08-11) — n=8 표본 부족으로 못 함, 표본 쌓일 때까지 대기가 원칙 |
| 사이즈: vol-target/risk-target 최소값 | ✅ 채택 | `execution_rules.combined_position_weight()`, 전 알고 공용, portfolio-risk-v2 |

**요약 원칙**: 이미 실패로 판명된 축(청산 재설계, 추세미러 숏, 모멘텀사이징
숏)은 절대 재시도하지 않는다. 이미 "확실한 개선"으로 판명된 축(TSMOM_NL 연속
사이징, N-of-M 완화, v22 역발산 청산)만 재사용한다. **이 알고 자체는 새 리서치가
아니라 기존 리서치의 배선(wiring)이다.**

## 2. 신호 로직 설계

### 2-1. 알고 이름

작업명 **`meridian`**("자오선" — 방향을 가르는 기준선, 롱/숏 양방향 판단이라는
성격과 맞고 기존 코드네임 컨벤션(Wellspring/Undertow/Chorus/Vanguard)과 일관).
확정 전 사용자 확인 필요.

### 2-2. 롱 신호 (`meridian_long`)

```python
def meridian_long(macro: dict, ind: dict) -> str | None:
    state = _regime_state(macro)
    if _is_risk_off(state):
        return None

    # 추세 leg — bull_trend에서만, TSMOM_NL 그대로 재사용(algorithms.py:556-575)
    if state == regime.REGIME_BULL_TREND:
        s = _tsmom_nl_signal(ind)
        if s is not None and s > parameters.TSMOM_NL_MIN_SIGNAL:
            return "long"

    # 역발산 leg — 레짐 무관(risk-off만 배제), fng_contrarian 핵심조건 재사용
    # (algorithms.py:409-459 — macro["fng"], parameters.FNG_LONG_BELOW=30.0)
    fng = macro.get("fng")
    if fng is not None and fng < parameters.FNG_LONG_BELOW:
        return "long"

    # 역발산 leg 2 — vix_rsi 핵심조건 재사용(algorithms.py:473-... —
    # vix_now < vix_q40*VIX_CALM_TOLERANCE_BAND, rsi < VIX_RSI_LONG_MAX=50.0)
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    if vix_now is not None:
        calm = (
            vix_now < vix_q40 * parameters.VIX_CALM_TOLERANCE_BAND
            if vix_q40
            else vix_now < 20.0
        )
        if calm and ind.get("rsi", 50.0) < parameters.VIX_RSI_LONG_MAX:
            return "long"

    return None
```

사이징은 leg별로 다르다 — 추세 leg는 `f(s)` 절댓값(TSMOM_NL 패턴), 역발산 leg는
`combined_position_weight()`(기존 6알고 공용 vol/risk 타깃). 두 leg가 동시에
발화하면(드묾, bull_trend에서 동시에 FNG<30은 논리상 거의 안 겹침) 추세 leg
우선(연속신호가 더 정보량이 많음).

### 2-3. 숏 신호 (`meridian_short`, perp 전용)

```python
def meridian_short(macro: dict, ind: dict) -> str | None:
    state = _regime_state(macro)
    if _is_risk_off(state):
        return None
    # 추세미러 숏 없음 — Phase B 근거로 의도적 배제(§1-2)

    # 역발산-fade leg만: 극단적 탐욕(FNG, macro["fng"]) 또는 RSI 과열
    fng = macro.get("fng")
    if fng is not None and fng > parameters.MERIDIAN_SHORT_FNG_ABOVE:  # 신규 상수, 제안 70.0
        return "short"
    if ind.get("rsi", 50.0) > parameters.MERIDIAN_SHORT_RSI_ABOVE and not _is_bullish(state):
        # 신규 상수, 제안 70.0 — 강세추세 중엔 fade 안 함(추세지속 vs 국소천장 구분)
        return "short"
    return None
```

`_is_bullish` 배제(RSI 과열이라도 강세 추세 중이면 숏 안 함) — 문헌(모멘텀
지속성)과 일치, "추세 중 일시 과열"과 "국소 천장"을 구분하려는 최소한의 안전장치.

**숏 사이징 감쇠**: `MERIDIAN_SHORT_SIZE_DAMPENER = 0.5`(신규 상수) — 숏 leg는
문헌·자체검증 둘 다 롱보다 근거가 약하므로, 최종 사이징에 곱하는 명시적 리스크
관리 장치. 이 자체가 백테스트로 최적화된 값이 아니라 "증거 비대칭을 자본배분에
반영한다"는 설계 판단임을 문서에 남긴다(추후 라이브 데이터로 재조정 가능).

### 2-4. 사이징·손절·청산

- 추세 leg 롱: `atr_multiple` 표준 손절 + 래칫 트레일링스탑(전 알고 공용).
- 역발산 leg 롱: `PRICE_STOP_DISABLED_ALGOS`에 `"meridian"` 추가(가격손절 제외),
  `TIME_STOP_HOURS_BY_ALGO["meridian"] = 72.0`(v22 그대로).
- 숏(perp 전용): 초기엔 표준 ATR 손절 + 래칫 트레일링(역발산 숏은 아직 v22류
  전용 처리를 검증한 적 없음 — 섣불리 새 메커니즘을 얹지 않고 6개 알고 공용
  기본값으로 시작, 라이브 데이터가 쌓이면 재검토).
- `MIN_HOLD_HOURS["meridian"] = 12.0`(regime_trend·multi_factor와 동일 기본값,
  추세/역발산 혼합이라 중간값).

## 3. 인프라·격리 설계

### 3-1. 트랙 범위 — perp 전용 (신규 스코핑 메커니즘 필요)

현재 `scheduler._run_cycle()`은 `for algo_id, fn in ALGORITHMS.items()`로
**등록된 모든 알고를 그 사이클이 도는 모든 트랙(spot+perp, BTC/ETH/SOL)에서
실행**한다(`scheduler.py:844`). `meridian`을 그대로 `ALGORITHMS`에 넣으면 spot
3트랙 + perp 3트랙 = 6슬롯×$1000 자본이 자동 생성되는데, 이 알고의 존재
이유(롱/숏 판단)가 spot에서는 절반만(롱뿐) 발현돼 중복·비효율이다.

**제안**: 신규 `parameters.ALGORITHM_TRACK_SCOPE: dict[str, frozenset[str]]`
(기본: 미등록 알고는 전체 트랙, 즉 기존 6알고는 무변화) — `"meridian"`만
`frozenset({"BTCUSDT-PERP", "ETHUSDT-PERP", "SOLUSDT-PERP"})`로 제한.
`scheduler._run_cycle()`의 알고 루프에 스코프 필터 한 줄 추가(트랙 심볼이
스코프에 없으면 skip). 기존 6알고·기존 트랙 동작에는 영향 없음(빈 스코프
자체가 "제한 없음"을 뜻하도록 설계).

### 3-2. 자본·트랙레코드 격리

- 신규 `algo_id="meridian"` — 기존 6개 알고 코드·자본·트랙레코드 무변경.
- perp 3트랙 × $1000 = $3,000 신규 독립자본(portfolio-risk-v2 원칙 그대로,
  자산×알고 독립).
- `MAX_OPEN_POSITIONS_TOTAL`/`MAX_LONG_POSITIONS`/`MAX_SHORT_POSITIONS`/
  `MAX_NET_LONG_EXPOSURE`/`MAX_NET_SHORT_EXPOSURE`: 현재 6(알고 수와 동일하게
  설정하는 관행, portfolio-risk-v2) → **7로 상향**(CLAUDE.md "알고 추가 시 캡도
  함께 올릴 것" 원칙).
- 대시보드(`arena/index.html`): 기존 6알고 그리드에 `meridian`을 perp 트랙에만
  추가 렌더(spot 탭에는 안 나타남 — ETH/SOL이 처음엔 shadow였던 것과 달리
  처음부터 "실거래, perp 전용, 실험적 종합 알고"로 명시 라벨링 — vision.md
  정직한 트랙레코드 원칙).

### 3-3. 숏 승격

`PERP_SHORT_ALGORITHMS["meridian"] = meridian_short` 등록 +
`PERP_SHORT_ENABLED_TRACKS`에 `("BTCUSDT-PERP", "meridian")`,
`("ETHUSDT-PERP", "meridian")`, `("SOLUSDT-PERP", "meridian")` 3개 추가.

D017("자산×알고리즘 단위로 제한")과 **모순되지 않는다** — D017은 "검증 없이
숏을 열지 않는다"는 원칙이었는데, 이 알고 자체가 그 검증(문헌·자체백테스트
종합)을 거친 설계이고, 사용자가 이번에 "사전 DSR 게이트 대신 라이브 표본으로
검증하자"고 명시적으로 방향을 바꿨다. 즉 D017의 "임의로 열지 않는다"는 지켜지되
"게이트 기준"이 DSR≥0.95 사전클리어에서 "설계 근거 + 라이브 관찰"로 바뀐 것 —
이 전환 자체를 D017에 이어 D019로 기록할 것을 제안(§6).

## 4. 롤아웃 절차 (제안)

1. **사용자 확인**: 이 설계(이름·leg 구성·사이징 감쇠값·트랙 스코프)에 대한
   승인 또는 수정 요청.
2. **구현**: `algorithms.py`에 `meridian_long`/`meridian_short` 추가,
   `short_signals.py` 등록, `parameters.py` 상수·트랙 스코프·숏 allowlist 추가,
   `scheduler.py` 트랙 스코프 필터 배선, `parameters.py` 자본 캡 6→7.
3. **Sanity 백테스트(그리드/DSR 게이트 아님)** — 크래시 없음·거래 빈도·기존
   6알고 회귀 없음만 확인(macro 백필, `backtest_with_macro_backfill.py` 재사용
   패턴). §0 원칙대로 "통과선"을 만들지 않는다 — 명백히 깨진 로직(무한루프,
   0거래, 부호 반전)만 걸러낸다.
4. **PARAMS_VERSION bump**(신규 신호 로직이므로 v35→v36).
5. **로컬 테스트**: 신규 유닛테스트(`test_arena_perp_policy.py` 패턴 — 롱/숏
   오픈·반전·청산 케이스), 기존 `tests/test_arena_*.py` 전체 회귀.
6. **EC2 배포·재시작 확인** — 1~2 사이클 관찰(포지션 실제 오픈, 방향 라벨,
   펀딩 부호).
7. **관찰 사이클**: `/arena-status`로 정기 확인하되, 이 알고는 **DSR/CI 채택
   기준 통과를 목표로 하지 않는다** — 표본이 쌓이면(예: 50건 단위) 신호 자체를
   재조정할지, leg 비중을 바꿀지 등을 그때 논의한다. "언제 접을지" 기준(예: 최대
   드로다운 kill-switch, `ALGO_MAX_DRAWDOWN_KILL_PCT` 기존 인프라 재사용)은
   §6에서 사용자와 사전 합의.

## 5. 아직 결정 안 된 것 (사용자 확인 필요)

- 이름 확정(`meridian` 또는 다른 후보).
- `MERIDIAN_SHORT_SIZE_DAMPENER` 값(제안 0.5 — 임의값, 다른 값 선호 시 반영).
- `MERIDIAN_SHORT_FNG_ABOVE`/`MERIDIAN_SHORT_RSI_ABOVE` 구체 수치(제안:
  FNG>70·RSI>70 — 롱 임계값(`FNG_LONG_BELOW`=30, `VIX_RSI_LONG_MAX`=50)과
  대칭은 아니고 "명백한 극단"만 잡도록 보수적으로 70/70 제안, 그리드 아닌
  단일 사전값). 숏 RSI 과열 임계는 macd_momentum의 롱 RSI 상한(75)과 별개
  축이라 혼동 주의.
- 3자산(BTC/ETH/SOL) 전부로 시작할지, 1개(예: BTC)로 먼저 시작해 관찰 후
  확장할지.
- 자본 규모($1,000/트랙 기존 관행 유지 여부).
- kill-switch 기준(드로다운 몇 %에서 자동 정지·재검토 트리거로 볼지).
- profit-target(ATR 배수 익절)을 롱 추세 leg에도 처음부터 넣을지, 아니면
  기본 트레일링만으로 시작해 나중에 추가할지(§1-3 표에서는 "그리드 재탐색
  안 함" 원칙상 기본 미포함으로 제안했지만, 이건 선택 문제).

## 6. 문서화 계획

승인 후 구현 완료 시:
- `decision-log.md`에 **D019**로 신설(신규 알고 도입 원칙 — "사전 DSR 게이트
  대신 리서치 종합 설계 + 라이브 표본 검증"이라는 새로운 채택 경로를 D017과
  나란히 기록, D017을 대체하지 않음 — D017은 여전히 "기존 6알고 거울반전 숏"에
  적용되는 결론).
- `next-session-handoff.md`에 meridian 트랙 상태 추가.
- `CLAUDE.md`의 "Paper Trading Arena" 섹션에 7번째 알고로 등재.

## 7. 구현 완료 (2026-08-15, 같은 세션 후속)

§5의 열린 질문은 사용자 승인("네 구현진행") 후 전부 §5의 제안값 그대로
확정해 구현했다 — 재검증 그리드 없이 설계값 그대로 배포(v33/v34/v35와 동일
관행).

- 이름: `meridian` 확정.
- `MERIDIAN_SHORT_SIZE_DAMPENER = 0.5`, `MERIDIAN_SHORT_FNG_ABOVE = 70.0`,
  `MERIDIAN_SHORT_RSI_ABOVE = 70.0` — 제안값 그대로(`src/arena/parameters.py`).
- 3자산(BTC/ETH/SOL) perp 트랙 전부 처음부터 등록(단계적 확장 아님).
- 자본 $1,000/트랙(기존 관행 유지).
- kill-switch: 기존 `ALGO_MAX_DRAWDOWN_KILL_PCT` 인프라 그대로 재사용(신규
  meridian 전용 임계값 추가 안 함).
- profit-target(ATR 배수 익절): **포함 안 함** — §1-3 표의 기본 방향대로 표준
  ATR손절+래칫트레일링만 사용, `TARGET_EXIT_ATR_MULT_BY_ALGO`에 meridian 미등록.
- 트랙 스코프: `parameters.ALGORITHM_TRACK_SCOPE`(신규) + `scheduler._run_cycle()`
  필터 한 줄로 구현 — 미등록 알고(기존 6개)는 무제한(기존 동작 완전 보존),
  `meridian`만 perp 3트랙으로 제한.
- 사이징 배선: `_meridian_active_leg()`(내부)/`meridian_active_leg()`(공개
  래퍼, `omnibus_regime_for`와 동일 관행)를 `backtest.py`·`scheduler.py` 양쪽에서
  재사용 — 추세leg 진입 시에만 `algo_id=="macd_momentum"`과 동일한 자리에
  `algo_id=="meridian"` 분기 추가해 TSMOM f(s) 곱셈, 역발산leg는 무보정, 숏은
  0.5배 감쇠.
- `PERP_SHORT_ENABLED_TRACKS`에 `("BTCUSDT-PERP","meridian")`/
  `("ETHUSDT-PERP","meridian")`/`("SOLUSDT-PERP","meridian")` 3개 즉시 등록(D019
  경로이므로 D017의 "자산별 개별 검증 후 단계적 등록" 절차 미적용 — 설계
  자체가 검증 절차라는 게 D019의 핵심).
- `MAX_OPEN_POSITIONS_TOTAL`/`MAX_LONG_POSITIONS`/`MAX_SHORT_POSITIONS`/
  `MAX_NET_LONG_EXPOSURE`/`MAX_NET_SHORT_EXPOSURE` 6→7.
- `PARAMS_VERSION` v35→v36.
- 신규 테스트 22건(`tests/test_arena_meridian.py`) — active leg 판정(추세/역발산/
  risk-off/오버레이라벨 제외), 롱/숏 신호 함수, explain_signal 진단, 트랙 스코프,
  backtest 사이징 배선(추세leg TSMOM 곱셈·역발산leg 무보정·숏 감쇠) 회귀 보호.
  기존 하드코딩값(캡 6, PARAMS_VERSION v35) 참조 테스트 2건 갱신. arena 전체
  284개 통과.
- Sanity 백테스트(`backtest_with_macro_backfill.py`, BTC, 튜닝 아닌 회귀확인용,
  `run_replay` 기본 `strategy_fns=algorithms.ALGORITHMS`가 자동으로 meridian
  포함) — 크래시 없음, 37거래, win% 37.8·sum_w_ret% -0.75(다른 6알고와 같은
  구간에서 비슷한 규모, 특이치 아님).

**의도적으로 구현 안 함(스코프 밖, 후속 필요)**: `arena/index.html` 대시보드
표시. `computeGrandTotal()`이 `ALGO_IDS`를 모든 자산×시장에 균일 적용하는
구조라, `meridian`을 `ALGOS`/`ALGO_IDS`에 그대로 추가하면 존재하지 않는 spot
슬롯 3개(빈 $1,000×0%)가 총수익률에 섞여 2026-08-15 오전 세션에서 고친 것과
같은 "빈 슬롯 희석" 버그가 재발한다(Phase A2 문서 참고). 알고별 트랙 스코프를
프론트엔드도 인식하게 고치는 작업은 브라우저 실측 검증이 필요해 별도 세션으로
분리 — 백엔드는 정상 거래·기록 중이라 데이터 유실은 없다(표시만 안 될 뿐).
재현: `next-session-handoff.md` §10-3.
