# Spot→Perp Phase A2 — 자산×시장 루트 트랙 분리 (2026-08-15)

**배경**: [Phase A(인프라)](spot-to-perp-phase-a-infrastructure-20260815.md) 직후
사용자가 방향을 명확히 함 — 기존 현물 트랙레코드는 절대 초기화하지 않고, 현물/선물을
자산(BTC/ETH/SOL)과 동일한 레벨의 독립 루트 트랙으로 나눈다. "BTC 현물"과 "BTC 선물"이
오늘의 "BTC"와 "ETH"처럼 완전히 독립된 자본 풀이 되는 구조. Phase A의
`PERP_LIVE_ENABLED_ALGOS`(알고별 spot/perp 전환 스위치)는 폐기가 아니라 역할이
좁아짐 — 이제 "이 알고가 (perp 트랙 안에서) 숏을 낼 수 있느냐"만 담당(Phase B).

## 핵심 설계 — 기존 멀티에셋 인프라 재사용

ETH/SOL이 BTC와 독립 자본으로 도는 메커니즘은 전부 `symbol` 문자열 하나를 파티션
키로 쓰는 것뿐이었다(`state.py`의 `open_positions[symbol]`, `paper_positions`의
`(symbol, algo_id)` 유니크 인덱스, 대시보드 `ASSETS[key].symbol`,
`risk.evaluate_open`에 넘기는 `state.positions_for(symbol)`). 하드코딩된 "3자산"
가정은 어디에도 없었다.

**따라서**: perp 트랙을 위해 새 자료구조·DB 마이그레이션이 필요 없다 — `symbol` 값
자체를 새 문자열(`"{실제티커}-PERP"`, 예: `"BTCUSDT-PERP"`)로 등록하면 기존 파티셔닝이
공짜로 따라온다. `symbol`이 겸하던 두 역할(① DB/state/대시보드 파티션 키, ② 실제
바이낸스 REST/WS 호출용 티커)만 분리 — `FrequencyProfile.binance_symbol` 필드 신설.

## 구현

- **`parameters.py`**: `perp_track_symbol()`/`real_ticker_for_track()`(유일한
  "-PERP" 접미사 생성·파싱 지점), `ARENA_PERP_LIVE_ENABLED`(기본 False).
- **`config.py`**: `ENABLE_ARENA_PERP_LIVE`(env 오버라이드), `ARENA_LIVE_TRACKS_BY_SYMBOL`
  (실제 티커→트랙 리스트 매핑, perp off면 `{symbol: (symbol,)}`로 기존과 동일),
  `ARENA_LIVE_REAL_SYMBOLS`(WS 구독용, 중복 제거), `ARENA_LIVE_ALL_TRACKS`(워밍업용,
  개별 트랙 전부).
- **`frequency.py`**: `FrequencyProfile`에 `binance_symbol`/`product_type` 필드 추가.
  신규 `perp_live_profile_id()`+`_register_perp_live_profiles()`(BTC/ETH/SOL 전부,
  `_register_multi_asset_shadow_profiles`와 동일 패턴 — 자산별 재튜닝 금지 원칙).
- **`scheduler.py`**: REST 호출 4곳(`_fetch_ohlcv`/`_fetch_book_ticker`/
  `_fetch_depth_snapshot`/`market_structure.fetch_market_structure_snapshot`)과
  실행게이트·실시간리스크 조회를 `profile.symbol`→`profile.binance_symbol`로 교체
  (실제 시장데이터는 항상 실제 티커). `positions.risk_metrics`/`state.*`는 그대로
  `profile.symbol`(트랙 단위 독립 리스크). `positions.open_position()`에
  `product_type=profile.product_type` 명시 전달로 전환(더 이상 algo_id로 역산 안 함).
  `scheduler.run()`에 `ENABLE_ARENA_PERP_LIVE` 게이트 세 번째 cron 루프 추가(기존
  멀티에셋 루프와 동일 패턴, 스태거 오프셋만 분리).
- **`positions.py`**: `open_position()`이 `product_type`/`position_semantics`를
  명시 인자로 받음(없으면 Phase A 알고별 폴백 유지, 하위호환). `close_position()`의
  펀딩 조회를 `real_ticker_for_track()`으로 감싸 트랙 심볼이 아닌 실제 티커로 조회하도록
  수정(안 하면 `arena_funding_rates`에서 0건 → 펀딩 항상 0 취급되는 조용한 버그).
- **`stream.py`/`server.py`**: WS 구독은 실제 티커만(perp도 spot 가격 프록시라 새
  커넥션 불필요) — 틱 하나가 도착하면 `config.ARENA_LIVE_TRACKS_BY_SYMBOL`로 그 실제
  티커에 매핑된 모든 트랙(perp off면 1개, on이면 spot+perp 2개)의 스탑로스를 체크.
  `server.py` 워밍업도 `ARENA_LIVE_ALL_TRACKS`로 확장.
- **`slack_notify.py`**: `_symbol_label()`이 `real_ticker_for_track()`으로 역변환 후
  "-F" 접미사(예: "BTC-F")로 선물임을 표시.
- **`arena/index.html`**: `MARKETS`(현물/선물) + `activeMarket` 신설, `trackSymbol()`
  헬퍼. 자산 탭 옆에 시장 탭 추가(`renderMarketSwitcher`/`switchMarket`).
  `fetchPositions`/`fetchDecisions`는 `trackSymbol()`을, 가격/캔들(`fetchKlinesData`/
  `fetchPrice`)은 항상 실제 티커(`ASSETS[activeAsset].symbol`)를 쓴다(perp도 spot
  프록시라 시장과 무관). **`computeGrandTotal` 버그 수정**: 기존엔 symbol(=자산)로만
  묶어 spot·perp 포지션이 동시에 있으면 한 슬롯에 섞였을 것 — 자산×시장 중첩 루프로
  해결. 단, perp 데이터가 실제로 없으면(`ENABLE_ARENA_PERP_LIVE=False`) 빈 선물
  슬롯 18개를 합계에 안 끼워넣도록 `hasPerpData` 가드 추가(안 하면 총수익률이
  0%짜리 빈 슬롯들로 희석되는 표시 오류가 생겼을 것).

## 구현 중 발견·수정한 버그 (Phase A2 자체 검증 과정)

**경합 조건(신규 도입)**: 시장 축을 추가하면서 사용자가 탭을 빠르게 연속 전환할
가능성이 늘었는데, 이전 트랙에 대한 느린 응답이 나중에 도착해 최신 트랙 데이터를
덮어쓰는 경합이 실제로 로컬 프리뷰에서 재현됨(ETH 클릭 시 실제 데이터 대신 빈
$6000/0건이 렌더된 사례) — `refreshActiveTrack()`에 시퀀스 토큰(`trackRequestSeq`)을
추가해 막바지 요청의 응답만 반영하고 그 사이 도착한 stale 응답은 폐기하도록 수정.
프로그래밍 방식 단일 호출로는 재현 안 되고 실제 빠른 클릭에서만 재현되는 전형적인
비동기 경합 — 재현 후 수정, 이후 자산×시장 4개 조합 전부 왕복 클릭으로 재검증 완료.

## 검증

- `ENABLE_ARENA_PERP_LIVE` 기본 False — 꺼져 있으면 오늘 코드와 100% 동일 동작
  (perp 프로파일은 등록만 되고 스케줄 안 됨).
- 신규 테스트 10건(`test_arena_perp_track_split.py`) + 갱신 2건(펀딩 조회 real-ticker
  변환, `open_position` 명시적 product_type) — arena 272개 전체 통과.
- 로컬 프리뷰(실제 라이브 Supabase 데이터)로 BTC/ETH/SOL × 현물/선물 8개 조합 전부
  왕복 클릭 검증: 현물 3개는 실제 프로덕션 수치와 일치, 선물 3개는 예상대로 완전
  빈 상태($1,000 flat·신호 대기)로 렌더, 그랜드토탈은 perp 데이터 없는 동안 18슬롯
  그대로 유지(경합 수정 후 확인) — 콘솔 상 원인 특정 불가한 "500" 리소스 에러 1건
  발견(아래 참조), 그 외 기능적 문제 없음.

## 미해결 — 원인 불명 콘솔 500 (기능 영향 없음, 후속 조사 필요)

로컬 프리뷰에서 페이지를 새로고침하거나 탭을 전환할 때마다 브라우저 콘솔에
"Failed to load resource: the server responded with a status of 500"가 한 번씩
찍힌다. **철저히 조사했으나 원인을 특정하지 못함**:
- `window.fetch`/`XMLHttpRequest`를 전부 몽키패치해 요청 로그를 남겨봤지만 실제
  발생한 모든 요청(Binance REST 3건, Supabase REST 4~5건)이 전부 200 — 앱이 만드는
  네트워크 호출 중엔 없음.
- 로컬 정적 파일 서버(`python -m http.server`) 로그에도 500이 안 찍힘 — 내 서버발도
  아님.
- `setupRealtime()`(Supabase Realtime WebSocket 구독)을 완전히 비활성화해도 재현됨
  — 그것도 아님.
- **미변경 원본 파일**(`git show HEAD:arena/index.html`)을 같은 방식으로 별도
  포트에서 서빙해 동일하게 테스트 — 이쪽은 몇 차례 재현 시도에서 단 한 번도 발생
  안 함. 즉 내 변경분과 상관관계는 있는데, 실제 원인이 되는 네트워크 호출을 못 찾음
  (CDN 스크립트 태그(`unpkg.com`/`jsdelivr.net`)는 두 파일이 완전히 동일한 URL).
- 기능적으로는 무해함(렌더링된 데이터는 항상 정확했음, 경합조건 수정 후 재확인) —
  실제 프로덕션(Cloudflare Pages) 배포 환경에서도 재현되는지, 아니면 이 로컬
  프리뷰 인프라(`python http.server` + 브라우저 프리뷰 패널) 고유의 아티팩트인지
  다음에 실제 배포 후 확인 필요.

## 미착수 (변경 없음, Phase A와 동일)

- 전용 perp 가격 피드(fapi klines/fstream WS) — spot 프록시 유지.
- Phase B(알고별 숏 로직 설계·백테스트).
- EC2 배포·커밋 — 이번에도 로컬 구현·검증까지, 배포는 사용자 확인 후.
