"""fng_contrarian 숏 진입 후보 격리 백테스트 (Phase B §3.5/§1원칙3 최후순).

배경: docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md §3.5.
6개 알고 순환의 마지막 후보. §3.5가 명시하듯 fng_contrarian은 "공포에서 반등을
사는" 역발산 전략이라 **롱 조건의 부호 반전이 숏의 자연스러운 거울이 아니다** —
"탐욕 구간에서 판다"가 자연스러운 숏 가설이라 이 스크립트는 §3.5 원문 그대로 새
가설을 세운다: FNG > FNG_SHORT_ABOVE(70.0, FNG_LONG_BELOW=30.0의 50 중심 대칭).

핵심 조건: FNG > 70(과도한 탐욕) + `momentum_not_improving`(`_momentum_not_worsening`의
거울 — 상승 가속이 아직 안 멈췄으면 숏 보류, "고점 추격 매도" 회피, v23 정량검증된
필터의 대칭). risk-off veto는 §3.1/§3.4/§3.5(vix_rsi)와 동일한 미해결 질문이라 두
변형(유지/제거)을 비교한다(그리드 아닌 사전 설계값 2개).

**낙폭 거울 게이트는 이 스크립트에서 구현하지 않는다(알려진 한계, no-op)** — 롱의
`_drawdown_sufficient`(90일 고점 대비 낙폭 ≤ -10%)를 그대로 미러링하려면 "90일 저점
대비 충분한 상승폭"이 필요한데, 그런 필드가 macro/indicator 어디에도 없다(risk_overlay.py가
btc_drawdown_90d만 산출, 저점 기준 상승폭은 별도 계산 인프라가 없음). §3.5도 "탐욕
구간에서 판다"를 정의만 하고 이 세부 게이트의 값을 정하지 않았으므로, 임의로
새 계산을 급조하기보다 **품질필터 3표 중 2표(FNG_CONTRARIAN_ENTRY_MIN_SECONDARY_VOTES)를
남은 2표(breadth/stablecoin) 둘 다 충족으로 대체**하고 이 사실을 결과에 명시한다
— 나중에 낙폭 거울 필드를 추가하면 재검증이 필요하다.

ALGORITHMS dict·PERP_SHORT_ENABLED_TRACKS·algorithms.py 어느 것도 건드리지 않음 —
backtest.run_replay(strategy_fns=...)로 algo_id="fng_contrarian"만 오버라이드해
product_type="usdm_perp" 상태머신에 태운다.

재현:
  .venv/bin/python3 scripts/analysis/fng_contrarian_short_backtest.py
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from collections import defaultdict
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from macd_momentum_short_backtest import _bootstrap_ci, _split_half  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402
from vix_rsi_short_backtest import _momentum_not_improving  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402
from arena.algorithms import _is_risk_off, _regime_state  # noqa: E402

FNG_SHORT_ABOVE = 100.0 - parameters.FNG_LONG_BELOW  # 30.0의 50 중심 대칭 = 70.0

# algo_id="fng_contrarian"를 재사용하면 backtest.py의 fng 전용 롱 메커니즘 2개가 방향과
# 무관하게 켜진다(둘 다 algo_id로만 게이팅, direction 미확인):
#   1) FNG_TARGET_EXIT_ENABLED(P-A 이익포착) — target=open_price*(1+pct)를 항상
#      bar.high와 비교(backtest.py:791-796). 롱은 맞지만 숏 포지션에 적용하면 진입가
#      "위"를 목표가로 잡고 그 위치를 최고가와 비교하는 꼴이 돼(부호 반전 없음), 실측
#      결과 전 거래가 1봉 만에 손실 확정으로 청산되는 병리적 패턴이 나왔다(win%=0.0,
#      exit_reason 전부 target_exit) — 이 스크립트의 §3.5 설계에는 이 메커니즘이 아예
#      없으므로 코드 버그를 실측한 것이지 숏 신호 자체의 결과가 아니다.
#   2) FNG_CONTRARIAN_SCALE_IN_ENABLED(가격 하락 시 물타기) — "하락할수록 추가 매수"
#      로직이라 롱 전용 개념, 숏에 대응하는 미러가 이 코드베이스에 없다.
# 둘 다 프로세스 로컬로 비활성화한다(소스 무변경, macd 스크립트의 몽키패치 관행과 동일).
parameters.FNG_TARGET_EXIT_ENABLED = False
parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED = False


def _fng_short_env_ok(macro: dict) -> bool:
    # 낙폭 거울 게이트 부재(파일 docstring 참조) — 남은 2표(breadth/stablecoin) 둘 다 요구.
    return not algorithms._breadth_collapsed(macro) and not algorithms._stablecoin_contracting(
        macro
    )


def _fng_short_core(macro: dict, ind: dict) -> bool:
    fng = macro.get("fng")
    if fng is None:
        return False
    if not _fng_short_env_ok(macro):
        return False
    if not _momentum_not_improving(ind):
        return False
    return fng > FNG_SHORT_ABOVE


def fng_contrarian_short_veto_kept(macro: dict, ind: dict) -> str | None:
    if _is_risk_off(_regime_state(macro)):
        return None
    return "short" if _fng_short_core(macro, ind) else None


def fng_contrarian_short_veto_removed(macro: dict, ind: dict) -> str | None:
    return "short" if _fng_short_core(macro, ind) else None


VARIANTS_VETO_KEPT: dict[str, backtest.StrategyFn] = {
    "fng_contrarian": fng_contrarian_short_veto_kept
}
VARIANTS_VETO_REMOVED: dict[str, backtest.StrategyFn] = {
    "fng_contrarian": fng_contrarian_short_veto_removed
}


def _summarize(label: str, symbol: str, trades: list) -> dict:
    algo_trades = [t for t in trades if t.algo_id == "fng_contrarian"]
    n = len(algo_trades)
    print(f"\n--- {label} / {symbol} (n={n}) ---")
    if n == 0:
        print("  거래 없음")
        return {"label": label, "symbol": symbol, "n": 0}
    wins = [t for t in algo_trades if t.ret_pct > 0]
    losses = [t for t in algo_trades if t.ret_pct <= 0]
    win_rate = len(wins) / n * 100
    sum_w = sum(t.ret_pct * t.position_weight for t in algo_trades) * 100
    gross_win = sum(t.ret_pct for t in wins)
    gross_loss = -sum(t.ret_pct for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    avg_hold = sum(t.hold_hours for t in algo_trades) / n
    exits = defaultdict(int)
    for t in algo_trades:
        exits[t.exit_reason] += 1
    print(
        f"  win%={win_rate:.1f}  sum_w%={sum_w:+.2f}  PF={pf:.2f}  "
        f"avg_hold={avg_hold:.0f}h  exits={dict(exits)}"
    )
    point, lo, hi = _bootstrap_ci(algo_trades)
    print(
        f"  가중합 부트스트랩95%CI: [{lo * 100:+.2f}%, {hi * 100:+.2f}%] (point={point * 100:+.2f}%)"
    )
    first = second = 0.0
    if n >= 6:
        first, second = _split_half(algo_trades)
        print(f"  전/후반 분할: 전반={first:+.2f}%  후반={second:+.2f}%")
    returns = np.array([t.ret_pct for t in algo_trades])
    dsr = deflated_sharpe_ratio(returns, n_trials=2)
    print(f"  DSR(n_trials=2)={dsr['dsr']:.3f}  sharpe={dsr['sharpe']:.3f}")
    return {
        "label": label,
        "symbol": symbol,
        "n": n,
        "win_rate": win_rate,
        "sum_w_pct": sum_w,
        "pf": pf,
        "ci_lo_pct": lo * 100,
        "ci_hi_pct": hi * 100,
        "split_first_pct": first,
        "split_second_pct": second,
        "dsr": dsr["dsr"],
    }


async def _run_symbol(db, symbol: str, macro_rows: list[dict], from_dt, to_dt) -> list:
    warmup = 220
    profile_id = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    profile = frequency.get_frequency_profile(profile_id)
    return await backtest.load_frames_from_supabase(
        db,
        symbol=symbol,
        interval=profile.interval,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_dt,
        to_date=to_dt,
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows[-1]["reference_date"], tz=timezone.utc).to_pydatetime()
    print(
        f"macro 백필: {len(macro_rows)}일 {macro_rows[0]['reference_date']}~"
        f"{macro_rows[-1]['reference_date']}"
    )
    print(f"FNG_SHORT_ABOVE={FNG_SHORT_ABOVE}")

    settings_perp = backtest.BacktestSettings(product_type="usdm_perp")

    await positions.init()
    db = positions.db()

    results: list[dict] = []
    for symbol in args.symbols:
        print(f"\n{'=' * 70}\n{symbol}\n{'=' * 70}")
        frames = await _run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        if not frames:
            print(f"  frames 없음 — {symbol} 히스토리 확인 필요")
            continue
        print(
            f"  frames={len(frames)}  {frames[0].bar.close_time.date()}~"
            f"{frames[-1].bar.close_time.date()}"
        )
        buy_hold = (frames[-1].bar.close / frames[0].bar.close - 1.0) * 100
        print(f"  buy&hold(구간 전체): {buy_hold:+.2f}%")

        for label, variant_fns in (
            ("veto유지", VARIANTS_VETO_KEPT),
            ("veto제거", VARIANTS_VETO_REMOVED),
        ):
            result = backtest.run_replay(frames, strategy_fns=variant_fns, settings=settings_perp)
            results.append(_summarize(f"fng_contrarian_short[{label}]", symbol, result.trades))

    print(f"\n{'=' * 70}\n요약표\n{'=' * 70}")
    header = (
        f"{'label':32s} {'symbol':10s} {'n':>4s} {'win%':>6s} {'sum_w%':>8s} {'PF':>6s} "
        f"{'CI_lo%':>8s} {'CI_hi%':>8s} {'전반%':>7s} {'후반%':>7s} {'DSR':>6s}"
    )
    print(header)
    for r in results:
        if r.get("n", 0) == 0:
            print(f"{r['label']:32s} {r['symbol']:10s} {0:>4d}  거래없음")
            continue
        print(
            f"{r['label']:32s} {r['symbol']:10s} {r['n']:>4d} {r['win_rate']:>6.1f} "
            f"{r['sum_w_pct']:>+8.2f} {(r['pf'] if math.isfinite(r['pf']) else 99.99):>6.2f} "
            f"{r['ci_lo_pct']:>+8.2f} {r['ci_hi_pct']:>+8.2f} "
            f"{r['split_first_pct']:>+7.2f} {r['split_second_pct']:>+7.2f} {r['dsr']:>6.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
