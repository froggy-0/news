-- ETH/SOL 아레나 대시보드 보조용 뉴스 헤드라인 (2026-08-03).
-- 순수 표시용 테이블 — 트레이딩 로직 미접촉(src/arena/asset_news.py 참조).

CREATE TABLE IF NOT EXISTS arena_asset_news (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol       TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    url          TEXT        NOT NULL,
    source       TEXT,
    published_at TIMESTAMPTZ,
    summary      TEXT,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, url)
);

CREATE INDEX IF NOT EXISTS idx_arena_asset_news_symbol_pub
    ON arena_asset_news (symbol, published_at DESC);

ALTER TABLE arena_asset_news ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_select" ON arena_asset_news FOR SELECT TO anon USING (true);

GRANT SELECT ON arena_asset_news TO anon;
