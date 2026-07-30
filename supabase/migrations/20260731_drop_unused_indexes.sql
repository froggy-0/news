-- =============================================================================
-- 미사용 인덱스 정리 (2026-07-31, DB 사이즈 최적화 3단계)
--
-- 2026-07-31 DB 사이즈 진단(pg_stat_user_indexes.idx_scan=0 확인 + Supabase
-- performance advisor의 unused_index 플래그 일치) — 실제 조회에 한 번도 쓰이지 않은
-- 인덱스 22개 제거. 각각은 작지만(총 ~5.3MB) 누적 디스크 + 매 insert/update마다의
-- 인덱스 유지 오버헤드 감소. 이미 Supabase MCP로 프로덕션에 적용 완료
-- (383MB → 378MB). 이 파일은 로컬 마이그레이션 이력 기록용.
-- =============================================================================

DROP INDEX IF EXISTS idx_arena_realtime_feature_bars_time;
DROP INDEX IF EXISTS idx_arena_realtime_risk_events_state;
DROP INDEX IF EXISTS idx_arena_execution_gates_reject;
DROP INDEX IF EXISTS idx_arena_open_interest_symbol_time;
DROP INDEX IF EXISTS idx_arena_runs_feature_set_version;
DROP INDEX IF EXISTS idx_arena_indicator_snapshots_symbol_time;
DROP INDEX IF EXISTS idx_arena_market_feature_symbol_time;
DROP INDEX IF EXISTS idx_arena_shadow_decisions_algo_created;
DROP INDEX IF EXISTS idx_arena_shadow_decisions_sleeve_created;
DROP INDEX IF EXISTS idx_arena_runs_frequency_profile;
DROP INDEX IF EXISTS idx_arena_runs_strategy_version;
DROP INDEX IF EXISTS idx_paper_positions_data_timestamp;
DROP INDEX IF EXISTS idx_arena_strategy_versions_feature_set;
DROP INDEX IF EXISTS idx_paper_positions_strategy_version;
DROP INDEX IF EXISTS idx_arena_indicator_feature_bars_profile_time;
DROP INDEX IF EXISTS idx_arena_walk_forward_splits_frequency;
DROP INDEX IF EXISTS idx_arena_backtest_runs_symbol_interval;
DROP INDEX IF EXISTS idx_arena_walk_forward_splits_symbol_interval;
DROP INDEX IF EXISTS idx_arena_backtest_validation_runs_status;
DROP INDEX IF EXISTS idx_arena_backtest_validation_checks_status;
DROP INDEX IF EXISTS idx_arena_risk_events_run_algo;
DROP INDEX IF EXISTS idx_arena_liquidation_bars_symbol_start;
DROP INDEX IF EXISTS idx_arena_risk_state_status;
