-- 멀티자산 대시보드(P1-7)가 anon key로 ETH/SOL shadow 신호를 읽을 수 있도록 공개 읽기 허용.
-- 실측(2026-08-03): EC2는 서비스키로 정상 기록 중(4h마다 POST 201)이지만, 대시보드가
-- 쓰는 anon(publishable) key로 조회하면 arena_runs/arena_shadow_decisions 둘 다
-- content-range: */0 — 기존 관례(docs/arena/operations/dashboard-runbook.md)대로
-- 테이블별 GRANT SELECT TO anon이 이 두 테이블엔 적용된 적이 없었음(P1-7이 그동안 보류였으므로).
-- paper_positions/arena_decisions는 이미 anon 조회 가능함을 실측 확인(변경 불필요).

GRANT SELECT ON arena_runs TO anon;
GRANT SELECT ON arena_shadow_decisions TO anon;
