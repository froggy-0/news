-- =============================================================================
-- Arena walk-forward enhancements
-- 목적:
-- - arena_walk_forward_splits에 risk_model_version 컬럼 추가
-- - backtest report mart 뷰 추가 (end_of_data 분리, risk event count 포함)
-- =============================================================================

-- risk_model_version 컬럼 추가 (이미 존재하면 무시)
ALTER TABLE arena_walk_forward_splits
    ADD COLUMN IF NOT EXISTS risk_model_version TEXT NOT NULL DEFAULT '';


-- =============================================================================
-- Backtest report mart v1
-- 각 backtest run × algo 조합에 대해 거래 분류, 성과, validation 상태를 한 행으로 집계한다.
-- end_of_data 거래와 정상 거래를 분리해 표시한다.
-- =============================================================================

CREATE OR REPLACE VIEW arena_backtest_report_mart_v1 AS
WITH run_algos AS (
    -- unnest는 FROM/JOIN 안에서만 허용 — CTE로 먼저 펼침
    SELECT r.backtest_run_id, a.algo_id
    FROM arena_backtest_runs r
    CROSS JOIN LATERAL unnest(r.algo_ids) AS a(algo_id)
),
trade_agg AS (
    SELECT
        t.backtest_run_id,
        t.algo_id,
        COUNT(*) AS trade_count,
        COUNT(*) FILTER (WHERE t.exit_reason IN ('signal_flat', 'signal_reverse'))
            AS normal_exit_trade_count,
        COUNT(*) FILTER (WHERE t.exit_reason = 'end_of_data')
            AS end_of_data_trade_count,
        COUNT(*) FILTER (WHERE t.exit_reason = 'stop_loss')
            AS stop_loss_trade_count,
        SUM(CASE WHEN t.ret_pct > 0 THEN 1.0 ELSE 0.0 END)
            / NULLIF(COUNT(*), 0) AS win_rate,
        SUM(t.ret_pct) AS sum_ret_pct,
        SUM(t.ret_pct) FILTER (WHERE t.exit_reason != 'end_of_data')
            AS sum_ret_ex_end_of_data_pct
    FROM arena_backtest_trades t
    GROUP BY t.backtest_run_id, t.algo_id
),
equity_agg AS (
    SELECT
        e.backtest_run_id,
        e.algo_id,
        MIN(e.drawdown_pct) AS max_drawdown_pct,
        MAX(e.cumulative_ret_pct) AS peak_cumulative_ret_pct
    FROM arena_backtest_equity_curve e
    GROUP BY e.backtest_run_id, e.algo_id
),
risk_event_agg AS (
    SELECT
        re.backtest_run_id,
        re.algo_id,
        COUNT(*) AS risk_event_count
    FROM arena_backtest_risk_events re
    GROUP BY re.backtest_run_id, re.algo_id
),
validation_agg AS (
    -- 최신 validation run만 사용 (한 backtest에 여러 번 validation이 가능)
    SELECT DISTINCT ON (vr.backtest_run_id)
        vr.backtest_run_id,
        vr.status AS validation_status,
        vr.fail_count,
        vr.warn_count
    FROM arena_backtest_validation_runs vr
    ORDER BY vr.backtest_run_id, vr.checked_at DESC
)
SELECT
    ra.backtest_run_id,
    ra.algo_id,
    r.symbol,
    r.interval,
    r.strategy_version,
    r.params_version,
    r.risk_model_version,
    r.data_start,
    r.data_end,
    r.bar_count,
    r.fee_bps,
    r.slippage_bps,
    -- trade breakdown
    COALESCE(ta.trade_count, 0) AS trade_count,
    COALESCE(ta.normal_exit_trade_count, 0) AS normal_exit_trade_count,
    COALESCE(ta.end_of_data_trade_count, 0) AS end_of_data_trade_count,
    COALESCE(ta.stop_loss_trade_count, 0) AS stop_loss_trade_count,
    -- performance
    ta.win_rate,
    ta.sum_ret_pct AS total_return_pct,
    ta.sum_ret_ex_end_of_data_pct AS total_return_ex_end_of_data_pct,
    ea.max_drawdown_pct,
    -- risk blocks
    COALESCE(rea.risk_event_count, 0) AS risk_event_count,
    -- validation
    va.validation_status,
    COALESCE(va.fail_count, 0) AS fail_count,
    COALESCE(va.warn_count, 0) AS warn_count,
    -- research_only flag: small sample warning matches backtest_validation thresholds
    (
        COALESCE(ta.trade_count, 0) < 30
        OR r.bar_count < 180
    ) AS research_only
FROM run_algos ra
JOIN arena_backtest_runs r ON r.backtest_run_id = ra.backtest_run_id
LEFT JOIN trade_agg ta
  ON ta.backtest_run_id = ra.backtest_run_id
 AND ta.algo_id = ra.algo_id
LEFT JOIN equity_agg ea
  ON ea.backtest_run_id = ra.backtest_run_id
 AND ea.algo_id = ra.algo_id
LEFT JOIN risk_event_agg rea
  ON rea.backtest_run_id = ra.backtest_run_id
 AND rea.algo_id = ra.algo_id
LEFT JOIN validation_agg va
  ON va.backtest_run_id = ra.backtest_run_id;


-- =============================================================================
-- Backtest algo summary v1
-- algo × strategy_version 단위로 전체 run에 걸친 집계 (연구용 비교 뷰)
-- =============================================================================

CREATE OR REPLACE VIEW arena_backtest_algo_summary_v1 AS
SELECT
    m.algo_id,
    m.strategy_version,
    m.params_version,
    m.risk_model_version,
    COUNT(DISTINCT m.backtest_run_id) AS run_count,
    SUM(m.trade_count) AS total_trade_count,
    SUM(m.normal_exit_trade_count) AS total_normal_exit_count,
    SUM(m.end_of_data_trade_count) AS total_end_of_data_count,
    SUM(m.stop_loss_trade_count) AS total_stop_loss_count,
    SUM(m.risk_event_count) AS total_risk_event_count,
    AVG(m.win_rate) AS avg_win_rate,
    AVG(m.total_return_pct) AS avg_total_return_pct,
    AVG(m.total_return_ex_end_of_data_pct) AS avg_total_return_ex_eod_pct,
    MIN(m.max_drawdown_pct) AS worst_drawdown_pct,
    COUNT(*) FILTER (WHERE m.research_only) AS research_only_run_count
FROM arena_backtest_report_mart_v1 m
GROUP BY m.algo_id, m.strategy_version, m.params_version, m.risk_model_version;


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
