-- =============================================================================
-- arena_backtest_trades.exit_reason CHECK 제약 정정 (2026-07-31)
--
-- 발견 경위: 멀티자산 확장 P1-6 산출물을 arena_backtest_runs/trades에 영구 저장하려다
-- (scripts/analysis/persist_cross_asset_backtest.py) INSERT가 이 제약에 막혀 실패.
--
-- 원인: 이 제약은 초기(v0) exit_reason 어휘(signal_flat/signal_reverse/stop_loss/
-- end_of_data)만 허용하는데, 실제 backtest.py는 그 이후(v22~v28) 추가된
-- flat_signal(현재 이름, signal_flat 아님)·trailing_stop·target_exit·time_stop·
-- spot_semantics_migration·short_signal_spot_risk_off를 exit_reason으로 기록한다.
-- backtest_report.py의 주간 저장 호출이 이 예외를 warning으로만 삼켜서(치명적이지
-- 않게 설계) 지금까지 표면화되지 않았을 뿐 — 즉 arena_backtest_trades 저장은 이
-- 제약 도입 이후 사실상 계속 실패해왔을 가능성이 높다.
-- =============================================================================

ALTER TABLE arena_backtest_trades
    DROP CONSTRAINT IF EXISTS arena_backtest_trades_exit_reason_check;

ALTER TABLE arena_backtest_trades
    ADD CONSTRAINT arena_backtest_trades_exit_reason_check
    CHECK (exit_reason IN (
        'signal_flat',
        'flat_signal',
        'signal_reverse',
        'stop_loss',
        'trailing_stop',
        'target_exit',
        'time_stop',
        'end_of_data',
        'spot_semantics_migration',
        'short_signal_spot_risk_off'
    ));
