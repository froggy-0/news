-- =============================================================================
-- 멀티자산 확장 1차(BTC·ETH·SOL) 기초 스키마 (2026-07-31)
-- 설계: docs/arena/research/structural-priority-multi-asset-expansion-20260730.md
-- 계획: docs/arena/research/multi-asset-implementation-plan-20260731.md (P1-2)
--
-- paper_positions에는 symbol 컬럼이 없었음(라이브가 지금까지 BTC 단일자산이라 불필요
-- 했음). 멀티자산 shadow는 이 테이블에 쓰지 않지만(paper_positions는 라이브 전용 유지),
-- 기존 데이터가 전부 BTC임을 명시적으로 기록해두어야 이후 어떤 조회도 자산 혼동이 없다.
-- =============================================================================

ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS symbol TEXT;

-- 기존 라이브 레코드는 전부 BTC 단일자산 가동 기간에 생성됨 — 사실에 근거한 backfill.
UPDATE paper_positions SET symbol = 'BTCUSDT' WHERE symbol IS NULL;

ALTER TABLE paper_positions ALTER COLUMN symbol SET DEFAULT 'BTCUSDT';

CREATE INDEX IF NOT EXISTS idx_paper_positions_symbol_status
    ON paper_positions (symbol, status);
