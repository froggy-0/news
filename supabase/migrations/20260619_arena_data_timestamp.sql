-- =============================================================================
-- paper_positions — data_timestamp
-- 목적: 진입 판단에 사용한 데이터 기준시각을 open_time과 분리해 보존한다.
-- 정의: EC2 arena에서는 마지막 Binance 4H closed candle close time.
-- =============================================================================

ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS data_timestamp TIMESTAMPTZ;

UPDATE paper_positions
SET data_timestamp = open_time
WHERE data_timestamp IS NULL
  AND open_time IS NOT NULL;

ALTER TABLE paper_positions ALTER COLUMN data_timestamp SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_paper_positions_data_timestamp
    ON paper_positions (data_timestamp DESC);
