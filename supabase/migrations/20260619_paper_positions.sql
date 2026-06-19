-- =============================================================================
-- paper_positions — 아레나 페이퍼트레이딩 포지션 원장
-- 신호 변경 기반 오픈/클로즈 방식 (고정 7일 정산 아님)
-- 스톱로스: ATR 기반 동적 손절가 (stop_loss_price) + Binance WebSocket 감지
-- =============================================================================

CREATE TABLE IF NOT EXISTS paper_positions (
    id               BIGSERIAL        PRIMARY KEY,
    algo_id          TEXT             NOT NULL,
    direction        TEXT             NOT NULL,
    status           TEXT             NOT NULL DEFAULT 'open',
    open_time        TIMESTAMPTZ      NOT NULL,
    open_price       DOUBLE PRECISION NOT NULL,
    stop_loss_price  DOUBLE PRECISION NOT NULL,
    close_time       TIMESTAMPTZ,
    close_price      DOUBLE PRECISION,
    ret_pct          DOUBLE PRECISION,
    hit              BOOLEAN,
    hold_hours       DOUBLE PRECISION,
    is_stop_loss     BOOLEAN          NOT NULL DEFAULT FALSE,
    fee_bps          DOUBLE PRECISION NOT NULL DEFAULT 5.0,
    created_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS open_time TIMESTAMPTZ;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS open_price DOUBLE PRECISION;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS stop_loss_price DOUBLE PRECISION;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS close_time TIMESTAMPTZ;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS close_price DOUBLE PRECISION;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS hold_hours DOUBLE PRECISION;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS is_stop_loss BOOLEAN DEFAULT FALSE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'signal_time'
    ) THEN
        EXECUTE 'UPDATE paper_positions SET open_time = signal_time WHERE open_time IS NULL AND signal_time IS NOT NULL';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'entry_price'
    ) THEN
        EXECUTE 'UPDATE paper_positions SET open_price = entry_price WHERE open_price IS NULL AND entry_price IS NOT NULL';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'exit_price'
    ) THEN
        EXECUTE 'UPDATE paper_positions SET close_price = exit_price WHERE close_price IS NULL AND exit_price IS NOT NULL';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_positions' AND column_name = 'settled_at'
    ) THEN
        EXECUTE 'UPDATE paper_positions SET close_time = settled_at WHERE close_time IS NULL AND settled_at IS NOT NULL';
    END IF;
END $$;

UPDATE paper_positions
SET status = CASE WHEN close_time IS NULL THEN 'open' ELSE 'closed' END
WHERE status IS NULL;

UPDATE paper_positions
SET is_stop_loss = FALSE
WHERE is_stop_loss IS NULL;

UPDATE paper_positions
SET hold_hours = ROUND(EXTRACT(EPOCH FROM (close_time - open_time)) / 3600.0, 2)
WHERE hold_hours IS NULL
  AND open_time IS NOT NULL
  AND close_time IS NOT NULL;

-- 기존 7일 정산형 레코드에는 ATR이 없으므로, 재시작 안전용으로 5% fallback 손절가를 보존한다.
UPDATE paper_positions
SET stop_loss_price = CASE
    WHEN direction = 'short' THEN open_price * 1.05
    ELSE open_price * 0.95
END
WHERE stop_loss_price IS NULL
  AND open_price IS NOT NULL;

ALTER TABLE paper_positions ALTER COLUMN status SET DEFAULT 'open';
ALTER TABLE paper_positions ALTER COLUMN fee_bps SET DEFAULT 5.0;
ALTER TABLE paper_positions ALTER COLUMN is_stop_loss SET DEFAULT FALSE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM paper_positions
        WHERE status IS NULL
           OR open_time IS NULL
           OR open_price IS NULL
           OR stop_loss_price IS NULL
           OR is_stop_loss IS NULL
    ) THEN
        ALTER TABLE paper_positions ALTER COLUMN status SET NOT NULL;
        ALTER TABLE paper_positions ALTER COLUMN open_time SET NOT NULL;
        ALTER TABLE paper_positions ALTER COLUMN open_price SET NOT NULL;
        ALTER TABLE paper_positions ALTER COLUMN stop_loss_price SET NOT NULL;
        ALTER TABLE paper_positions ALTER COLUMN is_stop_loss SET NOT NULL;
        ALTER TABLE paper_positions ALTER COLUMN fee_bps SET NOT NULL;
        ALTER TABLE paper_positions ALTER COLUMN created_at SET NOT NULL;
    ELSE
        RAISE WARNING 'paper_positions has legacy rows with NULL required fields; backfill before enforcing NOT NULL';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_paper_positions_open
    ON paper_positions (algo_id)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_paper_positions_algo_closed
    ON paper_positions (algo_id, close_time DESC)
    WHERE status = 'closed';
