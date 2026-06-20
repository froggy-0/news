-- Arena real-time observation and shadow execution gate v1

CREATE TABLE IF NOT EXISTS arena_realtime_feature_bars (
    symbol TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    window_seconds INTEGER NOT NULL,
    spread_bps_avg DOUBLE PRECISION,
    spread_bps_p95 DOUBLE PRECISION,
    depth_10bp_bid_usd DOUBLE PRECISION,
    depth_10bp_ask_usd DOUBLE PRECISION,
    orderbook_imbalance DOUBLE PRECISION,
    taker_buy_sell_ratio DOUBLE PRECISION,
    realized_volatility_1m DOUBLE PRECISION,
    realized_volatility_5m DOUBLE PRECISION,
    volume_spike DOUBLE PRECISION,
    volatility_score DOUBLE PRECISION,
    expected_slippage_bps DOUBLE PRECISION,
    api_latency_ms_p95 DOUBLE PRECISION,
    last_bid DOUBLE PRECISION,
    last_ask DOUBLE PRECISION,
    last_price DOUBLE PRECISION,
    raw_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_status TEXT NOT NULL DEFAULT 'ok',
    quality_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, window_start, window_seconds),
    CONSTRAINT arena_realtime_feature_quality_check
        CHECK (quality_status IN ('ok', 'degraded'))
);

CREATE INDEX IF NOT EXISTS idx_arena_realtime_feature_bars_time
    ON arena_realtime_feature_bars (symbol, window_start DESC);

CREATE TABLE IF NOT EXISTS arena_execution_gates (
    run_id UUID NOT NULL,
    algo_id TEXT NOT NULL,
    signal TEXT,
    timeframe TEXT NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    signal_score DOUBLE PRECISION,
    regime TEXT,
    expected_return_bps DOUBLE PRECISION,
    expected_cost_bps DOUBLE PRECISION,
    spread_bps DOUBLE PRECISION,
    expected_slippage_bps DOUBLE PRECISION,
    depth_score DOUBLE PRECISION,
    volatility_score DOUBLE PRECISION,
    api_latency_ms DOUBLE PRECISION,
    decision TEXT NOT NULL,
    reject_reason TEXT,
    feature_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    gate_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, algo_id),
    CONSTRAINT arena_execution_gates_signal_check
        CHECK (signal IS NULL OR signal IN ('long', 'short')),
    CONSTRAINT arena_execution_gates_decision_check
        CHECK (decision IN ('trade_allowed', 'no_trade'))
);

CREATE INDEX IF NOT EXISTS idx_arena_execution_gates_created
    ON arena_execution_gates (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_arena_execution_gates_reject
    ON arena_execution_gates (reject_reason, created_at DESC);

CREATE TABLE IF NOT EXISTS arena_parent_orders (
    parent_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID,
    algo_id TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
    side TEXT NOT NULL,
    order_intent TEXT NOT NULL,
    target_weight DOUBLE PRECISION,
    decision_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'shadow',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_parent_orders_side_check
        CHECK (side IN ('buy', 'sell')),
    CONSTRAINT arena_parent_orders_intent_check
        CHECK (order_intent IN ('post_only_limit', 'limit', 'marketable_limit', 'ioc', 'fok', 'no_trade')),
    CONSTRAINT arena_parent_orders_status_check
        CHECK (status IN ('shadow', 'submitted', 'filled', 'partially_filled', 'cancelled', 'rejected'))
);

CREATE TABLE IF NOT EXISTS arena_child_orders (
    child_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_order_id UUID NOT NULL REFERENCES arena_parent_orders(parent_order_id) ON DELETE CASCADE,
    exchange_order_id TEXT,
    order_type TEXT NOT NULL,
    side TEXT NOT NULL,
    price DOUBLE PRECISION,
    quantity DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'shadow',
    submitted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS arena_executions (
    execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    child_order_id UUID REFERENCES arena_child_orders(child_order_id) ON DELETE SET NULL,
    parent_order_id UUID REFERENCES arena_parent_orders(parent_order_id) ON DELETE SET NULL,
    exchange_trade_id TEXT,
    symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
    side TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION,
    fee_asset TEXT,
    liquidity TEXT,
    executed_at TIMESTAMPTZ NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_executions_side_check
        CHECK (side IN ('buy', 'sell')),
    CONSTRAINT arena_executions_liquidity_check
        CHECK (liquidity IS NULL OR liquidity IN ('maker', 'taker'))
);

CREATE TABLE IF NOT EXISTS arena_execution_quality (
    execution_quality_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_order_id UUID REFERENCES arena_parent_orders(parent_order_id) ON DELETE CASCADE,
    run_id UUID,
    algo_id TEXT,
    expected_cost_bps DOUBLE PRECISION,
    realized_cost_bps DOUBLE PRECISION,
    realized_slippage_bps DOUBLE PRECISION,
    spread_at_entry_bps DOUBLE PRECISION,
    fill_ratio DOUBLE PRECISION,
    maker_taker_ratio DOUBLE PRECISION,
    partial_fill_ratio DOUBLE PRECISION,
    api_latency_ms DOUBLE PRECISION,
    quality_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE VIEW arena_realtime_execution_v1_ready AS
SELECT
    'arena_realtime_execution_v1_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_realtime_feature_bars'
    ) AS has_arena_realtime_feature_bars,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_execution_gates'
    ) AS has_arena_execution_gates,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_parent_orders'
    ) AS has_arena_parent_orders,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_child_orders'
    ) AS has_arena_child_orders,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_executions'
    ) AS has_arena_executions,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_execution_quality'
    ) AS has_arena_execution_quality;

CREATE OR REPLACE VIEW arena_execution_gate_shadow_ready AS
SELECT
    'arena_execution_gate_shadow_ready' AS check_name,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_execution_gates'
          AND column_name = 'gate_snapshot'
    ) AS has_gate_snapshot,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_execution_gates'
          AND column_name = 'reject_reason'
    ) AS has_reject_reason,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_realtime_feature_bars'
          AND column_name = 'expected_slippage_bps'
    ) AS has_expected_slippage_bps;
