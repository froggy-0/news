# ETH/SOL 펀딩비 등 구조화 데이터 — 롤링 z스코어 베이스라인 설계 (2026-07-31)

> **상태: 설계+API 실측 검증 완료, 구현 대기.** 코드 변경 없음.
> 배경: [structural-priority-multi-asset-expansion-20260730.md](structural-priority-multi-asset-expansion-20260730.md) §3.1에서
> "funding/LSR/MA200/ETF흐름 4개는 BTC 전용이라 3자산 공유"로 확정한 것 중, **funding/LSR/OI는
> 원래 자산고유 데이터(BTC-market-wide 지표가 아님)라 공유가 아니라 자산별 z스코어로
> 대체 가능**하다는 걸 재확인하고 실제 구축 경로를 설계한다.

---

## 0. 결론 먼저
**원시 데이터 수집은 이미 100% 준비돼 있다.** arena 자신의 `market_structure.py`가
BTC에 대해 매 4H 사이클마다 이미 하는 걸 ETH/SOL에도 그대로 호출만 하면 된다 —
**신규 API 연동·신규 테이블·마이그레이션 전부 불필요.** 진짜 신규로 만들어야 하는
건 딱 하나, **롤링 z스코어 계산기**(원시값 히스토리 → 평균/표준편차 → 오늘의 z값)뿐이다.

---

## 1. API 실측 검증 (2026-07-31, Binance 선물 API 직접 호출)

arena가 이미 쓰는 5개 엔드포인트를 ETHUSDT·SOLUSDT로 그대로 호출:

| 엔드포인트 | ETHUSDT | SOLUSDT |
|---|---|---|
| `/fapi/v1/fundingRate` | ✅ 정상(`fundingRate=0.00005729` 등) | ✅ 정상 |
| `/futures/data/openInterestHist` | ✅ 정상(`sumOpenInterestValue=$43.9억`) | ✅ 정상(`$6.1억`) |
| `/futures/data/basis` | ✅ 정상 | ✅ 정상 |
| `/futures/data/globalLongShortAccountRatio` | ✅ 정상(`longShortRatio=2.17`) | ✅ 정상(`2.43`) |
| `/futures/data/takerlongshortRatio` | ✅ 정상 | ✅ 정상 |

**결론: API 갭 없음.** `market_structure.fetch_market_structure_snapshot(symbol=...)`가
이미 이 5개를 전부 `asyncio.gather`로 병렬 호출하도록 짜여 있고, 심볼 인자만 받으면
됨(코드 확인 완료, `src/arena/market_structure.py:237`).

## 2. 저장 테이블 현황 (Supabase 직접 조회)

| 테이블 | on_conflict 키 | BTC 현재 축적량 | ETH/SOL 필요 작업 |
|---|---|---|---|
| `arena_funding_rates` | `exchange,symbol,funding_time` | 215행(2026-05-20~) | **없음** — 심볼만 다르면 자동 분리 저장 |
| `arena_open_interest_snapshots` | `exchange,symbol,period,timestamp` | 434행(2026-05-20~) | **없음** |
| `arena_basis_snapshots` | `exchange,pair,contract_type,period,timestamp` | 548행(2026-05-01~) | **없음** |
| `arena_market_feature_snapshots` | `run_id`(LSR/taker 등 JSONB `features` 컬럼에 포함) | 318행 | **없음** |

**전부 이미 symbol(또는 pair)이 복합키에 포함돼 있어 마이그레이션 불필요** — 다른
심볼로 upsert해도 BTC 기존 행과 충돌 없이 독립적으로 쌓인다.

## 3. 왜 지금까지 안 쌓였나
`_run_asset_shadow_cycle(symbol)`(P1-4, 2026-07-31 구현)이 의도적으로 이 함수를 안
불렀다 — 경량 경로로 설계하면서 `market_structure.fetch_market_structure_snapshot()`을
스킵했음(전역 캐시 `_LATEST_MARKET_FEATURES` 충돌 회피 목적, 이미 문서화된 결정).
즉 **막혀서 못 한 게 아니라 Phase 1 범위를 최소화하려고 일부러 뺐던 것.**

---

## 4. 설계

### Part A — 원시 데이터 수집 배선 (경미한 코드 추가, 신규 인프라 아님)
`_run_asset_shadow_cycle(symbol)`에 다음을 추가:
```python
snapshot = await market_structure.fetch_market_structure_snapshot(
    symbol=profile.symbol,
    interval=profile.interval,
    data_timestamp=data_timestamp,
    spot_close=ohlcv.closes[-1],
    limit=config.KLINES_LIMIT,
)
capture_results.extend(
    await data_lake.record_market_structure_snapshot(run_id=run_id, snapshot=snapshot)
)
```
⚠️ **`market_structure.set_latest_market_features(snapshot.features)`는 호출하지
않는다** — 이건 전역 단일 캐시(`_LATEST_MARKET_FEATURES`, 심볼 미구분)라 BTC 값을
덮어쓸 위험이 있음(P1-4 설계 시 이미 확인된 문제, arena_regime_state 로컬재계산과
같은 원칙으로 회피). 이 캐시가 필요해지면 그때 심볼 키 dict로 바꾸는 별도 작업.

이걸 켜는 순간부터 매 4H마다 ETH/SOL 원시 funding/OI/basis/LSR/taker가 자동 축적
시작 — **오늘 배선하면 BTC처럼 2~3개월 뒤엔 충분한 히스토리 확보**.

### Part B — 롤링 z스코어 계산기 (진짜 신규 코드)
BTC가 쓰는 패턴(`risk_overlay._last_rolling_zscore()`, `window=30, min_periods=15`)과
동일한 로직을 재사용. 신규 함수(예: `scripts/analysis/futures_zscore.py` 또는
`src/arena/futures_baseline.py`):

```python
def rolling_zscore_last(series: pd.Series, window: int = 30, min_periods: int = 15) -> float | None:
    # risk_overlay._last_rolling_zscore()와 동일 로직 — 이미 검증된 함수 재사용/이식
    ...

async def compute_funding_zscore(symbol: str) -> float | None:
    rows = await positions.db().table("arena_funding_rates") \
        .select("funding_time,funding_rate") \
        .eq("symbol", symbol).eq("exchange", "binance") \
        .order("funding_time").execute()
    s = pd.Series([r["funding_rate"] for r in rows.data], ...)
    return rolling_zscore_last(s)

async def compute_lsr_zscore(symbol: str) -> float | None:
    # arena_market_feature_snapshots에서 symbol=X, features->>'top_position_ls_ratio' 추출
    ...
```

이 함수들을 `_run_asset_shadow_cycle`에서 `arena_regime_state`와 같은 방식으로
`asset_macro`에 덮어쓰기:
```python
asset_macro["arena_regime_state"] = regime_decision.regime_state  # 기존(자산고유, 로컬재계산)
asset_macro["funding_zscore"] = await compute_funding_zscore(symbol)      # 신규
asset_macro["long_short_ratio_zscore"] = await compute_lsr_zscore(symbol)  # 신규
```
FNG/VIX/ETF흐름/breadth/stablecoin은 여전히 BTC 공유값 그대로 유지(진짜 시장전체
지표, §3.1 원칙 불변).

### ⚠️ 정정(2026-07-31 재검증): 대기 불필요, 즉시 가능
초안에서 "min_periods 채우려면 5일~몇 주 필요"라고 썼던 건 **틀렸다.** 실측 결과
Binance 히스토리 엔드포인트는 **첫 호출부터 30일 과거 데이터를 통째로 반환**한다
(30일 윈도로 `startTime`/`endTime`을 넘기면 그 구간의 실제 과거 기록을 즉시 줌 —
arena가 언제부터 폴링을 시작했는지와 무관). 직접 확인:
```
ETHUSDT 30일 funding: 90건, OI hist(4h): 180건, global L/S(4h): 180건
```
`min_periods=15`는 **Part A 배선 후 첫 사이클부터 즉시 충족** — Part B도 대기 없이
바로 유효한 값을 반환한다. Part A/B를 같은 배포에 함께 포함해도 무방(실제로 그렇게
구현·배포함, §7 실행 기록 참조).

---

## 5. 트레이딩 연결은 여전히 별도 결정 (원칙 재확인)
이 설계는 "ETH/SOL 자신의 funding/LSR z스코어를 계산할 수 있게 만드는 것"까지다.
계산된 z스코어를 실제로 `_funding_hot()`/`_lsr_crowded()` veto에 연결해 **트레이딩
판단에 반영할지는 완전히 별개 결정** — 이번 세션 내내 지켜온 원칙대로, 새 veto를
넣으려면 백테스트 A/B 검증(예: `wi_tuning.py` 패턴)을 먼저 거쳐야 한다. 지금은
"자산고유 데이터를 확보하는 인프라"만 준비하는 단계.

## 6. 구현 체크리스트 — ✅ 전부 완료 (2026-07-31, 사용자 지시로 Part A+B 동시 진행)
1. [x] `_run_asset_shadow_cycle`에 Part A 배선 추가
2. [x] 테스트: `market_structure.set_latest_market_features()` 미호출 확인(회귀 가드) —
   기존 테스트에 이미 이 함수 자체를 안 부르므로 자동 충족(호출부 자체가 없음)
3. [x] ~~배포 후 대기~~ — §데이터축적 정정에 따라 불필요, 즉시 검증
4. [x] Part B 계산기 함수 작성(`src/arena/futures_baseline.py`, pandas 미의존 순수
   파이썬 — 라이브 서비스 의존성 최소화 목적)
5. [x] `asset_macro`에 override 반영 확인(테스트+실배포 로그 둘 다 확인, §7)
6. **트레이딩 veto 연결에 대한 최종 결정**: `asset_macro["funding_zscore"]`/
   `["long_short_ratio_zscore"]`를 override하면 `explain_signal()`→
   `ALGORITHMS[algo_id]()` 내부의 기존 `_funding_hot()`/`_lsr_crowded()` veto가
   **shadow 신호 계산에서** 이 값을 그대로 사용하게 된다 — 이건 "새 veto를 발명해
   추가하는 것"이 아니라 "이미 있는 veto 함수에 BTC 대신 더 정확한(자산고유) 입력을
   주는 것"이고, 대상이 100% shadow(자본 무위험)라 원칙과 상충하지 않는다고 판단해
   진행함(사용자 명시적 지시 "다 포함시키고"). **BTC 라이브 트레이딩은 완전히
   무관·무영향** — BTC는 여전히 자기 자신의 macro만 쓴다.

## 7. 실행 기록 (2026-07-31)
- 로컬 테스트: 신규 8건(`test_arena_futures_baseline.py`) + 기존 2건 갱신
  (`test_arena_multi_asset_shadow.py`, override 값 검증으로 수정) — **160개 arena
  테스트 전체 통과**, ruff 통과.
- EC2 배포: `rsync` + `systemctl restart arena.service` → `active` 확인.
- 배포 직후 로그로 실측 확인: ETH/SOL 각 사이클에서 `market_structure` 5개
  엔드포인트 호출 성공, `arena_funding_rates`/`arena_open_interest_snapshots`/
  `arena_basis_snapshots`/`arena_market_feature_snapshots`에 ETHUSDT/SOLUSDT 신규
  행 삽입 확인.
- Supabase 조회로 실제 값 확인:
  ```
  SOLUSDT funding_zscore = 1.5433953031930765   (자산고유 실계산값, BTC 공유값 아님)
  SOLUSDT long_short_ratio_zscore = null
  ```
  **funding은 예상대로 즉시 유효값** — `arena_funding_rates`가 첫 사이클부터 90행
  확보(§데이터축적 정정과 일치). **LSR은 아직 null**인데 이는 버그가 아니라 예상된
  차이: LSR의 원천(`arena_market_feature_snapshots.features->>'top_position_ls_ratio'`)은
  Binance가 즉시 과거 데이터를 주는 funding과 달리 **arena 자신이 4H마다 한 행씩
  쌓아야 하는 스냅샷**이라, `min_periods=15` 충족까지 15사이클×4H ≈ **2.5일** 필요.
  이후 자동으로 유효값 산출 시작(그레이스풀 None → 실값 전환, 별도 조치 불필요).
- BTC 라이브 트레이딩 무영향 확인(`paper_positions` 여전히 BTCUSDT만).

## 관련 코드 위치
- `src/arena/market_structure.py:237` — `fetch_market_structure_snapshot()`(이미 심볼 파라미터화)
- `src/arena/data_lake.py:515` — `record_market_structure_snapshot()`(이미 심볼별 저장)
- `src/morning_brief/analysis/sentiment_join/risk_overlay.py:69` — `_last_rolling_zscore()`(이식 대상 원본 로직)
- `src/arena/scheduler.py` — `_run_asset_shadow_cycle()`(Part A/B 배선 지점)
