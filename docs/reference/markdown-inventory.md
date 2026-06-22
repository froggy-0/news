# Markdown Inventory

이 문서는 프로젝트 문서 Markdown 경로를 누락 없이 찾기 위한 인벤토리입니다.

기준: Git 추적 문서와 이번 문서 정리에서 추가한 `docs/` 문서입니다.

제외 대상: `.agents`, `.claude`, `.kiro`, 가상환경, 캐시, `node_modules`, `.next`, `.wrangler`, 리뷰 이미지, 기타 미추적 생성물 디렉터리.

Total project Markdown files: 180

| Category | Path | Heading |
| --- | --- | --- |
| root | `README.md` | SOVEREIGNWON |
| analysis-artifact | `analysis/reports/master_20260424_report.md` | master_20260424.parquet 데이터 상태 보고서 |
| analysis-artifact | `analysis/reports/master_20260426_analysis.md` | Master Parquet 데이터 품질 분석 리포트 |
| analysis-artifact | `analysis/reports/n_articles_threshold_analysis.md` | n_articles 최소 임계값 분석 |
| dataset | `dataset/pipeline/README.md` | CoinDesk 뉴스 데이터셋 파이프라인 |
| docs/ops | `docs/CONTRIBUTING.md` | Contributing |
| docs/ops | `docs/README.md` | SOVEREIGNWON Documentation |
| docs/ops | `docs/ai-evals.md` | AI Eval Matrix |
| docs/analysis | `docs/analysis/README.md` | Analysis Docs |
| docs/analysis | `docs/analysis/sentiment-join/diagnostic-runbook.md` | Sentiment Join Diagnostic Runbook |
| docs/analysis | `docs/analysis/sentiment-join/feature-roadmap-20260504.md` | Feature Roadmap — 복합 수급 인덱스 설계 (2026-05-04) |
| docs/analysis | `docs/analysis/sentiment-join/oi_hit_rate_diagnostic_report_20260430.md` | OI Divergence Hit-Rate Diagnostic Report |
| docs/analysis | `docs/analysis/sentiment-join/outlier-policy-review-20260424.md` | OUTLIER_POLICY_REVIEW — IQR vs Winsorize 결정 분석 |
| docs/analysis | `docs/analysis/sentiment-join/p0-improvement-results-20260430.md` | Sentiment Join P0 개선 결과 보고서 |
| docs/analysis | `docs/analysis/sentiment-join/p0-pipeline-improvement-plan-20260429.md` | Sentiment Join 파이프라인 P0 개선 계획 |
| docs/analysis | `docs/analysis/sentiment-join/parquet-status-report-20260424.md` | Sentiment Join Parquet 현황 리포트 |
| docs/analysis | `docs/analysis/sentiment-join/peer-review-feedback-20260507.md` | Peer Review 피드백 — Sovereign Index & Regime Signal |
| docs/analysis | `docs/analysis/sentiment-join/pipeline-development-guide.md` | Sentiment Join Pipeline — 개발 가이드 (2026-04-30) |
| docs/analysis | `docs/analysis/sentiment-join/post-backfill-review-20260419.md` | SENTIMENT_JOIN_POST_BACKFILL_REVIEW_20260419 |
| docs/analysis | `docs/analysis/sentiment-join/run-issues-20260418.md` | Sentiment Join Run Issues |
| docs/analysis | `docs/analysis/sentiment-join/run-summary-20260418-lookback365.md` | Sentiment Join Run Summary (2026-04-18, lookback=365) |
| docs/analysis | `docs/analysis/sentiment-join/sentiment_join_payoff_review_20260427.md` | Sentiment Join Payoff Review - 2026-04-27 |
| docs/analysis | `docs/analysis/sentiment-join/sentiment_join_pipeline_changes.md` | Sentiment Join 파이프라인 변경 요약 및 운영 체크포인트 |
| docs/analysis | `docs/analysis/sentiment-join/sentiment_join_review_20260427.md` | Sentiment Join 파이프라인 진단 리뷰 |
| docs/analysis | `docs/analysis/sentiment-join/sentiment_join_sprint_review_20260427.md` | Sentiment Join 스프린트 구현 검증 리포트 |
| docs/analysis | `docs/analysis/sentiment-join/signal-pipeline-status-20260503.md` | Signal Pipeline 현황 — 2026-05-03 |
| docs/analysis | `docs/analysis/sentiment-join/sovereign-regime-signal-baseline-20260507.md` | Sovereign Index + Regime Signal — 부가가치 기준점 문서 |
| docs/analysis | `docs/analysis/signal-improvement-audit-20260514.md` | vol_regime_v2 신호 개선 감사 리포트 |
| docs/arena | `docs/arena/README.md` | SOVEREIGNWON Arena Docs |
| docs/arena | `docs/arena/architecture/data-lake-v0.md` | Arena Data Lake v0 |
| docs/arena | `docs/arena/architecture/strategy-taxonomy-and-sleeve-contract.md` | Arena Strategy Taxonomy and Sleeve Contract |
| docs/arena | `docs/arena/architecture/system-map.md` | Arena System Map |
| docs/arena | `docs/arena/operations/access-runbook.md` | Arena Access Runbook |
| docs/arena | `docs/arena/operations/dashboard-runbook.md` | Arena 대시보드 Runbook |
| docs/arena | `docs/arena/operations/deploy-runbook.md` | BTC Signal Arena 배포 Runbook 초안 |
| docs/arena | `docs/arena/overview/current-state.md` | Arena Current State |
| docs/arena | `docs/arena/overview/decision-log.md` | Arena Decision Log |
| docs/arena | `docs/arena/overview/next-session-handoff.md` | Arena Next Session Handoff |
| docs/arena | `docs/arena/product/business-model.md` | BTC Signal Arena — 비즈니스 모델 분석 |
| docs/arena | `docs/arena/product/product-requirements.md` | BTC Signal Arena — 제품 요구사항 문서 (PRD) |
| docs/arena | `docs/arena/product/roadmap.md` | BTC Signal Arena — 단계별 로드맵 |
| docs/arena | `docs/arena/product/vision.md` | BTC Signal Arena — 비전 및 장기 목표 |
| docs/arena | `docs/arena/reference/parameter-inventory.md` | Parameter Inventory |
| docs/arena | `docs/arena/research/backtest-framework-v1.md` | Arena Backtest Framework v1 |
| docs/arena | `docs/arena/research/frequency-research-v1.md` | Arena Frequency Research v1 |
| docs/arena | `docs/arena/research/realtime-execution-gate-v1.md` | Real-time Execution Gate v1 |
| docs/arena | `docs/arena/research/realtime-risk-trigger-v1.md` | Realtime Risk Trigger v1 |
| docs/arena | `docs/arena/research/research-mart-v1.md` | Arena Research Mart v1 |
| docs/arena | `docs/arena/research/roster-diagnostics-and-parity-v1.md` | Roster Diagnostics and Parity v1 |
| docs/arena | `docs/arena/research/shadow-tca-v1.md` | Shadow TCA v1 |
| docs/arena | `docs/arena/spot-deep-research-report.md` | BTC 현물 전용 알고리즘 트레이딩 심층 리서치 보고서 |
| docs/briefing | `docs/briefing/README.md` | Sovereign Briefing Docs |
| docs/ops | `docs/codex-ops.md` | Codex Ops Setup |
| docs/ops | `docs/data-flow.md` | 데이터 수집·정제 흐름 (Data Flow) |
| docs/ops | `docs/data-sources.md` | 데이터 소스 및 품질 기준 |
| docs/ops | `docs/development-standards.md` | Development Standards |
| docs/frontend | `docs/frontend/README.md` | Frontend Docs |
| docs/infrastructure | `docs/infrastructure/README.md` | Infrastructure Docs |
| docs/ops | `docs/llm-cost-ops.md` | LLM 비용 절감 운영 체크리스트 |
| docs/ops | `docs/logging-ops.md` | Logging Ops |
| docs/reference | `docs/reference/codebase-map.md` | Codebase Map |
| docs/reference | `docs/reference/docs-rubric.md` | Documentation Rubric |
| docs/reference | `docs/reference/markdown-inventory.md` | Markdown Inventory |
| docs/reports | `docs/reports/README.md` | Reports Docs |
| docs/reports | `docs/reports/sentiment-join-code-report-draft.md` | Sovereign Brief — Sentiment-Join 파이프라인 코드 기반 보고서 |
| docs/reports | `docs/reports/sentiment-join-final-report.md` | **1. 프로젝트 개요 및 연구 질문** |
| docs/research | `docs/research/README.md` | Research Docs |
| docs/research | `docs/research/eda-visualization-questionnaire.md` | EDA 시각화 요구사항 — 작업자 전달용 질문서 |
| docs/research | `docs/research/sentiment-join-pipeline-research.md` | 파이프라인 코드 리서치 정리 |
| docs/specs | `docs/specs/03-granger-cross-pairs/tasks.md` | Implementation Plan: Granger Cross-Pairs (Task 03) |
| docs/specs | `docs/specs/README.md` | Specs Docs |
| docs/specs | `docs/specs/analytics-storage-contract-v2/design.md` | Design Document: Analytics Storage Contract V2 |
| docs/specs | `docs/specs/analytics-storage-contract-v2/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/analytics-storage-contract-v2/tasks.md` | Implementation Plan: Analytics Storage Contract V2 |
| docs/specs | `docs/specs/aws-ses-mail-migration/design.md` | Design Document: AWS SES Mail Migration |
| docs/specs | `docs/specs/aws-ses-mail-migration/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/aws-ses-mail-migration/tasks.md` | Implementation Plan: aws-ses-mail-migration |
| docs/specs | `docs/specs/binance-integration/design.md` | Design Document — binance-integration |
| docs/specs | `docs/specs/binance-integration/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/binance-integration/tasks.md` | Implementation Plan: binance-integration |
| docs/specs | `docs/specs/btc-etf-collection-redesign/design.md` | Design Document: BTC ETF Collection Redesign |
| docs/specs | `docs/specs/btc-etf-collection-redesign/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/btc-etf-collection-redesign/tasks.md` | Implementation Plan: BTC ETF Collection Redesign |
| docs/specs | `docs/specs/data-ingestion-quality-improvement/design.md` | Design Document: data-ingestion-quality-improvement |
| docs/specs | `docs/specs/data-ingestion-quality-improvement/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/data-ingestion-quality-improvement/tasks.md` | Implementation Plan: data-ingestion-quality-improvement |
| docs/specs | `docs/specs/finbert-sentiment/design.md` | Design Document: FinBERT Sentiment |
| docs/specs | `docs/specs/finbert-sentiment/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/finbert-sentiment/tasks.md` | Implementation Plan: FinBERT Sentiment |
| docs/specs | `docs/specs/front-page-readability-refresh/design.md` | Design Document: front-page-readability-refresh |
| docs/specs | `docs/specs/front-page-readability-refresh/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/front-page-readability-refresh/tasks.md` | Implementation Plan: front-page-readability-refresh |
| docs/specs | `docs/specs/frontend-restructure/design.md` | Design — frontend-restructure |
| docs/specs | `docs/specs/frontend-restructure/requirements.md` | Requirements — frontend-restructure |
| docs/specs | `docs/specs/frontend-restructure/tasks.md` | Implementation Plan: frontend-restructure |
| docs/specs | `docs/specs/frontend-ssg-redesign-migration/design.md` | Design Document: Frontend SSG Redesign Migration |
| docs/specs | `docs/specs/frontend-ssg-redesign-migration/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/frontend-ssg-redesign-migration/tasks.md` | Implementation Plan: Frontend SSG Redesign Migration |
| docs/specs | `docs/specs/hybrid-dynamic-registry/design.md` | Fully Automated Dynamic Registry — Feature Design |
| docs/specs | `docs/specs/hybrid-dynamic-registry/operations.md` | Hybrid Dynamic Registry — 운영 가이드 |
| docs/specs | `docs/specs/hybrid-dynamic-registry/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/hybrid-dynamic-registry/tasks.md` | Implementation Plan |
| docs/specs | `docs/specs/kis-market-data-expansion/design.md` | KIS Market Data Expansion — Design Document |
| docs/specs | `docs/specs/kis-market-data-expansion/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/kis-market-data-expansion/tasks.md` | Implementation Plan: KIS Market Data Expansion |
| docs/specs | `docs/specs/logging-unification/design.md` | Logging Unification — Feature Design |
| docs/specs | `docs/specs/logging-unification/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/logging-unification/tasks.md` | Implementation Plan |
| docs/specs | `docs/specs/mail-template-brand-alignment/design.md` | Design Document: Mail Template Brand Alignment |
| docs/specs | `docs/specs/mail-template-brand-alignment/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/mail-template-brand-alignment/tasks.md` | Implementation Plan: mail-template-brand-alignment |
| docs/specs | `docs/specs/news-analysis-prompt-grok-optimization/design.md` | Design Document: News Analysis Prompt & Grok Optimization |
| docs/specs | `docs/specs/news-analysis-prompt-grok-optimization/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/news-analysis-prompt-grok-optimization/tasks.md` | Implementation Plan: News Analysis Prompt & Grok Optimization |
| docs/specs | `docs/specs/news-sentiment-backfill/design.md` | Design Document: news-sentiment-backfill |
| docs/specs | `docs/specs/news-sentiment-backfill/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/news-sentiment-backfill/tasks.md` | Implementation Plan: news-sentiment-backfill |
| docs/specs | `docs/specs/news-sentiment-market-causality/design.md` | Design Document: News Sentiment Market Causality |
| docs/specs | `docs/specs/news-sentiment-market-causality/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/newsletter-subscriptions/design.md` | Design Document: newsletter-subscriptions |
| docs/specs | `docs/specs/newsletter-subscriptions/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/newsletter-subscriptions/tasks.md` | Implementation Plan: newsletter-subscriptions |
| docs/specs | `docs/specs/prompt-governance-unification/design.md` | Design Document: prompt-governance-unification |
| docs/specs | `docs/specs/prompt-governance-unification/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/public-brief-frontend/design.md` | Design — 금융 뉴스 데일리 프론트 페이지 |
| docs/specs | `docs/specs/public-brief-frontend/requirements.md` | Requirements — 금융 뉴스 데일리 프론트 페이지 |
| docs/specs | `docs/specs/public-brief-frontend/tasks.md` | 구현 계획: 금융 뉴스 데일리 프론트 페이지 |
| docs/specs | `docs/specs/public-brief-ux-plan.md` | 공개 브리프 UX/데이터 정리 계획 |
| docs/specs | `docs/specs/public-news-analysis-generation/design.md` | Design Document: Public News Analysis Generation |
| docs/specs | `docs/specs/public-news-analysis-generation/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/public-news-analysis-generation/tasks.md` | Implementation Plan: Public News Analysis Generation |
| docs/specs | `docs/specs/public-news-article-selection/bugfix.md` | Bugfix Document |
| docs/specs | `docs/specs/public-news-article-selection/design.md` | Design Document: Public News Article Selection |
| docs/specs | `docs/specs/public-news-article-selection/tasks.md` | Implementation Plan: Public News Article Selection |
| docs/specs | `docs/specs/public-news-feed-quality/design.md` | Design Document |
| docs/specs | `docs/specs/public-news-feed-quality/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/public-news-feed-quality/tasks.md` | Tasks Document |
| docs/specs | `docs/specs/r2-storage/r2-json-contract.md` | R2 JSON 저장 기준 |
| docs/specs | `docs/specs/r2-storage/r2-rollout-plan.md` | 공개 R2 단계적 도입 계획 |
| docs/specs | `docs/specs/sentiment-insight-visualization/design.md` | Design Document: Sentiment Insight Visualization |
| docs/specs | `docs/specs/sentiment-insight-visualization/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/sentiment-insight-visualization/tasks.md` | Implementation Plan: Sentiment Insight Visualization |
| docs/specs | `docs/specs/sentiment-join-advanced-features/design.md` | Design Document: Sentiment-Join Advanced Features |
| docs/specs | `docs/specs/sentiment-join-advanced-features/tasks.md` | Implementation Plan: Sentiment-Join Advanced Features |
| docs/specs | `docs/specs/sentiment-join-outlier-rework/design.md` | Design — Sentiment-Join Outlier Rework & Ablation Platform |
| docs/specs | `docs/specs/sentiment-join-outlier-rework/tasks.md` | Tasks — Sentiment-Join Outlier Rework & Ablation Platform |
| docs/specs | `docs/specs/sentiment-time-join/data-dictionary.md` | Sentiment Time Join — 데이터 사전 |
| docs/specs | `docs/specs/sentiment-time-join/design.md` | Design Document: Sentiment Time Join |
| docs/specs | `docs/specs/sentiment-time-join/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/sentiment-time-join/tasks.md` | Implementation Plan: Sentiment Time Join |
| docs/specs | `docs/specs/statistical-rigor-fixes/tasks.md` | Implementation Plan: 02 Statistical Rigor Fixes |
| docs/specs | `docs/specs/stooq-to-kis-migration/design.md` | Design Document: Stooq → KIS Migration |
| docs/specs | `docs/specs/stooq-to-kis-migration/requirements.md` | Requirements Document |
| docs/specs | `docs/specs/stooq-to-kis-migration/tasks.md` | Implementation Plan: Stooq → KIS Migration |
| docs/specs | `docs/specs/tasks/01-pre-backfill-fixes.md` | Sentiment-Join 파이프라인 — 선행 개선 사항 |
| docs/specs | `docs/specs/tasks/02-statistical-rigor-fixes.md` | 2순위: 통계적 엄밀성(Rigor) — 코드 리뷰 결과 |
| docs/specs | `docs/specs/tasks/03-granger-cross-pairs.md` | Granger 교차 쌍 설계 |
| docs/specs | `docs/specs/tasks/04-hybrid-index-fixes.md` | 3순위: 하이브리드 지수 모델링 — 최신 코드 기준 정리 |
| docs/specs | `docs/specs/tasks/05-alpha-validation.md` | 5순위: 실전 예측 성능 검증 (Alpha Validation) |
| docs/specs | `docs/specs/tasks/06-completion-review.md` | Tasks → 리포트 완성 가능성 검토 |
| docs/specs | `docs/specs/tasks/07-grok-cost-tracking.md` | Grok API 비용 추적 개선 |
| docs/specs | `docs/specs/tasks/08-etf-collection-fixes.md` | ETF 수집 실패 및 부분 합산 문제 |
| docs/specs | `docs/specs/tasks/09-sentiment-join-review-20260418.md` | Sentiment-Join Review (2026-04-18) |
| docs/ops | `docs/sprint-review-2026-05.md` | Sprint Review — 2026-05 |
| docs/ops | `docs/subscriptions-ops.md` | Newsletter Subscription Ops |
| docs/teaching | `docs/teaching/README.md` | Teaching Docs |
| docs/teaching | `docs/teaching/frontend-analysis-contract-rubric.md` | Frontend Analysis Contract Rubric |
| docs/teaching | `docs/teaching/presentation-script-15min.md` | BTC 뉴스 감성 분석 — 15분 발표 스크립트 |
| docs/teaching | `docs/teaching/research-narrative.md` | 연구 서사 — 질문에서 61.8%까지 |
| docs/teaching | `docs/teaching/signal-design-log.md` | Signal Design Log — 고민·실패·결정의 기록 |
| docs/teaching | `docs/teaching/wfv-deep-dive.md` | Walk-Forward Validation — 시계열 검증의 정공법 |
| docs/teaching | `docs/teaching/wfv-slide-script.md` | Walk-Forward Validation — 발표 슬라이드 스크립트 |
| docs/ux | `docs/ux/README.md` | UX Docs |
| docs/ux | `docs/ux/conversion-ux-plan.md` | Sovereign Brief — 전환율 극대화 UX 개선 계획 |
| frontend | `frontend/DESIGN.md` | Overview |
| frontend | `frontend/README.md` | SOVEREIGNWON Frontend |
| frontend | `frontend/components/hero/scatter-text-philosophy.md` | Gravitational Crystallization |
| misc | `report_final.md` | BTC 뉴스 감성의 역설: 가격을 예측하지 못하지만 레짐을 기술한다 |
| schema | `schema/README.md` | Public JSON Contract Mapping |
| source-adjacent | `src/morning_brief/data/AGENTS.md` | AGENTS.md |
