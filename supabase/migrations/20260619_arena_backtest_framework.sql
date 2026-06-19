-- =============================================================================
-- Arena backtest and walk-forward framework v1
-- 목적:
-- - 라이브 실행 규칙과 같은 fee/slippage/min_hold/stale_macro/stop_loss 규칙으로
--   과거 4H 데이터를 재생한 결과를 별도 원장에 저장한다.
-- - 파라미터 튜닝 전에 baseline backtest와 walk-forward split을 재현 가능하게 만든다.
-- =============================================================================

CREATE TABLE IF NOT EXISTS arena_backtest_runs (
    backtest_run_id    UUID        PRIMARY KEY,
    started_at         TIMESTAMPTZ NOT NULL,
    completed_at       TIMESTAMPTZ,
    status             TEXT        NOT NULL DEFAULT 'started',
    runtime            TEXT        NOT NULL DEFAULT 'research',
    symbol             TEXT        NOT NULL,
    interval           TEXT        NOT NULL,
    strategy_version   TEXT        NOT NULL,
    params_version     TEXT        NOT NULL,
    feature_set_version TEXT       NOT NULL,
    risk_model_version TEXT        NOT NULL,
    params_snapshot    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    rules_snapshot     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    data_start         TIMESTAMPTZ,
    data_end           TIMESTAMPTZ,
    bar_count          INTEGER     NOT NULL DEFAULT 0,
    warmup_bars        INTEGER     NOT NULL DEFAULT 0,
    algo_ids           TEXT[]      NOT NULL DEFAULT ARRAY[]::TEXT[],
    fee_bps            DOUBLE PRECISION NOT NULL DEFAULT 0,
    slippage_bps       DOUBLE PRECISION NOT NULL DEFAULT 0,
    macro_policy       TEXT        NOT NULL DEFAULT 'disable_when_stale',
    stop_fill_policy   TEXT        NOT NULL DEFAULT 'stop_price_or_gap_open',
    min_hold_policy    TEXT        NOT NULL DEFAULT 'same_as_live_signal_exits',
    metrics            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    notes              TEXT,
    error_message      TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_backtest_runs_status_check
        CHECK (status IN ('started', 'completed', 'failed')),
    CONSTRAINT arena_backtest_runs_runtime_check
        CHECK (runtime IN ('research', 'manual', 'ci')),
    CONSTRAINT arena_backtest_runs_bar_count_check
        CHECK (bar_count >= 0),
    CONSTRAINT arena_backtest_runs_warmup_bars_check
        CHECK (warmup_bars >= 0),
    CONSTRAINT arena_backtest_runs_cost_check
        CHECK (fee_bps >= 0 AND slippage_bps >= 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_runs_strategy_time
    ON arena_backtest_runs (strategy_version, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_runs_symbol_interval
    ON arena_backtest_runs (symbol, interval, data_end DESC);


CREATE TABLE IF NOT EXISTS arena_backtest_trades (
    id                  BIGSERIAL   PRIMARY KEY,
    backtest_run_id     UUID        NOT NULL REFERENCES arena_backtest_runs (backtest_run_id)
        ON DELETE CASCADE,
    algo_id             TEXT        NOT NULL,
    direction           TEXT        NOT NULL,
    open_time           TIMESTAMPTZ NOT NULL,
    close_time          TIMESTAMPTZ NOT NULL,
    entry_data_timestamp TIMESTAMPTZ NOT NULL,
    close_data_timestamp TIMESTAMPTZ NOT NULL,
    open_price          DOUBLE PRECISION NOT NULL,
    close_price         DOUBLE PRECISION NOT NULL,
    stop_loss_price     DOUBLE PRECISION,
    ret_pct             DOUBLE PRECISION NOT NULL,
    hold_hours          DOUBLE PRECISION NOT NULL,
    exit_reason         TEXT        NOT NULL,
    params_snapshot     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    indicator_snapshot  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    macro_snapshot      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_backtest_trades_direction_check
        CHECK (direction IN ('long', 'short')),
    CONSTRAINT arena_backtest_trades_exit_reason_check
        CHECK (exit_reason IN ('signal_flat', 'signal_reverse', 'stop_loss', 'end_of_data')),
    CONSTRAINT arena_backtest_trades_price_check
        CHECK (open_price > 0 AND close_price > 0),
    CONSTRAINT arena_backtest_trades_hold_check
        CHECK (hold_hours >= 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_trades_run_algo_time
    ON arena_backtest_trades (backtest_run_id, algo_id, open_time);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_trades_exit_reason
    ON arena_backtest_trades (backtest_run_id, exit_reason);


CREATE TABLE IF NOT EXISTS arena_backtest_equity_curve (
    backtest_run_id    UUID        NOT NULL REFERENCES arena_backtest_runs (backtest_run_id)
        ON DELETE CASCADE,
    algo_id            TEXT        NOT NULL,
    data_timestamp     TIMESTAMPTZ NOT NULL,
    bar_open_time      TIMESTAMPTZ NOT NULL,
    bar_close_time     TIMESTAMPTZ NOT NULL,
    equity             DOUBLE PRECISION NOT NULL,
    realized_ret_pct   DOUBLE PRECISION NOT NULL DEFAULT 0,
    cumulative_ret_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    drawdown_pct       DOUBLE PRECISION NOT NULL DEFAULT 0,
    open_position      JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (backtest_run_id, algo_id, data_timestamp),
    CONSTRAINT arena_backtest_equity_curve_equity_check
        CHECK (equity > 0),
    CONSTRAINT arena_backtest_equity_curve_drawdown_check
        CHECK (drawdown_pct <= 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_equity_curve_algo_time
    ON arena_backtest_equity_curve (algo_id, data_timestamp);


CREATE TABLE IF NOT EXISTS arena_walk_forward_splits (
    split_id          UUID        PRIMARY KEY,
    split_name        TEXT        NOT NULL UNIQUE,
    symbol            TEXT        NOT NULL,
    interval          TEXT        NOT NULL,
    strategy_version  TEXT        NOT NULL,
    params_version    TEXT        NOT NULL,
    train_start       TIMESTAMPTZ NOT NULL,
    train_end         TIMESTAMPTZ NOT NULL,
    test_start        TIMESTAMPTZ NOT NULL,
    test_end          TIMESTAMPTZ NOT NULL,
    embargo_bars      INTEGER     NOT NULL DEFAULT 0,
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_walk_forward_splits_time_check
        CHECK (train_start < train_end AND train_end <= test_start AND test_start < test_end),
    CONSTRAINT arena_walk_forward_splits_embargo_check
        CHECK (embargo_bars >= 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_walk_forward_splits_symbol_interval
    ON arena_walk_forward_splits (symbol, interval, train_start, test_start);


CREATE OR REPLACE VIEW arena_backtest_run_summary_v1 AS
SELECT
    r.backtest_run_id,
    r.started_at,
    r.completed_at,
    r.status,
    r.symbol,
    r.interval,
    r.strategy_version,
    r.params_version,
    r.feature_set_version,
    r.risk_model_version,
    r.data_start,
    r.data_end,
    r.bar_count,
    r.warmup_bars,
    r.algo_ids,
    r.fee_bps,
    r.slippage_bps,
    r.metrics,
    COUNT(t.id) AS trade_count,
    AVG(t.ret_pct) AS avg_trade_ret_pct,
    SUM(t.ret_pct) AS sum_trade_ret_pct,
    SUM(CASE WHEN t.ret_pct > 0 THEN 1 ELSE 0 END)::DOUBLE PRECISION
        / NULLIF(COUNT(t.id), 0) AS win_rate
FROM arena_backtest_runs r
LEFT JOIN arena_backtest_trades t
  ON t.backtest_run_id = r.backtest_run_id
GROUP BY r.backtest_run_id;

SELECT
    'arena_backtest_framework_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_backtest_runs'
    ) AS has_arena_backtest_runs,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_backtest_trades'
    ) AS has_arena_backtest_trades,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_backtest_equity_curve'
    ) AS has_arena_backtest_equity_curve,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_walk_forward_splits'
    ) AS has_arena_walk_forward_splits,
    EXISTS (
        SELECT 1 FROM information_schema.views WHERE table_name = 'arena_backtest_run_summary_v1'
    ) AS has_arena_backtest_run_summary_v1;
