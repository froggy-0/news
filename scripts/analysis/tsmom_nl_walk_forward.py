"""Nonlinear TSMOM(macd_momentum 대체 후보) walk-forward 견고성 검증 (2026-08-08).

배경: tsmom_nl_tuning.py(단일 3년 프레임 그리드, 18변형)에서 lookback=126이 vol_mode·
min_signal 전 조합(6/6)에서 플러스인 반면 180/372는 혼조/마이너스 — 이론적으로도
(Goulding et al. 2023, "fast momentum(1개월)이 시장 전환점 근처에서 더 유효" — Nonlinear
TSMOM 논문 리터러처 리뷰에 인용) 근거가 있는 구조적 신호로 보인다. 하지만 최선 단일
변형(L126_ewma_min0.5)은 DSR 0.110·부트스트랩CI가 0 포함·전후반 분할 불일치로 기각됨
(nonlinear-tsmom-design-20260808.md §9).

이 스크립트는 target_exit_walk_forward.py와 동일 원리(비중첩 N윈도, config별 윈도합·
양의윈도비율·표준편차)로 L126 6변형 + 레거시 MACD baseline을 재검증해 "전체기간 평균은
좋은데 특정 구간에만 몰린 결과인가"를 직접 확인한다.

재현:
  .venv/bin/python3 scripts/analysis/tsmom_nl_walk_forward.py --windows 6
  .venv/bin/python3 scripts/analysis/validation_stats.py --json /tmp/tsmom_nl_wf.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

TARGET = "macd_momentum"
CONFIGS: dict[str, dict] = {
    "legacy_macd": {"TSMOM_NL_ENABLED": False},
    "L126_rv6_min0.0": {
        "TSMOM_NL_ENABLED": True,
        "TSMOM_NL_LOOKBACK_BARS": 126,
        "TSMOM_NL_VOL_MODE": "rv6",
        "TSMOM_NL_MIN_SIGNAL": 0.0,
    },
    "L126_rv6_min0.2": {
        "TSMOM_NL_ENABLED": True,
        "TSMOM_NL_LOOKBACK_BARS": 126,
        "TSMOM_NL_VOL_MODE": "rv6",
        "TSMOM_NL_MIN_SIGNAL": 0.2,
    },
    "L126_rv6_min0.5": {
        "TSMOM_NL_ENABLED": True,
        "TSMOM_NL_LOOKBACK_BARS": 126,
        "TSMOM_NL_VOL_MODE": "rv6",
        "TSMOM_NL_MIN_SIGNAL": 0.5,
    },
    "L126_ewma_min0.0": {
        "TSMOM_NL_ENABLED": True,
        "TSMOM_NL_LOOKBACK_BARS": 126,
        "TSMOM_NL_VOL_MODE": "ewma",
        "TSMOM_NL_MIN_SIGNAL": 0.0,
    },
    "L126_ewma_min0.2": {
        "TSMOM_NL_ENABLED": True,
        "TSMOM_NL_LOOKBACK_BARS": 126,
        "TSMOM_NL_VOL_MODE": "ewma",
        "TSMOM_NL_MIN_SIGNAL": 0.2,
    },
    "L126_ewma_min0.5": {
        "TSMOM_NL_ENABLED": True,
        "TSMOM_NL_LOOKBACK_BARS": 126,
        "TSMOM_NL_VOL_MODE": "ewma",
        "TSMOM_NL_MIN_SIGNAL": 0.5,
    },
}


@contextmanager
def _params(**overrides):
    saved = {k: getattr(parameters, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(parameters, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(parameters, k, v)


def _weighted_returns(trades, algo: str) -> list[float]:
    return [t.ret_pct * t.position_weight for t in trades if t.algo_id == algo]


def _per_bar_returns(result, algo: str) -> list[float]:
    return [p.realized_ret_pct for p in result.equity_curve if p.algo_id == algo]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--limit", type=int, default=6000)
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--out-json", default="/tmp/tsmom_nl_wf.json")
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    await positions.init()
    warm = max(parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD, 400)
    prof = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        positions.db(),
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=args.limit,
        warmup_bars=warm,
        indicator_profile_id=prof.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    W = args.windows
    size = len(frames) // W
    windows = [frames[i * size : (i + 1) * size] for i in range(W)]
    print(
        f"frames={len(frames)} {frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
        f"  → {W}개 윈도(각 ~{size}봉, ~{size / 6:.0f}일)  target={TARGET}"
    )

    per_config_full_returns: dict[str, list[float]] = {}
    print(f"\n=== {TARGET} walk-forward (윈도별 가중수익 합, 견고성) ===")
    for label, ov in CONFIGS.items():
        window_sums = []
        window_ns = []
        for w in windows:
            with _params(**ov):
                res = backtest.run_replay(w, settings=backtest.BacktestSettings())
            rets = _weighted_returns(res.trades, TARGET)
            window_sums.append(sum(rets) * 100)
            window_ns.append(len(rets))
        with _params(**ov):
            full_res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        per_config_full_returns[label] = _per_bar_returns(full_res, TARGET)
        pos_w = sum(1 for x in window_sums if x > 0)
        full_sum = sum(_weighted_returns(full_res.trades, TARGET)) * 100
        print(
            f"[{label:16}] 윈도합%: {['%+.1f' % x for x in window_sums]}  n={window_ns}  "
            f"양의윈도 {pos_w}/{W}  평균{statistics.mean(window_sums):+.2f}  "
            f"표준편차{statistics.pstdev(window_sums):.2f}  전체합{full_sum:+.2f}"
        )

    out_path = Path(args.out_json)
    out_path.write_text(json.dumps(per_config_full_returns, indent=2))
    print(f"\nDSR/PBO 입력 저장: {out_path}")
    print(f"다음: .venv/bin/python3 scripts/analysis/validation_stats.py --json {out_path}")
    print(
        "\n판정 기준: 양의윈도 비율↑·표준편차↓·평균↑ = 견고. 특정 윈도에만 몰린 이익은 과적합 의심."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
