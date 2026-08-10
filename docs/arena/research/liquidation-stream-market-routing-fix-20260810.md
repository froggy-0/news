# WI-9 청산 스트림 — "/market" 라우팅 누락이 근본원인이었음 (2026-08-10)

## 배경

2026-07-14 진단(`priority-improvements-20260714.md` §P1-3)은 서울 EC2에서 바이낸스 선물
WS(`fstream.binance.com`)가 forceOrder 프레임을 59시간 무중단 가동에도 0건 수신한 것을
"구조적 네트워크 문제(지역차단 추정)"로 판정하고, 재개 조건으로 "타 리전 재시도 또는 유료
서드파티(CoinGlass/Coinalyze) 교체"를 제시했었다.

사용자가 "청산 데이터는 다 유료 아니냐"고 반문한 것을 계기로 재조사 — Binance 공식 문서
(`developers.binance.com`)를 확인한 결과 **WS 구독 경로에 라우팅 세그먼트
(`/public`·`/market`·`/private`)가 필요**하며, `forceOrder`류 스트림은 `/market` 경로가
필수라는 문서를 발견. 기존 코드(`config.BINANCE_FUTURES_LIQUIDATION_WS_URL =
"wss://fstream.binance.com/ws/btcusdt@forceOrder"`)는 이 라우팅 세그먼트가 없었다.

## 실측 (로컬, 비-서울 네트워크, `scripts/analysis/liquidation_ws_probe.py`)

25~60초 리슨 결과:

```
wss://fstream.binance.com/ws/!forceOrder@arr              0 frames  (라우팅 없음, 전체마켓)
wss://fstream.binance.com/market/ws/!forceOrder@arr      28 frames  (라우팅 있음, 전체마켓) ✅
wss://fstream.binance.com/ws/btcusdt@forceOrder            0 frames  (= 기존 EC2 코드, BTC 단일)
wss://fstream.binance.com/stream?streams=!forceOrder@arr   0 frames  (combined mode, 라우팅 없음)
wss://fstream.binance.com/market/ws/btcusdt@forceOrder     1 frame/60s (라우팅 있음, BTC 단일) ✅
```

**로컬(서울 EC2 아님)에서도 라우팅 없는 URL은 전부 0건** — 지역차단이 아니라 URL 자체가
더 이상 유효하지 않았던 것으로 결론. `/market` 경로를 추가하면 기존과 동일한 단일 심볼
(BTCUSDT) 구독으로도 정상 수신된다(빈도는 낮음 — 60초에 1건 수준, 알고리즘 4h 버킷 집계
목적엔 충분).

## 조치

- `config.BINANCE_FUTURES_LIQUIDATION_WS_URL`: `/ws/btcusdt@forceOrder` →
  `/market/ws/btcusdt@forceOrder` (심볼 범위는 기존과 동일하게 BTC 단일 유지 — 전체마켓
  스트림으로 확장할 이유 없음, 4h 버킷 집계 로직은 이미 BTC 전용).
- `liquidation_stream.py` 주석·idle 경고 로그의 "지역차단 추정" 문구를 정정.
- 트레이딩 경로 무영향(수집 전용), 코드·테스트 변경 없이(URL 상수 1줄) 배포 가능. arena
  220개 테스트 통과.

## 재발 방지 메모

"WS 핸드셰이크 성공(connected 로그) = 정상"이라는 가정이 이번에도(2번째) 문제를 놓칠 뻔한
근본 원인이었다 — 라우팅 세그먼트가 틀려도 핸드셰이크 자체는 성공하고, 단지 구독한 스트림에
해당하는 프레임을 안 줄 뿐이다. W7(주간 헬스체크, `docs/arena/research/
implementation-plan-w-series-20260715.md`)이 아직 미구현인데, 그 설계에 있는 "산출물
카운트 기반 체크"(로그가 아니라 `arena_liquidation_bars` 신규 행 존재 확인)가 정확히
이런 종류의 실패를 잡기 위한 것 — 이번 건으로 그 설계의 필요성이 재확인됨.

## 상태

- ✅ EC2 배포 완료 시 `ARENA_LIQUIDATION_STREAM_ENABLED=true`이면 즉시 수집 재개.
- 30일+ 축적 후 WI-9 원래 목표(fng_contrarian·omnibus REBOUND "매도 소진" 확인 지표 연결)를
  별도 WI로 재개 가능.
