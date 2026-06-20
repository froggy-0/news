-- Arena shadow TCA mart v1

CREATE OR REPLACE VIEW arena_shadow_tca_mart_v1 AS
SELECT
    p.parent_order_id,
    p.run_id,
    p.algo_id,
    p.symbol,
    p.side,
    p.order_intent,
    p.status,
    p.created_at,
    (p.decision_snapshot->>'signal_time')::timestamptz AS signal_time,
    p.decision_snapshot->>'timeframe' AS timeframe,
    NULLIF(p.decision_snapshot->>'arrival_mid', '')::double precision AS arrival_mid,
    NULLIF(p.decision_snapshot->>'arrival_spread_bps', '')::double precision AS arrival_spread_bps,
    NULLIF(p.decision_snapshot->>'target_notional_usd', '')::double precision AS target_notional_usd,
    NULLIF(p.decision_snapshot->>'target_qty', '')::double precision AS target_qty,
    p.decision_snapshot->'gate_decision'->>'decision' AS gate_decision,
    p.decision_snapshot->'gate_decision'->>'reject_reason' AS reject_reason,
    NULLIF(
        p.decision_snapshot->'gate_decision'->>'expected_return_bps',
        ''
    )::double precision AS expected_return_bps,
    q.expected_cost_bps,
    q.realized_cost_bps,
    q.realized_slippage_bps AS arrival_slippage_bps,
    q.spread_at_entry_bps,
    q.fill_ratio,
    q.maker_taker_ratio,
    q.partial_fill_ratio,
    q.api_latency_ms,
    q.quality_snapshot->>'quality_status' AS quality_status,
    CASE
        WHEN ABS(NULLIF(
            p.decision_snapshot->'gate_decision'->>'expected_return_bps',
            ''
        )::double precision) > 0
            THEN q.realized_cost_bps / ABS(NULLIF(
                p.decision_snapshot->'gate_decision'->>'expected_return_bps',
                ''
            )::double precision)
        ELSE NULL
    END AS cost_to_edge_ratio
FROM arena_parent_orders p
LEFT JOIN arena_execution_quality q
    ON q.parent_order_id = p.parent_order_id
WHERE p.status = 'shadow';

CREATE OR REPLACE VIEW arena_shadow_tca_daily_v1 AS
WITH mart AS (
    SELECT * FROM arena_shadow_tca_mart_v1
),
daily AS (
    SELECT
        date_trunc('day', created_at)::date AS day,
        COUNT(*) AS signal_count,
        COUNT(*) FILTER (WHERE gate_decision = 'trade_allowed') AS trade_allowed_count,
        COUNT(*) FILTER (WHERE gate_decision = 'no_trade') AS no_trade_count,
        AVG(expected_return_bps) AS avg_expected_return_bps,
        AVG(expected_cost_bps) AS avg_expected_cost_bps,
        AVG(arrival_slippage_bps) AS avg_arrival_slippage_bps,
        AVG(spread_at_entry_bps) AS avg_spread_bps,
        AVG(fill_ratio) AS avg_fill_ratio,
        AVG(cost_to_edge_ratio) AS avg_cost_to_edge_ratio,
        COUNT(*) FILTER (WHERE quality_status = 'ok')::double precision
            / NULLIF(COUNT(*), 0) AS quality_ok_ratio
    FROM mart
    GROUP BY 1
),
rejects AS (
    SELECT
        date_trunc('day', created_at)::date AS day,
        COALESCE(reject_reason, 'trade_allowed') AS reject_reason,
        COUNT(*) AS reject_count
    FROM mart
    GROUP BY 1, 2
)
SELECT
    d.*,
    (
        SELECT jsonb_object_agg(r.reject_reason, r.reject_count)
        FROM rejects r
        WHERE r.day = d.day
    ) AS reject_reason_distribution
FROM daily d;

CREATE OR REPLACE VIEW arena_shadow_tca_by_algo_v1 AS
SELECT
    algo_id,
    COUNT(*) AS signal_count,
    COUNT(*) FILTER (WHERE gate_decision = 'trade_allowed') AS trade_allowed_count,
    COUNT(*) FILTER (WHERE gate_decision = 'no_trade') AS no_trade_count,
    AVG(expected_return_bps) AS avg_expected_return_bps,
    AVG(expected_cost_bps) AS avg_expected_cost_bps,
    AVG(arrival_slippage_bps) AS avg_arrival_slippage_bps,
    AVG(spread_at_entry_bps) AS avg_spread_bps,
    AVG(fill_ratio) AS avg_fill_ratio,
    AVG(cost_to_edge_ratio) AS avg_cost_to_edge_ratio,
    COUNT(*) FILTER (WHERE quality_status = 'ok')::double precision
        / NULLIF(COUNT(*), 0) AS quality_ok_ratio
FROM arena_shadow_tca_mart_v1
GROUP BY 1;

CREATE OR REPLACE VIEW arena_tca_shadow_v1_ready AS
SELECT
    'arena_tca_shadow_v1_ready' AS check_name,
    EXISTS (
        SELECT 1
        FROM information_schema.views
        WHERE table_name = 'arena_shadow_tca_mart_v1'
    ) AS has_shadow_tca_mart,
    EXISTS (
        SELECT 1
        FROM information_schema.views
        WHERE table_name = 'arena_shadow_tca_daily_v1'
    ) AS has_shadow_tca_daily,
    EXISTS (
        SELECT 1
        FROM information_schema.views
        WHERE table_name = 'arena_shadow_tca_by_algo_v1'
    ) AS has_shadow_tca_by_algo,
    EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = 'arena_parent_orders'
    ) AS has_parent_orders,
    EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = 'arena_execution_quality'
    ) AS has_execution_quality;
