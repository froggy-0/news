#!/usr/bin/env python3
"""sentiment-join parquet에서 보고서 시각화용 데이터를 추출합니다.

출력:
  1. Granger 인과성 검정: 시차별 P-value 테이블 + 시계열 원본
  2. 이상치 제거 비율
  3. FinBERT 감성 점수 기초 통계량 및 분포
  4. §4 v4: full / core 하이브리드 지수별 PCA / VIF 진단
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


def _find_latest_parquet(output_dir: Path) -> Path:
    candidates = sorted(output_dir.glob("master_*.parquet"))
    if not candidates:
        sys.exit(f"ERROR: {output_dir}에 master_*.parquet 파일이 없습니다.")
    return candidates[-1]


def _load_stats_metadata(path: Path) -> dict:
    meta = pq.read_schema(path).metadata or {}
    raw = meta.get(b"sentiment_join_stats")
    if raw is None:
        sys.exit("ERROR: sentiment_join_stats 메타데이터가 없습니다.")
    return json.loads(raw)


def _render_hybrid_block(index_name: str, entry: dict[str, Any]) -> None:
    pca = entry.get("pca_summary", {}) or {}
    vif = entry.get("vif_diagnostics", []) or []
    coverage = entry.get("coverage", {}) or {}

    print(f"\n[{index_name.upper()} hybrid index]")
    print(f"  status: {pca.get('status')}")
    print(f"  selected_features: {pca.get('selected_features')}")
    print(f"  n_components: {pca.get('n_components')}")
    print(f"  explained_variance: {pca.get('explained_variance')}")
    print(f"  loadings: {pca.get('loadings')}")
    print(f"  pc1_min: {pca.get('pc1_min')}")
    print(f"  pc1_max: {pca.get('pc1_max')}")
    print(f"  score_scale_method: {pca.get('score_scale_method')}")
    print(
        "  coverage: "
        f"rows_used={coverage.get('rows_used')}/{coverage.get('rows_total')} "
        f"ratio={coverage.get('ratio')}"
    )
    print(f"  signal_label: {entry.get('signal_label')} (z={entry.get('signal_zscore')})")
    if vif:
        print("  VIF:")
        for v in vif:
            print(f"    {v.get('feature')}: {v.get('vif', v.get('VIF', 'N/A'))}")


def main() -> None:
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/sentiment_join").resolve()
    path = _find_latest_parquet(output_dir)
    print(f"파일: {path.name}\n")

    stats = _load_stats_metadata(path)
    df = pd.read_parquet(path).sort_values("date").reset_index(drop=True)

    print("=" * 60)
    print("1. Granger 인과성 검정 (뉴스 감성 → F&G Index 포함)")
    print("=" * 60)
    granger = stats.get("granger_results", [])
    if granger:
        gdf = pd.DataFrame(granger)
        print(gdf.to_string(index=False))
        fng_pairs = gdf[
            gdf["predictor"].str.contains("sentiment") | gdf["target"].str.contains("fng")
        ]
        if fng_pairs.empty:
            print(
                "\n※ 현재 GRANGER_PAIRS에 (news_sentiment_mean → fng_value) 직접 쌍이 없습니다."
                "\n   파이프라인은 news_sentiment_mean → btc_log_return, "
                "fng_value → btc_log_return 을 각각 검정합니다."
                "\n   두 결과를 비교하면 감성 지표와 F&G의 BTC 수익률 예측력 차이를 볼 수 있습니다."
            )
    else:
        print("Granger 검정 미실행 (행 수 부족 또는 오류)")
    print(f"  granger_eligible_rows: {stats.get('granger_eligible_rows')}")
    print(f"  granger_executed: {stats.get('granger_executed')}")

    print(f"\n{'=' * 60}")
    print("2. 시계열 데이터 미리보기 (차트 입력)")
    print("=" * 60)
    ts_cols = [
        "date",
        "news_sentiment_mean",
        "fng_value",
        "btc_log_return",
        "full_hybrid_index",
        "full_hybrid_index_score",
        "core_hybrid_index",
        "core_hybrid_index_score",
    ]
    available = [c for c in ts_cols if c in df.columns]
    print(df[available].tail(10).to_string(index=False))
    print(f"  전체 행 수: {len(df)}")

    print(f"\n{'=' * 60}")
    print("3. 이상치 제거 통계")
    print("=" * 60)
    print(f"  필터 전 행 수: {stats.get('rows_before_outlier_filter')}")
    print(f"  필터 후 행 수: {stats.get('rows_after_outlier_filter')}")
    print(f"  제거 건수:     {stats.get('outlier_filtered_count')}")
    print(f"  제거 비율:     {stats.get('outlier_filtered_ratio')}")
    exc = stats.get("exclusion_counts", {})
    if exc:
        print(f"  감성 품질 게이트 제외: {exc}")

    print(f"\n{'=' * 60}")
    print("4. FinBERT 감성 점수 분포 (news_sentiment_mean)")
    print("=" * 60)
    if "news_sentiment_mean" in df.columns:
        s = df["news_sentiment_mean"].dropna()
        print(s.describe().to_string())
        for q in [0.05, 0.95]:
            print(f"  {int(q * 100)}%ile: {s.quantile(q):.6f}")
    else:
        print("  news_sentiment_mean 컬럼 없음")

    # §4 3-2: ADF 필드는 v4에서 `adf_statistic`, `adf_pvalue`로 저장됩니다.
    print(f"\n{'=' * 60}")
    print("5. ADF 정상성 검정")
    print("=" * 60)
    adf = stats.get("adf", {})
    if adf:
        for col, res in adf.items():
            if not isinstance(res, dict):
                continue
            statistic = res.get("adf_statistic", res.get("statistic"))
            pvalue = res.get("adf_pvalue", res.get("pvalue"))
            stationary = res.get("stationary")
            stat_str = f"{statistic:.4f}" if isinstance(statistic, (int, float)) else "<NA>"
            p_str = f"{pvalue:.6f}" if isinstance(pvalue, (int, float)) else "<NA>"
            print(f"  {col}: statistic={stat_str}, pvalue={p_str}, stationary={stationary}")
    else:
        print("  ADF 검정 미실행")

    print(f"\n{'=' * 60}")
    print("6. PCA / VIF 진단 (지수별)")
    print("=" * 60)
    hybrid_indices = stats.get("hybrid_indices", {})
    if isinstance(hybrid_indices, dict) and hybrid_indices:
        for name in ("full", "core"):
            entry = hybrid_indices.get(name)
            if isinstance(entry, dict):
                _render_hybrid_block(name, entry)
    else:
        print("  hybrid_indices 메타데이터 없음")


if __name__ == "__main__":
    main()
