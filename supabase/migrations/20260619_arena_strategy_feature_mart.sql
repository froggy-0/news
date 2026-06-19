-- =============================================================================
-- Arena strategy registry, feature registry, and backtest-ready mart v1
-- 목적:
-- - strategy_version / params_version / feature_set_version / risk_model_version을
--   명시적으로 관리한다.
-- - 모델 입력 feature의 단위, lag, 누수 안전성, 리스크 영향을 registry화한다.
-- - decision 단위 분석 mart를 제공해 forward return label을 일관되게 계산한다.
-- =============================================================================

ALTER TABLE arena_runs
    ADD COLUMN IF NOT EXISTS feature_set_version TEXT NOT NULL DEFAULT 'arena-features-v1',
    ADD COLUMN IF NOT EXISTS risk_model_version TEXT NOT NULL DEFAULT 'atr-stop-v1';

CREATE INDEX IF NOT EXISTS idx_arena_runs_feature_set_version
    ON arena_runs (feature_set_version, started_at DESC);

CREATE TABLE IF NOT EXISTS arena_strategy_versions (
    strategy_version  TEXT        PRIMARY KEY,
    params_version    TEXT        NOT NULL,
    feature_set_version TEXT      NOT NULL,
    risk_model_version TEXT       NOT NULL,
    runtime           TEXT        NOT NULL DEFAULT 'ec2',
    status            TEXT        NOT NULL DEFAULT 'active',
    description       TEXT        NOT NULL,
    params_snapshot   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    code_ref          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    methodology       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    deployed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_strategy_versions_status_check
        CHECK (status IN ('active', 'research', 'retired')),
    CONSTRAINT arena_strategy_versions_runtime_check
        CHECK (runtime IN ('ec2', 'lambda', 'manual'))
);

CREATE INDEX IF NOT EXISTS idx_arena_strategy_versions_feature_set
    ON arena_strategy_versions (feature_set_version);

CREATE TABLE IF NOT EXISTS arena_feature_registry (
    feature_set_version TEXT        NOT NULL,
    feature_name        TEXT        NOT NULL,
    source_table        TEXT        NOT NULL,
    source_column       TEXT        NOT NULL,
    layer               TEXT        NOT NULL,
    dtype               TEXT        NOT NULL,
    unit                TEXT        NOT NULL,
    frequency           TEXT        NOT NULL,
    lookback_bars       INTEGER,
    lag_bars            INTEGER     NOT NULL DEFAULT 0,
    leakage_safe        BOOLEAN     NOT NULL DEFAULT TRUE,
    is_model_input      BOOLEAN     NOT NULL DEFAULT TRUE,
    null_policy         TEXT        NOT NULL DEFAULT 'nullable_until_source_available',
    risk_impact         TEXT        NOT NULL,
    active              BOOLEAN     NOT NULL DEFAULT TRUE,
    description         TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (feature_set_version, feature_name),
    CONSTRAINT arena_feature_registry_layer_check
        CHECK (layer IN ('raw_market', 'derived_indicator', 'macro', 'decision', 'label', 'market_structure')),
    CONSTRAINT arena_feature_registry_risk_impact_check
        CHECK (risk_impact IN ('low', 'medium', 'high')),
    CONSTRAINT arena_feature_registry_lag_check
        CHECK (lag_bars >= 0),
    CONSTRAINT arena_feature_registry_lookback_check
        CHECK (lookback_bars IS NULL OR lookback_bars >= 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_feature_registry_active
    ON arena_feature_registry (feature_set_version, active, is_model_input);

INSERT INTO arena_strategy_versions (
    strategy_version,
    params_version,
    feature_set_version,
    risk_model_version,
    runtime,
    status,
    description,
    params_snapshot,
    code_ref,
    methodology
)
VALUES (
    'arena-ec2-v1',
    'arena-params-v1',
    'arena-features-v1',
    'atr-stop-v1',
    'ec2',
    'active',
    'EC2 BTCUSDT 4H paper-trading arena with five rule-based strategies.',
    '{
        "params_version": "arena-params-v1",
        "feature_set_version": "arena-features-v1",
        "risk_model_version": "atr-stop-v1",
        "runtime": "ec2"
    }'::jsonb,
    '{
        "module": "src/arena",
        "algorithms_module": "src/arena/algorithms.py",
        "parameters_module": "src/arena/parameters.py"
    }'::jsonb,
    '{
        "decision_frequency": "4h",
        "symbol": "BTCUSDT",
        "feature_timing": "closed_candle_only",
        "label_horizons_bars": [1, 3, 6],
        "cost_basis": "gross_forward_returns; paper_positions stores realized fee-adjusted returns"
    }'::jsonb
)
ON CONFLICT (strategy_version)
DO UPDATE SET
    params_version = EXCLUDED.params_version,
    feature_set_version = EXCLUDED.feature_set_version,
    risk_model_version = EXCLUDED.risk_model_version,
    runtime = EXCLUDED.runtime,
    status = EXCLUDED.status,
    description = EXCLUDED.description,
    params_snapshot = EXCLUDED.params_snapshot,
    code_ref = EXCLUDED.code_ref,
    methodology = EXCLUDED.methodology,
    updated_at = NOW();

INSERT INTO arena_feature_registry (
    feature_set_version,
    feature_name,
    source_table,
    source_column,
    layer,
    dtype,
    unit,
    frequency,
    lookback_bars,
    lag_bars,
    leakage_safe,
    is_model_input,
    null_policy,
    risk_impact,
    active,
    description
)
VALUES
    ('arena-features-v1', 'rsi', 'arena_indicator_snapshots', 'rsi', 'derived_indicator', 'double', 'index', '4h', 14, 0, TRUE, TRUE, 'nullable_until_source_available', 'medium', TRUE, 'Relative Strength Index computed from closed 4H closes.'),
    ('arena-features-v1', 'macd_hist', 'arena_indicator_snapshots', 'macd_hist', 'derived_indicator', 'double', 'price', '4h', 35, 0, TRUE, TRUE, 'nullable_until_source_available', 'high', TRUE, 'MACD histogram from closed 4H closes; thresholded by ATR in strategy.'),
    ('arena-features-v1', 'bb_pos', 'arena_indicator_snapshots', 'bb_pos', 'derived_indicator', 'double', 'ratio_0_1', '4h', 20, 0, TRUE, TRUE, 'nullable_until_source_available', 'medium', TRUE, 'Close position within Bollinger band, clipped by DB check to 0..1.'),
    ('arena-features-v1', 'atr', 'arena_indicator_snapshots', 'atr', 'derived_indicator', 'double', 'price', '4h', 14, 0, TRUE, TRUE, 'nullable_until_source_available', 'high', TRUE, 'Average True Range from closed 4H OHLC, used for dynamic stop distance.'),
    ('arena-features-v1', 'regime_state', 'arena_macro_snapshots', 'risk_overlay.regimeState', 'macro', 'text', 'category', '4h', NULL, 0, TRUE, TRUE, 'nullable_until_source_available', 'high', TRUE, 'Risk overlay regime state from R2 latest macro payload.'),
    ('arena-features-v1', 'fng', 'arena_macro_snapshots', 'risk_overlay.regimeRaw.fng', 'macro', 'double', 'index_0_100', '4h', NULL, 0, TRUE, TRUE, 'nullable_until_source_available', 'high', TRUE, 'Fear and Greed index used by contrarian strategy.'),
    ('arena-features-v1', 'vix_now', 'arena_macro_snapshots', 'risk_overlay.regimeRaw.vix_now', 'macro', 'double', 'index', '4h', NULL, 0, TRUE, TRUE, 'nullable_until_source_available', 'medium', TRUE, 'Current VIX level from macro risk overlay.'),
    ('arena-features-v1', 'vix_q40', 'arena_macro_snapshots', 'risk_overlay.regimeRaw.vix_q40', 'macro', 'double', 'index', '4h', NULL, 0, TRUE, TRUE, 'nullable_until_source_available', 'medium', TRUE, 'VIX 40th percentile threshold from macro risk overlay.')
ON CONFLICT (feature_set_version, feature_name)
DO UPDATE SET
    source_table = EXCLUDED.source_table,
    source_column = EXCLUDED.source_column,
    layer = EXCLUDED.layer,
    dtype = EXCLUDED.dtype,
    unit = EXCLUDED.unit,
    frequency = EXCLUDED.frequency,
    lookback_bars = EXCLUDED.lookback_bars,
    lag_bars = EXCLUDED.lag_bars,
    leakage_safe = EXCLUDED.leakage_safe,
    is_model_input = EXCLUDED.is_model_input,
    null_policy = EXCLUDED.null_policy,
    risk_impact = EXCLUDED.risk_impact,
    active = EXCLUDED.active,
    description = EXCLUDED.description,
    updated_at = NOW();

CREATE OR REPLACE VIEW arena_decision_mart_v1 AS
WITH bar_series AS (
    SELECT
        b.*,
        ROW_NUMBER() OVER (
            PARTITION BY b.exchange, b.symbol, b.interval
            ORDER BY b.open_time
        ) - 1 AS bar_index
    FROM arena_ohlcv_bars b
),
run_bar AS (
    SELECT
        r.run_id,
        bs.exchange,
        bs.symbol,
        bs.interval,
        bs.open_time AS signal_bar_open_time,
        bs.close_time AS signal_bar_close_time,
        bs.open AS signal_open,
        bs.high AS signal_high,
        bs.low AS signal_low,
        bs.close AS signal_close,
        bs.volume AS signal_volume,
        bs.bar_index
    FROM arena_runs r
    JOIN bar_series bs
      ON bs.symbol = r.symbol
     AND bs.interval = r.interval
     AND bs.close_time = r.data_timestamp
)
SELECT
    r.run_id,
    r.started_at,
    r.completed_at,
    r.status AS run_status,
    r.capture_status,
    r.symbol,
    r.interval,
    r.data_timestamp,
    r.strategy_version,
    r.params_version,
    r.feature_set_version,
    r.risk_model_version,
    d.algo_id,
    d.signal,
    d.action,
    d.skipped_reason,
    d.current_position_id,
    d.resulting_position_id,
    rb.signal_bar_open_time,
    rb.signal_bar_close_time,
    rb.signal_open,
    rb.signal_high,
    rb.signal_low,
    rb.signal_close,
    rb.signal_volume,
    ind.rsi,
    ind.macd_hist,
    ind.bb_pos,
    ind.atr,
    macro.reference_date AS macro_reference_date,
    macro.stale_hours AS macro_stale_hours,
    macro.risk_overlay ->> 'regimeState' AS regime_state,
    NULLIF(macro.risk_overlay #>> '{regimeRaw,fng}', '')::DOUBLE PRECISION AS fng,
    NULLIF(macro.risk_overlay #>> '{regimeRaw,vix_now}', '')::DOUBLE PRECISION AS vix_now,
    NULLIF(macro.risk_overlay #>> '{regimeRaw,vix_q40}', '')::DOUBLE PRECISION AS vix_q40,
    f1.close AS close_plus_1bar,
    f3.close AS close_plus_3bar,
    f6.close AS close_plus_6bar,
    (f1.close / NULLIF(rb.signal_close, 0.0) - 1.0) AS forward_return_1bar,
    (f3.close / NULLIF(rb.signal_close, 0.0) - 1.0) AS forward_return_3bar,
    (f6.close / NULLIF(rb.signal_close, 0.0) - 1.0) AS forward_return_6bar,
    CASE d.signal
        WHEN 'long' THEN (f1.close / NULLIF(rb.signal_close, 0.0) - 1.0)
        WHEN 'short' THEN -(f1.close / NULLIF(rb.signal_close, 0.0) - 1.0)
        ELSE NULL
    END AS signal_return_1bar,
    CASE d.signal
        WHEN 'long' THEN (f3.close / NULLIF(rb.signal_close, 0.0) - 1.0)
        WHEN 'short' THEN -(f3.close / NULLIF(rb.signal_close, 0.0) - 1.0)
        ELSE NULL
    END AS signal_return_3bar,
    CASE d.signal
        WHEN 'long' THEN (f6.close / NULLIF(rb.signal_close, 0.0) - 1.0)
        WHEN 'short' THEN -(f6.close / NULLIF(rb.signal_close, 0.0) - 1.0)
        ELSE NULL
    END AS signal_return_6bar,
    d.reason AS decision_reason
FROM arena_runs r
JOIN arena_decisions d
  ON d.run_id = r.run_id
LEFT JOIN run_bar rb
  ON rb.run_id = r.run_id
LEFT JOIN arena_indicator_snapshots ind
  ON ind.run_id = r.run_id
LEFT JOIN arena_macro_snapshots macro
  ON macro.run_id = r.run_id
LEFT JOIN bar_series f1
  ON f1.exchange = rb.exchange
 AND f1.symbol = rb.symbol
 AND f1.interval = rb.interval
 AND f1.bar_index = rb.bar_index + 1
LEFT JOIN bar_series f3
  ON f3.exchange = rb.exchange
 AND f3.symbol = rb.symbol
 AND f3.interval = rb.interval
 AND f3.bar_index = rb.bar_index + 3
LEFT JOIN bar_series f6
  ON f6.exchange = rb.exchange
 AND f6.symbol = rb.symbol
 AND f6.interval = rb.interval
 AND f6.bar_index = rb.bar_index + 6;

SELECT
    'arena_strategy_feature_mart_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_strategy_versions'
    ) AS has_arena_strategy_versions,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_feature_registry'
    ) AS has_arena_feature_registry,
    EXISTS (
        SELECT 1 FROM information_schema.views WHERE table_name = 'arena_decision_mart_v1'
    ) AS has_arena_decision_mart_v1,
    (SELECT COUNT(*) FROM arena_strategy_versions) AS strategy_versions,
    (SELECT COUNT(*) FROM arena_feature_registry WHERE feature_set_version = 'arena-features-v1') AS registered_features,
    (SELECT COUNT(*) FROM arena_decision_mart_v1) AS mart_rows;
