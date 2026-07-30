-- =============================================================================
-- arena_realtime_risk_states/_events 보존정책 (2026-07-31, DB 사이즈 최적화 후속)
--
-- 두 테이블은 1분 주기로 무한히 계속 쌓이는 구조(2026-06-19 가동 시작, 현재 ~6주치
-- 5.6만/2.4만행). 컬럼 중복 제거(risk_snapshot 등, 20260731_arena_realtime_risk_
-- states_drop_duplicate_snapshot.sql)로 행당 크기는 절반이 됐지만, 보존정책 없이는
-- 여전히 장기적으로 계속 증가한다(추정 성장률 ~2.6MB/일 → 무제한 누적 시 연 ~950MB).
--
-- 180일 보존 선택 근거: scripts/analysis/replay_realtime_risk_gate.py(실시간 risk
-- 게이트가 실제로 나쁜 진입을 막아주는지 검증하는 연구 스크립트)가 과거 데이터를
-- 최대한 활용하는 게 유리해 짧게 자르지 않음. 현재 데이터가 6주치뿐이라 이 정책은
-- 즉시 아무것도 삭제하지 않고, 앞으로의 무한 증가만 방지하는 선제적 조치.
--
-- Supabase MCP로 프로덕션에 이미 적용 완료(pg_cron 확장 활성화 + cron.job 등록,
-- jobid=1, 매일 03:00 UTC). 이 파일은 로컬 마이그레이션 이력 기록용.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT cron.schedule(
  'arena_realtime_risk_retention',
  '0 3 * * *',
  $$
    DELETE FROM arena_realtime_risk_states WHERE window_start < now() - interval '180 days';
    DELETE FROM arena_realtime_risk_events WHERE window_start < now() - interval '180 days';
  $$
);
