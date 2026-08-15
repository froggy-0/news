# Spot→Perp 전환 Phase A — 인프라 구현 (2026-08-15)

**배경**: [relative-strength-candidate-vanguard-20260815.md](relative-strength-candidate-vanguard-20260815.md)
스프린트 직후, 사용자가 "spot만으로는 한계가 명확하다 — future로 전환해서 롱/숏 모두
대응 가능하게" 방향을 확정. 레버리지 없음(1x)·인프라 우선(플래그 기본 off)·알고별
백테스트 통과분만 순차 라이브 전환으로 스코프 확정 후 계획 승인(plan mode) → 이 세션에서
Phase A(인프라) 구현·검증까지 완료.

## 핵심 발견 — "새로 만드는" 게 아니라 "이미 있는 대칭 로직을 라이브까지 연결"

이 저장소는 **2026-06-20 이전엔 실제로 perp long/short 시뮬레이션을 돌렸었다**
(`docs/arena/operations/spot-semantics-migration.sql`로 spot 전용 전환). 그 결과:
- `execution_rules.py`(손절·트레일·사이징)와 `risk.py`(포지션 캡)는 **이미 완전히
  long/short 대칭**.
- `backtest.py`의 `run_replay()`는 `product_type != "spot"`일 때 이미 열림/보유/반전/
  청산을 방향 무관하게 처리하는 상태머신을 갖고 있음(다만 이번에 fng_contrarian 물타기
  호출 누락을 발견·수정 — 아래 참조).
- `paper_positions.direction` 컬럼은 애초에 free text.

막혀있던 곳은 라이브 경로 하나: `spot_policy.py`(숏 신호=항상 청산/무시)와
`positions.py`의 숏 오픈 가드, `scheduler.py`가 product_type 분기 없이 무조건
`spot_policy.decide()`를 호출하던 지점.

## 구현 내역

**알고별 opt-in 스위치** (`parameters.py`): `PERP_LIVE_ENABLED_ALGOS: frozenset[str]`
(기본 빈 집합). `target_product_for_algo()`/`target_position_semantics_for_algo()`가
algo_id 기준으로 `spot`/`usdm_perp`를 결정 — 이 집합이 비어있으면 전 알고 기존 spot
동작과 100% 동일.

**신규 `perp_policy.py`**: `spot_policy.py`의 대칭 버전. 방향 무관 열림/보유/반전
(같은 사이클 내 청산 후 재진입)/flat 청산 — `backtest.py` 비-spot 상태머신과 동일
의미론을 미러링(새 설계 아님). `SpotExecutionDecision`과 동일한 필드 shape이라
`scheduler.py` 호출부가 타입을 몰라도 동일하게 다룰 수 있음.

**`scheduler.py` 배선**:
- `_risk_policy()`: `PERP_LIVE_ENABLED_ALGOS`가 비어있지 않으면 숏 캡 개방(전
  알고 대상 portfolio 캡이라 algo_id 단위 아님 — `positions.open_position()`의
  algo_id별 허용목록이 실제 이중 방어).
- 메인 루프: algo_id가 허용목록에 있으면 `perp_policy.decide()`, 아니면 기존
  `spot_policy.decide()`. 청산 후 `continue` 무조건 실행하던 걸 `is_perp and
  should_open`이면 그대로 통과시켜 같은 사이클에서 반전 재진입 평가 — spot 경로는
  100% 무변화(조건이 항상 거짓이라 항상 continue).
- min-hold 게이팅: spot의 "legacy short/숏 신호는 min_hold 무시하고 즉시 강제청산"
  bypass가 perp 반전에는 적용되지 않도록 분리(perp는 backtest.py 비-spot 분기와
  동일하게 균일 min_hold 적용, 원치 않는 즉시 반전 매매 억제).

**`positions.py`**:
- 숏 오픈 가드를 `config.TARGET_PRODUCT`/`ALLOW_LIVE_SHORT`(전역) 대신
  `algo_id not in parameters.PERP_LIVE_ENABLED_ALGOS`(알고별 허용목록)로 교체.
- 포지션 행의 `product_type`/`position_semantics`를 algo_id 기준으로 기록(이전엔
  전역 상수 고정값).
- **라이브 펀딩 정산 신규 추가** — 이전엔 라이브 경로에 펀딩 개념 자체가 없었음(백테스트만
  계산). perp 포지션 청산 시 `data_lake.fetch_funding_rates()`(신규, `arena_funding_rates`
  조회 — 이미 4h마다 수집 중인 실데이터)로 보유기간 펀딩 행을 가져와
  `market_structure.funding_return_pct()`(기존 backtest 전용 함수, 그대로 재사용)로
  정산, `ret_pct`에 가산. 조회 실패는 그레이스풀(펀딩 0, 청산 자체는 계속).

**`slack_notify.py` 버그 수정**: `notify_open()`이 `direction != "long"`이면 무조건
무음 반환하던 것 발견 — 숏 포지션이 열려도 알림이 아예 안 갔을 것. `direction in
("long","short")`로 수정 + "legacy synthetic short"/"현물 실행 제외 신호" 라벨을
"숏 진입"/"숏 청산"으로 교체(더 이상 legacy 잔재 전용이 아니라 정상 방향이므로).

**대시보드 (`arena/index.html`)**: `fetchPositions`/`fetchAllPositions`가
`direction==='long' && product_type==='spot'`로 하드필터링해 숏 포지션이 생기면
그냥 안 보였을 것 — `(product_type∈{spot,usdm_perp}) && (direction∈{long,short})`로
일반화(2026-06-20 이전 `legacy_perp_sim` 행은 product_type 불일치로 계속 자동 배제).
P&L 부호 계산 3곳에 `dirSign(direction)` 헬퍼 적용, 포지션 카드 배지를
direction/product_type 기반 동적 라벨(`▲ SPOT LONG`/`▲ PERP LONG`/`▼ SHORT`)로,
차트 마커에 숏용 `arrowDown`/`aboveBar` 추가.

**`backtest.py` 패리티 버그 수정 (구현 중 발견)**: Phase A 패리티 백테스트(product_type을
spot→usdm_perp로만 바꾸고 알고 로직은 무변화 상태에서 손익차가 펀딩비만큼만 나는지
확인)를 돌리다 `fng_contrarian`만 거래수가 어긋나는 걸 발견 — `run_replay()`의 비-spot
분기(`else: signal = raw_signal`)에 fng의 가격기준 물타기(`_maybe_scale_in_fng_sim`)
호출이 원래 없었음(그 호출은 `product_type=="spot"` 분기 안에만 있었음). 라이브
`scheduler.py`는 이 문제 없음(스케일인 호출이 애초에 product_type 분기 밖, 공용) —
순수 `backtest.py` 연구도구의 기존 격차였고 이번에 발견 계기로 같이 수정. 회귀 테스트
추가(`test_fng_contrarian_scale_in_has_parity_under_non_spot_product_type`).

## 의도적으로 미룬 것 (다음 스프린트)

- **전용 perp 가격 피드**: 지금은 perp 모드 알고도 여전히 spot klines/가격을 씀(1x
  레버리지라 베이시스 오차가 작고 바운드돼 있다는 판단 — BTC/ETH 통상 <0.1~0.3%).
  전용 `fapi.binance.com` klines·전용 WS 스트림 추가는 별도 스레드로 분리.
- **Phase B(알고별 숏 로직)**: 이 문서는 인프라만 다룸. 제안 순서(설계 계획서 참조):
  macd_momentum(TSMOM_NL 이미 연속·부호형 신호) → omnibus DOWN_TREND 레그
  (STRUCTURAL_DOWN/PANIC_DROP 이미 계산되고 버려짐) → regime_trend → multi_factor →
  vix_rsi/fng_contrarian(역발산 알고라 "탐욕→숏" 대칭 가정 자체가 검증 대상).
- **Phase C**: EC2 라이브 env에서 `ENABLE_ARENA_MULTI_ASSET_SHADOW` 실제 활성 여부
  확인(ETH/SOL 펀딩 데이터 축적 전제조건).

## 검증

- `PERP_LIVE_ENABLED_ALGOS` 기본 빈 집합 — 모든 변경이 조건부 분기 뒤에 있어 기본
  상태는 기존 spot 동작과 바이트 단위로 동일해야 한다는 원칙으로 설계.
- 신규 테스트 27건(`test_arena_perp_policy.py` 12·`test_arena_positions_perp_funding.py`
  4·`test_arena_scheduler_perp.py` 2·`test_arena_slack_notify.py` 신규 2건·
  `test_arena_backtest.py` 패리티 회귀 1건 + 기존 2건 문구 갱신), arena 전체
  262개 통과. 전체 리포 테스트(무관한 사전 실패 2건 제외, 기존부터 있던 실패) 통과.
- **패리티 백테스트**(스크래치, `product_type` spot↔usdm_perp 대조, BTC 4h 366봉):
  6알고 전부 거래수·방향 완전 동일, 손익차는 펀딩비만(-0.02~-0.10%p, fng는 물타기
  버그 수정 후 -0.10%p) — 트레이딩 로직이 product_type 전환으로 안 바뀐다는 것 확인.
- 대시보드: 로컬 프리뷰(`arena-dashboard` launch config, 8791)로 실제 라이브 Supabase
  데이터 렌더 확인 — 총자산·알고별 성과·오픈 포지션 카드(`▲ SPOT LONG` 배지)·가격차트
  마커 전부 정상, 콘솔 에러 없음, `/arena-status` 최근 출력과 수치 일치.
- **PARAMS_VERSION bump 없음** — 플래그 전부 off, 라이브 신호·손익 무변화(인프라·버그
  수정만).

## 배포 상태

⚠️ **이 세션에서 커밋·EC2 배포는 하지 않음** — 구현·로컬 검증까지 완료, 커밋/배포는
사용자 확인 후 별도 진행.
