"""주간 자동 백테스트 리포트 — 최근 N봉 시뮬레이션 후 Slack 요약 전송.

매주 월요일 09:10 KST(00:10 UTC) 스케줄러가 호출.
기존 backtest.run_replay() 엔진을 그대로 재사용하므로 live와 100% 동일한 비용·스톱·레짐 로직.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from . import backtest, positions, slack_notify

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

REPORT_BARS = 300  # 최근 300봉 ≈ 50일 (4H 기준)


def _fmt_pct(v: float | None, *, sign: bool = False) -> str:
    if v is None:
        return "—"
    if sign:
        return f"{v * 100:+.1f}%"
    return f"{v * 100:.1f}%"


def _fmt_hold(v: float | None) -> str:
    return f"{v:.0f}h" if v is not None else "—"


def _algo_row(algo_id: str, m: dict[str, Any]) -> str:
    name = {
        "regime_trend": "REGIME_TREND",
        "fng_contrarian": "FNG_CONTRA",
        "vix_rsi": "VIX_RSI",
        "macd_momentum": "MACD_MOMT",
        "multi_factor": "MULTI_FACT",
        "omnibus": "OMNIBUS",
    }.get(algo_id, algo_id[:12].upper())
    n = m["trade_count"]
    if n == 0:
        return f"{name:<12}   0    —       —        —      —"
    wr = _fmt_pct(m["win_rate"])
    ret = _fmt_pct(m["total_return_pct"], sign=True)
    dd = _fmt_pct(m["max_drawdown_pct"], sign=True)
    hold = _fmt_hold(m["avg_hold_hours"])
    return f"{name:<12}  {n:>2}  {wr:>5}  {ret:>7}  {dd:>7}  {hold:>4}"


def build_summary(result: backtest.BacktestResult) -> dict[str, Any]:
    """BacktestResult → Slack 전송용 요약 dict."""
    frames = result.frames
    metrics = result.metrics["by_algo"]
    total_trades = sum(m["trade_count"] for m in metrics.values())
    rows = [_algo_row(aid, metrics[aid]) for aid in metrics]
    header_row = f"{'ALGO':<12}   N   WIN%     RET     DD   HOLD"
    table = "\n".join([header_row, "-" * 48, *rows])
    data_start = frames[0].bar.open_time.strftime("%Y-%m-%d") if frames else "—"
    data_end = frames[-1].bar.close_time.strftime("%Y-%m-%d") if frames else "—"
    data_days = (
        round((frames[-1].bar.close_time - frames[0].bar.open_time).total_seconds() / 86400)
        if len(frames) >= 2
        else 0
    )
    return {
        "table": table,
        "data_start": data_start,
        "data_end": data_end,
        "data_days": data_days,
        "bar_count": len(frames),
        "total_trades": total_trades,
        "params_version": result.settings.params_version,
        "strategy_version": result.settings.strategy_version,
        "backtest_run_id": result.backtest_run_id,
        "by_algo": metrics,
    }


async def run_and_notify() -> None:
    """최근 REPORT_BARS봉 백테스트 실행 후 Slack 리포트 전송."""
    started_at = datetime.now(timezone.utc)
    try:
        db = positions.db()
        warmup = backtest.BacktestSettings().warmup_bars
        frames = await backtest.load_frames_from_supabase(
            db,
            limit=REPORT_BARS + warmup,
        )
        if not frames:
            logger.warning("backtest_report: 프레임 없음 — 스킵")
            return
        funding = await backtest.load_funding_events_from_supabase(
            db,
            from_date=frames[0].bar.close_time,
            to_date=frames[-1].bar.close_time,
        )
        result = backtest.run_replay(
            frames,
            settings=backtest.BacktestSettings(),
            funding_events=funding,
        )
        # P-C(2026-07-10): 주간 결과를 arena_backtest_runs에 저장 → /arena-status 라이브 vs
        #   백테스트 기준선을 주간 갱신(현재 params·최근 날짜). 이전엔 Slack 전용이라 저장
        #   테이블이 초기 CLI 실행분(v7·수주 전)에 고정돼 있었음. macro는 arena_macro_snapshots
        #   기반이라 라이브 커버 구간만 게이트 유효(저장본 한계는 스킬 문서에 명시). 저장 실패는
        #   비치명 — Slack 리포트는 계속 전송.
        try:
            await backtest.save_result_to_supabase(db, result)
        except Exception as exc:
            logger.warning("backtest_report DB 저장 실패(무시): %s", exc)
        summary = build_summary(result)
        elapsed = round((datetime.now(timezone.utc) - started_at).total_seconds())
        logger.info(
            "backtest_report 완료: %d frames / %d trades / %ds",
            len(frames),
            len(result.trades),
            elapsed,
        )
        await slack_notify.notify_backtest_report(summary)
    except Exception as exc:
        logger.error("backtest_report 오류: %s", exc, exc_info=True)
        try:
            await slack_notify.notify_error("주간 백테스트 리포트", exc, severity="error")
        except Exception:
            pass
