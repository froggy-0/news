-- =============================================================================
-- Arena data lake v0
-- 목적: 거래 발생 여부와 무관하게 4H 판단 단위의 raw/derived/decision 데이터를 분리 저장한다.
--
-- 설계 원칙:
-- - raw OHLCV와 derived indicators를 분리한다.
-- - macro 원본 payload를 보존해 향후 risk overlay 재계산을 가능하게 한다.
-- - paper_positions는 체결/포지션 원장으로 유지하고, arena_decisions가 판단 원장을 맡는다.
-- - 여러 symbol/interval/strategy_version으로 확장 가능하게 key를 둔다.
-- =============================================================================

CREATE TABLE IF NOT EXISTS arena_runs (
    run_id           UUID        PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL,
    completed_at     TIMESTAMPTZ,
    status           TEXT        NOT NULL DEFAULT 'started',
    runtime          TEXT        NOT NULL DEFAULT 'ec2',
    symbol           TEXT        NOT NULL,
    interval         TEXT        NOT NULL,
    data_timestamp   TIMESTAMPTZ,
    strategy_version TEXT        NOT NULL,
    params_version   TEXT        NOT NULL,
    params_snapshot  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_runs_status_check
        CHECK (status IN ('started', 'completed', 'data_failed', 'partial_failed')),
    CONSTRAINT arena_runs_runtime_check
        CHECK (runtime IN ('ec2', 'lambda', 'manual'))
);

CREATE INDEX IF NOT EXISTS idx_arena_runs_started_at
    ON arena_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_arena_runs_strategy_version
    ON arena_runs (strategy_version, started_at DESC);


CREATE TABLE IF NOT EXISTS arena_ohlcv_bars (
    exchange               TEXT        NOT NULL,
    symbol                 TEXT        NOT NULL,
    interval               TEXT        NOT NULL,
    open_time              TIMESTAMPTZ NOT NULL,
    close_time             TIMESTAMPTZ NOT NULL,
    open                   DOUBLE PRECISION NOT NULL,
    high                   DOUBLE PRECISION NOT NULL,
    low                    DOUBLE PRECISION NOT NULL,
    close                  DOUBLE PRECISION NOT NULL,
    volume                 DOUBLE PRECISION NOT NULL,
    quote_volume           DOUBLE PRECISION,
    trade_count            BIGINT,
    taker_buy_base_volume  DOUBLE PRECISION,
    taker_buy_quote_volume DOUBLE PRECISION,
    raw_payload            JSONB       NOT NULL,
    run_id                 UUID        REFERENCES arena_runs (run_id),
    fetched_at             TIMESTAMPTZ NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, symbol, interval, open_time),
    CONSTRAINT arena_ohlcv_bars_price_check
        CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CONSTRAINT arena_ohlcv_bars_ohlc_shape_check
        CHECK (high >= low AND high >= open AND high >= close AND low <= open AND low <= close),
    CONSTRAINT arena_ohlcv_bars_time_order_check
        CHECK (close_time >= open_time)
);

CREATE INDEX IF NOT EXISTS idx_arena_ohlcv_bars_symbol_interval_time
    ON arena_ohlcv_bars (symbol, interval, open_time DESC);

CREATE INDEX IF NOT EXISTS idx_arena_ohlcv_bars_run_id
    ON arena_ohlcv_bars (run_id);


CREATE TABLE IF NOT EXISTS arena_macro_snapshots (
    run_id         UUID        PRIMARY KEY REFERENCES arena_runs (run_id),
    fetched_at     TIMESTAMPTZ NOT NULL,
    source_url     TEXT        NOT NULL,
    reference_date DATE,
    stale_hours    DOUBLE PRECISION,
    payload_hash   TEXT        NOT NULL,
    payload        JSONB       NOT NULL,
    risk_overlay   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arena_macro_snapshots_reference_date
    ON arena_macro_snapshots (reference_date DESC);

CREATE INDEX IF NOT EXISTS idx_arena_macro_snapshots_payload_hash
    ON arena_macro_snapshots (payload_hash);


CREATE TABLE IF NOT EXISTS arena_indicator_snapshots (
    run_id           UUID        PRIMARY KEY REFERENCES arena_runs (run_id),
    symbol           TEXT        NOT NULL,
    interval         TEXT        NOT NULL,
    data_timestamp   TIMESTAMPTZ NOT NULL,
    params_version   TEXT        NOT NULL,
    indicator_params JSONB       NOT NULL DEFAULT '{}'::jsonb,
    rsi              DOUBLE PRECISION,
    macd_hist        DOUBLE PRECISION,
    bb_pos           DOUBLE PRECISION,
    atr              DOUBLE PRECISION,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_indicator_snapshots_bb_pos_check
        CHECK (bb_pos IS NULL OR (bb_pos >= 0 AND bb_pos <= 1)),
    CONSTRAINT arena_indicator_snapshots_atr_check
        CHECK (atr IS NULL OR atr >= 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_indicator_snapshots_symbol_time
    ON arena_indicator_snapshots (symbol, interval, data_timestamp DESC);


CREATE TABLE IF NOT EXISTS arena_decisions (
    run_id                UUID        NOT NULL REFERENCES arena_runs (run_id),
    algo_id               TEXT        NOT NULL,
    signal                TEXT,
    action                TEXT        NOT NULL,
    reason                JSONB       NOT NULL DEFAULT '{}'::jsonb,
    current_position_id   BIGINT      REFERENCES paper_positions (id),
    resulting_position_id BIGINT      REFERENCES paper_positions (id),
    skipped_reason        TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, algo_id),
    CONSTRAINT arena_decisions_signal_check
        CHECK (signal IS NULL OR signal IN ('long', 'short')),
    CONSTRAINT arena_decisions_action_check
        CHECK (
            action IN (
                'open',
                'close_flat',
                'reverse',
                'hold',
                'flat_skip',
                'min_hold_skip',
                'error'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_arena_decisions_algo_created
    ON arena_decisions (algo_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_arena_decisions_action_created
    ON arena_decisions (action, created_at DESC);


SELECT
    'arena_data_lake_v0_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_runs'
    ) AS has_arena_runs,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_ohlcv_bars'
    ) AS has_arena_ohlcv_bars,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_macro_snapshots'
    ) AS has_arena_macro_snapshots,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_indicator_snapshots'
    ) AS has_arena_indicator_snapshots,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_decisions'
    ) AS has_arena_decisions;
