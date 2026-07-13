# 아레나 우선순위 개선점 (2026-07-14)

> `/arena-status --fresh-backtest`(기본 30일 창) + gate_block_rates + 라이브 close 22건 drill-down
> + EC2 직접 점검(journalctl, fstream 연결 테스트) + git blame으로 검증. 매매방식·비중·데이터수집
> ·프로세스 4개 카테고리, 카테고리 내 우선순위순. 기존 백로그([remaining-improvements-20260710](remaining-improvements-20260710.md))
> 재탕 금지 — 여기 항목은 이번 점검에서 새로 발견/검증된 것만.

## 헤드라인

가장 시급한 건 알고 파라미터가 아니라 **버전 라벨링 버그 하나가 향후 모든 전후비교를 무효화하고
있다는 것**과 **WI-9 청산 수집이 59시간째 0건으로 조용히 죽어있다는 것**. 둘 다 트레이딩 로직과
무관한 인프라 결함이라 지금까지 아무도 눈치채지 못했다. 알고 성과 자체는 표본이 여전히 작아
(알고당 라이브 4~9건/30일) 방향 참고 수준.

---

## P0 — 즉시 수정 (버그, 공수 소)

### 1. `PARAMS_VERSION` 라벨이 v30 변경분을 못 따라감 ⚠️
- **증거**: `git log`에서 `b9e3c7e`(fng target atr2.0 재채택)·`21bcdd8`(ts/mh 재조정)
  두 커밋 모두 메시지에 "arena-params-v30"을 명시하지만, `src/arena/parameters.py:23`의
  `PARAMS_VERSION` 상수는 여전히 `"arena-params-v29"`. 이전 모든 버전업(v14→v29, 9회)은
  전부 이 상수도 함께 bump했는데 이번만 빠짐. EC2 배포본도 동일(`ssh ... grep PARAMS_VERSION`
  확인, 로컬과 일치 — 배포 지연이 아니라 소스 자체 버그).
- **영향**: 2026-07-11 이후 체결되는 모든 거래가 실제로는 v30 파라미터(fng target ATR 2.0,
  time_stop 72→60h, min_hold 48→36h)로 실행되면서도 DB에는 `params_version="arena-params-v29"`로
  찍힘. `/arena-status` 섹션2·분석 플레이북 §7("params_version별 성과 — 변경 전후 분리")이
  이 필드에 의존하므로, v29와 v30 거래가 섞여 전후 비교가 영구히 오염된다. R4(fng 재튜닝)의
  라이브 검증(§1 대기 항목 "P-B vix_rsi 재평가"·유사 항목)이 근본적으로 불가능해짐.
- **조치**: `PARAMS_VERSION = "arena-params-v30"`으로 즉시 수정 + EC2 재배포. 이미 v30 파라미터로
  체결된 기존 v29-라벨 거래는 `open_time >= 2026-07-11`(커밋 시각) 기준으로 수동 재라벨링 검토.
- **재발 방지**: 파라미터 커밋 시 `PARAMS_VERSION` 변경을 diff에 강제하는 pre-commit 훅 또는
  CI 체크 고려(커밋 메시지에 `arena-params-v\d+`가 있는데 parameters.py의 상수값과 다르면 실패).

### 2. `arena_status.py --fresh-backtest` 기본 parquet이 2.5개월 stale
- **증거**: `--parquet` 기본값이 `data/sentiment_join/sentiment_join_master_20260502.parquet`
  (2026-05-03 생성). 그런데 `data/sentiment_join/master_20260710.parquet`(2026-07-10 생성,
  R1 항목에서 이미 확보된 최신본)이 같은 디렉터리에 존재. 기본 인자가 최신 파일을 안 가리킴.
- **검증 실험**: 두 parquet으로 각각 fresh 백테스트 후 최근 30일 구간만 비교.
  | 알고 | stale(0502) LAST30D | fresh(0710) LAST30D |
  |---|---|---|
  | fng_contrarian | n=0 | n=9 win=56% +0.09% |
  | vix_rsi | n=0 | n=2 win=100% +1.02% |
  | omnibus | n=9 win=78% +0.05% | n=7 win=86% +1.45% |

  stale parquet에서는 fng_contrarian·vix_rsi가 최근 30일 구간에 **백테스트 신호가 아예 0건**
  나온다(라이브는 각각 7건·5건 진입) — macro가 5월 값으로 forward-fill되어 지금 시장과
  다른 전략을 검증하고 있었기 때문. fresh parquet은 라이브와 훨씬 가까운 진입 빈도를 보임.
  즉 지금까지 이 스크립트로 본 "라이브 vs 백테스트 괴리" 진단은 상당 부분 **parquet stale로
  인한 가짜 신호**였을 가능성이 크다.
- **조치**: `--parquet` 기본값을 디렉터리에서 `master_*.parquet` 중 최신 파일을 자동 선택하도록
  변경(또는 최소한 기본값을 `master_20260710.parquet`으로 갱신 + CLAUDE.md의 "최신 parquet"
  표도 동기화). 근본 해결은 R1처럼 parquet을 주기적으로(주 1회) 갱신하는 자동화(§3 참고).

---

## P1 — 데이터 수집 인프라 (트레이딩 로직에 즉시 영향은 없지만 로드맵 핵심 전제가 깨짐)

### 3. WI-9 청산 스트림(`arena_liquidation_bars`)이 59시간째 0건 — 조용히 죽어있음
- **증거**:
  - `SELECT count(*) FROM arena_liquidation_bars` → **0**. 서비스는 2026-07-11 04:05:34 UTC부터
    무중단 가동 중(59h+, 재시작 0회) — 4h 버킷 경계를 14회 이상 지났어야 정상.
  - journalctl: `Liquidation WebSocket connected` 로그는 있지만(마지막 04:05:35),
    `Liquidation bar flushed` 로그는 **전체 기간 0건**.
  - EC2에서 직접 `wss://fstream.binance.com/ws/btcusdt@aggTrade` 연결 테스트 →
    20초 타임아웃 내내 응답 없이 행(`timeout 20` exit 124, TCP 핸드셰이크 자체가 안 끝남).
  - 로컬 샌드박스에서도 같은 엔드포인트(단일 심볼 forceOrder·전체 심볼 `!forceOrder@arr`
    둘 다) 60초간 메시지 0건. 반면 같은 환경에서 `stream.binance.com`(현물) kline은
    즉시 정상 수신됨 — **fstream(선물 데이터) 엔드포인트만 응답이 없음**.
- **원인 추정**: `fstream.binance.com`이 특정 리전(서울 EC2 IP 등)에서 지역 차단되어 있을
  가능성이 높음(Binance가 국가별로 선물 상품 접근을 제한하는 경우가 있음). 확정은 아니고
  네트워크 레벨 조사가 더 필요하지만, "connected 로그 = 정상 가동"이라는 기존 가정이 틀렸다는
  것은 확실하다(핸드셰이크 성공과 데이터 수신은 별개).
- **영향**: WI-9 전체 전제("30일+ 축적 후 fng·omnibus 역발산 지표 연결")가 시작도 못 하고
  있음. `docs/arena/CLAUDE.md`에는 "⏸️ 수집 전용, 정상 배선"으로 적혀 있어 실제 상태와 문서가
  괴리됨.
- **조치**:
  1. 지속성 재확인 — 다른 소스(예: 로컬 VPN/타 리전 인스턴스)에서 같은 fstream 엔드포인트
     접근 테스트해 "일시적 장애 vs 구조적 지역 차단"을 구분.
  2. 구조적 차단이면 대안: CoinGlass/Coinalyze 같은 REST 기반 청산 집계 API로 교체하거나,
     WI-9를 로드맵에서 보류 처리(현재는 로드맵 §1에 남아있어 "언젠가 30일 찬다"고 오해 유발).
  3. **모니터링 추가**: `flush 이벤트 없이 N시간 경과` 같은 존재 확인 알림 추가 — "connected"
     로그만으로는 데이터가 실제로 쌓이는지 알 수 없다는 게 이번에 드러난 맹점.

### 4. `arena_macro_snapshots` stale_hours=36h — 구조상 정상이지만 임계값(48h) 여유 적음
- 최신 macro 행(`fetched_at=2026-07-13T12:05`)의 `stale_hours=36.08`. 아키텍처상 R2
  latest.json이 하루 1회(KST ~08:49)만 갱신되므로 일간 지연은 정상이지만, 48h 비활성 임계값과
  36h 사이 여유가 12h뿐 — R2 갱신이 하루만 밀려도(공휴일·파이프라인 실패 등) macro 게이트가
  꺼져버릴 수 있다. 우선순위는 낮지만 "R2 파이프라인 실패 시 알림"이 없다면 §3에 추가 검토.

---

## P2 — 매매 방식 (청산/게이트 튜닝 후보, 표본 작음 — A/B 검증 게이트 필수)

### 5. MFE 포착률이 fng_contrarian·vix_rsi·multi_factor 전부 음수
| 알고 | n | 평균MFE% | 포착률% | 해석 |
|---|---|---|---|---|
| fng_contrarian | 7 | +2.35 | -38 | omnibus처럼 target_exit 있음(P-A, v30) — 그런데도 음수. 물타기 트랜치 재검토(R4b) 우선 |
| vix_rsi | 5 | +0.72 | -34 | target_exit 메커니즘 없음. flat_signal/trailing_stop만 존재 |
| multi_factor | 6 | +0.60 | -92 | target_exit 메커니즘 없음. 표본 최소(n=6)라 방향 참고만 |
| omnibus | 4 | +1.41 | +4 | v28 target_exit 있음에도 낮음 — n=4라 노이즈 가능성 큼 |

- vix_rsi·multi_factor는 omnibus(WI-7)·fng_contrarian(P-A)처럼 "목표가 도달 시 선청산" 메커니즘이
  없는 유일한 두 알고. 다만 표본이 5~6건뿐이라 지금 바로 파라미터를 바꾸기보다, **R4b(fng 물타기
  제거 검증)가 끝난 뒤 같은 walk-forward 틀로 vix_rsi/multi_factor target-exit A/B**를 잡는 게
  순서상 맞다(§ 기존 로드맵 R3 SJM 다음 후보로 추가).
- **2026-07-14 범위 결정**: 코드로 옮기지 않았다. omnibus WI-7 target_exit 구현은 algorithms.py
  (목표가 산식) + backtest.py + stream.py + scheduler.py 4개 파일에 걸친 전용 배선이었고
  (커밋 `9cad4d0`), 그 자체가 하나의 설계 사이클(MFE 진단 근거 → 산식 선택 → walk-forward
  검증)을 거쳤다. vix_rsi·multi_factor에 동일 수준으로 확장하려면 같은 사이클이 필요한데
  표본 5~6건으로는 산식 선택 근거가 부족하다. "나머지 개선사항 전부 적용" 지시를 받았지만,
  검증 없이 라이브 청산 로직에 새 분기를 얹는 건 이 프로젝트 자체의 게이트 규칙(§ 개선 후보
  확정 절차)과 충돌해 보류 — 표본이 쌓이는 대로(§1 대기 항목 patterns) 별도 세션에서 진행.

### 6. gate_block_rates dead-weight 후보 — ~~2026-07-14 철회~~ (근거 불충분/이미 기각됨 확인)
> **2026-07-14 정정**: 아래 원안은 near-miss 통계만 보고 작성한 것으로, 실제로는 적용 대상이
> 아니다. "나머지 개선사항 전부 적용" 지시를 받고 실행하려는 과정에서 사전 문서를 재확인해
> 발견함 — 원안을 그대로 실행하지 않고 여기 남겨 왜 기각했는지 기록한다.
>
> - `regime_trend.adx_trending`·`macd_momentum.rsi_below_long_max`/`macd_hist_positive`:
>   **이미 2026-07-11 실거래 A/B로 전부 기각된 아이디어**였다
>   ([regime-macd-diagnosis](regime-macd-diagnosis-20260711.md) §1d·§3 M-1). near-miss의
>   "이후 6봉 수익"은 청산 로직이 없는 선행수익이라 실제 트레일링스톱·flat 청산을 거치면
>   전부 악화로 뒤집힌다는 게 그 문서의 핵심 결론이고, "게이트 완화 튜닝 금지"가 명시적으로
>   박제돼 있다. 내가 이번에 gate_block_rates만 재실행하고 이 선행 결론을 확인하지 않은 채
>   "dead-weight 후보"라고 적은 것 자체가 실수였다 — SKILL.md의 "near-miss 단독으로 게이트
>   완화 결정 금지" 규칙을 스스로 어긴 셈.
> - `omnibus.regime_not_risk_off`: near-miss 258건으로 표본은 가장 크지만, 코드를 다시
>   보면 이건 "제거 가능한 필터"가 아니라 `omnibus()`의 5중 레짐 상태머신(UP_TREND/RANGE/
>   DOWN_TREND/RISK_OFF/TRANSITION)에서 RISK_OFF·TRANSITION이 애초에 어떤 서브전략에도
>   매핑되지 않는다는 것뿐이다(`src/arena/algorithms.py:657` `if omni_regime in (RISK_OFF,
>   TRANSITION): return None`). "완화"하려면 RISK_OFF용 신규 서브전략을 설계해야 하는데,
>   이는 근본적으로 새 전략을 만드는 일이라 근거(near-miss 6봉 선행수익)가 위 사례와 동일한
>   함정을 가진 채로 훨씬 큰 리스크를 정당화하기엔 부족하다.
> - **결론**: 세 조건 모두 지금 코드 변경 없이 보류. 실제로 재검토할 가치가 있다면
>   regime-macd-diagnosis M-3(SJM 레짐, 2026-08-10 판단 예정)이 선행 조건 — 레짐 분류기
>   자체가 개선되면 이 조건들의 근거 데이터가 다시 계산되므로 그때 재평가.

(원안 텍스트는 삭제 — 위 정정 참고)

---

## P3 — 비중(사이징) — 이번 점검에서는 새 결함 발견 없음

`combined_position_weight()`(변동성타깃∧리스크타깃, 0.25~0.7 클램프)·독립 자본 캡(portfolio-risk-v2)
구조를 코드 레벨로 재확인했으나 이상 없음. 현재 열린 포지션(fng_contrarian, weight=0.40)도 범위 내.
비중 관련 다음 액션은 기존 로드맵의 R2(EWMA 변동성 추정, 이미 A/B 완료·off 확정)로 충분 — 재작업
불필요. 우선순위 낮음.

---

## P4 — 프로세스·문서 (공수 소, 누적 이득)

### 7. `CLAUDE.md`의 "최신 parquet" 표가 stale
- `data/sentiment_join/sentiment_join_master_20260502.parquet`을 가리키지만 실제 최신은
  `data/sentiment_join/master_20260710.parquet`(2개월 더 최신, R1에서 이미 확보됨). 표 갱신 필요.

### 8. `remaining-improvements-20260710.md`의 "✅ 완료" 표기와 코드 상태 불일치
- R4가 "✅ 완료(적용·배포)"로 마킹되어 있지만 실제로는 `PARAMS_VERSION`이 안 올라가 배포 확인이
  불가능했던 상태(P0-1). "완료" 마킹 전에 `PARAMS_VERSION` diff를 확인하는 체크리스트 항목 추가 제안.

### 9. §3 "모니터링 루틴화"(주 1회 `/arena-status` 자동 실행) — 여전히 미착수
- 기존 로드맵에 이미 있는 항목이지만, 이번에 P0-1·P1-3처럼 "겉보기엔 정상(로그상 connected,
  버전 라벨 그럴듯)인데 실제로는 죽어있는" 결함이 발견된 걸 보면 **로그 기반 확인이 아니라
  실제 산출물(row count, 버전 라벨 diff) 기반 헬스체크**가 필요하다는 게 이번 점검의 교훈.
  루틴화 시 단순 요약 출력보다 "이상 감지 시에만 알림" 형태(row count 0, params_version
  커밋과 불일치 등)를 함께 넣는 걸 권장.

---

## 적용 현황 (2026-07-14 세션 종료 시점)

| 항목 | 상태 | 비고 |
|---|---|---|
| P0-1 PARAMS_VERSION 수정 | ✅ 적용·EC2 배포 | v29→v30, 테스트 갱신 |
| P0-2 fresh-backtest parquet 자동 최신화 | ✅ 적용 | `master_*.parquet` 중 최신 mtime 자동 선택 |
| P1-3 WI-9 근본 원인 확정 | ✅ 진단 완료 | fstream이 핸드셰이크는 성공·데이터 프레임 0건(aggTrade로 재현) — 구조적 네트워크 문제 확정, 지역차단이 유력 |
| P1-3 WI-9 관측성 개선 | ✅ 적용·EC2 배포 | `liquidation_stream.py`에 30분 무음 idle 경고 로깅 추가 — "connected"만으론 안 잡히던 무음 상태를 로그로 노출 |
| P1-3 WI-9 근본 수정(대안 데이터소스) | ⏸️ 미적용 | REST 서드파티(CoinGlass 등) 교체는 제공자·비용 결정 필요 — 사용자 확인 후 진행 |
| P2-6 게이트 dead-weight 3건 | ❌ 철회 | 재조사 결과 이미 실거래 A/B로 기각됐거나(regime_trend/macd) 아키텍처상 단순 토글이 아님(omnibus) — 코드 변경 없음 |
| P2-5 vix_rsi/multi_factor target-exit | ⏸️ 미적용(설계 보류) | 표본 부족 + 검증 없이 라이브 청산 로직 확장은 리스크 — 별도 세션 필요 |
| P1-4 macro stale_hours 여유 | ⏸️ 관찰만 | 코드 변경 불필요, 계속 모니터링 |
| P4-7 CLAUDE.md parquet 표 | ✅ 적용 | 최신 parquet 위치 각주 추가 |
| P4-8 remaining-improvements 완료 마킹 정정 | ✅ 적용 | R4·WI-9 상태 갱신 |
| P4-9 모니터링 루틴화 | ⏸️ 미적용 | 주기 실행은 스케줄 설정(비용·알림 수신 방식) 결정이 필요해 별도 확인 후 진행 권장 |

**핵심 교훈**: 이번 세션에서 P2-6을 스스로 정정한 것 자체가 유의미한 결과다 — near-miss
통계만으로 "적용"을 서두르면 이미 검증·기각된 아이디어를 되풀이하게 된다는 것을 실증했다.
앞으로 gate_block_rates 결과를 개선 후보로 올릴 때는 반드시 관련 diagnosis 문서를 먼저
확인할 것.
