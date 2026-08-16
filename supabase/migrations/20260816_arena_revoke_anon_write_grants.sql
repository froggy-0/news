-- =============================================================================
-- 전체 DB 루브릭 감사 후속: anon/authenticated 쓰기 권한 REVOKE + 중복 인덱스 제거
-- (2026-08-16, 2차)
--
-- 상세 근거: docs/arena/research/supabase-full-db-rubric-audit-20260816.md
-- 이미 Supabase MCP apply_migration으로 프로덕션에 적용 완료. 이 파일은 로컬 마이그레이션
-- 이력과 실제 스키마를 일치시키기 위한 기록.
-- =============================================================================

-- 1) anon/authenticated의 쓰기 권한 REVOKE (public 스키마 전체, 66개 테이블)
--
-- Supabase 신규 프로젝트 기본 템플릿이 ALTER DEFAULT PRIVILEGES로 모든 public 테이블에
-- anon/authenticated INSERT/UPDATE/DELETE/TRUNCATE를 자동 부여한다. 지금은 RLS가 유일한
-- 방어선이고(46개 테이블 전부 RLS on 확인) 이 프로젝트는 2026-08-07에 정확히 이 카테고리의
-- 사고(RLS 비활성 테이블 5개 방치)를 이미 한 번 낸 전례가 있다. 방어선을 하나 더 둔다.
--
-- 안전성: EC2 백엔드는 service_role만 사용(전역 컨벤션), service_role/postgres는 anon/
-- authenticated와 완전히 별도의 GRANT를 가지므로 이 REVOKE로 영향받지 않는다. 대시보드가
-- 쓰는 5개 테이블(arena_asset_news/arena_decisions/arena_runs/arena_shadow_decisions/
-- paper_positions)은 이미 SELECT 전용 정책만 있어 REVOKE 후에도 동일하게 동작한다.
-- 실제 검증(SET LOCAL ROLE anon): SELECT는 그대로 성공, INSERT는 42501 permission denied로
-- GRANT 단계에서부터 차단(이전엔 RLS 단계에서만 차단됨 — 방어선 이중화 확인).
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon, authenticated;

-- 앞으로 생길 테이블도 자동으로 쓰기 권한을 받지 않도록. public 스키마 테이블 45개 전부
-- postgres 소유이고 이 마이그레이션도 postgres로 실행되므로 FOR ROLE 없이(=현재 역할
-- 기준) 걸면 실제 테이블 생성 경로를 정확히 커버한다.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM anon, authenticated;

-- 2) arena_realtime_risk_states 중복 인덱스 제거
--
-- idx_arena_realtime_risk_states_time(symbol, window_start DESC)는 PK
-- arena_realtime_risk_states_pkey(symbol, window_start)와 완전히 겹친다. btree는 양방향
-- 스캔이 기본이라 PK만으로 ORDER BY ... DESC가 이미 최적 실행된다(실측: PK idx_scan
-- 80,811회 vs 이 인덱스 202회). 프로젝트 최고빈도 쓰기 테이블이라 모든 INSERT마다 공짜
-- 비용이 붙던 것 — 제거.
DROP INDEX IF EXISTS idx_arena_realtime_risk_states_time;
