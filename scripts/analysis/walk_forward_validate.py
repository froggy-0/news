"""R7: walk-forward 견고성 검증 — 파라미터 선택이 시간 분할별로도 유지되는지.

단일 기간 백테스트로 채택한 값(WI-1/7·P-A)이 특정 구간에 과적합됐는지 확인. 특히 P-A
fng 목표배수는 stale↔fresh macro 사이 결론이 뒤집혔으므로(atr1.0 vs atr2.0) 시간 분할
검증이 결정적. frames를 N개 비중첩 윈도로 나눠 각 윈도에서 독립 replay → config별로
"양(+) 윈도 비율·평균·표준편차"로 견고성 판정.

재현:
  .venv/bin/python3 scripts/analysis/walk_forward_validate.py \
      --parquet data/sentiment_join/master_20260710.parquet --windows 6
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGOS = ["regime_trend", "fng_contrarian", "vix_rsi", "macd_momentum", "multi_factor", "omnibus"]


@contextmanager
def _params(**ov):
    saved = {k: getattr(parameters, k) for k in ov}
    try:
        for k, v in ov.items():
            setattr(parameters, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(parameters, k, v)


def _sum_w(trades, algo: str | None = None) -> float:
    return (
        sum(t.ret_pct * t.position_weight for t in trades if algo is None or t.algo_id == algo)
        * 100
    )


def _n(trades, algo: str) -> int:
    return sum(1 for t in trades if t.algo_id == algo)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--target", default="fng_contrarian", help="윈도별 상세 출력 알고")
    args = ap.parse_args()
    if not Path(args.parquet).exists():
        print(f"parquet 없음: {args.parquet}")
        return 1

    macro_rows = build_macro_rows(Path(args.parquet))
    await positions.init()
    warm = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    prof = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        positions.db(),
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warm,
        indicator_profile_id=prof.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    # 비중첩 윈도 분할
    W = args.windows
    size = len(frames) // W
    windows = [frames[i * size : (i + 1) * size] for i in range(W)]
    print(
        f"frames={len(frames)} {frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
        f"  → {W}개 윈도(각 ~{size}봉)"
    )

    # 물타기 제거 검증: fng_optimize(master_20260710)에서 0.15단일이 1위(종가자산 1.0339 vs 3단 1.0214)
    # → WF에서도 일관 우위인지 확인. P-A익절(atr2.0)·ts60·mh36은 현행 parameters 기본값 그대로.
    _T3 = parameters.FNG_CONTRARIAN_PRICE_TRANCHES  # 현행 3단
    _S15 = ((0.0, 0.15),)  # 단일 0.15 (물타기 제거)
    _S40 = ((0.0, 0.40),)  # 단일 0.40 (물타기 제거 + 사이즈 업)

    configs = {
        "현재라이브(3단·atr2.0)": {},
        "물타기제거(0.15단일)": {"FNG_CONTRARIAN_PRICE_TRANCHES": _S15},
        "물타기제거(0.40단일)": {"FNG_CONTRARIAN_PRICE_TRANCHES": _S40},
    }

    for cname, ov in configs.items():
        # 윈도별 총 포트폴리오 sum_w + target 알고 sum_w
        port, tgt, tgt_n = [], [], []
        for w in windows:
            with _params(**ov):
                res = backtest.run_replay(w, settings=backtest.BacktestSettings())
            port.append(_sum_w(res.trades))
            tgt.append(_sum_w(res.trades, args.target))
            tgt_n.append(_n(res.trades, args.target))
        pos_port = sum(1 for x in port if x > 0)
        pos_tgt = sum(1 for x in tgt if x > 0)
        print(f"\n[{cname}]")
        print(
            f"  포트폴리오 총합/윈도: {['%+.1f' % x for x in port]}  "
            f"양의윈도 {pos_port}/{W}  평균{statistics.mean(port):+.2f} 표준편차{statistics.pstdev(port):.2f}"
        )
        print(
            f"  {args.target}/윈도:   {['%+.1f' % x for x in tgt]}  (n={tgt_n})  "
            f"양의윈도 {pos_tgt}/{W}  평균{statistics.mean(tgt):+.2f}"
        )

    print(
        "\n판정 기준: 양의윈도 비율↑·표준편차↓·평균↑ = 견고. 특정 윈도에만 몰린 이익은 과적합 의심."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
