-- =============================================================================
-- arena_macro_snapshots.payload/payload_hash 제거 (2026-07-31, DB 사이즈 최적화)
--
-- 발견: DB 사이즈 진단 중 arena_macro_snapshots가 309행뿐인데 42MB(행당 평균 141KB
-- TOAST)를 차지하는 걸 확인. payload 컬럼이 R2 latest.json 원본 전체(행당 132KB)를
-- 그대로 저장하지만, backtest.py/arena_status.py 등 코드 전체가 risk_overlay만
-- select하고 payload/payload_hash는 어디서도 조회한 적 없는 write-only 컬럼이었음.
--
-- 이미 Supabase MCP로 프로덕션에 적용·VACUUM FULL 완료(42MB → 408kB 확인). 이 파일은
-- 로컬 마이그레이션 이력과 실제 스키마를 일치시키기 위한 기록.
-- =============================================================================

ALTER TABLE arena_macro_snapshots DROP COLUMN IF EXISTS payload;
ALTER TABLE arena_macro_snapshots DROP COLUMN IF EXISTS payload_hash;
DROP INDEX IF EXISTS idx_arena_macro_snapshots_reference_date;
