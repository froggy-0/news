-- =============================================================================
-- paper_positions — arena ledger hardening
-- 목적: 전략 재현성 컬럼 도입 이후, 잘못된 상태값과 중복 open position을 DB 레벨에서 차단한다.
--
-- 실행 전제:
-- - 20260619_paper_positions.sql 적용 완료
-- - 20260619_arena_position_snapshots.sql 적용 완료
-- - 20260619_arena_data_timestamp.sql 적용 완료
--
-- 기존 legacy row는 유지한다. 이 마이그레이션은 과거 row를 꾸며서 바꾸지 않고,
-- 앞으로 들어오는 데이터의 무결성을 강화한다.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. 기존 NULL 방어 및 기본값 재확인
-- ---------------------------------------------------------------------------

UPDATE paper_positions
SET status = 'open'
WHERE status IS NULL;

UPDATE paper_positions
SET is_stop_loss = FALSE
WHERE is_stop_loss IS NULL;

UPDATE paper_positions
SET fee_bps = 5.0
WHERE fee_bps IS NULL;

UPDATE paper_positions
SET strategy_version = 'legacy'
WHERE strategy_version IS NULL;

UPDATE paper_positions
SET params_version = 'legacy'
WHERE params_version IS NULL;

UPDATE paper_positions
SET params_snapshot = '{}'::jsonb
WHERE params_snapshot IS NULL;

UPDATE paper_positions
SET indicator_snapshot = '{}'::jsonb
WHERE indicator_snapshot IS NULL;

UPDATE paper_positions
SET macro_snapshot = '{}'::jsonb
WHERE macro_snapshot IS NULL;

UPDATE paper_positions
SET market_snapshot = '{}'::jsonb
WHERE market_snapshot IS NULL;

UPDATE paper_positions
SET signal_reason = '{}'::jsonb
WHERE signal_reason IS NULL;

UPDATE paper_positions
SET runtime = 'ec2'
WHERE runtime IS NULL;

UPDATE paper_positions
SET data_timestamp = open_time
WHERE data_timestamp IS NULL
  AND open_time IS NOT NULL;

ALTER TABLE paper_positions ALTER COLUMN status SET DEFAULT 'open';
ALTER TABLE paper_positions ALTER COLUMN is_stop_loss SET DEFAULT FALSE;
ALTER TABLE paper_positions ALTER COLUMN fee_bps SET DEFAULT 5.0;
ALTER TABLE paper_positions ALTER COLUMN strategy_version SET DEFAULT 'legacy';
ALTER TABLE paper_positions ALTER COLUMN params_version SET DEFAULT 'legacy';
ALTER TABLE paper_positions ALTER COLUMN params_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN indicator_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN macro_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN market_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN signal_reason SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN runtime SET DEFAULT 'ec2';

ALTER TABLE paper_positions ALTER COLUMN status SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN open_time SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN data_timestamp SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN open_price SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN stop_loss_price SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN is_stop_loss SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN fee_bps SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN strategy_version SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN params_version SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN params_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN indicator_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN macro_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN market_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN signal_reason SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN runtime SET NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. 상태값 CHECK constraints
-- ---------------------------------------------------------------------------

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_direction_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_direction_check
    CHECK (direction IN ('long', 'short'));

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_status_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_status_check
    CHECK (status IN ('open', 'closed'));

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_runtime_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_runtime_check
    CHECK (runtime IN ('ec2', 'lambda', 'manual', 'legacy'));

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_price_positive_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_price_positive_check
    CHECK (
        open_price > 0
        AND stop_loss_price > 0
        AND (close_price IS NULL OR close_price > 0)
    );

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_fee_nonnegative_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_fee_nonnegative_check
    CHECK (fee_bps >= 0);

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_closed_fields_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_closed_fields_check
    CHECK (
        status = 'open'
        OR (
            close_time IS NOT NULL
            AND close_price IS NOT NULL
            AND ret_pct IS NOT NULL
            AND hit IS NOT NULL
            AND hold_hours IS NOT NULL
        )
    );

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_data_time_order_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_data_time_order_check
    CHECK (data_timestamp <= open_time);

-- ---------------------------------------------------------------------------
-- 3. 인덱스
-- ---------------------------------------------------------------------------

-- 알고리즘별 open position은 하나만 허용한다.
CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_positions_one_open_per_algo
    ON paper_positions (algo_id)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_paper_positions_open
    ON paper_positions (algo_id)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_paper_positions_algo_closed
    ON paper_positions (algo_id, close_time DESC)
    WHERE status = 'closed';

CREATE INDEX IF NOT EXISTS idx_paper_positions_strategy_version
    ON paper_positions (strategy_version, open_time DESC);

CREATE INDEX IF NOT EXISTS idx_paper_positions_data_timestamp
    ON paper_positions (data_timestamp DESC);

-- ---------------------------------------------------------------------------
-- 4. 실행 후 확인용 조회
-- ---------------------------------------------------------------------------

SELECT
    'paper_positions_hardening_ok' AS check_name,
    COUNT(*) AS total_positions,
    COUNT(*) FILTER (WHERE status = 'open') AS open_positions,
    COUNT(*) FILTER (WHERE strategy_version = 'legacy') AS legacy_positions,
    COUNT(*) FILTER (WHERE params_snapshot = '{}'::jsonb) AS empty_params_snapshots
FROM paper_positions;
