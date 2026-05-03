#!/usr/bin/env python3
"""기존 parquet에 btc_taker 파생 피처를 패치합니다.

전체 파이프라인 재실행 없이 Binance klines에서 taker buy volume을 가져와
기존 parquet에 join합니다. R2 인증 불필요.

사용법:
    python scripts/analysis/patch_parquet_taker.py
    python scripts/analysis/patch_parquet_taker.py --parquet data/sentiment_join/sentiment_join_master_20260502.parquet
    python scripts/analysis/patch_parquet_taker.py --dry-run  # 변경 내용만 출력
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import pandas as pd  # noqa: E402

from morning_brief.analysis.sentiment_join.join import _add_taker_features  # noqa: E402
from morning_brief.analysis.sentiment_join.sources.binance import (  # noqa: E402
    fetch_btc_close_binance,
)


def patch_parquet(parquet_path: Path, dry_run: bool = False) -> None:
    print(f"[1/4] 기존 parquet 로드: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    print(f"  행 수: {len(df)}, 날짜 범위: {df['date'].min()} ~ {df['date'].max()}")

    start_date = df["date"].min()
    end_date = df["date"].max()

    print(f"[2/4] Binance klines 수집: {start_date} ~ {end_date}")
    btc_df = fetch_btc_close_binance(start_date, end_date, api_key="")
    print(f"  소스: {btc_df.attrs.get('btc_source')}, 행 수: {len(btc_df)}")
    print(
        f"  btc_taker_buy_quote_volume 비결측: {btc_df['btc_taker_buy_quote_volume'].notna().sum()}"
    )

    print("[3/4] taker 컬럼 패치 및 파생 피처 생성")
    # 기존 taker 컬럼 제거 후 새로 join
    taker_raw_cols = ["btc_quote_volume", "btc_taker_buy_quote_volume"]
    for col in taker_raw_cols:
        if col in df.columns:
            df = df.drop(columns=[col])

    taker_derived = [
        "btc_taker_buy_ratio_7d",
        "btc_taker_imbalance_zscore_30d",
        "btc_taker_imbalance_zscore_30d_lag1",
        "btc_taker_buy_ratio_7d_lag1",
    ]
    for col in taker_derived:
        if col in df.columns:
            df = df.drop(columns=[col])

    btc_taker = btc_df[["date", "btc_quote_volume", "btc_taker_buy_quote_volume"]]
    df = df.merge(btc_taker, on="date", how="left")
    df = _add_taker_features(df)

    zscore_col = "btc_taker_imbalance_zscore_30d"
    non_null = df[zscore_col].notna().sum()
    print(f"  {zscore_col} 비결측: {non_null}/{len(df)}")
    print(f"  첫 유효값 날짜: {df.loc[df[zscore_col].notna(), 'date'].min()}")
    print(f"  통계: mean={df[zscore_col].mean():.3f}, std={df[zscore_col].std():.3f}")

    if dry_run:
        print("[dry-run] 저장 생략")
        print(
            df[["date", "btc_quote_volume", "btc_taker_buy_quote_volume", zscore_col]]
            .tail(10)
            .to_string()
        )
        return

    print(f"[4/4] parquet 저장: {parquet_path}")
    df.to_parquet(parquet_path, index=False)
    print("  완료.")


def main() -> None:
    parser = argparse.ArgumentParser(description="parquet taker 피처 패치")
    parser.add_argument(
        "--parquet",
        type=Path,
        default=PROJECT_ROOT / "data/sentiment_join/sentiment_join_master_20260502.parquet",
        help="패치할 parquet 경로",
    )
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 결과만 출력")
    args = parser.parse_args()

    if not args.parquet.exists():
        print(f"ERROR: parquet 파일 없음: {args.parquet}", file=sys.stderr)
        sys.exit(1)

    patch_parquet(args.parquet, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
