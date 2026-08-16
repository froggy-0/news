# Supabase DB 운영 가이드

이 프로젝트(BTC 감정분석 morning-brief + Paper Trading Arena)가 쓰는 Supabase Postgres
프로젝트(`etscgpquupksucbyrvhh`, ap-northeast-2, Postgres 17.6)의 접속·스키마·최적화 이력
문서. **`schema.sql`이나 `migrations/*.sql`을 읽고 "현재 스키마"를 파악하지 말 것** — 이
파일들은 로컬 참고용일 뿐 실시간으로 실제 DB와 동기화되지 않는다(이유는 [스키마 확인
방법](#스키마-현황--정적-파일-대신-mcp로-확인) 참조). 이 README가 "지금 DB가 어떤 상태이고
어떻게 다뤄야 하는가"의 1차 출처다.

이 문서는 1인 운영·46개 테이블·DB 156MB 규모에 맞춰 쓴다. 엔터프라이즈급 데이터 스택
(Kafka/Spark/Airflow류)은 이 규모에 안 맞고, 아래 최적화 이력 전부가 "과잉설계하지 말 것"을
반복 확인한 결과다 — 이 문서도 같은 원칙을 따른다.

---

## 접속 방법

**이 프로젝트엔 psql/raw Postgres 커넥션이 없다.** 코드베이스 전체(`src/arena/positions.py`
포함)가 `supabase-py`의 `AsyncClient`(PostgREST REST API)만 쓴다. `asyncpg`/`psycopg`/
`DATABASE_URL` 사용처 0건(2026-08-16 전수 grep 확인). 따라서 스키마 조사·최적화 작업은
**Supabase MCP 도구**로 한다.

| 도구 | 용도 |
|---|---|
| `execute_sql` | 읽기 전용 조사(`pg_stat_*`, `information_schema`, 임시 트랜잭션 검증). DDL엔 쓰지 말 것 |
| `apply_migration` | 실제 스키마 변경(DDL) — **이게 이 프로젝트의 유일한 배포 경로**(CI/CD 없음, 아래 참조) |
| `get_advisors` | 보안/성능 린트. 마이그레이션 직후 습관적으로 재확인 |
| `list_tables` | 테이블 목록(verbose=true로 컬럼/PK/FK까지) — 큰 프로젝트라 출력이 잘릴 수 있음, `execute_sql`로 필요한 컬럼만 뽑는 게 나음 |
| `query_logs` | ClickHouse 기반 로그 조회(postgres_logs/postgrest_logs/realtime_logs 등), 최대 24시간 창 |
| `list_extensions` | 설치 가능/설치됨 익스텐션 |

모든 호출에 `project_id: etscgpquupksucbyrvhh`가 필요하다.

---

## 스키마 현황 — 정적 파일 대신 MCP로 확인

`supabase/schema.sql`은 **2026-05-05 기준 스냅샷이고 이미 폐기했다**(2026-08-16) — 테이블
20개만 기록돼 있었는데 실제는 46개였고, `arena_asset_news`/`arena_liquidation_bars` 같은
이후 추가분이 통째로 빠져 있었다. 손으로 관리하는 스키마 파일은 이 프로젝트 변경 속도에서
구조적으로 못 따라간다 — 그래서 정적 파일을 유지하는 대신 **필요할 때 MCP로 직접 조회**하는
쪽을 택했다.

### 전체 테이블 최신 목록

```sql
select relname, pg_size_pretty(pg_total_relation_size(relid)) as size,
  n_live_tup as rows
from pg_stat_user_tables order by pg_total_relation_size(relid) desc;
```

### 카테고리별 지도 (2026-08-16 기준 스냅샷 — 정확한 최신값은 위 쿼리로)

| 카테고리 | 대표 테이블 | 성격 |
|---|---|---|
| `arena_trading_core` | `paper_positions`, `arena_decisions`, `arena_runs` | 실거래 트랙레코드 본체. anon 대시보드가 읽는 5개 테이블 중 3개 포함 |
| `arena_realtime_telemetry` | `arena_realtime_risk_states`(49MB), `arena_realtime_feature_bars`, `arena_realtime_risk_events` | 1분 주기 shadow 기능 로그(`ENABLE_ARENA_REALTIME_RISK_LIVE=False`, 실거래 미적용). `arena_prune_telemetry()`가 14일 보존 |
| `arena_shadow_execution` | `arena_execution_gates`, `arena_shadow_decisions`, `arena_execution_quality` | 실행품질 섀도우 게이트, 마찬가지로 실거래 미적용 |
| `arena_backtest` | `arena_backtest_trades`(11MB), `arena_backtest_runs` | 리서치 백테스트 산출물 |
| `arena_market_data_research` | `arena_ohlcv_bars`(24MB, 최대 테이블), `arena_mark_price_bars`, `arena_funding_rates` 등 | 바이낸스 원본 시장데이터 캐시 |
| `morning_brief_macro` | `btc_etf_gold/silver/reference`, `btc_futures_daily`, `stablecoin_supply_daily` | morning-brief 파이프라인 소관, arena와 무관 |
| `morning_brief_signal_mail` | `signal_log`, `mail_events`, `subscriptions` | 뉴스레터/신호기록 |
| `view`(21개) | `arena_*_v1`, `arena_*_ready` | 전부 일반 VIEW(matview 아님, 0 bytes). 대부분 142일간 호출 1~4회 — 대개 리서치 스크립트가 어쩌다 쓰는 것들, 대시보드 핫패스 아님 |

### pg_cron 상시 작업

```sql
select jobid, schedule, command, active from cron.job;
```

현재 1개: `arena_prune_telemetry()`, 매일 03:00 UTC — realtime telemetry 14일/
execution_gates 30일 보존.

### 설치된 익스텐션 (5개, plpgsql 제외)

`pg_cron` 1.6.4 · `pg_stat_statements` 1.11 · `pgcrypto` 1.3 · `supabase_vault` 0.3.1 ·
`uuid-ossp` 1.1. 그 외 `pg_partman`처럼 설치 가능하지만 안 깐 것들도 있다(파티셔닝 필요해질 때 후보).

---

## 인덱싱 원칙

- **FK 컬럼엔 인덱스를 건다.** 2026-08-07에 unindexed FK 12개를 일괄 보강한 이력이 있고,
  지금 어드바이저에 뜨는 `unused_index` 11개는 전부 이 FK 인덱스들이다 — 대상 테이블이
  0~7천 행이라 아직 안 쓰였을 뿐 **지우면 안 된다**(FK 조인이 커지면 바로 필요해짐).
- **`ORDER BY <시각컬럼> DESC LIMIT n` 패턴엔 반드시 `(시각컬럼 DESC)` 인덱스.** 없으면
  seq scan + 전체 정렬이 걸린다 — `arena_decisions`가 실제로 이 구멍으로 12.2M행을
  스캔한 전례가 있다([disk-io-audit](../docs/arena/research/supabase-io-audit-20260816.md) §F).
- **btree는 양방향 스캔이 기본이라 `(a,b)` 인덱스가 있으면 `(a, b DESC)`를 따로 만들 필요
  없다.** 2026-08-16에 `arena_realtime_risk_states`에서 PK `(symbol,window_start)`와
  거의 완전히 겹치는 `(symbol,window_start DESC)` 인덱스를 발견·삭제했다 — 옵티마이저도
  거의 안 쓰고 있었다(PK 8만 스캔 vs 이 인덱스 202회). 새 인덱스 만들 때 기존 PK/복합
  인덱스가 이미 커버하는지 먼저 확인할 것.
- 인덱스를 새로 만들거나 지운 뒤엔 `get_advisors(type=performance)`로 재확인.

---

## 캐싱 — 지금은 안 쓴다

HTTP 캐싱(Cache-Control, CDN)이나 애플리케이션 레벨 캐시는 도입하지 않았다. 근거: 대시보드가
읽는 5개 테이블의 anon SELECT 트래픽이 142일 누적으로 최다 쿼리도 하루 평균 2.5회
([full-db-rubric-audit](../docs/arena/research/supabase-full-db-rubric-audit-20260816.md) §3).
캐싱은 "반복 조회를 재계산 없이 서빙"하는 게 목적인데, 반복 조회 자체가 없다.

**재검토 기준**: 대시보드 방문이 늘어 anon SELECT가 **분당 여러 건** 수준으로 올라오면
(예: 소셜 공유로 트래픽 급증) 그때 PostgREST 응답에 `Cache-Control: max-age=N`을 붙이는
걸 고려한다. 지금 하면 복잡도만 늘고 체감 효과가 없다.

---

## 지금까지 적용한 최적화 (근거 문서 링크)

| 날짜 | 무엇을 | 왜 | 문서 |
|---|---|---|---|
| 2026-08-16 | 윈도우 재업서트 필터링(`_rows_needing_write`) + 중복 컬럼 2개 제거 + 인덱스 추가 | 사이클당 행-업데이트 98.8%↓, DB 209→156MB | [supabase-io-audit-20260816.md](../docs/arena/research/supabase-io-audit-20260816.md) |
| 2026-08-16 | anon/authenticated 쓰기권한 REVOKE + DEFAULT PRIVILEGES 수정 + 중복 인덱스 제거 | RLS 단일장애점 해소(2026-08-07 RLS 비활성 사고 재발 방지) | [supabase-full-db-rubric-audit-20260816.md](../docs/arena/research/supabase-full-db-rubric-audit-20260816.md) |
| 2026-08-16 | Matview/Partitioning/Supavisor/RPC 도입 검토 → 전부 보류 | 이 규모에서 과잉설계 방지(근거 실측 포함) | [supabase-feature-adoption-review-20260816.md](../docs/arena/research/supabase-feature-adoption-review-20260816.md) |
| 2026-08-07 | Supabase DB 최적화(476MB→222MB) + 보안 어드바이저 ERROR 2종 해소 | free tier 캡 임박 해소, RLS/SECURITY DEFINER 뷰 정리 | CLAUDE.md 해당 항목 참조 |

---

## 앞으로 조심해야 할 것

1. **새 테이블은 기본적으로 RLS를 켠다(`ENABLE ROW LEVEL SECURITY`).** Supabase 기본
   템플릿이 `anon`/`authenticated`에 모든 public 테이블 쓰기 권한을 자동 부여하므로
   ([REVOKE 이력](../docs/arena/research/supabase-full-db-rubric-audit-20260816.md) §1),
   RLS를 안 켜면 그 순간 공개 anon key로 쓰기가 가능해진다. 대시보드가 읽어야 하는
   테이블만 `CREATE POLICY ... FOR SELECT TO anon USING (true)` 식으로 최소한만 열 것.
2. **매 사이클 같은 윈도우를 통째로 다시 쓰는 패턴을 새로 만들 때** `data_lake.
   _rows_needing_write()` 패턴(값 비교 대신 키 존재+최신 N개만 재기록)을 재사용할지
   먼저 검토할 것 — 이게 1차 감사에서 발견한 낭비의 근본 원인이었다.
3. **`supabase/migrations/*.sql`과 `schema.sql`은 이제 git에 안 올라간다**(`.gitignore`).
   실제 배포는 `apply_migration` MCP 호출이 하고 있어서(아래 4번 참조) 이 파일들은 "로컬
   참고 이력"일 뿐이다. 사람이 실수로 지우면 그 마이그레이션의 SQL 원문은 로컬에만
   있었으므로 복구 불가 — 중요한 스키마 변경을 적용할 땐 로컬에 파일을 남겨두는 습관을
   유지할 것(git에는 안 올려도 디스크에는 보존).
4. **마이그레이션은 CI/CD가 아니라 `apply_migration` MCP 호출로 직접 프로덕션에 적용된다.**
   로컬 `migrations/` 디렉토리 파일 순서·존재 여부가 실제 스키마와 항상 일치한다는 보장이
   없다(사람이 직접 실행하는 방식이라 파일 작성과 적용이 분리될 수 있음). 스키마 상태를
   신뢰할 땐 항상 [MCP로 직접 확인](#스키마-현황--정적-파일-대신-mcp로-확인)할 것, 로컬
   파일 목록을 믿지 말 것.
5. **DEFAULT PRIVILEGES를 주기적으로 재확인.** 신규 마이그레이션이 실수로
   `GRANT ... TO anon`을 다시 걸 수 있으니, 의심되면:
   ```sql
   select grantee, count(distinct table_name)
   from information_schema.role_table_grants
   where table_schema='public' and grantee in ('anon','authenticated')
     and privilege_type in ('INSERT','UPDATE','DELETE','TRUNCATE')
   group by grantee;
   -- 0이 아니면 조사 필요
   ```
6. **마이그레이션 적용 직후엔 `get_advisors`를 양쪽(security/performance) 다 재확인**하는
   걸 습관으로 — 이번 세션 3차례 감사 전부 이 루틴으로 새 문제를 조기에 잡았다.
