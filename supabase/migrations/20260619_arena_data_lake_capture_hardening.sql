-- =============================================================================
-- Arena data lake capture hardening
-- 목적:
-- - run별 OHLCV 입력 candle set을 junction table로 영구 고정한다.
-- - capture write 실패를 arena_runs에 요약해 운영 관측성을 확보한다.
-- =============================================================================

ALTER TABLE arena_runs
    ADD COLUMN IF NOT EXISTS capture_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS capture_error_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS capture_warnings JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'arena_runs_capture_status_check'
    ) THEN
        ALTER TABLE arena_runs
            ADD CONSTRAINT arena_runs_capture_status_check
            CHECK (capture_status IN ('pending', 'ok', 'degraded'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'arena_runs_capture_error_count_check'
    ) THEN
        ALTER TABLE arena_runs
            ADD CONSTRAINT arena_runs_capture_error_count_check
            CHECK (capture_error_count >= 0);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS arena_run_ohlcv_bars (
    run_id         UUID        NOT NULL REFERENCES arena_runs (run_id) ON DELETE CASCADE,
    exchange       TEXT        NOT NULL,
    symbol         TEXT        NOT NULL,
    interval       TEXT        NOT NULL,
    open_time      TIMESTAMPTZ NOT NULL,
    close_time     TIMESTAMPTZ NOT NULL,
    input_position INTEGER     NOT NULL,
    fetched_at     TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, exchange, symbol, interval, open_time),
    CONSTRAINT arena_run_ohlcv_bars_bar_fk
        FOREIGN KEY (exchange, symbol, interval, open_time)
        REFERENCES arena_ohlcv_bars (exchange, symbol, interval, open_time),
    CONSTRAINT arena_run_ohlcv_bars_position_check
        CHECK (input_position >= 0),
    CONSTRAINT arena_run_ohlcv_bars_time_order_check
        CHECK (close_time >= open_time)
);

CREATE INDEX IF NOT EXISTS idx_arena_run_ohlcv_bars_run_position
    ON arena_run_ohlcv_bars (run_id, input_position);

CREATE INDEX IF NOT EXISTS idx_arena_run_ohlcv_bars_symbol_time
    ON arena_run_ohlcv_bars (symbol, interval, open_time DESC);

WITH ranked_bars AS (
    SELECT
        run_id,
        exchange,
        symbol,
        interval,
        open_time,
        close_time,
        ROW_NUMBER() OVER (
            PARTITION BY run_id
            ORDER BY open_time
        ) - 1 AS input_position,
        fetched_at
    FROM arena_ohlcv_bars
    WHERE run_id IS NOT NULL
)
INSERT INTO arena_run_ohlcv_bars (
    run_id,
    exchange,
    symbol,
    interval,
    open_time,
    close_time,
    input_position,
    fetched_at
)
SELECT
    run_id,
    exchange,
    symbol,
    interval,
    open_time,
    close_time,
    input_position,
    fetched_at
FROM ranked_bars
ON CONFLICT (run_id, exchange, symbol, interval, open_time)
DO UPDATE SET
    close_time = EXCLUDED.close_time,
    input_position = EXCLUDED.input_position,
    fetched_at = EXCLUDED.fetched_at;

UPDATE arena_runs
SET capture_status = CASE
        WHEN capture_error_count = 0 THEN 'ok'
        ELSE 'degraded'
    END
WHERE capture_status = 'pending'
  AND status IN ('completed', 'data_failed', 'partial_failed');

SELECT
    'arena_data_lake_capture_hardening_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'arena_run_ohlcv_bars'
    ) AS has_arena_run_ohlcv_bars,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_runs'
          AND column_name = 'capture_status'
    ) AS has_capture_status,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_runs'
          AND column_name = 'capture_error_count'
    ) AS has_capture_error_count,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'arena_runs'
          AND column_name = 'capture_warnings'
    ) AS has_capture_warnings,
    (SELECT COUNT(*) FROM arena_run_ohlcv_bars) AS linked_ohlcv_rows;
