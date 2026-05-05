# Frontend Contract Mapping

이 디렉토리의 `brief.types.ts` 는 프론트엔드가 읽는 JSON 계약의 기준입니다.

현재 파이프라인은 `src/morning_brief` 아래에서 packet 을 만들고, 프론트는 그 packet 을 직접 읽지 않고 아래 목표 계약으로 정규화된 JSON 을 읽습니다.

## 주요 매핑

| 현재 packet | 프론트 계약 |
| --- | --- |
| `generated_at_utc` | `meta.generatedAt` |
| `data_footer_notes` | `meta.qualityNotes` |
| `macro`, `bitcoin.spot` | `marketSnapshot.items` |
| `risk_overlay` | `riskOverlay` |
| `bitcoin.spot`, `bitcoin.fear_greed_*`, `bitcoin.official_etf_*`, `macro.dxy`, `macro.vix` | `cryptoIndicators` |
| `tech_stocks` | `techStocks` (legacy field; crypto-related reference equities) |
| `bitcoin.fear_greed_value`, `bitcoin.fear_greed_label` | `bitcoin.fearGreedIndex` |
| `bitcoin.official_etf_total_btc`, `bitcoin.official_etf_total_aum_usd` | `bitcoin.etf.totalHolding`, `bitcoin.etf.totalAum` |
| `bitcoin.official_etf_snapshots` | `bitcoin.etf.issuers` |
| 뉴스 packet | `news[]` |
| X 시그널 packet | `xSignals[]` |

## 주의

- 프론트는 stale ETF snapshot 기반 추정치를 노출하지 않습니다.
- 핵심 블록은 값이 없더라도 상태 문구를 유지합니다.
- `schema/brief.types.ts` 변경 시 `docs/specs/public-brief-frontend/design.md`, fixture, validation 로직을 함께 갱신해야 합니다.
