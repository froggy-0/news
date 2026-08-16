# Supabase 고급 기능 6종 도입 검토 (2026-08-16, 3차)

사용자가 나열한 6개 기능(Materialized Views, Declarative Partitioning, Supavisor 튜닝,
Postgres Functions/RPC, pg_stat_statements, Advisors)이 이 프로젝트에 적용할 만한지
전부 MCP 실측 + 코드 확인으로 검토. **결론: 6개 중 4개는 이미 최대로 쓰고 있거나 아예
해당 없음, 2개(Materialized Views·Partitioning)는 지금 도입하면 과잉설계.**

---

## 1. Materialized Views — 도입 안 함 (근거: 핫패스에 없음)

`pg_matviews`를 조회하면 **실제 Materialized View는 0개**다. `arena_decision_mart_v1`,
`arena_spot_position_mart_v1` 같은 `_mart_v1`/`_ready` 접미사 21개는 전부 **일반 VIEW**
(relkind='v', 저장 공간 0 bytes — 매 쿼리마다 재계산).

142일 누적 호출량을 재봤다:

| 뷰 | 호출(142일) | 누적 시간 |
|---|---:|---:|
| `arena_spot_position_mart_v1` | 215 | 1.19초 |
| 나머지 20개 뷰 | 각 1~4회 | 거의 0 |

가장 많이 불린 것도 하루 1.5회, 나머지는 142일 통틀어 1~4회 — 리서치 스크립트를 그때그때
실행한 흔적이다(정기 스케줄 아님, `crontab`/GitHub Actions 어디에도 없음 확인).
`arena_spot_position_mart_v1`은 대시보드 코드 주석에 **"BTC 단일자산 시절 뷰, 멀티자산
전환(2026-08-06)으로 대체됨"**이라고 이미 적혀 있어 지금 잡히는 호출은 그 이전 트래픽이
142일 누적창에 남은 잔재다.

**판단**: Materialized View는 "자주 조회되는데 계산이 비싼 쿼리"를 미리 구워두는 도구다.
지금 이 프로젝트엔 그런 쿼리가 없다 — 있는 뷰들은 핫패스가 아니라 어쩌다 한 번 돌리는
분석용이고, 그마저 실행시간이 밀리초 단위다. 매트뷰로 바꾸면 얻는 게 없고 REFRESH 스케줄
관리라는 새 부담만 생긴다. **도입 안 함.**

---

## 2. Declarative Table Partitioning — 도입 안 함 (근거: 이미 보존정책으로 상한선이 있음)

가장 빨리 자라는 테이블들의 순증가율(142일 평균, 삽입-삭제):

| 테이블 | 현재 행수 | 순증가/일 | 비고 |
|---|---:|---:|---|
| `arena_realtime_risk_states` | 20,341 | 143.2 | **하지만 pg_cron이 14일 지나면 DELETE**(`arena_prune_telemetry`) — 상한 고정 |
| `arena_decisions` | 3,856 | 27.2 | 보존정책 없음, 계속 누적되지만 극히 느림 |
| `arena_execution_gates` | 2,532 | 17.8 | 30일 보존 DELETE — 상한 고정 |
| `arena_shadow_decisions` | 1,177 | 8.3 | 느림 |
| `paper_positions` | 100 | 0.7 | 트랙레코드 본체 — 거의 안 자람 |

파티셔닝이 값어치를 하는 지점은 보통 **테이블이 GB~수천만 행대**가 되거나, **오래된
파티션을 통째로 DROP해서 정리**해야 할 때다. 이 프로젝트는:
- 제일 빨리 자라는 두 테이블(`realtime_risk_states`/`execution_gates`)은 **이미
  `arena_prune_telemetry()`(pg_cron, 매일 03:00 UTC)가 DELETE로 14~30일치만 유지**해서
  자연 상한이 있다(지금 20,341행이 그 상한과 정확히 일치).
- 보존정책이 없는 `arena_decisions`도 하루 27행이면 **10만 행(현재 대비 25배) 도달까지
  약 9년**이 걸린다. 파티셔닝을 정당화할 규모가 아니다.

**판단**: 지금 도입하면 "언젠가 필요할 것"을 대비한 인프라 비용을 미리 지불하는 것이고,
그 "언젠가"가 현재 성장률로는 수년 뒤다. 필요해지면 그때 `pg_partman`(이미 확장 목록에
있음, 설치는 안 된 상태)으로 전환하면 된다 — 지금은 **DELETE 기반 보존이 더 단순하고
충분하다.**

---

## 3. Supavisor (커넥션 풀러 튜닝) — 해당 없음 (앱이 아예 안 씀)

전체 저장소를 `asyncpg`/`psycopg`/`DATABASE_URL`/`postgres://` 로 grep했지만 **한 곳도
없다.** `src/arena/positions.py`가 쓰는 건 `supabase-py`의 `AsyncClient`
(`acreate_client`) — 이건 **PostgREST를 HTTPS로 호출하는 REST 클라이언트**이지 Postgres
프로토콜로 직접 붙는 클라이언트가 아니다. 아레나 백엔드·대시보드·이 세션의 모든 쓰기가
REST(`https://.../rest/v1/...`)로 나가는 걸 로그로 이미 확인한 바 있다(2026-08-16 1차
감사 재배포 검증 로그).

Supavisor는 `postgres://` 커넥션 스트링으로 직접 붙는 클라이언트(ORM, `psql`, BI 툴 등)를
위한 풀러다. 이 프로젝트엔 그런 클라이언트가 하나도 없으므로 **튜닝할 대상 자체가 없다.**
(실제 커넥션 풀링은 PostgREST 자체 내부 풀이 담당 — 로그에 `Connection Pool initialized
with a maximum size of 10 connections`로 이미 확인됨, 이건 PostgREST 설정이지 Supavisor가
아니다.)

**판단**: 도입 대상이 없음. 앞으로 만약 직접 `psycopg`로 붙는 배치 스크립트를 새로 만든다면
(예: 대용량 백필) 그때 Supavisor 풀 모드(transaction vs session)를 고려하면 된다.

---

## 4. Postgres Functions / RPC — 도입 안 함 (근거: 왕복 수 자체가 이미 적음)

현재 서버사이드 함수는 `arena_prune_telemetry()`(pg_cron 유지보수용)와 `set_updated_at()`
(트리거) 2개뿐 — 비즈니스 로직 RPC는 없다.

RPC를 고려할 만한 유일한 후보는 대시보드의 다중 쿼리 조합 로직인데, 실제 코드를 보면
대시보드 로드 1회당 REST 호출이 **`paper_positions`×2, `arena_decisions`, `arena_asset_news`
총 4개뿐**이고 이미 `Promise.all`로 **병렬 실행**돼 있다(`arena/index.html:1632`,`1690`).
RPC로 하나로 합쳐도 왕복 수가 4→1로 줄 뿐 병렬이라 지연시간 이득은 미미하고, 트래픽이
하루 몇 회(§캐싱 검토 참고, 1차 루브릭 감사에서 실측)라 그 이득도 체감되지 않는다.

**판단**: 지금 클라이언트 사이드에서 하는 조합 로직(예: 자산×시장 합산)을 RPC로 옮기면
얻는 게 "서버가 계산 일관성을 보장"하는 정도인데, 이건 최근 경합조건 버그(2026-08-15
`refreshActiveTrack` 시퀀스 토큰 수정)를 근본적으로 재발 방지하는 방향이긴 하다. 다만
**성능 문제가 아니라 코드 구조 선택**이라 이번 감사 스코프(성능 최적화) 밖으로 판단,
실행하지 않음. 재발하면 그때 RPC화를 검토할 후보로 기록만 해둔다.

---

## 5. pg_stat_statements — 이미 최대로 쓰는 중 (조치 불필요)

`shared_preload_libraries`에 이미 로드돼 있고(`track=all` 관련 옵션 확인, `dealloc=0`),
`pg_stat_statements.max=5000`으로 여유도 충분(현재 entries 2,149). **이번 세션 3차례
감사 전부가 이 확장 하나로 진행됐다** — 쓰기 증폭 발견(1차), 권한 문제 발견은 별개지만
쿼리 비용 검증(2차), 이번 뷰 트래픽 실측(3차) 전부 여기서 나왔다.

**판단**: 이미 의도대로 완전히 활용 중. 추가 설정 변경 불필요.

---

## 6. Performance / Security Advisors — 이미 최대로 쓰는 중 (조치 불필요)

`get_advisors`를 이번 세션에서만 6번 호출해 매 마이그레이션 직후 재검증하는 루틴으로
써왔다(1차: unused_index/no_primary_key 확인 → 2차: REVOKE 전후 rls_enabled_no_policy
재확인). 현재 남은 항목(unused_index 11개, no_primary_key 2개, function_search_path
2개)은 전부 이전 세션들에서 "확인 후 의도적으로 유지" 판정이 난 것들이다.

**판단**: 이미 의도대로 완전히 활용 중. 앞으로도 마이그레이션 적용 직후 습관적으로
재확인하는 것 외엔 추가 조치 없음.

---

## 요약

| 기능 | 상태 | 판단 |
|---|---|---|
| Materialized Views | 미사용(뷰는 있으나 matview 아님) | 핫패스 없음 — 도입 안 함 |
| Declarative Partitioning | 미사용 | 보존정책이 이미 상한 역할 — 도입 안 함(수년 뒤 재검토) |
| Supavisor 튜닝 | 해당 없음 | REST 전용 클라이언트라 대상 자체가 없음 |
| Postgres Functions/RPC | 유지보수용 2개만 존재 | 왕복 수 이미 적고 병렬 — 성능상 도입 안 함(코드구조 이슈로 별도 기록) |
| pg_stat_statements | **이미 최대 활용** | 조치 불필요 |
| Advisors | **이미 최대 활용** | 조치 불필요 |

이번엔 실행한 조치가 없다 — 6개 전부 "지금 규모에서는 안 하는 게 맞다"는 판정이
결과이고, 이게 과잉설계를 막는 실제 결정이다.
