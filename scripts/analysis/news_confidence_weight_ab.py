"""뉴스 감성 집계 A/B: 단순 평균 vs FinBERT confidence 가중 평균.

감사(docs/analysis/data-collection-audit-20260724.md §1.2) 가설 검증:
  confidence 가중 평균 Σ(score·conf)/Σconf 이 단순 평균 Σscore/n 보다
  BTC forward return 예측력(IC)이 높은가?

과거 기사별 confidence는 어디에도 보존돼 있지 않으므로(parquet=집계만, raw_backup=
점수화 이전 None), 아카이브의 raw 기사 텍스트에 FinBERT를 재실행해 (score, confidence)를
재구성한다. FinBERT는 결정론적이고, 두 집계가 동일 재구성 점수를 공유하므로 A/B 비교는
텍스트가 프로덕션과 미세하게 달라도 내부적으로 유효하다.

재현:
  .venv/bin/python3 scripts/analysis/news_confidence_weight_ab.py
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from morning_brief.data.finbert_sentiment import FinBertScorer  # noqa: E402

ARCHIVE = Path("data/raw_backup/news/pipeline/news_packet")
PARQUET = Path("data/sentiment_join/master_20260710.parquet")


def _load_articles_by_date() -> dict[str, list[dict]]:
    """날짜별 기사 로드 + URL dedup(감사 §3.3: dup rate 48.9%)."""
    by_date: dict[str, list[dict]] = {}
    for date_dir in sorted(ARCHIVE.iterdir()):
        if not date_dir.is_dir():
            continue
        seen: set[str] = set()
        arts: list[dict] = []
        for f in sorted(glob.glob(f"{date_dir}/*.json")):
            obj = json.load(open(f))
            items = obj.get("items", []) if isinstance(obj, dict) else obj
            for a in items:
                url = a.get("url") or a.get("title")
                if url in seen:
                    continue
                seen.add(url)
                arts.append(a)
        if arts:
            by_date[date_dir.name] = arts
    return by_date


def _score_articles(by_date: dict[str, list[dict]]) -> pd.DataFrame:
    """FinBERT 재실행 → 날짜별 (simple_mean, conf_weighted_mean, n)."""
    stub = SimpleNamespace(
        finbert_model="ProsusAI/finbert",
        finbert_model_revision="",
        finbert_model_path="",
        finbert_batch_size=32,
        finbert_bullish_threshold=0.3,
        finbert_bearish_threshold=-0.3,
    )
    scorer = FinBertScorer(stub)  # type: ignore[arg-type]

    rows = []
    for date, arts in by_date.items():
        texts = [
            FinBertScorer.combine_fields(
                str(a.get("title") or ""),
                str(a.get("summary") or ""),
                str(a.get("why_it_matters") or ""),
            )
            for a in arts
        ]
        results = scorer.score_texts(texts)
        pairs = [
            (r.score, r.confidence)
            for r in results
            if r.score is not None and r.confidence is not None
        ]
        if not pairs:
            continue
        scores = np.array([p[0] for p in pairs], dtype=float)
        confs = np.array([p[1] for p in pairs], dtype=float)
        simple = float(scores.mean())
        conf_w = float((scores * confs).sum() / confs.sum()) if confs.sum() > 0 else simple
        rows.append(
            {
                "date": date,
                "n": len(pairs),
                "simple_mean": simple,
                "conf_weighted": conf_w,
                "abs_diff": abs(simple - conf_w),
            }
        )
    return pd.DataFrame(rows)


def _merge_returns(agg: pd.DataFrame) -> pd.DataFrame:
    """parquet의 사전계산 forward return 병합 (누수 없음: date D 감성 → D의 btc_fwd_ret_1d).

    파이프라인 규약(news_sentiment_mean_lag1로 예측: D-1 감성 → D)과 정합:
    D 감성 → D+1 수익 = btc_fwd_ret_1d(at D).
    """
    df = pd.read_parquet(PARQUET)
    px = df[["date", "btc_fwd_ret_1d", "btc_fwd_ret_3d"]].copy()
    px["date"] = pd.to_datetime(px["date"]).dt.strftime("%Y-%m-%d")
    px = px.drop_duplicates("date")
    px = px.rename(columns={"btc_fwd_ret_1d": "fwd_1d", "btc_fwd_ret_3d": "fwd_3d"})

    merged = agg.merge(px, on="date", how="inner")
    return merged.dropna(subset=["fwd_1d"]).reset_index(drop=True)


def _ic(a: np.ndarray, b: np.ndarray, method: str = "spearman") -> float:
    s = pd.Series(a)
    return float(s.corr(pd.Series(b), method=method))


def _bootstrap_ic_diff(
    sig_a: np.ndarray, sig_b: np.ndarray, ret: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> tuple[float, float, float, float]:
    """IC(b) - IC(a) 부트스트랩. 반환 (관측 diff, ci_lo, ci_hi, p(diff>0))."""
    rng = np.random.default_rng(seed)
    m = len(ret)
    obs = _ic(sig_b, ret) - _ic(sig_a, ret)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, m, m)
        diffs[i] = _ic(sig_b[idx], ret[idx]) - _ic(sig_a[idx], ret[idx])
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p_pos = float((diffs > 0).mean())
    return obs, float(lo), float(hi), p_pos


def main() -> int:
    print("1) 아카이브 로드 + dedup...")
    by_date = _load_articles_by_date()
    print(f"   {len(by_date)}일, 총 {sum(len(v) for v in by_date.values())}건(dedup 후)")

    print("2) FinBERT 재실행(과거 점수·confidence 재구성)...")
    agg = _score_articles(by_date)
    print(f"   점수화 성공: {len(agg)}일, 평균 기사수 {agg['n'].mean():.1f}")
    print(f"   두 집계 평균 절대차: {agg['abs_diff'].mean():.4f} (max {agg['abs_diff'].max():.4f})")

    print("3) BTC forward return 병합...")
    m = _merge_returns(agg)
    print(f"   유효 표본: {len(m)}일 ({m['date'].min()} ~ {m['date'].max()})")
    if len(m) < 20:
        print("   ⚠️ 표본 <20 — 통계적 판정 불가.")

    print("\n=== IC 비교 (Spearman, 신호=감성 vs 타깃=forward return) ===")
    for horizon in ["fwd_1d", "fwd_3d"]:
        sub = m.dropna(subset=[horizon])
        if len(sub) < 20:
            print(f"[{horizon}] 표본 부족({len(sub)}) — 스킵")
            continue
        ret = sub[horizon].to_numpy()
        a = sub["simple_mean"].to_numpy()
        b = sub["conf_weighted"].to_numpy()
        ic_a = _ic(a, ret)
        ic_b = _ic(b, ret)
        obs, lo, hi, p_pos = _bootstrap_ic_diff(a, b, ret)
        verdict = (
            "confidence 가중 우위(유의)"
            if lo > 0
            else "단순 평균 우위(유의)"
            if hi < 0
            else "차이 불명확(CI가 0 포함)"
        )
        print(f"\n[{horizon}] n={len(sub)}")
        print(f"  IC 단순평균     = {ic_a:+.4f}")
        print(f"  IC confidence   = {ic_b:+.4f}")
        print(
            f"  IC 차이(conf-단순) = {obs:+.4f}  95%CI [{lo:+.4f}, {hi:+.4f}]  P(diff>0)={p_pos:.2f}"
        )
        print(f"  판정: {verdict}")

    print("\n※ 주의: n≈50 소표본. IC 자체가 작고 CI가 넓으면 '개선 미확인'이 정직한 결론.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
