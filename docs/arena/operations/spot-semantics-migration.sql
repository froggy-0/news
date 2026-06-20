-- Spot semantics migration operational SQL
--
-- 1) 스키마 적용 후 readiness 확인
SELECT * FROM arena_spot_semantics_v1_ready;

-- 2) 현재 열려 있는 synthetic short를 최신 저장 OHLCV close로 닫고 legacy simulation으로 분리한다.
WITH latest_spot_close AS (
    SELECT close::double precision AS close_price, close_time
    FROM arena_ohlcv_bars
    WHERE symbol = 'BTCUSDT'
      AND interval = '4h'
    ORDER BY close_time DESC
    LIMIT 1
),
legacy_open_shorts AS (
    SELECT p.*
    FROM paper_positions p
    WHERE p.status = 'open'
      AND p.direction = 'short'
)
UPDATE paper_positions p
SET
    status = 'closed',
    close_time = latest_spot_close.close_time,
    close_price = latest_spot_close.close_price,
    ret_pct = -((latest_spot_close.close_price / NULLIF(p.open_price, 0.0)) - 1.0)
              - ((COALESCE(p.fee_bps, 5.0) * 2.0) / 10000.0)
              - ((COALESCE(p.slippage_bps, 0.0) * 2.0) / 10000.0)
              - (COALESCE(p.spread_bps_round_trip, 0.0) / 10000.0),
    hit = (
        -((latest_spot_close.close_price / NULLIF(p.open_price, 0.0)) - 1.0)
        - ((COALESCE(p.fee_bps, 5.0) * 2.0) / 10000.0)
        - ((COALESCE(p.slippage_bps, 0.0) * 2.0) / 10000.0)
        - (COALESCE(p.spread_bps_round_trip, 0.0) / 10000.0)
    ) > 0,
    hold_hours = EXTRACT(EPOCH FROM (latest_spot_close.close_time - p.open_time)) / 3600.0,
    close_reason = 'spot_semantics_migration',
    product_type = 'legacy_perp_sim',
    position_semantics = 'perp_long_short_sim'
FROM latest_spot_close, legacy_open_shorts s
WHERE p.id = s.id
  AND latest_spot_close.close_price > 0.0;

-- 3) 이미 닫힌 과거 short도 spot 성과 mart에서 제외되도록 legacy label로 재분류한다.
UPDATE paper_positions
SET
    product_type = 'legacy_perp_sim',
    position_semantics = 'perp_long_short_sim',
    close_reason = COALESCE(close_reason, 'spot_semantics_migration')
WHERE direction = 'short';

-- 4) 정리 후 open spot short가 없는지 재확인
SELECT * FROM arena_spot_semantics_v1_ready;
