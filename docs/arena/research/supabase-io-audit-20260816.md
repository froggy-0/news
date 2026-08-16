# Supabase Disk I/O 감사 — 현황 분석 (2026-08-16)

Disk I/O 알람 대응. MCP(`execute_sql`/`query_logs`/`get_advisors`)로 실측한 현황과
"정말 다 필요한 연산인가"에 대한 판정.

**결론 요약**: 정상상태 부하는 인스턴스 스펙 대비 가볍다(읽기 캐시적중 99.6%, WAL 22MB/일).
알람의 원인은 스펙 부족이 아니라 **(a) 값이 안 바뀐 행을 매 사이클 재기록하는 구조**와
**(b) 실거래에 안 쓰이는 shadow 텔레메트리가 WAL의 45%를 차지**하는 것,
그리고 **(c) 앱과 무관한 PostgREST 스키마캐시 리로드가 DB 최대 CPU 소비자**인 것이다.

---

## 0. 측정 창과 신뢰도

| 카운터 | 리셋 시점 | 창 길이 |
|---|---|---|
| `pg_stat_statements` | 2026-03-27 20:47 (프로젝트 생성) | 142일 |
| `pg_stat_database` / `pg_stat_wal` / `pg_stat_checkpointer` | 2026-02-12 23:51 | 185일 |

⚠️ **`pg_stat_database.temp_bytes = 135 GB`는 현재 워크로드의 증거가 아니다.**
같은 창에서 `pg_stat_statements`가 집계한 temp는 **1,956 MB**뿐이고,
`dealloc=0` · `entries 2,149 / max 5,000`이라 **pgss는 3-27 이후 단 한 건도 축출하지 않았다**
(즉 3-27 이후 전체 temp = 1,956 MB로 확정). 135 GB는 프로젝트 생성(3-27) 이전,
복원 이전 인스턴스 이력이 카운터에 남은 것. **이 숫자를 쫓지 말 것.**

인스턴스: `shared_buffers` 224 MB · `effective_cache_size` 384 MB · `max_connections` 60
→ **Micro(1 GB RAM)** 급. DB 크기 209 MB.

---

## 1. 문제가 아닌 것 (먼저 제외)

이쪽을 더 만지는 건 낭비다.

| 항목 | 실측 | 판정 |
|---|---|---|
| 읽기 I/O | 캐시적중 **99.60%**, `blks_read` 822K / 185일 = 45 MB/일 | DB(209MB)가 shared_buffers(224MB)에 거의 통째로 들어감. 논이슈 |
| 복제 슬롯 WAL 보존 | `pg_replication_slots` **0건** | Realtime이 WAL을 잡고 있지 않음. 논이슈 |
| 데드락 | 0 | 논이슈 |
| DB 용량 | 209 MB (8-07 정리 후 유지) | free tier 500MB 대비 여유. 논이슈 |
| `arena_run_ohlcv_bars` | 8-15 마이그레이션이 TRUNCATE, `src/`에 writer 없음 | **이미 해소됨**(과거 182MB WAL 생산했으나 현재 0). 인덱스 4개만 잔존(32KB, 무해) |
| 체크포인트 | 287회/일 = `checkpoint_timeout` 300s 그대로 | 설정상 최대치지만 Supabase 기본값, 변경 권한 없음 |

---

## 2. 핵심 발견

### A. 안 바뀐 행을 매 사이클 재기록 — 최대 구조적 낭비

`data_lake.record_market_structure_snapshot()`이 Binance에서 받은 **300봉 윈도우 전체**를
매 사이클 upsert한다(`parameters.BINANCE_KLINES_LIMIT = 300`).
실제로 새로 생기는 봉은 사이클당 1~2개뿐인데 나머지 ~298개는 **바이트 단위로 동일한 값을 다시 쓴다.**

Postgres의 `ON CONFLICT DO UPDATE`는 값이 같아도 무조건 새 튜플 버전을 만든다
→ 매번 heap 새 버전 + 인덱스 엔트리 + WAL 레코드 + dead tuple + autovacuum.

| 테이블 | 유지 행수 | 누적 UPDATE | **행당 재기록 횟수** | autovacuum 횟수 | 크기 |
|---|---:|---:|---:|---:|---:|
| `arena_mark_price_bars` | 2,866 | 412,334 | **144회** | 473 | 1.8 MB |
| `arena_basis_snapshots` | 1,433 | 177,667 | **124회** | 447 | 1.2 MB |
| `arena_open_interest_snapshots` | 1,085 | 126,737 | **117회** | 459 | 584 kB |
| `arena_funding_rates` | 539 | 62,101 | **115회** | 340 | 320 kB |
| `arena_feature_registry` | 88 | 9,794 | **111회** | 1 | 120 kB |
| `btc_futures_daily` | 1,710 | 52,769 | 31회 | 21 | 384 kB |
| `arena_ohlcv_bars` | 41,587 | 184,483 | 4회 | 40 | 24 MB |

합계 **약 7,150 행-업데이트/일**이 사실상 전부 동일값 재기록이다.
1.8 MB짜리 테이블 하나에 autovacuum이 473번 돈 것이 그 증거.

**I/O로 이어지는 경로**: 흩어진 페이지를 계속 더럽힘 → 5분마다 오는 체크포인트 직후
각 페이지 첫 수정마다 full-page image 발생 → **`wal_fpi` 776,850건(5,470건/일)**.
FPI 원본은 8KB×776,850 ≈ 6.2 GB로 압축 후 총 WAL(3.9GB)보다 크다
= **WAL의 대부분이 "안 바뀐 데이터의 전체 페이지 이미지"**.

### B. `policy_snapshot` — 20,271행 전부 동일한 값

```
distinct_policy = 1   (전체 20,271행, 행당 492 bytes)
```

`arena_realtime_risk_states.policy_snapshot`은 정적 정책 설정이라 **모든 행이 완전히 같다.**
그걸 분당 1회, 하루 1,440번 다시 저장 중(≈ 700 kB/일 WAL + 스토리지).

### C. `risk_events`에 `risk_snapshot` 중복이 남아있음 — 2026-07-31 최적화 누락분

`data_lake.record_realtime_risk_state()`에는 이런 주석이 이미 있다:

> risk_snapshot(= decision.as_dict() 전체)은 저장하지 않는다 — 아래 별도 컬럼들과 완전히 중복이었음

그런데 **바로 아래 `record_realtime_risk_event()`는 `"risk_snapshot": decision.as_dict()`를 그대로 쓴다.**
같은 판정을 `risk_state`/`risk_score`/`trigger_reasons`/`recommended_action` 컬럼으로도
따로 저장하면서 전체 dict를 또 넣는 것. 실측:

| | heap | TOAST | 비율 |
|---|---:|---:|---:|
| `arena_realtime_risk_events` | 2,120 kB | **27 MB** | 스냅샷이 테이블의 **93%** |

행당 `risk_snapshot` 평균 2,223 bytes. **risk_states에 적용한 수정이 risk_events에는 안 들어간 것.**

### D. shadow 전용 텔레메트리가 WAL의 45%

3개 테이블 모두 분당 1회(1,440행/일) 기록되고, CLAUDE.md 기준
`ENABLE_ARENA_REALTIME_RISK_LIVE=False`라 **실거래 게이팅에 쓰이지 않는다.**

| 테이블 | 누적 WAL | 전체 대비 | 행 크기 | 일 기록 | 1행 INSERT당 버퍼 접근 |
|---|---:|---:|---:|---:|---:|
| `arena_realtime_risk_states` | 750 MB | 24.0% | 2,708 B | 1,440 | 64 |
| `arena_realtime_risk_events` | 483 MB | 15.4% | (스냅샷 2,223 B) | ~600 | **142** |
| `arena_realtime_feature_bars` | 164 MB | 5.2% | 344 B | 1,440 | 27 |
| **합계** | **1,397 MB** | **44.6%** | | | |

`risk_events`의 1행 INSERT에 버퍼 142개를 만지는 건 TOAST 쓰기 + 인덱스 3개 + FK 체크 탓
(비교: 인덱스 1개·TOAST 없는 `feature_bars`는 27).
C를 고치면 이 수치가 같이 내려간다.

`arena_realtime_risk_states`는 74 MB로 **DB 전체(209MB)의 35%**를 차지 — 꺼져 있는 기능의 로그다.

### E. PostgREST 스키마캐시 리로드가 DB 최대 CPU 소비자

로그 실측(24시간): 스키마캐시 리로드 **33회**, 커넥션풀 재초기화 16회.

리로드 1회마다 도는 인트로스펙션 쿼리들의 누적 비용:

| 쿼리 | 호출 | 누적 시간 | temp |
|---|---:|---:|---:|
| `SELECT name FROM pg_timezone_names` | 2,396 | **1,053.9 s** | — |
| 타입/도메인 인트로스펙션 ×2 | 4,792 | 287.5 s | — |
| pk/fk 인트로스펙션 | 2,396 | 105.6 s | — |
| 함수 시그니처 인트로스펙션 | 204 | 54.7 s | **1,814 MB** |
| **합계** | | **≈1,502 s** | **1,814 MB** |

- `pg_timezone_names`(440ms/회)는 **앱 쿼리를 전부 제치고 DB 단일 최대 CPU 소비 쿼리**다.
  로그의 `Schema cache loaded ... 1196 Timezones`가 같은 동작임을 확인해준다.
- **전체 temp 1,956 MB 중 1,814 MB(92.7%)가 이 인트로스펙션 스필**이다.
  즉 temp 파일 I/O는 앱이 아니라 Studio/MCP/마이그레이션 쪽에서 나온다.
  (평균 temp 파일 1.83 MB ≈ `work_mem` 2,184 kB 바로 위 — 정렬이 아슬아슬하게 넘쳐 흐르는 전형)

### F. 인덱스 미스매치

`arena_decisions`에 인덱스가 6개 있는데 **`created_at` 단독 인덱스만 없다**.
그런데 실제 쿼리는 `ORDER BY created_at DESC LIMIT n`이라 매번 seq scan + top-N 정렬:

```
seq_scan 14,897회 · seq_tup_read 12,233,262행   (테이블은 3,700행)
→ 누적 659.7 s, 호출당 버퍼 187개
```

호출자는 `roster_diagnostics.summarize_live_decisions()`(14,356회, 대부분 과거 누적)와
현행 대시보드 `arena/index.html:1650`의 조인 변형(335회, 67.2 s, 200ms/회).
현행 대시보드도 같은 정렬을 쓰므로 인덱스 하나로 둘 다 해결된다.

미사용 인덱스(어드바이저): `idx_arena_decisions_resulting_position_id`,
`idx_arena_realtime_risk_events_position_id`, `idx_arena_risk_events_{position_id,run_id}`,
`idx_arena_indicator_feature_bars_run_id`, `idx_arena_child_orders_parent_order_id`,
`idx_arena_execution_quality_parent_order_id`, `idx_arena_executions_{child,parent}_order_id`,
`idx_mail_events_subscriber_id`, `idx_subscription_tokens_subscriber_id` — 12개.

---

## 3. 권고 (효과/리스크 순)

전부 **트레이딩 로직 무관**(수집·기록 계층). 라이브 신호에 영향 없음.

| # | 조치 | 대상 | 예상 효과 | 리스크 |
|---|---|---|---|---|
| **P1** | 변경분만 upsert — 이미 저장된 `max(open_time)` 이후 봉만 기록(계산에는 300봉 유지) | `market_structure` 5개 테이블 | 행-업데이트 7,150/일 → ~40/일. FPI·autovacuum 동반 급감 | 낮음. 백필은 별도 경로 |
| **P2** | `record_realtime_risk_event()`에서 `risk_snapshot` 제거 (risk_states와 동일 조치) | `arena_realtime_risk_events` | TOAST 27MB 소멸, WAL −483MB분, INSERT 버퍼 142→~30 | 낮음. **단 reader 폴백 확인 필요** (risk_states 때 `_latest_realtime_risk_features()`가 폴백 보유했던 것처럼) |
| **P3** | `policy_snapshot` 컬럼 제거 또는 정적 테이블 1행 참조 | `arena_realtime_risk_states` | 492 B/행 × 1,440/일 제거 | 낮음(값이 상수) |
| **P4** | `CREATE INDEX ON arena_decisions (created_at DESC)` | 대시보드·진단 | seq scan 12.2M행/누적 660s 제거 | 없음(쓰기 3,700건뿐인 테이블) |
| **P5** | shadow 텔레메트리 주기 1분 → 5분, 또는 수집 중단 | realtime 3종 | WAL −45%, DB −35% | **판단 필요**: 꺼진 기능의 로그를 계속 쌓을 가치가 있는지 |
| ~~P6~~ | ~~미사용 인덱스 제거~~ | — | — | **철회** — 전부 FK 뒷받침 인덱스(§3-1 참조) |
| **P7** | 스키마캐시 리로드 33회/일의 원인 추적(DDL 이벤트/`NOTIFY pgrst`) | PostgREST | CPU 최대 소비원 감소 | 조사 필요 |

**P1+P2가 전체 효과의 대부분**이고 둘 다 순수 기록 계층 수정이다.
→ **P1~P4는 2026-08-16 같은 날 적용 완료. §3-1에 실측 결과.** 남은 건 P5(사용자 판단)·P7(조사).

---

## 3-1. 실행 결과 (2026-08-16, 같은 날 적용 완료)

P1~P4 적용. **P5(shadow 주기 변경)는 수집 데이터가 달라지므로 제외**(기능 변경),
**P6(미사용 인덱스 제거)는 착수 후 철회** — 11개 전부 FK를 뒷받침하는 인덱스로,
2026-08-07에 "unindexed FK 12개 보강"으로 **의도적으로 추가한 것들**이었다. 제거하면
그 작업을 되돌리고 어드바이저 경고를 재발시키면서, 대상 테이블이 0~7천 행이라 얻는 것이
사실상 없다. 어드바이저의 `unused_index`만 보고 지웠으면 퇴행이었을 건.

### 적용 내역

| # | 변경 | 위치 |
|---|---|---|
| P1 | `_rows_needing_write()` 신설 + 5개 윈도우 업서트에 배선 | `src/arena/data_lake.py`, `parameters.MARKET_WINDOW_HOT_TAIL_BARS=3` |
| P2 | `risk_events.risk_snapshot` 쓰기 중단 + 컬럼 DROP | `data_lake.record_realtime_risk_event()`, 마이그레이션 |
| P3 | `risk_states.policy_snapshot` 쓰기 중단 + 컬럼 DROP | `data_lake.record_realtime_risk_state()`, 마이그레이션 |
| P4 | `idx_arena_decisions_created` 생성 | 마이그레이션 |

마이그레이션: [20260816_arena_disk_io_dedupe.sql](../../../supabase/migrations/20260816_arena_disk_io_dedupe.sql)

### 실측 효과

**사이클당 행-업데이트** (재배포 후 restart 사이클 전후 `n_tup_upd` 델타 실측):

| 테이블 | 이전 | 이후 | 감소 |
|---|---:|---:|---:|
| `arena_mark_price_bars` | ~1,800 | **36** | 98.0% |
| `arena_basis_snapshots` | ~1,800 | **18**\* | 99.0% |
| `arena_open_interest_snapshots` | ~1,800 | **18** | 99.0% |
| `arena_funding_rates` | ~1,800 | **18** | 99.0% |
| `arena_ohlcv_bars` | ~1,800 | **18** | 99.0% |
| **합계** | **~9,000** | **~108** | **98.8%** |

\* 측정 사이클에 basis fetch가 Binance 418(연속 재시작에 따른 일시적 rate limit)로 2트랙
실패해 12건. 정상 시 18건.

이론값과 정확히 일치한다: 6트랙 × 3(hot tail) = 18, mark_price_bars는 price_type 2종이라 36.

**용량**: DB 209 MB → **156 MB** (−25%)
- `arena_realtime_risk_events` 30 MB → **2,096 kB** (TOAST 27 MB → 8 kB)
- `arena_realtime_risk_states` 74 MB → **49 MB**

**쿼리 플랜**: `arena_decisions ORDER BY created_at DESC LIMIT 200`
- 이전: Seq Scan + Top-N Sort, 호출당 버퍼 ~187
- 이후: `Index Scan using idx_arena_decisions_created`, 버퍼 115, Sort 노드 없음

### 배포 중 발견·수정한 자체 버그 (실측이 아니었으면 놓쳤을 것)

1차 배포 후 측정하니 4개 테이블은 18건으로 떨어졌는데 **`arena_mark_price_bars`만
1,633건으로 거의 안 줄었다.** 원인: 이 테이블은 3심볼 × 2 price_type이 한 테이블에 살아서
시각 범위만으로 조회하면 배치(300행)의 6배가 딸려오는데, 내가 건 `limit = len(rows)*4+100`
= 1,300에 **잘려서** 기존 키 ~500개를 못 찾고 "신규"로 판정해 재기록하고 있었다.
- 수정: 배치 내 값이 하나뿐인 키 컬럼(exchange/symbol/interval/price_type)을 `eq` 필터로
  내려 조회를 정확히 스코프 + 결과가 limit에 닿으면 잘림으로 보고 전량 업서트 폴백.
- 회귀 테스트 2건 추가(`..._scopes_query_to_single_valued_key_columns`,
  `..._falls_back_when_existing_key_fetch_truncated`).

"적용했으니 됐다"로 끝냈으면 이 테이블만 그대로 낭비 중이었을 것.

### 안전성 근거

- **값을 비교하지 않는다** — 키 존재 + 최신 N봉만 본다. float/JSONB 왕복 정밀도 이슈 원천 배제.
- 전제 "마감된 과거 봉은 불변"은 대상 4개 바이낸스 엔드포인트 모두 참.
- DB에 키가 없으면 과거 봉이라도 무조건 쓴다 → 과거 구멍 메우기·백필 정상 동작.
- 조회 실패/잘림 시 전량 업서트로 폴백(기존 동작).
- `arena_runs.input_*` 갱신은 필터 **이전** 전체 행으로 계산(판정에 투입된 윈도우 범위 기록).
- 제거한 두 컬럼은 저장소 전수 grep으로 reader 부재 확인.
- 롤백: `MARKET_WINDOW_HOT_TAIL_BARS`를 음수로(필터 비활성). 컬럼은 재추가 불필요(쓰기 중단 상태).

### 부작용 (허용)

- 건너뛴 행의 `fetched_at`이 갱신되지 않는다 → 의미가 "마지막 조회 시각"에서 "값이 마지막으로
  변한 시각"으로 바뀐다. 이 컬럼을 읽는 코드는 저장소 전체에 없다(2026-08-16 확인).
- 테이블당 사이클마다 SELECT 1회가 추가된다. 캐시에서 키 컬럼 수백 행을 읽는 비용
  (WAL 0)과 300행 재기록(heap+인덱스+WAL+FPI+autovacuum)을 맞바꾼 것이라 명확히 이득.

### 검증

- arena 테스트 **323개 통과**(신규 8건 포함). 리포 전체는 기존 사전 실패 2건
  (`test_sentiment_join/test_config.py`, R2 환경변수 건)만 남고 통과.
- EC2 배포·재시작 후 3분 관찰: 에러 0(Binance 418은 연속 재시작 탓, 코드 무관·자동 복구),
  risk_states/risk_events/feature_bars/decisions 전부 정상 기록 확인.

---

## 4. 재현

```sql
-- 재기록 비율
select relname, n_live_tup, n_tup_upd,
       round(n_tup_upd::numeric/nullif(n_live_tup,0),0) as rewrites_per_row, autovacuum_count
from pg_stat_user_tables where n_tup_upd > 5000 and n_live_tup < 50000 order by n_tup_upd desc;

-- WAL/temp 상위
select calls, round(total_exec_time::numeric/1000,1) total_s,
       pg_size_pretty(wal_bytes::bigint) wal, temp_blks_written,
       left(regexp_replace(query,'\s+',' ','g'),120) q
from pg_stat_statements order by wal_bytes desc limit 15;

-- 중복 컬럼 탐지
select count(*), count(distinct md5(policy_snapshot::text)) from arena_realtime_risk_states;
```

## 5. 미확인 / 남은 것

- 스키마캐시 리로드 33회/일의 트리거를 특정하지 못함(마이그레이션 수보다 많음).
- `work_mem` 2,184 kB는 Micro 스펙상 올리기 어렵고, 스필의 92.7%가 앱 밖(Studio)이라 우선순위 낮음.
- `btc_etf_reference`/`btc_etf_silver` PK 없음(어드바이저 INFO) — 모닝브리프 소관, 비즈니스 키 미확인. 이번 범위 밖.
