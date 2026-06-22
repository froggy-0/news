# Public JSON Contract Mapping

`schema/`는 브리핑 파이프라인이 발행하고 프론트엔드가 읽는 JSON 계약의 기준입니다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `brief.types.ts` | 공개 브리핑 JSON 타입 계약 |
| `analysis.types.ts` | 분석 대시보드 JSON 타입 계약 |
| `mail/quiet-signal.tokens.json` | 이메일/디자인 토큰 |

## 생산자와 소비자

| 단계 | 경로 | 역할 |
| --- | --- | --- |
| 생산 | `src/morning_brief/public_site.py` | public brief JSON 생성/R2 업로드 |
| 정규화 | `src/morning_brief/unified_output.py` | 브리핑 내용을 프론트 계약에 가까운 구조로 변환 |
| 소비 | `frontend/lib/` | R2/fixture/output JSON 로드 |
| 표시 | `frontend/components/` | 브리핑/분석/뉴스/시그널 렌더링 |

## 주요 매핑

| pipeline packet | frontend contract |
| --- | --- |
| `generated_at_utc` | `meta.generatedAt` |
| `data_footer_notes` | `meta.qualityNotes` |
| `macro`, `bitcoin.spot` | `marketSnapshot.items` |
| `risk_overlay` | `riskOverlay` |
| `bitcoin.spot`, `bitcoin.fear_greed_*`, `bitcoin.official_etf_*`, `macro.dxy`, `macro.vix` | `cryptoIndicators` |
| `tech_stocks` | `techStocks` legacy/reference field |
| `bitcoin.fear_greed_value`, `bitcoin.fear_greed_label` | `bitcoin.fearGreedIndex` |
| `bitcoin.official_etf_total_btc`, `bitcoin.official_etf_total_aum_usd` | `bitcoin.etf.totalHolding`, `bitcoin.etf.totalAum` |
| `bitcoin.official_etf_snapshots` | `bitcoin.etf.issuers` |
| news packet | `news[]` |
| X signal packet | `xSignals[]` |

## 변경 규칙

- `brief.types.ts`를 바꾸면 `src/morning_brief/public_site.py`, frontend loader, fixture, tests를 함께 확인합니다.
- 분석 JSON을 바꾸면 `schema/analysis.types.ts`, `frontend/components/analysis/`, Sentiment Join frontend artifact 생성을 함께 확인합니다.
- stale ETF snapshot 기반 추정치는 프론트에 핵심 지표로 노출하지 않습니다.
- 핵심 블록은 값이 없더라도 상태 문구를 유지합니다.

관련 문서: `docs/frontend/README.md`, `docs/specs/public-brief-frontend/design.md`.
