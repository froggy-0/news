-- =============================================================================
-- paper_positions — strategy/parameter snapshot columns
-- 목적: 각 포지션이 어떤 전략 버전, 파라미터, 지표, 매크로 입력으로 열렸는지 보존한다.
-- =============================================================================

ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS strategy_version TEXT;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS params_version TEXT;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS params_snapshot JSONB;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS indicator_snapshot JSONB;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS macro_snapshot JSONB;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS market_snapshot JSONB;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS signal_reason JSONB;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS runtime TEXT;

UPDATE paper_positions
SET strategy_version = 'legacy'
WHERE strategy_version IS NULL;

UPDATE paper_positions
SET params_version = 'legacy'
WHERE params_version IS NULL;

UPDATE paper_positions
SET params_snapshot = '{}'::jsonb
WHERE params_snapshot IS NULL;

UPDATE paper_positions
SET indicator_snapshot = '{}'::jsonb
WHERE indicator_snapshot IS NULL;

UPDATE paper_positions
SET macro_snapshot = '{}'::jsonb
WHERE macro_snapshot IS NULL;

UPDATE paper_positions
SET market_snapshot = '{}'::jsonb
WHERE market_snapshot IS NULL;

UPDATE paper_positions
SET signal_reason = '{}'::jsonb
WHERE signal_reason IS NULL;

UPDATE paper_positions
SET runtime = 'ec2'
WHERE runtime IS NULL;

ALTER TABLE paper_positions ALTER COLUMN strategy_version SET DEFAULT 'legacy';
ALTER TABLE paper_positions ALTER COLUMN params_version SET DEFAULT 'legacy';
ALTER TABLE paper_positions ALTER COLUMN params_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN indicator_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN macro_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN market_snapshot SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN signal_reason SET DEFAULT '{}'::jsonb;
ALTER TABLE paper_positions ALTER COLUMN runtime SET DEFAULT 'ec2';

ALTER TABLE paper_positions ALTER COLUMN strategy_version SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN params_version SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN params_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN indicator_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN macro_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN market_snapshot SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN signal_reason SET NOT NULL;
ALTER TABLE paper_positions ALTER COLUMN runtime SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_paper_positions_strategy_version
    ON paper_positions (strategy_version, open_time DESC);
