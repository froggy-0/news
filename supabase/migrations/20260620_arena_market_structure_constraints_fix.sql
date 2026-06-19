-- Arena market-structure constraint fix
-- Apply this after 20260620_arena_market_structure_v1.sql if that migration was
-- already applied before premium-index and market-structure layer constraints
-- were loosened.

ALTER TABLE arena_feature_registry
    DROP CONSTRAINT IF EXISTS arena_feature_registry_layer_check;

ALTER TABLE arena_feature_registry
    ADD CONSTRAINT arena_feature_registry_layer_check
    CHECK (layer IN (
        'raw_market',
        'derived_indicator',
        'macro',
        'decision',
        'label',
        'market_structure'
    ));

ALTER TABLE arena_mark_price_bars
    DROP CONSTRAINT IF EXISTS arena_mark_price_bars_price_check;

ALTER TABLE arena_mark_price_bars
    ADD CONSTRAINT arena_mark_price_bars_price_check
    CHECK (
        price_type = 'premium_index'
        OR (open > 0 AND high > 0 AND low > 0 AND close > 0)
    );
