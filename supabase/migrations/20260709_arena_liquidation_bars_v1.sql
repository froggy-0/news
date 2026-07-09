-- WI-9: Binance 선물 강제청산(forceOrder) 4h 버킷 집계 저장.
-- 수집 전용 — 트레이딩 경로와 분리. 역발산 계열(fng_contrarian·omnibus REBOUND)의
-- '매도 소진(캐피출레이션)' 직접 증거. 지표 연결은 30일+ 축적 후 별도 WI(v2).

CREATE TABLE IF NOT EXISTS arena_liquidation_bars (
    bar_start TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    long_liq_usd DOUBLE PRECISION NOT NULL DEFAULT 0,   -- SELL forceOrder(롱 강제청산) 명목합
    short_liq_usd DOUBLE PRECISION NOT NULL DEFAULT 0,  -- BUY forceOrder(숏 강제청산) 명목합
    long_liq_count INTEGER NOT NULL DEFAULT 0,
    short_liq_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bar_start, symbol)
);

CREATE INDEX IF NOT EXISTS idx_arena_liquidation_bars_symbol_start
    ON arena_liquidation_bars (symbol, bar_start DESC);
