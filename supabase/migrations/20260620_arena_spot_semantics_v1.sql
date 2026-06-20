-- Arena spot semantics v1
--
-- 목적:
-- - live/paper execution을 현물 long/flat 기준으로 명확히 분리한다.
-- - 알고리즘 raw short 신호는 보존하되, executable signal은 NULL 또는 long만 허용한다.
-- - 과거 long/short paper simulation은 legacy/perp_sim 계층으로 분리 분석한다.

ALTER TABLE arena_runs
    ADD COLUMN IF NOT EXISTS product_type TEXT NOT NULL DEFAULT 'spot',
    ADD COLUMN IF NOT EXISTS position_semantics TEXT NOT NULL DEFAULT 'spot_long_flat';

ALTER TABLE paper_positions
    ADD COLUMN IF NOT EXISTS product_type TEXT NOT NULL DEFAULT 'spot',
    ADD COLUMN IF NOT EXISTS position_semantics TEXT NOT NULL DEFAULT 'spot_long_flat',
    ADD COLUMN IF NOT EXISTS close_reason TEXT;

ALTER TABLE arena_decisions
    ADD COLUMN IF NOT EXISTS raw_signal TEXT,
    ADD COLUMN IF NOT EXISTS executable_signal TEXT,
    ADD COLUMN IF NOT EXISTS product_policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE arena_decisions
    DROP CONSTRAINT IF EXISTS arena_decisions_raw_signal_check;

ALTER TABLE arena_decisions
    ADD CONSTRAINT arena_decisions_raw_signal_check
        CHECK (raw_signal IS NULL OR raw_signal IN ('long', 'short'));

ALTER TABLE arena_decisions
    DROP CONSTRAINT IF EXISTS arena_decisions_executable_signal_check;

ALTER TABLE arena_decisions
    ADD CONSTRAINT arena_decisions_executable_signal_check
        CHECK (executable_signal IS NULL OR executable_signal = 'long');

ALTER TABLE arena_decisions
    DROP CONSTRAINT IF EXISTS arena_decisions_action_check;

ALTER TABLE arena_decisions
    ADD CONSTRAINT arena_decisions_action_check
        CHECK (
            action IN (
                'open',
                'close_flat',
                'close_spot_risk_off',
                'close_legacy_short',
                'hold',
                'flat_skip',
                'spot_short_no_trade',
                'min_hold_skip',
                'risk_blocked',
                'execution_gate_blocked',
                'error'
            )
        );

CREATE INDEX IF NOT EXISTS idx_paper_positions_product_status
    ON paper_positions (product_type, position_semantics, status, open_time DESC);

CREATE INDEX IF NOT EXISTS idx_arena_decisions_raw_executable
    ON arena_decisions (raw_signal, executable_signal, created_at DESC);

CREATE OR REPLACE VIEW arena_spot_position_mart_v1 AS
SELECT
    id,
    algo_id,
    direction,
    status,
    open_time,
    close_time,
    open_price,
    close_price,
    ret_pct,
    hold_hours,
    is_stop_loss,
    close_reason,
    strategy_version,
    params_version,
    product_type,
    position_semantics,
    data_timestamp,
    created_at
FROM paper_positions
WHERE product_type = 'spot'
  AND position_semantics = 'spot_long_flat'
  AND direction = 'long';

CREATE OR REPLACE VIEW arena_legacy_perp_sim_position_mart_v1 AS
SELECT
    id,
    algo_id,
    direction,
    status,
    open_time,
    close_time,
    open_price,
    close_price,
    ret_pct,
    hold_hours,
    is_stop_loss,
    close_reason,
    strategy_version,
    params_version,
    product_type,
    position_semantics,
    data_timestamp,
    created_at
FROM paper_positions
WHERE product_type <> 'spot'
   OR position_semantics <> 'spot_long_flat'
   OR direction = 'short';

CREATE OR REPLACE VIEW arena_spot_semantics_v1_ready AS
SELECT
    'arena_spot_semantics_v1_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'product_type'
    ) AS has_position_product_type,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'position_semantics'
    ) AS has_position_semantics,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'close_reason'
    ) AS has_position_close_reason,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_decisions' AND column_name = 'raw_signal'
    ) AS has_decision_raw_signal,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_decisions' AND column_name = 'executable_signal'
    ) AS has_decision_executable_signal,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_decisions' AND column_name = 'product_policy_snapshot'
    ) AS has_product_policy_snapshot,
    EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'arena_spot_position_mart_v1'
    ) AS has_spot_position_mart,
    EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'arena_legacy_perp_sim_position_mart_v1'
    ) AS has_legacy_perp_sim_mart,
    NOT EXISTS (
        SELECT 1 FROM paper_positions
        WHERE status = 'open'
          AND product_type = 'spot'
          AND position_semantics = 'spot_long_flat'
          AND direction = 'short'
    ) AS no_open_spot_short_positions;
