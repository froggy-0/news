# SENTIMENT_JOIN_POST_BACKFILL_REVIEW_20260419

## OVERALL

- 평가 파일: `data/sentiment_join/master_20260419.parquet`
- 평가 기간: 2025-04-24 ~ 2026-04-18, 360 rows
- 관점:
  - Data Scientist: 통계적 유효성, 예측력, 신호 해석 가능성
  - Senior Data Engineer: 데이터 계약, lineage, 재현성, 운영 안정성
- 결론:
  - 이전 최상위 결함이던 `VIX=0%`, `OI/LSR 장기 공백`은 해소됨
  - 현재 가장 큰 결함은 데이터 커버리지가 아니라 `알파/예측력의 약함`
  - `full_hybrid_index`는 기술적으로 usable 상태로 승격됐지만, 투자 판단 신호로 쓰기 전 별도 검증이 필요함

## CURRENT_STATE

### COVERAGE

| Feature | Coverage | Status |
|---|---:|---|
| news_sentiment_mean | 360/360, 100.00% | ok |
| funding_rate | 360/360, 100.00% | ok |
| open_interest_usd | 360/360, 100.00% | ok |
| btc_long_short_ratio | 360/360, 100.00% | ok |
| etf_total_btc | 360/360, 100.00% | ok |
| etf_total_aum_usd | 360/360, 100.00% | ok |
| etf_net_inflow_usd | 359/360, 99.72% | ok |
| fng_value | 360/360, 100.00% | ok |
| vix | 359/360, 99.72% | ok |
| usdkrw_log_return | 350/360, 97.22% | acceptable |
| full_hybrid_index_score | 283/360, 78.61% | ok |
| core_hybrid_index_score | 284/360, 78.89% | ok |

### STRUCTURED_SOURCES

- `btc_etf`
  - mode: `gold_history`
  - quality_status: `ok`
  - coverage_ratio: `1.0`
- `futures`
  - mode: `supabase`
  - quality_status: `ok`
  - funding_ratio: `1.0`
  - oi_ratio: `1.0`
  - lsr_ratio: `1.0`
  - returned_min_date: 2025-04-23
  - returned_max_date: 2026-04-19

### HYBRID_INDEX_STATUS

| Index | Rows Used | Coverage | PCA Status | Quality | Signal |
|---|---:|---:|---|---|---|
| full | 283/360 | 78.61% | ok | ok | risk_on |
| core | 284/360 | 78.89% | ok | ok | neutral |

## DEFECTS_BY_SEVERITY

### 1. ALPHA / PREDICTIVE VALIDITY IS STILL WEAK

#### Severity

Critical

#### Evidence

- Hit rate is near random:
  - `full_hybrid_index_score_lag1`: 47.35%
  - `core_hybrid_index_score_lag1`: 49.30%
  - `fng_value_lag1`: 49.82%
  - `vix_lag1`: 50.35%
- Correlation with next-day BTC return is effectively zero:
  - full score vs `btc_log_return`: Pearson -0.0039, Spearman -0.0149
  - core score vs `btc_log_return`: Pearson -0.0044, Spearman -0.0096
- Walk-forward validation is weak:
  - full avg hit rate: 48.97%
  - full avg cumulative return: -1.27%
  - full avg alpha: +0.33%
  - core avg hit rate: 42.82%
  - core avg alpha: -0.54%
- Full score quartiles do not show clean monotonic next-day return separation:
  - Q1 low mean return: -0.058%
  - Q2 mean return: -0.162%
  - Q3 mean return: -0.033%
  - Q4 high mean return: -0.149%

#### Interpretation

Data coverage is now sufficient enough to test the index, and the current result says the index is not yet a reliable next-day directional alpha signal.

This does not mean the index is useless. It may still be useful as:

- market regime descriptor
- risk-on/risk-off context
- prompt grounding feature
- ETF/futures/sentiment dashboard signal

But it should not yet be described as a directional predictor.

#### Recommendation

- Label current `full_hybrid_index` as `regime_index`, not `prediction_index`.
- Keep it in brief generation as context only.
- Avoid language such as "leading signal" unless target-specific validation is strong.
- Add model comparison against trivial baselines:
  - always-up
  - previous-day direction
  - FNG-only
  - BTC momentum-only
  - volatility regime-only
- Evaluate longer horizons:
  - T+1, T+3, T+7 return
  - forward max drawdown
  - forward realized volatility
  - probability of large move, not just direction

### 2. OUTLIER MASKING REMOVES TOO MUCH EFFECTIVE SAMPLE

#### Severity

High

#### Evidence

- `outlier_filtered_count`: 74
- `outlier_filtered_ratio`: 20.56%
- Raw coverage is near complete, but hybrid coverage is only:
  - full: 283/360, 78.61%
  - core: 284/360, 78.89%
- Recent full-score missing rows include market-stress dates:
  - 2026-04-13
  - 2026-04-17
  - 2026-04-18

#### Interpretation

The pipeline currently treats a large share of rows as unusable for statistical/PCA analysis. In financial time series, extreme rows are often the signal, not merely bad data.

If outlier masking removes major volatility episodes, the index may become most blind when users need it most.

#### Recommendation

- Split outlier handling into two categories:
  - `data_error_outlier`: impossible or provider-broken values
  - `market_regime_outlier`: valid stress-market observations
- Do not mask `market_regime_outlier` by default.
- Add outlier diagnostics by column and date.
- Recompute hybrid coverage and walk-forward performance with:
  - no market outlier mask
  - winsorized features
  - robust scaler
  - rolling z-score clipping

### 3. GRANGER RESULTS ARE EASY TO MISINTERPRET

#### Severity

High

#### Evidence

- Granger tests executed: 63
- Significant tests: 16
- Primary significant tests: 6
- Significant target=`btc_log_return`: none
- Significant results are mostly:
  - `news_sentiment_mean -> fng_value`
  - `news_sentiment_mean -> etf_net_inflow_usd`
  - `btc_log_return -> news_sentiment_mean`
  - `btc_log_return -> fng_value`
  - `btc_log_return -> btc_long_short_ratio`
- Many significant entries include `warning: non_contiguous_dates`.

#### Interpretation

The strongest Granger evidence is not "signals predict BTC returns." It is closer to:

- BTC returns affect sentiment and positioning metrics.
- News sentiment/FNG/ETF flows move together.
- Some variables may be reaction indicators, not leading indicators.

This is valuable, but it changes the story. The system should not promote broad Granger significance as alpha unless the target is explicitly BTC return and survives the data-contiguity warning.

#### Recommendation

- Separate Granger outputs into:
  - `alpha_target_tests`: predictors -> `btc_log_return`
  - `market_structure_tests`: predictors -> non-return features
  - `reverse_causality_tests`: `btc_log_return` -> predictors
- In prompt/report surfaces, only call something "leading" if it is in `alpha_target_tests`.
- Treat `non_contiguous_dates` as degraded inference until the gap handling is improved.

### 4. FULL INDEX ADDS LIMITED INCREMENTAL INFORMATION OVER CORE

#### Severity

Medium-High

#### Evidence

- full/core score correlation:
  - Pearson: 0.9528
  - Spearman: 0.9571
- Full PCA selected all 7 features, but PC1 loadings are still dominated by sentiment/FNG:
  - `fng_value_lag1`: +0.5365
  - `news_sentiment_mean_lag1`: +0.5278
  - `btc_long_short_ratio_lag1`: -0.4698
  - `funding_rate_lag1`: +0.2919
  - `etf_net_inflow_usd_lag1`: +0.2794
  - `vix_lag1`: -0.2214
  - `volume_change_pct_lag1`: +0.0241
- `volume_change_pct_lag1` contributes almost nothing to PC1.

#### Interpretation

The backfilled futures data makes full index computable, but the index may not yet be informationally distinct from core. Full is currently more feature-rich, not necessarily more useful.

#### Recommendation

- Add incremental value tests:
  - full vs core walk-forward delta
  - full-only features ablation
  - likelihood/log-loss or Brier score if predicting direction probability
  - regime classification stability
- Consider replacing unsupervised PCA with supervised or semi-supervised alternatives:
  - regularized logistic regression for direction
  - regression for forward volatility
  - tree-based feature importance as diagnostic only
  - PCA for regime compression, not alpha prediction

### 5. FUTURES LINEAGE IS NOT PRECISE ENOUGH AFTER COINALYZE BACKFILL

#### Severity

Medium-High

#### Evidence

- `btc_futures_daily.source` is a row-level field.
- Coinalyze backfill upserts `source="coinalyze"` for OI/LSR rows.
- Funding values can still be pre-existing Binance/Supabase values on the same row.
- The OI `date + 1 day` alignment rule is implemented in `scripts/backfill_btc_futures.py`, but not represented as source-contract metadata in the table.

#### Interpretation

The data values are now complete, but the table cannot precisely answer:

- Which provider supplied funding for this date?
- Which provider supplied OI for this date?
- Which provider supplied LSR for this date?
- Which date-alignment contract was applied?

This matters for future audits, provider migration, and regression debugging.

#### Recommendation

- Add metric-level lineage columns or a companion audit table:
  - `funding_source`
  - `open_interest_source`
  - `long_short_ratio_source`
  - `source_contract_version`
  - `ingested_at`
  - `provider_symbol`
  - `provider_interval`
  - `date_alignment_rule`
- For current table, at minimum document that `source` is row-level and may represent the latest writer, not every metric source.
- Store a backfill manifest for Coinalyze runs:
  - requested_start
  - requested_end
  - row_count
  - provider
  - OI alignment rule
  - dry-run hash or sample checksum

### 6. COINALYZE BACKFILL IS LOCAL-ONLY AND NOT YET OPERATIONALIZED

#### Severity

Medium

#### Evidence

- Coinalyze is intentionally local-only for backfill.
- GitHub Actions does not need `COINALYZE_API_KEY`.
- The current pipeline reads Supabase, but does not monitor whether historical coverage regresses.

#### Interpretation

This is acceptable for a one-time backfill, but operational guardrails should exist so future table edits or partial overwrites do not silently degrade full index coverage.

#### Recommendation

- Add a lightweight coverage assertion command:
  - fail if OI/LSR coverage < 95% for the configured lookback
  - warn if returned_min_date / returned_max_date do not cover requested window
- Add a recurring manual checklist after futures backfill:
  - Supabase coverage query
  - `make sentiment-join`
  - inspect full/core quality
  - compare latest Binance vs Supabase for last 30 days
- Consider a local-only script flag:
  - `--validate-only`
  - `--compare-binance-latest`
  - `--write-manifest data/futures/backfill_manifest_YYYYMMDD.json`

### 7. USD/KRW AND MARKET-CALENDAR GAPS ARE MINOR BUT STILL PRESENT

#### Severity

Low-Medium

#### Evidence

- `usdkrw_log_return`: 350/360, 97.22%
- `vix`: 359/360, 99.72%
- Several Granger outputs warn `non_contiguous_dates`.

#### Interpretation

This is not a blocking issue, but it can affect statistical tests that assume evenly spaced observations.

#### Recommendation

- Make calendar treatment explicit per feature:
  - 24/7 crypto series
  - US market daily series
  - Korea FX/holiday series
- For time-series tests, either:
  - use a common valid calendar after forward-fill rules, or
  - report that inference is on an irregular effective calendar.

## UPDATED_COMPONENT_ASSESSMENT

| Component | Status | Reason |
|---|---|---|
| ETF flow / total BTC / AUM | valid | 100% coverage, source mode `gold_history` |
| funding_rate | valid_for_context | 100% coverage, weak standalone directional signal |
| OI / LSR | valid_for_analysis | 100% coverage after Coinalyze backfill; lineage needs improvement |
| VIX | valid | 99.72% coverage after FRED key fix |
| news_sentiment | valid_but_not_alpha_proven | coverage ok, but return prediction weak |
| core_hybrid_index | usable_as_context | quality ok, predictive performance weak |
| full_hybrid_index | usable_as_context_and_research | quality ok, full coverage ok, alpha not proven |
| Granger outputs | diagnostic_only | no significant BTC-return target; reverse causality strong |

## PRIORITIZED_ACTIONS

### IMMEDIATE

1. Update downstream wording:
   - full/core index = market regime context
   - not confirmed directional alpha
2. Add a report guard:
   - hide or soften "leading signal" unless target is `btc_log_return` and significant.
3. Audit outlier masking:
   - list masked rows by date and triggering column.
   - determine whether masked rows are valid market stress days.

### SHORT_TERM

1. Add metric-level futures lineage.
2. Add Coinalyze backfill manifest output.
3. Add validation command for Supabase coverage:
   - funding/OI/LSR min/max/count
   - recent 30-day Binance comparison
4. Add full-vs-core incremental evaluation:
   - ablation
   - walk-forward delta
   - full-only feature contribution.

### MID_TERM

1. Test alternative targets:
   - T+3/T+7 return
   - forward volatility
   - drawdown probability
   - large-move classification.
2. Evaluate supervised models as benchmark, not necessarily production:
   - logistic regression
   - elastic net
   - gradient boosting diagnostics.
3. Revisit index construction:
   - keep PCA for regime compression
   - build separate alpha model only if out-of-sample evidence improves.

## FINAL_JUDGMENT

The pipeline has moved from a data engineering failure state into a statistically testable state.

Resolved:

- VIX missing
- OI/LSR long-horizon gap
- full index coverage below threshold

Remaining highest-risk issues:

1. The hybrid indices do not yet show reliable next-day BTC return prediction.
2. Outlier masking removes around one-fifth of rows and may suppress important market stress regimes.
3. Granger outputs can be misread as alpha, while significant evidence is mostly non-return or reverse-causality.
4. Futures lineage is not metric-level, which weakens auditability after Coinalyze backfill.

Recommended operating stance:

- Use `core_hybrid_index` and `full_hybrid_index` as quantitative regime context.
- Do not use either as a standalone trading or direction signal yet.
- Treat the new full index as ready for research and controlled monitoring, not as proven alpha.
