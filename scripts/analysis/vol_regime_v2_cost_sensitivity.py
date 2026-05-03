#!/usr/bin/env python3
"""vol_regime_v2 Transaction Cost Sensitivity 분석 스크립트.

다양한 수수료 시나리오에서 vol_regime_v2 전략의 Sharpe / MDD / hit_rate 를 출력한다.
BTC 24/7 실물 환경 기준: maker ~2 bps, taker ~5-7 bps, 현물+슬리피지 최대 ~20 bps.

사용법 (로컬):
    python scripts/analysis/vol_regime_v2_cost_sensitivity.py \\
        --parquet data/sentiment_join/master_latest.parquet

사용법 (R2):
    python scripts/analysis/vol_regime_v2_cost_sensitivity.py --from-r2
    python scripts/analysis/vol_regime_v2_cost_sensitivity.py --from-r2 --r2-key sentiment_join/master_20260430.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

_DEFAULT_R2_PREFIX = "sentiment_join/"

_FEE_SCENARIOS: list[tuple[str, float]] = [
    ("무비용 (이론)", 0.0),
    ("Maker (~2 bps)", 2.0),
    ("Taker (~7 bps)", 7.0),
    ("현물+슬리피지 (~15 bps)", 15.0),
    ("극단 보수 (~25 bps)", 25.0),
]

_BASELINES = ["always_up", "vol_regime", "vol_regime_v2", "fng_contrarian", "btc_momo_20d"]


def _resolve_parquet(path: Path) -> Path | None:
    if path.exists():
        return path
    parent = path.parent
    if not parent.exists():
        return None
    candidates = sorted(parent.glob("master_*.parquet"), reverse=True)
    return candidates[0] if candidates else None


def _resolve_r2_parquet_key(r2_key: str | None, r2_cfg: object) -> str:
    """r2_key가 지정되지 않으면 R2에서 최신 master_*.parquet 키를 탐색한다."""
    if r2_key:
        return r2_key
    from morning_brief.analysis.sentiment_join.storage import list_r2_keys

    keys = list_r2_keys(
        _DEFAULT_R2_PREFIX,
        r2_s3_endpoint=r2_cfg.s3_endpoint,
        r2_access_key_id=r2_cfg.access_key_id,
        r2_secret_access_key=r2_cfg.secret_access_key,
        r2_public_bucket=r2_cfg.public_bucket,
    )
    parquet_keys = [k for k in keys if k.endswith(".parquet")]
    if not parquet_keys:
        raise FileNotFoundError(f"R2 {_DEFAULT_R2_PREFIX} 아래 parquet 파일 없음")
    return parquet_keys[-1]  # 오름차순 정렬이므로 마지막이 최신


def _fmt(v: object, digits: int = 3) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "     N/A"
    return f"{float(v):>8.{digits}f}"  # type: ignore[arg-type]


def _find_breakeven_fee(
    df: pd.DataFrame,
    signal: "pd.Series",
    return_col: str,
    benchmark_signal: "pd.Series",
) -> float | None:
    from morning_brief.analysis.sentiment_join.baselines import evaluate_baseline

    ref = evaluate_baseline(df, benchmark_signal, return_col=return_col, fee_per_leg_bps=0.0)
    ref_sharpe = ref.get("sharpe")
    if ref_sharpe is None or (isinstance(ref_sharpe, float) and ref_sharpe != ref_sharpe):
        ref_sharpe = 0.0

    lo, hi = 0.0, 100.0
    for _ in range(20):
        mid = (lo + hi) / 2
        res = evaluate_baseline(df, signal, return_col=return_col, fee_per_leg_bps=mid)
        sh = res.get("sharpe")
        if sh is None or (isinstance(sh, float) and sh != sh):
            return None
        if float(sh) > float(ref_sharpe):
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.1:
            break
    return (lo + hi) / 2 if hi < 99.9 else None


def _run(args: argparse.Namespace) -> None:
    parquet_path = _resolve_parquet(args.parquet)
    if parquet_path is None:
        print(f"[ERROR] parquet 없음: {args.parquet.parent}")
        sys.exit(1)

    df = pd.read_parquet(parquet_path)
    if args.return_col not in df.columns:
        print(f"[ERROR] 컬럼 없음: {args.return_col}")
        sys.exit(1)

    from morning_brief.analysis.sentiment_join.baselines import (
        always_up,
        btc_momo_20d,
        evaluate_baseline,
        fng_contrarian,
        vol_regime,
        vol_regime_v2,
    )

    signal_fns = {
        "always_up": always_up,
        "vol_regime": vol_regime,
        "vol_regime_v2": vol_regime_v2,
        "fng_contrarian": fng_contrarian,
        "btc_momo_20d": btc_momo_20d,
    }
    baseline_names = list(_BASELINES)
    if args.baseline:
        for b in args.baseline:
            if b not in baseline_names:
                baseline_names.append(b)

    if args.from_r2:
        src_label = f"r2://{args.r2_key}"
    else:
        src_label = parquet_path.name
    print(f"\n=== Transaction Cost Sensitivity · {src_label} ===")
    print(f"    return column: {args.return_col}\n")

    for name in baseline_names:
        fn = signal_fns.get(name)
        if fn is None:
            print(f"[WARN] baseline '{name}' 미지원 — 스킵\n")
            continue
        try:
            signal = fn(df)
        except Exception as exc:
            print(f"[WARN] {name} 신호 계산 실패: {exc}\n")
            continue

        print(f"--- {name} ---")
        hdr = f"  {'시나리오':<24} {'hit_rate':>9} {'sharpe':>8} {'mdd':>8} {'coverage':>9}"
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))

        for scenario_name, fee_bps in _FEE_SCENARIOS:
            res = evaluate_baseline(
                df,
                signal,
                return_col=args.return_col,
                fee_per_leg_bps=fee_bps,
            )
            hr = res.get("hit_rate")
            sh = res.get("sharpe")
            mdd = res.get("max_drawdown")
            cov = res.get("coverage")
            print(
                f"  {scenario_name:<24} {_fmt(hr, 3):>9} {_fmt(sh, 3):>8} "
                f"{_fmt(mdd, 4):>8} {_fmt(cov, 3):>9}"
            )

        be_fee = _find_breakeven_fee(df, signal, args.return_col, always_up(df))
        if be_fee is not None:
            edge_warn = "  ⚠ 실거래 edge 없음 가능성" if be_fee < 7.0 else ""
            print(f"  → breakeven fee ≈ {be_fee:.1f} bps/leg{edge_warn}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="vol_regime_v2 거래비용 민감도 분석")
    parser.add_argument(
        "--parquet",
        type=Path,
        default=PROJECT_ROOT / "data" / "sentiment_join" / "master_latest.parquet",
        help="master parquet 경로 (로컬, sentinel 파일명)",
    )
    parser.add_argument("--return-col", default="btc_log_return", help="수익률 컬럼명")
    parser.add_argument("--baseline", action="append", help="추가 baseline (반복 가능)")
    parser.add_argument("--from-r2", action="store_true", help="R2에서 직접 읽기")
    parser.add_argument(
        "--r2-key",
        default=None,
        help="R2 parquet 키 오버라이드 (미지정 시 최신 master_*.parquet 자동 탐색)",
    )
    args = parser.parse_args()

    if args.from_r2:
        from morning_brief.analysis.sentiment_join.storage import r2_tempfile
        from morning_brief.r2_env import load_public_r2_env

        r2 = load_public_r2_env()
        r2_key = _resolve_r2_parquet_key(args.r2_key, r2)
        print(f"[R2] 다운로드: {r2_key}")
        with r2_tempfile(
            r2_key,
            suffix=".parquet",
            r2_s3_endpoint=r2.s3_endpoint,
            r2_access_key_id=r2.access_key_id,
            r2_secret_access_key=r2.secret_access_key,
            r2_public_bucket=r2.public_bucket,
        ) as tmp:
            args.parquet = tmp
            args.r2_key = r2_key
            _run(args)
    else:
        _run(args)


if __name__ == "__main__":
    main()
