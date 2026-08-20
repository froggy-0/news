"""신규 알고 후보 4번째 — Riptide: 선물 프리미엄 지수(premium index) 극단 양수→음수
플립(디레버리징 캡추레이션) 역발산 백테스트 (2026-08-20).

배경: 사용자가 "펀딩비 극단 양수→음수 플립을 추세반전에 베팅"하는 기법을 물어봐서, 이미
검증된 것(Undertow — funding_zscore 정적 레벨 임계값, 2026-08-14 기각)과 겹치지 않는
새 가설을 찾음. Undertow는 "현재 레벨이 극단적으로 음수인가"(상태)를 봤지 "최근 극단
양수였다가 지금 막 음수로 전환됐는가"(디레버리징 이벤트)는 테스트한 적이 없음 — 이벤트
탐지와 레벨 임계값은 정보구조가 다름(문헌상 캡추레이션 마커는 후자에 가까움).

또한 데이터원 자체도 다름: funding_zscore는 8h 정산 funding rate의 BTC공유 z-score
(2026-08-01 검증: ETH corr=0.476·SOL corr=0.082로 자산고유성 낮음, 기존 6알고가 쓰는 값)
인 반면, premium_index(마크가격 대비 무기한선물 프리미엄, 연속 측정)는 이 저장소가
market_structure.py로 이미 수집은 하면서도(arena_mark_price_bars) 주 신호로 쓴 적이
전혀 없는 데이터(전수 grep 확인, 2026-08-20) — funding rate의 더 고해상도·자산고유
선행판(funding rate는 premium index를 일정 기간 평균해 산출되는 파생값).

방법론: new_algo_candidates_backtest.py와 동일 — 단일 사전 사양(그리드 아님), DSR
n_trials=1, 부트스트랩 95%CI, 전/후반 분할. premium_index는 Binance
/fapi/v1/premiumIndexKlines(전체 히스토리 지원 확인됨, binance-data-catalog-audit
-20260811.md)에서 직접 자산별로 가져와 일별 z-score(30일 롤링, shift(1)로 lookahead
방지 — funding_zscore_asset_native_backtest.py와 동일 컨벤션) 계산 후 macro_rows에
overlay.

신호(Riptide): 최근 7일 중 하루라도 z-score>=2.0(극단 과열)이었고, 오늘 z-score<=0(평균
이하로 전환)이면 롱 — risk-off 제외.

재현:
  .venv/bin/python3 scripts/analysis/premium_flip_candidate_backtest.py
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402
from arena.algorithms import _is_risk_off, _regime_state  # noqa: E402

BINANCE_PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndexKlines"
BINANCE_MAX_LIMIT = 1500

LOOKBACK_DAYS = 7
EXTREME_Z = 2.0
FLIP_Z = 0.0


def _ms(dt) -> int:
    return int(dt.timestamp() * 1000)


def fetch_premium_daily(symbol: str, start_ms: int, end_ms: int) -> dict[str, float]:
    """일별 premium index 종가(마지막 값) — daily 캔들 자체가 Binance 서버에서 집계됨."""
    daily: dict[str, float] = {}
    cursor = start_ms
    for _ in range(10):
        resp = requests.get(
            BINANCE_PREMIUM_URL,
            params={
                "symbol": symbol,
                "interval": "1d",
                "startTime": str(cursor),
                "endTime": str(end_ms),
                "limit": str(BINANCE_MAX_LIMIT),
            },
            timeout=20,
        )
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        for row in page:
            open_time_ms = row[0]
            close_val = float(row[4])
            day = pd.Timestamp(open_time_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")
            daily[day] = close_val
        if len(page) < BINANCE_MAX_LIMIT:
            break
        cursor = int(page[-1][0]) + 24 * 3600 * 1000
        if cursor >= end_ms:
            break
        time.sleep(0.15)
    return daily


def build_flip_fields(
    daily_premium: dict[str, float], date_index: pd.DatetimeIndex
) -> pd.DataFrame:
    s = pd.Series(daily_premium).sort_index()
    s.index = pd.to_datetime(s.index)
    s = s.reindex(date_index)
    roll = s.shift(1).rolling(30, min_periods=20)
    z = (s - roll.mean()) / roll.std()
    max_z_7d = z.shift(1).rolling(LOOKBACK_DAYS, min_periods=3).max()
    return pd.DataFrame({"premium_index_zscore": z, "premium_index_zscore_max_7d": max_z_7d})


def override_premium_fields(macro_rows: list[dict], symbol: str) -> list[dict]:
    dates = pd.DatetimeIndex([pd.Timestamp(r["reference_date"]) for r in macro_rows])
    start_ms = _ms(dates.min().to_pydatetime().replace(tzinfo=timezone.utc))
    end_ms = _ms(dates.max().to_pydatetime().replace(tzinfo=timezone.utc) + pd.Timedelta(days=1))

    daily = fetch_premium_daily(symbol, start_ms, end_ms)
    fields = build_flip_fields(daily, dates)
    fields.index = dates

    out = copy.deepcopy(macro_rows)
    for row, (_, r) in zip(out, fields.iterrows(), strict=True):
        z = None if pd.isna(r["premium_index_zscore"]) else float(r["premium_index_zscore"])
        mz = (
            None
            if pd.isna(r["premium_index_zscore_max_7d"])
            else float(r["premium_index_zscore_max_7d"])
        )
        row["risk_overlay"]["regimeRaw"]["premium_index_zscore"] = z
        row["risk_overlay"]["regimeRaw"]["premium_index_zscore_max_7d"] = mz
    return out


def riptide(macro: dict, ind: dict) -> str | None:
    """프리미엄 극단과열 → 플립(디레버리징 캡추레이션) 역발산 롱."""
    z = macro.get("premium_index_zscore")
    max_z_7d = macro.get("premium_index_zscore_max_7d")
    if z is None or max_z_7d is None or _is_risk_off(_regime_state(macro)):
        return None
    return "long" if (max_z_7d >= EXTREME_Z and z <= FLIP_Z) else None


CANDIDATES = {"riptide": riptide}


def _bootstrap_ci(trades: list, n_resamples: int = 3000, seed: int = 42):
    if not trades:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    weighted = np.array([t.ret_pct * t.position_weight for t in trades])
    n = len(weighted)
    resampled = rng.choice(weighted, size=(n_resamples, n), replace=True).sum(axis=1)
    lo, hi = np.percentile(resampled, [2.5, 97.5])
    return float(weighted.sum()), float(lo), float(hi)


def _split_half(trades: list):
    ts = sorted(trades, key=lambda t: t.open_time)
    mid = len(ts) // 2
    if mid == 0:
        return 0.0, 0.0
    first = sum(t.ret_pct * t.position_weight for t in ts[:mid]) * 100
    second = sum(t.ret_pct * t.position_weight for t in ts[mid:]) * 100
    return first, second


def _summarize(algo_id: str, symbol: str, trades: list) -> None:
    algo_trades = [t for t in trades if t.algo_id == algo_id]
    n = len(algo_trades)
    print(f"\n--- {algo_id} / {symbol} (n={n}) ---")
    if n == 0:
        print("  거래 없음 (임계값 미도달 또는 macro 미커버)")
        return
    wins = [t for t in algo_trades if t.ret_pct > 0]
    losses = [t for t in algo_trades if t.ret_pct <= 0]
    win_rate = len(wins) / n * 100
    sum_w = sum(t.ret_pct * t.position_weight for t in algo_trades) * 100
    gross_win = sum(t.ret_pct for t in wins)
    gross_loss = -sum(t.ret_pct for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    avg_hold = sum(t.hold_hours for t in algo_trades) / n
    print(f"  win%={win_rate:.1f}  sum_w%={sum_w:+.2f}  PF={pf:.2f}  avg_hold={avg_hold:.0f}h")
    point, lo, hi = _bootstrap_ci(algo_trades)
    print(f"  부트스트랩95%CI: [{lo * 100:+.2f}%, {hi * 100:+.2f}%] (point={point * 100:+.2f}%)")
    if n >= 6:
        first, second = _split_half(algo_trades)
        print(f"  전/후반 분할: 전반={first:+.2f}%  후반={second:+.2f}%")
    returns = np.array([t.ret_pct for t in algo_trades])
    dsr = deflated_sharpe_ratio(returns, n_trials=1)
    print(f"  DSR(n_trials=1)={dsr['dsr']:.3f}  sharpe={dsr['sharpe']:.3f}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    macro_rows_shared = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows_shared[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows_shared[-1]["reference_date"], tz=timezone.utc).to_pydatetime()
    print(
        f"macro 백필: {len(macro_rows_shared)}일 "
        f"{macro_rows_shared[0]['reference_date']}~{macro_rows_shared[-1]['reference_date']}"
    )
    print(f"신호: max_z_7d>={EXTREME_Z} AND z<={FLIP_Z} (riptide, 단일 사전사양)")

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    for symbol in args.symbols:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")
        print("premium index 히스토리 조회 중...")
        macro_rows = override_premium_fields(macro_rows_shared, symbol)

        n_fire = sum(
            1
            for r in macro_rows
            if r["risk_overlay"]["regimeRaw"].get("premium_index_zscore_max_7d") is not None
            and r["risk_overlay"]["regimeRaw"]["premium_index_zscore_max_7d"] >= EXTREME_Z
            and r["risk_overlay"]["regimeRaw"].get("premium_index_zscore", 99) <= FLIP_Z
        )
        print(f"[민감도] 신호 발화 일수(risk-off 필터 전): {n_fire}/{len(macro_rows)}일")

        profile_id = (
            frequency.LIVE_4H_PROFILE_ID
            if symbol == parameters.BINANCE_SYMBOL
            else frequency.multi_asset_shadow_profile_id(symbol)
        )
        profile = frequency.get_frequency_profile(profile_id)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=profile.interval,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
            from_date=from_dt,
            to_date=to_dt,
        )
        if not frames:
            print(f"  frames 없음 — {symbol} 히스토리 확인 필요")
            continue

        result = backtest.run_replay(
            frames, strategy_fns=CANDIDATES, settings=backtest.BacktestSettings(symbol=symbol)
        )
        _summarize("riptide", symbol, result.trades)

    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
