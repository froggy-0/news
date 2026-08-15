-- Arena perp execution integrity + storage-light shared market inputs.
--
-- Execution-owned rows use the track key (BTCUSDT / BTCUSDT-PERP). Spot-proxy
-- market inputs stay keyed once by the real Binance symbol (BTCUSDT). A run now
-- stores only the exact input range instead of copying one link row per candle.

ALTER TABLE arena_runs
    ADD COLUMN IF NOT EXISTS market_data_symbol TEXT,
    ADD COLUMN IF NOT EXISTS input_open_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS input_close_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS input_bar_count INTEGER;

UPDATE arena_runs
SET market_data_symbol = regexp_replace(symbol, '-PERP$', '')
WHERE market_data_symbol IS NULL;

-- Preserve legacy reproducibility before releasing the redundant run↔bar ledger.
WITH input_ranges AS (
    SELECT
        run_id,
        MIN(open_time) AS input_open_time,
        MAX(close_time) AS input_close_time,
        COUNT(*)::INTEGER AS input_bar_count
    FROM arena_run_ohlcv_bars
    GROUP BY run_id
)
UPDATE arena_runs AS runs
SET
    input_open_time = ranges.input_open_time,
    input_close_time = ranges.input_close_time,
    input_bar_count = ranges.input_bar_count
FROM input_ranges AS ranges
WHERE runs.run_id = ranges.run_id
  AND runs.input_open_time IS NULL;

ALTER TABLE arena_runs
    ALTER COLUMN market_data_symbol SET NOT NULL;

ALTER TABLE arena_runs
    DROP CONSTRAINT IF EXISTS arena_runs_input_range_check;

ALTER TABLE arena_runs
    ADD CONSTRAINT arena_runs_input_range_check
    CHECK (
        (input_open_time IS NULL AND input_close_time IS NULL AND input_bar_count IS NULL)
        OR (
            input_open_time IS NOT NULL
            AND input_close_time IS NOT NULL
            AND input_bar_count > 0
            AND input_close_time >= input_open_time
        )
    );

ALTER TABLE arena_runs
    DROP CONSTRAINT IF EXISTS arena_runs_track_product_check;

ALTER TABLE arena_runs
    ADD CONSTRAINT arena_runs_track_product_check
    CHECK (
        (
            product_type = 'spot'
            AND position_semantics = 'spot_long_flat'
            AND symbol !~ '-PERP$'
            AND market_data_symbol = symbol
        )
        OR (
            product_type = 'usdm_perp'
            AND position_semantics = 'usdm_perp_long_short'
            AND symbol ~ '-PERP$'
            AND market_data_symbol = regexp_replace(symbol, '-PERP$', '')
        )
    );

ALTER TABLE paper_positions
    ALTER COLUMN symbol SET NOT NULL;

ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS paper_positions_track_product_check;

ALTER TABLE paper_positions
    ADD CONSTRAINT paper_positions_track_product_check
    CHECK (
        (
            product_type = 'spot'
            AND position_semantics = 'spot_long_flat'
            AND direction = 'long'
            AND symbol !~ '-PERP$'
        )
        OR (
            product_type = 'usdm_perp'
            AND position_semantics = 'usdm_perp_long_short'
            AND direction IN ('long', 'short')
            AND symbol ~ '-PERP$'
        )
        OR product_type NOT IN ('spot', 'usdm_perp')
    );

ALTER TABLE arena_decisions
    DROP CONSTRAINT IF EXISTS arena_decisions_executable_signal_check;

ALTER TABLE arena_decisions
    ADD CONSTRAINT arena_decisions_executable_signal_check
    CHECK (executable_signal IS NULL OR executable_signal IN ('long', 'short'));

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
            'realtime_risk_blocked',
            'reverse',
            'signal_reverse',
            'error'
        )
    );

-- The existing index already has the right key; rename it without allocating a
-- second copy. PostgreSQL treats symbol as the execution-track identifier.
DO $$
BEGIN
    IF to_regclass('public.ux_paper_positions_one_open_per_track_algo') IS NULL
       AND to_regclass('public.ux_paper_positions_one_open_per_algo') IS NOT NULL THEN
        ALTER INDEX ux_paper_positions_one_open_per_algo
            RENAME TO ux_paper_positions_one_open_per_track_algo;
    END IF;
END $$;

-- Keep calculated gate inputs, but remove raw 1,000-level order books and the
-- second nested copy of the same feature/risk payload. Typed scalar columns and
-- the policy are sufficient to reproduce the decision.
UPDATE arena_execution_gates
SET
    feature_snapshot = feature_snapshot
        - 'depth_bids'
        - 'depth_asks'
        - 'realtime_risk_snapshot',
    gate_snapshot = jsonb_build_object(
        'policy', COALESCE(gate_snapshot -> 'policy', '{}'::JSONB)
    )
WHERE feature_snapshot ?| ARRAY['depth_bids', 'depth_asks', 'realtime_risk_snapshot']
   OR gate_snapshot ? 'feature_snapshot'
   OR gate_snapshot ? 'risk_snapshot';

-- No code, view, or inbound FK reads this table. The input range above preserves
-- run reproducibility against the shared arena_ohlcv_bars ledger.
TRUNCATE TABLE arena_run_ohlcv_bars;

COMMENT ON COLUMN arena_runs.symbol IS
    'Execution track key, e.g. BTCUSDT or BTCUSDT-PERP.';

COMMENT ON COLUMN arena_runs.market_data_symbol IS
    'Shared market input key, e.g. BTCUSDT for spot and current perp proxy tracks.';

COMMENT ON COLUMN arena_runs.input_open_time IS
    'First shared OHLCV bar used by this run.';

COMMENT ON COLUMN arena_runs.input_close_time IS
    'Last shared OHLCV bar used by this run.';

COMMENT ON COLUMN arena_runs.input_bar_count IS
    'Number of shared OHLCV bars used by this run.';

SELECT
    'arena_perp_short_execution_v1_ready' AS check_name,
    COUNT(*) FILTER (WHERE market_data_symbol IS NULL) = 0 AS run_market_keys_complete,
    NOT EXISTS (
        SELECT 1
        FROM paper_positions
        WHERE status = 'open'
        GROUP BY symbol, algo_id
        HAVING COUNT(*) > 1
    ) AS one_open_position_per_track_algo,
    (SELECT COUNT(*) FROM arena_run_ohlcv_bars) = 0 AS shared_ohlcv_links_compacted
FROM arena_runs;
