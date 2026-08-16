-- =============================================================================
-- Disk I/O 최적화: 중복 JSONB 컬럼 제거 + 누락 인덱스 (2026-08-16)
--
-- 배경: Supabase Disk I/O 알람 대응으로 pg_stat_statements/pg_stat_user_tables를
-- 전수 감사(docs/arena/research/supabase-io-audit-20260816.md). 읽기 I/O는 논이슈
-- (캐시적중 99.6%, DB 209MB가 shared_buffers 224MB에 통째로 적재)였고, 실제 원인은
-- 쓰기 증폭이었다. 이 마이그레이션은 그중 DB 스키마로 해결되는 3건을 처리한다.
-- (윈도우 재업서트 중복은 코드 쪽 data_lake._rows_needing_write()에서 처리)
--
-- 세 변경 모두 트레이딩 로직과 무관하며, 제거 대상 컬럼은 읽는 코드가 없음을
-- 저장소 전수 grep으로 확인한 뒤 적용한다.
-- =============================================================================

-- 1) arena_realtime_risk_events.risk_snapshot 제거
--
-- 2026-07-31에 arena_realtime_risk_states에 적용했던 것과 **완전히 동일한 중복**인데
-- 이 테이블만 누락돼 있었다. risk_snapshot은 RealtimeRiskDecision.as_dict() 전체를
-- 통째로 저장하는데, 그 안의 risk_state/risk_score/trigger_reasons/recommended_action이
-- 이미 같은 행의 별도 컬럼으로 존재한다.
--
-- 실측(2026-08-16): 행당 risk_snapshot 2,223B, TOAST 27MB vs heap 2,120kB
--   → 스냅샷이 테이블 용량의 93%. 누적 WAL 483MB(전체의 15.4%).
--   1행 INSERT에 버퍼 142개 접근(비교: 인덱스 1개·TOAST 없는 feature_bars는 27개).
--
-- 안전성: 이 테이블은 저장소 전체에서 **읽는 코드가 없다**(data_lake.py의 INSERT와
-- 보존정책 DELETE뿐). scheduler는 arena_realtime_risk_states만 조회한다.
ALTER TABLE arena_realtime_risk_events DROP COLUMN IF EXISTS risk_snapshot;

-- 2) arena_realtime_risk_states.policy_snapshot 제거
--
-- 정적 정책 설정이라 전 행의 값이 동일하다. 실측: 20,271행 전부
--   count(distinct md5(policy_snapshot::text)) = 1, 행당 492B.
-- 이걸 1분마다(1,440회/일) 다시 저장하고 있었다.
--
-- 안전성: 유일한 소비자인 scheduler._decision_from_snapshot()은 이 값을 읽지 않고
-- `policy=realtime_risk.RealtimeRiskPolicy()`로 기본 정책을 새로 생성한다
-- (src/arena/scheduler.py). 조회 경로인 data_lake.fetch_latest_realtime_risk_state()는
-- select("*")라 컬럼이 사라져도 그대로 동작하고, 소비측은 전부 .get() 폴백이다.
ALTER TABLE arena_realtime_risk_states DROP COLUMN IF EXISTS policy_snapshot;

-- 3) arena_decisions(created_at DESC) 인덱스 추가
--
-- 이 테이블에 인덱스가 6개 있는데 실제 쿼리가 쓰는 created_at 단독만 없었다.
-- 기존 인덱스는 전부 (action|algo_id|raw_signal, created_at DESC) 복합이라
-- 선행 컬럼 조건이 없는 `ORDER BY created_at DESC LIMIT n`을 못 탄다.
--
-- 실측: seq_scan 14,897회 / seq_tup_read 12,233,262행(테이블은 3,700행),
--   누적 659.7초, 호출당 버퍼 187개. 현행 대시보드(arena/index.html:1650)와
--   roster_diagnostics.summarize_live_decisions()가 같은 정렬을 쓴다.
-- 쓰기 비용은 무시 가능(누적 INSERT 3,700건뿐인 저빈도 테이블).
CREATE INDEX IF NOT EXISTS idx_arena_decisions_created
    ON arena_decisions (created_at DESC);
