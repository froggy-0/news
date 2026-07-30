-- =============================================================================
-- arena_realtime_risk_states.risk_snapshot 제거 (2026-07-31, DB 사이즈 최적화)
--
-- 발견: risk_snapshot 컬럼은 RealtimeRiskDecision.as_dict() 전체를 그대로 저장하는데,
-- 이 안의 component_scores/trigger_reasons/feature_snapshot/baseline_snapshot/policy가
-- 전부 같은 행의 별도 컬럼(component_scores/trigger_reasons/feature_snapshot/
-- baseline_snapshot/policy_snapshot)으로 이미 저장돼 있음 — 완전 중복.
-- 실측(행당): risk_snapshot≈2.1KB ≈ 나머지 5개 컬럼 합 2.5KB(거의 1:1).
-- 56k행(1분 주기 실시간 리스크 상태) 테이블이 DB 전체(579MB)의 절반 이상을 차지하던
-- 원인. src/arena/scheduler.py의 _latest_realtime_risk_features()가 이미
-- `row.get("risk_snapshot") or row`로 폴백돼 있어(컬럼 없으면 원본 row 그대로 사용)
-- 코드 동작에 영향 없이 제거 가능함을 확인 후 적용.
--
-- 이미 Supabase MCP로 프로덕션에 적용·VACUUM FULL 완료(321MB → 166MB 확인). 이 파일은
-- 로컬 마이그레이션 이력과 실제 스키마를 일치시키기 위한 기록. data_lake.py의
-- record_realtime_risk_state()도 함께 수정(risk_snapshot 쓰기 중단).
-- =============================================================================

ALTER TABLE arena_realtime_risk_states DROP COLUMN IF EXISTS risk_snapshot;
