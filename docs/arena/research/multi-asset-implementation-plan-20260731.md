# 멀티자산 확장 구현 계획 (BTC·ETH·SOL) — 2026-07-31

> **상태: 계획 문서. 구현 착수 전. 코드 변경 없음.**
> 설계 근거: [structural-priority-multi-asset-expansion-20260730.md](structural-priority-multi-asset-expansion-20260730.md)
> (문제진단·자산선정·Track A/B 분리·판정기준). 이 문서는 그 설계를 **현 코드베이스에
> 어떻게 구현할지**를 파일·함수 단위로 상세화한 실행계획이다.

---

## 0. 목표 정의

### 0.1 최종 목표
BTC 단일자산으로는 검증 불가능했던 **cross-asset robustness**(전략이 BTC 특화인지, 인접
대형 L1 자산군에도 전이되는지)를 판정할 수 있는 상태로 아레나를 확장한다.

### 0.2 성공 기준 (이 계획이 완료됐다고 말할 수 있는 조건)
1. BTC·ETH·SOL 3자산에 대해 **동일 코드·동일 파라미터**로 4H 사이클이 shadow 모드로
   돌아가고, 자산별 의사결정·성과가 독립적으로 기록된다.
2. 20개월 백필 백테스트를 3자산 각각에 대해 실행해 Track A/B 분리 성과표를 산출할 수
   있다.
3. 대시보드에서 자산 탭으로 3자산 성과를 확인할 수 있다.
4. **기존 BTC 라이브 트랙레코드는 단 한 건도 오염되지 않는다**(회귀 없음).

### 0.3 비목표 (이번 범위에서 명시적으로 제외)
- ETH/SOL 실거래(live) 전환 — Phase 1은 shadow-only.
- 자산별 파라미터 튜닝 — 설계문서 §4 원칙 2에 의해 **금지**.
- ETH/SOL 전용 뉴스·감성·ETF·breadth 등 자산별 등가 피처 신설 — Phase 2로 분리(§0.4).
- morning-brief(뉴스레터·공개사이트) 제품의 3자산 확장 — BTC 전용 유지.

### 0.4 확정된 결정사항 (2026-07-31 사용자 승인)
| 결정 | 선택 | 근거 |
|---|---|---|
| 뉴스·비정형 자산별 확장 시점 | **Phase 2로 분리** | 설계문서 §3.2 "자산별 등가 피처 신설 1차 금지"(holdout 순수성) 유지. Phase 1은 글로벌 피처 공유 |
| morning-brief 제품 확장 | **아레나만** | 브리핑 콘텐츠·이메일·공개사이트는 BTC 전용 유지. LLM 비용·운영복잡도 증가 회피 |
| 대시보드 구조 | **자산 탭 전환** | 단일 페이지 유지 + 상단 BTC/ETH/SOL 탭. shadow 단계엔 충분, 코드 변경 최소 |

---

## 1. 현 코드베이스 실측 결과

착수 전 실제로 확인한 사실만 기록한다(추정 아님).

### 1.1 이미 준비돼 있는 것 (예상보다 유리)
| 항목 | 실측 내용 |
|---|---|
| arena 함수 심볼 파라미터화 | `data_lake.py`(4곳), `walk_forward.py`(3곳), `backtest.py`(3곳), `market_structure.py`, `realtime_market.py` 등 대부분이 이미 `symbol: str = parameters.BINANCE_SYMBOL` 기본인자 패턴. **호출부만 바꾸면 동작** |
| `FrequencyProfile.symbol` | `frequency.py`의 프로파일 dataclass가 이미 `symbol` 필드 보유. `_run_cycle()`은 `profile.symbol`을 사용(`scheduler.py:610,438`) — 전역 상수 직접 참조가 아님 |
| 데이터레이크 스키마 | `arena_ohlcv_bars`에 `symbol` 컬럼 이미 존재(`20260619_arena_data_lake_v0.sql:41`). `arena_runs`도 `record_run_started(symbol=...)`로 심볼 기록 중 |
| `arena_decisions`/`arena_shadow_decisions` | `run_id` FK로 `arena_runs`와 조인 → **심볼이 이미 파생 가능**, 마이그레이션 불필요 |
| 섀도우 격리 패턴 선례 | `_run_frequency_shadow_cycle(profile_id)`(`scheduler.py:1127`)가 이미 "같은 알고리즘을 다른 설정으로 shadow 실행하고 `record_shadow_decision`에만 기록, `paper_positions` 미접촉" 패턴을 구현해둠 — **멀티자산 shadow가 그대로 재사용할 템플릿** |
| R2 뉴스 경로 | `build_publish_paths(symbol=..., run_date=...)`(`news_data_paths.py:20`)가 이미 `curated/{symbol}/{date}.json` 구조. 호출부만 `"btc"` 하드코딩(`public_site.py:1926,1935`, `unified_output.py:387`) |
| FinBERT 감성 | `finbert_sentiment.py`는 텍스트 입력 기반이라 자산 무관 — Phase 2에서 그대로 재사용 |
| 환경변수 플래그 관례 | `config.py`에 `ENABLE_ARENA_*` bool 플래그 + `ARENA_FREQUENCY_SHADOW_PROFILES` tuple 패턴 확립 — 동일 방식으로 멀티자산 플래그 추가 가능 |

### 1.2 막혀 있는 것 (반드시 손대야 함)
| # | 항목 | 위치 | 영향 |
|---|---|---|---|
| B1 | **`paper_positions`에 symbol 컬럼 없음** | `20260619_paper_positions.sql:8-23` | 자산별 포지션 구분 불가 — **마이그레이션 필수** |
| B2 | `config.SYMBOL` 단일 전역 | `config.py:126` | 심볼별 컨텍스트 분리 필요 |
| B3 | `parameters.BINANCE_SYMBOL = "BTCUSDT"` 단일 상수 | `parameters.py:33` | 자산 목록 상수 신설 필요 |
| B4 | 대시보드 BTCUSDT 하드코딩 | `arena/index.html` — 타이틀·헤더(6,7,10,11,382), 가격티커(1306), 캔들(1331), buy&hold 벤치마크(714,917,926) | 자산 탭 도입 시 전부 심볼 변수화 |
| B5 | `_fetch_macro()` 심볼 무관 | `scheduler.py:96` | **의도된 설계** — Track B의 글로벌 피처 공유. 변경 안 함(§2.3) |
| B6 | 분석 스크립트 심볼 고정 | `scripts/analysis/*.py`(wi_tuning, gate_block_rates, exec_gate_ecr_sensitivity, fng_optimize 등 다수가 `symbol=parameters.BINANCE_SYMBOL`) | `--symbol` 인자 추가 필요 |
| B7 | `join.py` BTC 특화 로직 | `sentiment_join/join.py` — BTC 언급 90곳, `_add_btc_direction_label()`(507) 등 | **Phase 1 범위 밖**(morning-brief 확장 안 함). Phase 2 진입 시에만 대상 |
| B8 | CoinDesk 카테고리 고정 | `coindesk_news.py:17` `DEFAULT_CATEGORIES = "BTC"` | Phase 2 대상 |

---

## 2. Phase 1 — 아레나 3자산 shadow 확장

### 2.1 설계 원칙 (구현 시 반드시 지킬 것)
1. **기존 BTC 라이브 경로는 코드 상 단 한 줄도 동작이 바뀌면 안 된다.** 모든 신규 경로는
   환경변수 플래그(기본 off) 뒤에 둔다 — `ENABLE_ARENA_MULTI_ASSET_SHADOW`.
2. ETH·SOL은 **`paper_positions`에 쓰지 않는다.** `_run_frequency_shadow_cycle`과 동일하게
   `record_shadow_decision` 계열에만 기록 → 기존 트랙레코드 오염 물리적 차단.
3. 파라미터는 자산별로 분기하지 않는다. `parameters.py`에 자산별 오버라이드 dict를
   **만들지 않는다**(만드는 순간 설계문서 §4 원칙 2 위반이 구조적으로 가능해짐).
4. 글로벌 매크로 피처(FNG/VIX/ETF/breadth/stablecoin)는 3자산이 **동일 값 공유**.
   자산별 재계산 시도 금지 — Track B의 가설이 그렇게 정의돼 있음.

### 2.2 작업 항목

#### P1-1. 자산 상수 및 프로파일 정의
**파일**: `src/arena/parameters.py`, `src/arena/frequency.py`, `src/arena/config.py`

- `parameters.py`: `BINANCE_SYMBOL`(기존, BTC 라이브용)은 **그대로 두고**, 신규 상수 추가:
  ```
  MULTI_ASSET_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")   # 1차 실험 대상
  ```
  기존 상수를 건드리지 않는 이유: `BINANCE_SYMBOL`을 참조하는 30+ 지점의 기본인자가
  전부 BTC를 가리켜야 라이브 무회귀가 보장됨.
- `frequency.py`: `LIVE_4H_PROFILE_ID` 프로파일을 심볼별로 파생하는 팩토리 추가.
  기존 dict 리터럴을 심볼 파라미터화하되 **BTC 프로파일 ID는 변경 금지**(기존 데이터의
  `frequency_profile_id` 값과 연속성 필요). 신규 ID 규칙: `shadow_4h_{symbol.lower()}`.
- `config.py`: `ENABLE_ARENA_MULTI_ASSET_SHADOW`(기본 `false`),
  `ARENA_MULTI_ASSET_SHADOW_SYMBOLS`(기본 `"ETHUSDT,SOLUSDT"` — BTC는 라이브 경로가
  이미 담당하므로 shadow 중복 실행 불필요) 플래그 추가. 기존 `_bool_env`/tuple 파싱
  헬퍼 재사용.

**검증**: `tests/test_arena_parameters.py`에 상수 존재·기본 off 상태 단언 추가.

#### P1-2. 스키마 마이그레이션 (B1 해소)
**파일**: `supabase/migrations/20260731_arena_multi_asset_v1.sql`(신규)

```sql
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS symbol TEXT;
UPDATE paper_positions SET symbol = 'BTCUSDT' WHERE symbol IS NULL;   -- 기존 전부 BTC
ALTER TABLE paper_positions ALTER COLUMN symbol SET DEFAULT 'BTCUSDT';
CREATE INDEX IF NOT EXISTS idx_paper_positions_symbol_status
    ON paper_positions (symbol, status);
```
- **backfill 값이 `'BTCUSDT'`인 것이 핵심** — 기존 라이브 기록이 전부 BTC임이 사실이고,
  이 값이 없으면 이후 모든 자산별 집계가 NULL 처리로 왜곡됨.
- `DEFAULT 'BTCUSDT'`를 두는 이유: `positions.open_position()`이 symbol을 안 넘기는
  기존 호출부가 남아 있어도 안전하게 동작(점진적 마이그레이션).
- `arena_decisions`/`arena_shadow_decisions`/`arena_ohlcv_bars`는 **변경 불필요**(§1.1).

#### P1-3. 포지션 레이어 심볼 인지
**파일**: `src/arena/positions.py`

- `open_position(...)`에 `symbol: str = parameters.BINANCE_SYMBOL` 키워드 인자 추가 →
  `payload["symbol"]`에 반영(`positions.py:93,120` 부근).
- `refresh_open_positions()`, `risk_metrics()`가 심볼별 필터링을 지원하도록
  `symbol: str | None = None` 옵션 추가(None이면 전체 — 기존 동작 보존).
- ⚠️ **주의**: 독립자본 캡(`MAX_OPEN_POSITIONS_TOTAL` 등, portfolio-risk-v2)이 현재
  "알고 수(6)"로 설정돼 있음. 자산이 늘면 동시보유 가능 포지션이 6→18이 되므로,
  캡을 **심볼별로 독립 평가**하도록 바꾸거나(권장) 캡 값을 18로 올려야 함. 권장안은
  전자 — 자산 간 슬롯 경쟁이 생기면 portfolio-risk-v2가 해결한 "트랙레코드 상호오염"
  문제가 자산 축에서 재발함. **shadow 단계에선 `paper_positions`를 안 쓰므로 즉시
  문제되진 않지만, live 전환 시 반드시 선결**.

#### P1-4. 스케줄러 멀티자산 shadow 사이클
**파일**: `src/arena/scheduler.py`

`_run_frequency_shadow_cycle`(1127)을 템플릿으로 `_run_asset_shadow_cycle(symbol)` 신설:
- `frequency.get_frequency_profile(f"shadow_4h_{symbol.lower()}")`로 프로파일 획득
- `_fetch_ohlcv(symbol=profile.symbol, ...)` — 이미 심볼 인자 받음(69)
- `_fetch_macro()` — **심볼 인자 없이 그대로 호출**(글로벌 피처 공유, 설계 의도)
- `indicators.compute(...)` — 자산 자신의 OHLCV로 독립 계산
- **`regime.classify_regime(ind, ...)`를 이 자산의 `ind`로 직접 호출해 `arena_regime_state`를
  계산하고, `_fetch_macro()`가 반환한 공유 macro dict를 복사한 뒤 그 값을 덮어써서 이
  사이클 전용 macro dict를 만든다.** ⚠️ **코드검증으로 확인된 필수 사항**(2026-07-31,
  설계문서 §3.1/§3.3): `arena_regime_state`는 100% 자산고유라 자산별로 재계산해야
  하지만, `funding_zscore`/`long_short_ratio_zscore`/`etf_flow_zscore`/
  `btc_above_ma200` 4개는 BTC 전용 R2 파이프라인 산출물이라 **재계산 경로가 없음** —
  그대로 공유 유지(3자산 전부 BTC 값, Phase 1 범위 내 확정). 이 두 처리를 뒤섞으면
  (예: `arena_regime_state`까지 BTC 값을 그대로 쓰면) Track A의 "로컬 레짐은 자산고유"
  전제 자체가 깨짐 — 반드시 분리 처리.
- `_run_shadow_vnext(...)` 재사용 → `record_shadow_decision`에만 기록
- `run()`(1305)에 플래그 가드 하에 심볼별 cron job 등록. 기존 BTC `_run_cycle_safe`
  job은 **손대지 않음**.

**주의점**:
- `_fetch_depth_snapshot`/`_book_execution_features`는 심볼별 호출 필요(오더북은
  자산 고유) — `EXEC_GATE_DEPTH_SNAPSHOT_LIMIT=1000`이 ETH/SOL에서도 10bps 밴드를
  덮는지 **실측 확인 필요**(BTC 기준으로 정해진 값. 유동성이 얕은 자산은 더 적은
  레벨로도 덮이므로 문제없을 가능성이 높지만, 확인 없이 가정하지 말 것).
- `market_structure`/`realtime_market` 모듈 캐시가 심볼 구분 없이 전역 단일 슬롯이면
  자산 간 값이 덮어써짐 → `set/get_latest_market_features`를 심볼 키 dict로 변경 필요
  (`market_structure.py:98,239` 확인).

#### P1-5. 백테스트 하네스 멀티자산화
**파일**: `src/arena/backtest.py`, `scripts/analysis/backtest_with_macro_backfill.py`

- `load_frames_from_supabase(symbol=...)`는 이미 심볼 인자 보유(1134,1248) → 호출부만
  변경.
- `backtest_with_macro_backfill.py`에 `--symbol` 인자 추가. **macro_rows는 3자산 공통**
  (parquet에서 재구성한 글로벌 regimeRaw를 그대로 주입) — Track B 설계와 일치.
- **선결 확인**: `arena_ohlcv_bars`에 ETHUSDT/SOLUSDT 4H 봉이 **아직 없다**. 20개월치
  백테스트를 하려면 Binance klines에서 히스토리를 수집해 적재하는 선행 작업 필요
  (`data_lake.record_ohlcv_bars(symbol=...)`가 이미 심볼 지원). 1회성 백필 스크립트
  `scripts/analysis/backfill_ohlcv_symbol.py` 신설 권장.

#### P1-6. 분석 스크립트 심볼 인자화 (B6)
**파일**: `scripts/analysis/` 하위 — `wi_tuning.py:93`, `gate_block_rates.py:78`,
`exec_gate_ecr_sensitivity.py:88`, `fng_optimize.py:68` 등

- 각 스크립트에 `--symbol` 인자 추가(기본값 `BTCUSDT`로 기존 동작 보존).
- **신규 스크립트 `scripts/analysis/cross_asset_report.py`**: 설계문서 §5.1의 지표
  전체(거래수·비용후 expectancy·B&H 대비 초과수익·노출시간/beta-adjusted·PF·MaxDD·
  MAE/MFE·turnover·레짐별 성과·단일거래 기여도)를 **Algorithm × Asset 매트릭스**로
  산출하고, **Track A/B를 별도 표로 분리 출력**(설계문서 §5.2 조건6).
- `arena_status.py`에 `--symbol` 인자 추가(현행 BTC 전용 뷰 유지 + 자산 선택 가능).

#### P1-7. 대시보드 자산 탭 (B4)
**파일**: `arena/index.html`

- 상단에 BTC/ETH/SOL 탭 UI 추가. 선택 심볼을 전역 변수화하고 다음을 파라미터화:
  - 가격 티커 fetch(1306), 캔들 klines fetch(1331) — `symbol=` 쿼리 치환
  - buy&hold 벤치마크 계산(714,917,926) — 선택 자산 기준
  - 타이틀·헤더 텍스트(6,7,10,11,382,385,407,424,428,447)
- **ETH/SOL 탭은 "shadow — 실거래 아님" 배지를 명시**해야 함. 아레나는 공개 대시보드고
  제품 신뢰성의 핵심이 "투명한 실거래 트랙레코드"이므로, shadow 데이터를 라이브와
  시각적으로 구분하지 않으면 제품 주장 자체가 훼손됨.
- 데이터소스: ETH/SOL은 `paper_positions`가 아니라 `arena_shadow_decisions` 조인 뷰가
  필요 → Supabase view 신설 또는 대시보드 쿼리 분기.

#### P1-8. 테스트
**파일**: `tests/test_arena_multi_asset.py`(신규) + 기존 파일 보강

- 멀티자산 플래그 기본 off 상태에서 `run()`이 기존과 **동일한 job 집합**만 등록하는지
  (라이브 무회귀 회귀테스트).
- `_run_asset_shadow_cycle`이 `paper_positions`에 쓰지 않는지(mock으로 검증).
- `open_position(symbol=...)`이 payload에 symbol을 싣는지.
- 심볼별 market_structure 캐시가 서로 덮어쓰지 않는지.
- 기존 150+ arena 테스트 전체 통과(회귀 확인).

### 2.3 Phase 1에서 **하지 않는** 것 (명시)
- `_fetch_macro()` 심볼별 분기 — 글로벌 피처 공유가 Track B의 설계 전제.
- `parameters.py` 자산별 오버라이드 dict — 원칙 2 위반 방지.
- ETH/SOL live 전환 — shadow 결과 판정 후 별도 결정.
- `join.py`/morning-brief 확장 — Phase 2.

---

## 3. Phase 2 — 뉴스·정형·비정형 데이터 자산별 확장

> **진입 조건**: Phase 1 결과가 설계문서 §6.1의 A/B/C 분기 중 하나로 판정되고,
> 자산별 컨텍스트 데이터가 실제로 필요하다고 확인된 경우에만 착수.
> D 분기(두 자산 모두 붕괴)면 Phase 2는 **취소**한다(BTC 특화 규칙으로 확정되므로
> 자산별 데이터 수집이 무의미).

### 3.1 왜 Phase 1과 분리하는가
설계문서 §3.2: 자산별 등가 피처 신설은 "기존 전략의 holdout 검증이 아니라 **새로운
전략 및 데이터 파이프라인 개발**"이다. Phase 1에 섞으면 "BTC 룰이 전이되는가"라는
질문과 "새 데이터로 만든 새 전략이 좋은가"라는 질문이 뒤섞여 어느 쪽도 판정 불가.

### 3.2 확장 대상 (Phase 2 진입 시)
| 데이터 종류 | 현 상태 | 확장 방법 |
|---|---|---|
| **비정형 — 뉴스 기사** | CoinDesk `DEFAULT_CATEGORIES="BTC"`(`coindesk_news.py:17`), Google News RSS는 query 기반(`google_news_rss.py:30`) | CoinDesk는 카테고리 파라미터를 `ETH`/`SOL`로 확장(API 지원 여부 사전 확인 필요). RSS는 키워드 세트만 자산별로 추가 |
| **비정형 — X/소셜** | `grok_x_keyword.py` BTC 키워드 12곳 | 자산별 키워드 세트 분리 |
| **비정형 — 감성 스코어링** | `finbert_sentiment.py` 텍스트 기반, 자산 무관 | **코드 변경 불필요** — 입력만 자산별로 주면 됨 |
| **정형 — 가격/파생** | Binance API 심볼별 이미 제공 | Phase 1에서 이미 처리(funding/OI/LSR/taker) |
| **정형 — ETF 흐름** | `btc_etf_official.py` BTC 126곳 | ETH ETF는 존재(현물 ETF 승인됨), SOL은 상품 자체가 제한적 → **자산별 가용성 차이를 그대로 인정**하고 없는 자산은 None 처리 |
| **정형 — breadth/stablecoin** | `binance_breadth.py`(BTC 상위10 바스켓), `defillama_stablecoins.py`(시장전체) | stablecoin은 원래 시장전체 지표라 공유가 맞음. breadth는 자산별 재정의 가능하나 의미 재검토 필요 |
| **저장 경로** | `build_publish_paths(symbol=...)` 이미 심볼 슬롯 보유 | 호출부 하드코딩 `"btc"` 3곳(`public_site.py:1926,1935`, `unified_output.py:387`)만 변수화 |
| **키워드/토픽 정책** | `market_keywords.py`가 `market_packet["bitcoin"]` 고정, `news_policy.TOPIC_KEYWORDS`에 `"bitcoin": 1.7` | 자산별 키워드 맵으로 일반화 |
| **join 파이프라인** | `join.py` BTC 90곳, `_add_btc_direction_label()`(507) | 자산별 파이프라인 인스턴스화 — **가장 큰 작업**. 별도 설계 필요 |

### 3.3 Phase 2 비용 경고 (사전 인지)
- 뉴스 API는 대부분 **요청량 과금**(TheNewsAPI, Marketaux, Perplexity, Grok). 자산 3배
  = 호출 3배 = 비용 3배. Phase 1 결과가 "전이성 없음"이면 이 비용은 전액 낭비.
- FinBERT 추론량도 3배(자체 호스팅이면 CPU/시간, API면 과금).
- **이것이 Phase 2를 분리한 실용적 이유이기도 함** — Phase 1은 Binance API(무료·
  rate-limit 여유)와 기존 글로벌 피처만 쓰므로 **추가 비용이 사실상 0**.

---

## 4. 리스크 및 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| 기존 BTC 라이브 트랙레코드 오염 | **치명적**(제품 핵심 훼손) | 플래그 기본 off + shadow 경로가 `paper_positions` 미접촉 + 회귀테스트로 job 집합 고정 |
| 모듈 전역 캐시 자산 간 덮어쓰기 | 조용한 데이터 오염(발견 지연) | `market_structure`/`realtime_market` 캐시를 심볼 키 dict화, 테스트로 검증 |
| `arena_ohlcv_bars`에 ETH/SOL 히스토리 부재 | 백테스트 불가 | 선행 백필 스크립트(P1-5) |
| depth limit=1000이 ETH/SOL에 부적합 | 실행품질 섀도우 오탐 | 자산별 실측 후 필요시 심볼별 limit(단 이건 데이터수집 파라미터이지 전략 파라미터가 아니므로 원칙 2 위반 아님) |
| 독립자본 캡이 자산 축에서 재오염 | live 전환 시 트랙레코드 상호오염 | shadow 단계에선 무영향. live 전환 전 심볼별 독립 캡으로 선결(P1-3 주의사항) |
| EC2 리소스(4H×3자산 + 1분 실시간 수집) | 서버 부하 | shadow 사이클은 4H 1회씩이라 미미. 단 `realtime_market` 1분 수집을 3자산으로 늘리면 WS 연결 3개 → 부하·안정성 재확인 필요(**Phase 1에선 실시간 수집은 BTC만 유지 권장**) |
| 대시보드에서 shadow/live 혼동 | 제품 신뢰성 훼손 | ETH/SOL 탭에 "shadow" 배지 필수(P1-7) |

---

## 5. 착수 순서 (의존성 기준)

```
[선결] omnibus 트랙 배정 결정 (설계문서 §3.3)
   └─ 코드 확인: RISK_OFF/TRANSITION의 글로벌 신호 개입 여부
        ↓
P1-2 스키마 마이그레이션 (paper_positions.symbol)
        ↓
P1-1 자산 상수·프로파일·플래그
        ↓
P1-3 포지션 레이어 심볼 인지 ─┐
P1-4 스케줄러 shadow 사이클 ─┤ (병렬 가능)
        ↓                    │
[백필] ETH/SOL OHLCV 히스토리 적재  ← P1-5의 선결
        ↓
P1-5 백테스트 하네스 멀티자산화
        ↓
P1-6 분석 스크립트 + cross_asset_report.py
        ↓
P1-8 테스트 (전 단계 회귀 확인)
        ↓
P1-7 대시보드 자산 탭
        ↓
[판정] 설계문서 §5.2 기준으로 A/B/C/D 분기 결정
        ↓
Phase 2 착수 여부 결정 (D면 취소)
```

**체크포인트**: P1-8 완료 시점에 "기존 150+ arena 테스트 + 신규 멀티자산 테스트 전체
통과 + 플래그 off 상태에서 EC2 배포해 기존 동작 무변경 확인"을 반드시 거친 후에만
플래그를 켠다.

---

## 6. 남은 미결정 사항

1. ~~omnibus 트랙 배정~~ — **해결됨**(2026-07-31 코드검증, 설계문서 §3.3). Track A
   포함 확정. 부수적으로 Track A 3개 알고(regime_trend·macd_momentum·omnibus) 전부가
   funding/LSR/MA200/ETF흐름 4개 veto를 통해 BTC 전용 macro dict에 의존한다는 사실도
   확인됨 — P1-4에 처리방침(자산고유 성분/공유 성분 분리) 반영 완료.
2. **ETH/SOL 실시간 1분 수집 여부** — Phase 1 권장안은 "BTC만 유지"(부하·안정성). 단
   이 경우 ETH/SOL은 4H 봉 기반 MFE/MAE만 산출 가능(1분 정밀화 불가) — 설계문서 §5.1의
   MAE/MFE 지표 해상도가 자산별로 다르다는 점을 결과 해석 시 명시해야 함.
3. **shadow 결과의 대시보드 공개 시점** — 내부 검증 완료 전에 공개할지, 판정 후 공개할지.
4. **Track A `cross_asset_report.py` 출력 시 disclosure 문구 추가**(P1-6) — Track A
   결과표에 "funding/LSR/MA200/ETF유출 veto는 BTC 값 공유"라는 각주를 넣어야
   "순수 자산고유 검증"으로 오독되지 않게 한다.

## 관련 문서
- [structural-priority-multi-asset-expansion-20260730.md](structural-priority-multi-asset-expansion-20260730.md) — 실험설계(문제진단·자산선정·Track A/B·판정기준)
- [docs/papers/](../../papers/README.md) — 이 방향을 도출한 외부 논문 4편 분석
- CLAUDE.md Paper Trading Arena 섹션 — 현행 아키텍처·portfolio-risk-v2 원칙
