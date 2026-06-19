-- =============================================================================
-- Arena market-structure + shadow vNext v1
--
-- 목적:
-- - Binance futures raw market-structure 데이터를 Arena research 원장에 저장한다.
-- - vNext regime/trend/allocator 결과를 paper_positions와 분리된 shadow 원장에 저장한다.
-- - backtest trade 원장에 funding 포함 net return 분해 컬럼을 추가한다.
-- =============================================================================

CREATE TABLE IF NOT EXISTS arena_funding_rates (
    exchange      TEXT        NOT NULL,
    symbol        TEXT        NOT NULL,
    funding_time  TIMESTAMPTZ NOT NULL,
    funding_rate  DOUBLE PRECISION NOT NULL,
    mark_price    DOUBLE PRECISION,
    raw_payload   JSONB       NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, symbol, funding_time),
    CONSTRAINT arena_funding_rates_symbol_check
        CHECK (symbol <> '')
);

CREATE INDEX IF NOT EXISTS idx_arena_funding_rates_symbol_time
    ON arena_funding_rates (symbol, funding_time DESC);


CREATE TABLE IF NOT EXISTS arena_open_interest_snapshots (
    exchange                TEXT        NOT NULL,
    symbol                  TEXT        NOT NULL,
    period                  TEXT        NOT NULL,
    timestamp               TIMESTAMPTZ NOT NULL,
    sum_open_interest       DOUBLE PRECISION,
    sum_open_interest_value DOUBLE PRECISION,
    raw_payload             JSONB       NOT NULL,
    fetched_at              TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, symbol, period, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_arena_open_interest_symbol_time
    ON arena_open_interest_snapshots (symbol, period, timestamp DESC);


CREATE TABLE IF NOT EXISTS arena_basis_snapshots (
    exchange                TEXT        NOT NULL,
    pair                    TEXT        NOT NULL,
    contract_type           TEXT        NOT NULL,
    period                  TEXT        NOT NULL,
    timestamp               TIMESTAMPTZ NOT NULL,
    basis                   DOUBLE PRECISION,
    basis_rate              DOUBLE PRECISION,
    annualized_basis_rate   DOUBLE PRECISION,
    raw_payload             JSONB       NOT NULL,
    fetched_at              TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, pair, contract_type, period, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_arena_basis_pair_time
    ON arena_basis_snapshots (pair, contract_type, period, timestamp DESC);


CREATE TABLE IF NOT EXISTS arena_mark_price_bars (
    exchange    TEXT        NOT NULL,
    symbol      TEXT        NOT NULL,
    interval    TEXT        NOT NULL,
    price_type  TEXT        NOT NULL,
    open_time   TIMESTAMPTZ NOT NULL,
    close_time  TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    raw_payload JSONB       NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, symbol, interval, price_type, open_time),
    CONSTRAINT arena_mark_price_bars_price_type_check
        CHECK (price_type IN ('mark_price', 'premium_index')),
    CONSTRAINT arena_mark_price_bars_price_check
        CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CONSTRAINT arena_mark_price_bars_ohlc_shape_check
        CHECK (high >= low AND high >= open AND high >= close AND low <= open AND low <= close)
);

CREATE INDEX IF NOT EXISTS idx_arena_mark_price_bars_symbol_time
    ON arena_mark_price_bars (symbol, interval, price_type, open_time DESC);


CREATE TABLE IF NOT EXISTS arena_market_feature_snapshots (
    run_id         UUID        PRIMARY KEY REFERENCES arena_runs (run_id) ON DELETE CASCADE,
    symbol         TEXT        NOT NULL,
    interval       TEXT        NOT NULL,
    data_timestamp TIMESTAMPTZ NOT NULL,
    fetched_at     TIMESTAMPTZ NOT NULL,
    quality_status TEXT        NOT NULL DEFAULT 'ok',
    quality_errors JSONB       NOT NULL DEFAULT '[]'::jsonb,
    features       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_market_feature_quality_check
        CHECK (quality_status IN ('ok', 'degraded'))
);

CREATE INDEX IF NOT EXISTS idx_arena_market_feature_symbol_time
    ON arena_market_feature_snapshots (symbol, interval, data_timestamp DESC);


CREATE TABLE IF NOT EXISTS arena_shadow_decisions (
    run_id              UUID        NOT NULL REFERENCES arena_runs (run_id) ON DELETE CASCADE,
    sleeve_id           TEXT        NOT NULL,
    algo_id             TEXT        NOT NULL,
    signal              TEXT,
    allowed             BOOLEAN     NOT NULL,
    target_weight       DOUBLE PRECISION NOT NULL DEFAULT 0,
    risk_budget         DOUBLE PRECISION NOT NULL DEFAULT 0,
    action              TEXT        NOT NULL,
    reason              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    feature_snapshot    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    regime_snapshot     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    risk_snapshot       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    allocation_snapshot JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, sleeve_id, algo_id),
    CONSTRAINT arena_shadow_decisions_signal_check
        CHECK (signal IS NULL OR signal IN ('long', 'short')),
    CONSTRAINT arena_shadow_decisions_action_check
        CHECK (action IN ('shadow_open', 'shadow_flat', 'shadow_blocked'))
);

CREATE INDEX IF NOT EXISTS idx_arena_shadow_decisions_algo_created
    ON arena_shadow_decisions (algo_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_arena_shadow_decisions_sleeve_created
    ON arena_shadow_decisions (sleeve_id, created_at DESC);


ALTER TABLE arena_backtest_trades
    ADD COLUMN IF NOT EXISTS gross_ret_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS trading_cost_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS funding_ret_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS net_ret_pct DOUBLE PRECISION;

ALTER TABLE arena_indicator_snapshots
    ADD COLUMN IF NOT EXISTS macd_hist_prev DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bb_width DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS atr_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema_fast DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema_slow DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema_fast_slope DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema_slow_slope DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_24h DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_72h DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS realized_vol_24h DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS range_24h_atr DOUBLE PRECISION;


CREATE OR REPLACE VIEW arena_walk_forward_enhancements_ready AS
SELECT
    'arena_walk_forward_enhancements_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_walk_forward_splits'
          AND column_name = 'risk_model_version'
    ) AS has_risk_model_version,
    EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'arena_backtest_report_mart_v1'
    ) AS has_report_mart,
    EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'arena_backtest_algo_summary_v1'
    ) AS has_algo_summary;


CREATE OR REPLACE VIEW arena_market_structure_v1_ready AS
SELECT
    'arena_market_structure_v1_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_funding_rates'
    ) AS has_arena_funding_rates,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_open_interest_snapshots'
    ) AS has_arena_open_interest_snapshots,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_basis_snapshots'
    ) AS has_arena_basis_snapshots,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_mark_price_bars'
    ) AS has_arena_mark_price_bars,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_market_feature_snapshots'
    ) AS has_arena_market_feature_snapshots,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_backtest_trades'
          AND column_name = 'funding_ret_pct'
    ) AS has_backtest_funding_ret_pct,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_backtest_trades'
          AND column_name = 'net_ret_pct'
    ) AS has_backtest_net_ret_pct,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_indicator_snapshots'
          AND column_name = 'ema_fast'
    ) AS has_indicator_ema_fast,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_indicator_snapshots'
          AND column_name = 'return_24h'
    ) AS has_indicator_return_24h;


CREATE OR REPLACE VIEW arena_shadow_vnext_ready AS
SELECT
    'arena_shadow_vnext_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_shadow_decisions'
    ) AS has_arena_shadow_decisions,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_shadow_decisions'
          AND column_name = 'allocation_snapshot'
    ) AS has_shadow_allocation_snapshot,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_shadow_decisions'
          AND column_name = 'regime_snapshot'
    ) AS has_shadow_regime_snapshot;
