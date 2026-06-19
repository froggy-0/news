-- Arena portfolio risk layer v1
--
-- 목적:
-- - 알고리즘별 독립 포지션을 전체 포트폴리오 노출 관점으로 제한한다.
-- - 라이브와 백테스트가 같은 risk decision/snapshot을 남기게 한다.

ALTER TABLE paper_positions
    ADD COLUMN IF NOT EXISTS risk_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE arena_decisions
    ADD COLUMN IF NOT EXISTS risk_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS risk_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE arena_decisions
    DROP CONSTRAINT IF EXISTS arena_decisions_action_check;

ALTER TABLE arena_decisions
    ADD CONSTRAINT arena_decisions_action_check
        CHECK (
            action IN (
                'open',
                'close_flat',
                'reverse',
                'hold',
                'flat_skip',
                'min_hold_skip',
                'risk_blocked',
                'error'
            )
        );

CREATE TABLE IF NOT EXISTS arena_risk_events (
    risk_event_id UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID        REFERENCES arena_runs (run_id) ON DELETE CASCADE,
    algo_id       TEXT        NOT NULL,
    position_id   BIGINT      REFERENCES paper_positions (id),
    event_type    TEXT        NOT NULL,
    risk_decision JSONB       NOT NULL DEFAULT '{}'::jsonb,
    risk_snapshot JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arena_risk_events_run_algo
    ON arena_risk_events (run_id, algo_id);

CREATE INDEX IF NOT EXISTS idx_arena_risk_events_created
    ON arena_risk_events (created_at DESC);

CREATE TABLE IF NOT EXISTS arena_risk_state (
    algo_id            TEXT        NOT NULL,
    risk_model_version TEXT        NOT NULL,
    status             TEXT        NOT NULL DEFAULT 'active',
    reason             TEXT,
    triggered_at       TIMESTAMPTZ,
    cooldown_until     TIMESTAMPTZ,
    state_snapshot     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (algo_id, risk_model_version),
    CONSTRAINT arena_risk_state_status_check
        CHECK (status IN ('active', 'killed', 'cooldown'))
);

CREATE INDEX IF NOT EXISTS idx_arena_risk_state_status
    ON arena_risk_state (status, updated_at DESC);

ALTER TABLE arena_backtest_trades
    ADD COLUMN IF NOT EXISTS risk_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS arena_backtest_risk_events (
    backtest_run_id UUID        NOT NULL REFERENCES arena_backtest_runs (backtest_run_id) ON DELETE CASCADE,
    algo_id         TEXT        NOT NULL,
    data_timestamp  TIMESTAMPTZ NOT NULL,
    signal          TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,
    risk_decision   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    risk_snapshot   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (backtest_run_id, algo_id, data_timestamp, event_type),
    CONSTRAINT arena_backtest_risk_events_signal_check
        CHECK (signal IN ('long', 'short'))
);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_risk_events_run_time
    ON arena_backtest_risk_events (backtest_run_id, data_timestamp);

CREATE OR REPLACE VIEW arena_portfolio_risk_layer_ready_v1 AS
SELECT
    'arena_portfolio_risk_layer_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'risk_snapshot'
    ) AS has_position_risk_snapshot,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_decisions' AND column_name = 'risk_decision'
    ) AS has_decision_risk_decision,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'arena_decisions' AND column_name = 'risk_snapshot'
    ) AS has_decision_risk_snapshot,
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'arena_risk_events'
    ) AS has_arena_risk_events,
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'arena_risk_state'
    ) AS has_arena_risk_state,
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'arena_backtest_risk_events'
    ) AS has_arena_backtest_risk_events;
