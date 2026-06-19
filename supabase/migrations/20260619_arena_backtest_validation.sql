-- =============================================================================
-- Arena backtest validation rubric v1
-- 목적:
-- - 백테스트 결과의 무결성, 누수 방지, 체결 규칙 재현 여부를 check 단위로 저장한다.
-- - 파라미터 튜닝 전에 validation fail/warn을 명시적으로 확인할 수 있게 한다.
-- =============================================================================

CREATE TABLE IF NOT EXISTS arena_backtest_validation_runs (
    validation_run_id UUID        PRIMARY KEY,
    backtest_run_id   UUID        NOT NULL REFERENCES arena_backtest_runs (backtest_run_id)
        ON DELETE CASCADE,
    checked_at        TIMESTAMPTZ NOT NULL,
    status            TEXT        NOT NULL,
    evaluator_version TEXT        NOT NULL DEFAULT 'arena-backtest-validation-v1',
    pass_count        INTEGER     NOT NULL DEFAULT 0,
    warn_count        INTEGER     NOT NULL DEFAULT 0,
    fail_count        INTEGER     NOT NULL DEFAULT 0,
    na_count          INTEGER     NOT NULL DEFAULT 0,
    summary           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT arena_backtest_validation_runs_status_check
        CHECK (status IN ('pass', 'warn', 'fail')),
    CONSTRAINT arena_backtest_validation_runs_count_check
        CHECK (pass_count >= 0 AND warn_count >= 0 AND fail_count >= 0 AND na_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_validation_runs_backtest
    ON arena_backtest_validation_runs (backtest_run_id, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_validation_runs_status
    ON arena_backtest_validation_runs (status, checked_at DESC);


CREATE TABLE IF NOT EXISTS arena_backtest_validation_checks (
    validation_run_id UUID        NOT NULL REFERENCES arena_backtest_validation_runs (validation_run_id)
        ON DELETE CASCADE,
    check_name        TEXT        NOT NULL,
    category          TEXT        NOT NULL,
    status            TEXT        NOT NULL,
    severity          TEXT        NOT NULL,
    message           TEXT        NOT NULL,
    observed          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    expected          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    details           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (validation_run_id, check_name),
    CONSTRAINT arena_backtest_validation_checks_status_check
        CHECK (status IN ('pass', 'warn', 'fail', 'na')),
    CONSTRAINT arena_backtest_validation_checks_severity_check
        CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    CONSTRAINT arena_backtest_validation_checks_category_check
        CHECK (category IN ('integrity', 'leakage', 'execution', 'statistics'))
);

CREATE INDEX IF NOT EXISTS idx_arena_backtest_validation_checks_status
    ON arena_backtest_validation_checks (status, severity, category);


CREATE OR REPLACE VIEW arena_backtest_validation_summary_v1 AS
SELECT
    vr.validation_run_id,
    vr.backtest_run_id,
    vr.checked_at,
    vr.status,
    vr.evaluator_version,
    br.symbol,
    br.interval,
    br.strategy_version,
    br.params_version,
    br.data_start,
    br.data_end,
    br.bar_count,
    br.algo_ids,
    vr.pass_count,
    vr.warn_count,
    vr.fail_count,
    vr.na_count,
    vr.summary
FROM arena_backtest_validation_runs vr
JOIN arena_backtest_runs br
  ON br.backtest_run_id = vr.backtest_run_id;

SELECT
    'arena_backtest_validation_ready' AS check_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'arena_backtest_validation_runs'
    ) AS has_arena_backtest_validation_runs,
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'arena_backtest_validation_checks'
    ) AS has_arena_backtest_validation_checks,
    EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'arena_backtest_validation_summary_v1'
    ) AS has_arena_backtest_validation_summary_v1;
