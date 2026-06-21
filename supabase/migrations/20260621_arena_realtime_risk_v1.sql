-- Arena realtime risk trigger v1
-- Spot-only shadow risk state layer. Futures data remains auxiliary risk input.

ALTER TABLE arena_realtime_feature_bars
    ADD COLUMN IF NOT EXISTS aggressive_sell_ratio DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS trade_quote_volume DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS mid_return_1m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS short_drawdown_5m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS spread_widening_bps_per_min DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS depth_collapse_ratio DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS arena_realtime_risk_states (
    symbol TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    risk_state TEXT NOT NULL,
    risk_score DOUBLE PRECISION,
    component_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    trigger_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommended_action TEXT NOT NULL,
    quality_status TEXT NOT NULL DEFAULT 'ok',
    feature_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    baseline_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    evaluated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, window_start),
    CONSTRAINT arena_realtime_risk_state_check
        CHECK (
            risk_state IN (
                'NORMAL',
                'CAUTION',
                'BLOCK_ENTRY',
                'EXIT_CANDIDATE',
                'FORCE_EXIT_CANDIDATE',
                'UNKNOWN'
            )
        ),
    CONSTRAINT arena_realtime_risk_quality_check
        CHECK (quality_status IN ('ok', 'degraded'))
);

CREATE INDEX IF NOT EXISTS idx_arena_realtime_risk_states_time
    ON arena_realtime_risk_states (symbol, window_start DESC);

CREATE INDEX IF NOT EXISTS idx_arena_realtime_risk_states_state
    ON arena_realtime_risk_states (risk_state, window_start DESC);

CREATE TABLE IF NOT EXISTS arena_realtime_risk_events (
    realtime_risk_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID,
    symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
    window_start TIMESTAMPTZ NOT NULL,
    position_id BIGINT REFERENCES paper_positions (id),
    event_type TEXT NOT NULL,
    previous_state TEXT,
    risk_state TEXT NOT NULL,
    severity TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    risk_score DOUBLE PRECISION,
    trigger_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_realtime_risk_events_state_check
        CHECK (
            risk_state IN (
                'NORMAL',
                'CAUTION',
                'BLOCK_ENTRY',
                'EXIT_CANDIDATE',
                'FORCE_EXIT_CANDIDATE',
                'UNKNOWN'
            )
        ),
    CONSTRAINT arena_realtime_risk_events_severity_check
        CHECK (severity IN ('low', 'medium', 'high'))
);

CREATE INDEX IF NOT EXISTS idx_arena_realtime_risk_events_created
    ON arena_realtime_risk_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_arena_realtime_risk_events_state
    ON arena_realtime_risk_events (risk_state, created_at DESC);

CREATE OR REPLACE VIEW arena_realtime_risk_v1_ready AS
WITH latest_feature AS (
    SELECT MAX(window_start) AS latest_window_start
    FROM arena_realtime_feature_bars
    WHERE symbol = 'BTCUSDT'
),
feature_quality AS (
    SELECT
        COUNT(*) AS rows_24h,
        COUNT(*) FILTER (WHERE quality_status = 'ok') AS ok_rows_24h,
        COUNT(*) FILTER (
            WHERE spread_bps_avg IS NULL
               OR expected_slippage_bps IS NULL
               OR depth_10bp_bid_usd IS NULL
               OR depth_10bp_ask_usd IS NULL
               OR last_price IS NULL
        ) AS core_null_rows_24h
    FROM arena_realtime_feature_bars
    WHERE symbol = 'BTCUSDT'
      AND window_start >= NOW() - INTERVAL '24 hours'
),
feature_dupes AS (
    SELECT COUNT(*) AS duplicate_grain_rows_24h
    FROM (
        SELECT symbol, window_start, window_seconds, COUNT(*) AS row_count
        FROM arena_realtime_feature_bars
        WHERE symbol = 'BTCUSDT'
          AND window_start >= NOW() - INTERVAL '24 hours'
        GROUP BY 1, 2, 3
        HAVING COUNT(*) > 1
    ) d
)
SELECT
    'arena_realtime_risk_v1_ready' AS check_name,
    EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = 'arena_realtime_risk_states'
    ) AS has_arena_realtime_risk_states,
    EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = 'arena_realtime_risk_events'
    ) AS has_arena_realtime_risk_events,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_realtime_feature_bars'
          AND column_name = 'realized_volatility_5m'
    ) AS has_realized_volatility_5m,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_realtime_feature_bars'
          AND column_name = 'depth_collapse_ratio'
    ) AS has_depth_collapse_ratio,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_realtime_feature_bars'
          AND column_name = 'aggressive_sell_ratio'
    ) AS has_aggressive_sell_ratio,
    (SELECT latest_window_start FROM latest_feature) AS latest_feature_window_start,
    EXTRACT(
        EPOCH FROM (NOW() - (SELECT latest_window_start FROM latest_feature))
    ) AS latest_feature_lag_seconds,
    (SELECT rows_24h FROM feature_quality) AS realtime_feature_rows_24h,
    (SELECT ok_rows_24h FROM feature_quality) AS realtime_feature_ok_rows_24h,
    (SELECT core_null_rows_24h FROM feature_quality) AS core_null_rows_24h,
    (SELECT duplicate_grain_rows_24h FROM feature_dupes) AS duplicate_grain_rows_24h;
