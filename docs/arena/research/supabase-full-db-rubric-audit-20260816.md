# Supabase 전체 DB 루브릭 감사 (2026-08-16, 2차)

1차 감사([supabase-io-audit-20260816.md](supabase-io-audit-20260816.md))가 arena 쓰기 증폭에
집중했다면, 이번엔 **범위를 전체 스키마로 넓혀** 보안·권한·캐싱·풀링·백업·인덱스 전수를
MCP(`execute_sql`/`get_advisors`/`query_logs`)로 재검증했다.

**결론 요약**: 성능 쪽은 1차 조치 이후 건강하다(잠금 대기 0, 캐시적중 99.6%). 대신
**전체 스키마 66개 테이블에 anon/authenticated 쓰기 권한이 기본으로 부여돼 있고, 앞으로 생길
테이블에도 자동 상속되는** 구조적 문제를 발견했다 — 지금은 RLS가 막고 있지만 이 프로젝트는
이미 2026-08-07에 "RLS 비활성 테이블 5개"를 발견·수정한 전례가 있다. 방어선이 하나뿐이다.

---

## 1. 🔴 심각 — public 스키마 전체가 anon/authenticated에 쓰기 권한 기본 부여

```sql
select grantee, count(distinct table_name) from information_schema.role_table_grants
where table_schema='public' and grantee in ('anon','authenticated')
  and privilege_type in ('INSERT','UPDATE','DELETE','TRUNCATE')
group by grantee;
-- anon: 66개 테이블, authenticated: 66개 테이블 (public 스키마 테이블 전부)
```

원인을 추적하니 `ALTER DEFAULT PRIVILEGES`에 박혀있다:

```
grantor=postgres, schema=public, objtype=table(r)
  → anon=arwdDxtm, authenticated=arwdDxtm  (전체 권한: 조회/삽입/수정/삭제/truncate/참조/트리거)
```

**의미**: `paper_positions`, `arena_decisions`, `arena_runs` 같은 트레이딩 핵심 테이블도
SQL 권한 레벨에서는 익명 키(`arena/index.html`에 **공개 노출된 anon key**)로 DELETE·UPDATE가
가능하다. 지금 이게 막히는 건 **RLS 정책 하나** 때문이다 — 5개 테이블(`arena_asset_news`,
`arena_decisions`, `arena_runs`, `arena_shadow_decisions`, `paper_positions`)은 SELECT 전용
정책이 있어 다른 명령은 자동 거부되고, 나머지 61개는 RLS만 켜져 있고 정책이 아예 없어 전체
거부된다. 실측으로 46개 테이블 **전부 RLS on** 확인했고 현재 상태는 안전하다.

**왜 심각도를 올려 보고하는가**: 이건 Supabase 신규 프로젝트의 기본 템플릿이라 "사용자 실수"는
아니다. 하지만 이 프로젝트는 **정확히 이 카테고리의 실수를 이미 한 번 냈다**
(CLAUDE.md 2026-08-07: "5개 테이블이 RLS 완전 비활성 — anon key로 전체 읽기/쓰기 가능"을
뒤늦게 발견). 지금 구조는 앞으로 누군가 실수로 정책을 잘못 걸거나 새 테이블에서
`ENABLE ROW LEVEL SECURITY`를 빼먹으면 **그 즉시, 아무 추가 승인 없이** 공개 anon key로
쓰기가 가능해지는 구조다. RLS가 유일한 방어선이라 오탐지 여지가 없다.

**권고**: `anon`/`authenticated`에서 INSERT/UPDATE/DELETE/TRUNCATE를 REVOKE하고,
`ALTER DEFAULT PRIVILEGES`도 함께 바꿔 **앞으로 생길 테이블도 기본으로 읽기 전용**이 되게
한다. 대시보드가 필요로 하는 5개 테이블에는 이미 SELECT GRANT가 별도로 있어(REVOKE 대상이
아님) 영향 없음.

**안전성 검증**:
- 백엔드(EC2)는 `SUPABASE_SERVICE_ROLE_KEY`만 쓴다(CLAUDE.md 전역 컨벤션, grep으로 anon
  사용처가 `arena/index.html` 하나뿐임을 이미 확인한 바 있음). `service_role`은 anon/authenticated와
  **별도의 독립 GRANT**(`service_role=arwdDxtm/postgres`)를 가지고 있어 이번 REVOKE로
  전혀 영향받지 않는다.
- `postgres`/`supabase_admin`도 별도 GRANT + `rolbypassrls=true`라 무관.
- `service_role`은 `rolbypassrls=true`라 RLS 자체를 우회하지만, 이번 REVOKE는 GRANT
  레이어를 건드리는 것이라 RLS 우회 여부와 별개로 안전.
- 대시보드가 실제 쓰는 5개 테이블의 anon 정책은 전부 `cmd=SELECT`뿐이라 REVOKE 후에도
  동일하게 동작(SELECT GRANT는 그대로 있고, 애초에 그 정책들도 SELECT 이외엔 막고 있었음).

---

## 2. 🟡 중간 — `arena_realtime_risk_states` 중복 인덱스

```
arena_realtime_risk_states_pkey        UNIQUE btree (symbol, window_start)
idx_arena_realtime_risk_states_time    btree (symbol, window_start DESC)
```

btree 인덱스는 양방향 스캔이 기본 지원이라 `ORDER BY window_start DESC`는 PK만으로 이미
최적 실행된다(`idx_scan` 실측: PK 80,811회 vs 이 인덱스 202회 — 옵티마이저도 거의 안 씀).
이 테이블은 프로젝트 최고빈도 쓰기 테이블이라 여기 얹힌 여분 인덱스 하나가 모든 INSERT마다
공짜로 비용이 붙는다. 648KB, 안전하게 제거 가능.

---

## 3. ⚪ 확인만 — 캐싱: 지금은 필요 없음(과잉설계 주의)

anon SELECT 트래픽을 142일 누적으로 실측했다.

| 테이블 | 누적 호출(142일) | 하루 평균 |
|---|---:|---:|
| `paper_positions` (최다 쿼리) | 350 | 2.5 |
| `arena_asset_news` | 112 | 0.8 |
| `arena_decisions` | (조인 포함 소수) | <1 |

하루 몇 회 수준이라 **HTTP 캐싱 레이어(Cache-Control, CDN)를 추가해도 얻을 게 없다** —
지금 캐싱이 "부족"한 게 아니라 캐싱이 필요할 트래픽 자체가 없는 상태. 방문자가 늘면(예:
대시보드가 바이럴) 그때 `Cache-Control: max-age=30` 같은 걸 PostgREST 응답에 붙이는 게
맞고, 지금 하면 복잡도만 추가하고 체감 효과가 없다. **하지 않는 것을 권고.**

---

## 4. ⚪ 확인만 — 그 외 정상 항목

| 항목 | 실측 | 판정 |
|---|---|---|
| RLS 커버리지 | public 46개 테이블 **전부** RLS on, gap 0 | 정상 |
| 잠금 대기 | 0건 | 정상 |
| idle in transaction | 0건 | 정상(§5에서 타임아웃 미설정은 별도 언급) |
| Realtime 구독 | `realtime.subscription` 0건 | 아무도 안 씀(대시보드는 REST 폴링) — 로그의 "tenant stop/start" 반복은 Supabase 플랫폼이 무구독 프로젝트를 자동 정리하는 루틴, 코드와 무관 |
| Auth 사용자 | 0명 | Auth 기능 자체를 안 씀(스키마는 플랫폼 기본 탑재, 제거 불가) |
| Storage | 버킷 1개(`btc-etf-bronze`, private, 128MB, 569개 객체) | morning-brief 파이프라인 소관, arena와 무관. Disk I/O 알람과도 무관(오브젝트 스토리지는 별도 인프라) |
| WAL 아카이빙 | `archive_mode=on` | 자동 백업 인프라 정상 동작 중(PITR 애드온 여부는 플랫폼 결제 설정이라 SQL로 확인 불가 — 대시보드에서 별도 확인 필요) |
| 시퀀스 예산 등 | — | 특이사항 없음 |

---

## 5. 🟢 낮은 우선순위 — idle 타임아웃 무제한

```
idle_in_transaction_session_timeout = 0  (무제한)
idle_session_timeout = 0                 (무제한)
```

지금 idle-in-transaction 연결은 0건이라 당장 문제는 아니다. 다만 `max_connections=60`인
Micro 스펙에서, 만약 클라이언트 버그로 트랜잭션을 열어놓고 안 닫는 상황이 생기면 그 연결이
영구히 슬롯을 점유한다. 저비용 보험으로 `idle_in_transaction_session_timeout`을 60~120초
정도로 걸어두는 걸 권고하지만, 지금 당장 해야 할 일은 아니다.

---

## 6. 재검증한 1차 조치 (참고)

1차 감사([supabase-io-audit-20260816.md](supabase-io-audit-20260816.md)) 적용 이후 상태를
같은 세션에서 재확인:

- `arena_decisions` created_at 인덱스: `Index Scan` 정상 사용 중.
- 사이클당 쓰기: mark_price_bars 36건/사이클로 정상(재배포 버그 수정 반영됨).
- **P7(스키마캐시 리로드 원인)은 여전히 미해결** — `pg_timezone_names`가 142일 누적 전체
  DB 시간의 **18.8%**로 여전히 단일 최대 소비자. 오늘 세션 중 `apply_migration` 호출
  자체가 PostgREST에 리로드 신호를 보내므로 오늘치 일부는 이 조사가 유발한 것이지만,
  1차 감사 당시(24시간 33회) 기준선은 그 이전부터의 패턴이라 원인 미상 상태 유지.

---

## 7. 권고 우선순위 → 실행 결과 (2026-08-16, 같은 세션)

| # | 조치 | 근거 | 리스크 | 상태 |
|---|---|---|---|---|
| **1** | anon/authenticated REVOKE INSERT/UPDATE/DELETE/TRUNCATE (전 테이블 + DEFAULT PRIVILEGES) | §1 — 유일 방어선(RLS) 단일장애점 제거 | 없음(§1 안전성 검증) | ✅ 적용 완료 |
| **2** | `idx_arena_realtime_risk_states_time` 삭제 | §2 — PK와 완전 중복, 최고빈도 테이블 | 없음 | ✅ 적용 완료 |
| — | 캐싱 레이어 추가 | §3 — **하지 않는 게 맞음**(트래픽 없음) | — | 미실행(의도적) |
| 낮음 | idle timeout 설정 | §5 — 저비용 보험, 급하지 않음 | 없음 | 미실행(낮은 우선순위) |

**적용**: Supabase MCP `apply_migration` →
[20260816_arena_revoke_anon_write_grants.sql](../../../supabase/migrations/20260816_arena_revoke_anon_write_grants.sql)

**배포 후 검증**:
- `information_schema.role_table_grants`: anon/authenticated의 INSERT/UPDATE/DELETE/TRUNCATE
  보유 테이블 **0개**(이전 66개). 대시보드 5개 테이블은 `REFERENCES,SELECT,TRIGGER`만 남음.
- `service_role`: `DELETE,INSERT,REFERENCES,SELECT,TRIGGER,TRUNCATE,UPDATE` 그대로(무변화).
- `ALTER DEFAULT PRIVILEGES` 반영 확인: 신규 테이블 기본 ACL이
  `anon=rxtm(SELECT/REFERENCES/TRIGGER만), postgres/service_role=arwdDxtm(전체)`로 바뀜.
- 실동작 검증(`SET LOCAL ROLE anon` 후 트랜잭션·롤백): `paper_positions` SELECT는 정상
  (100행 조회), INSERT는 `42501 permission denied for table paper_positions`로 **GRANT
  단계에서부터** 차단(이전엔 RLS 단계에서만 막혔음 — 방어선이 하나에서 둘로 늘어난 것 실증).
- `arena_realtime_risk_states` 인덱스: PK + `idx_..._state` 2개만 남음(중복 제거 확인).
- 서비스 정상성: `arena_realtime_risk_states` 최신 기록이 검증 시점 기준 90초 전(EC2가
  `service_role`로 정상 계속 기록 중 — 권한 변경이 실거래 경로에 영향 없음 확인).
- 어드바이저 재확인: 신규 WARN/ERROR 없음. 기존 INFO(unused_index, rls_enabled_no_policy)는
  이번 조치 대상 밖이라 그대로(의도된 상태 — 각각 FK 뒷받침·의도적 default-deny).
