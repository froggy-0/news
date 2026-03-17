# 요구사항: 데이터 수집 실패 소스 3건 개선

## 배경

이 프로젝트는 매일 아침 미국 기술주+비트코인 시장 브리핑을 자동 생성하는 파이프라인입니다. 최근 10회 연속 실행 로그를 분석한 결과, 3개 데이터 소스가 구조적으로 수집에 실패하고 있어 브리핑 품질이 저하되고 있습니다.

분석 문서는 아래 경로에 있으니 반드시 먼저 읽어주세요:
- `docs/data-source-reliability.md` — 소스별 신뢰도 실측 분석 및 트레이드오프
- `docs/pipeline-diagnosis-20260317.md` — 최근 실행 진단 리포트
- `docs/data-flow.md` — 전체 데이터 흐름 문서

---

## 문제 1: DXY(달러 인덱스) 10/10 수집 실패

**현상**: yfinance 티커 `DX-Y.NYB`가 "possibly delisted"로 매번 실패. 거시 지표 5개 중 1개(20%)가 매일 누락됨. 캐시에도 값이 없어 fallback도 작동하지 않음.

**관련 코드**: `src/morning_brief/data/market.py`의 `MACRO_FALLBACK_TARGETS` 튜플에서 `("dxy", "DX-Y.NYB", 1.0)` 정의. 현재 DXY는 yfinance 단독 경로이며 Stooq/FRED fallback이 없음.

**요구사항**:
1. Stooq에서 DXY에 해당하는 심볼이 있는지 리서치해주세요 (예: `dx.f`, `usdx.idx` 등). Stooq는 이 프로젝트에서 18/18 = 100% 성공률을 보이는 가장 안정적인 소스입니다.
2. yfinance에서 `DX=F` (ICE 달러 선물) 티커가 유효한지도 확인해주세요.
3. 리서치 결과를 바탕으로 가장 신뢰도 높은 조합으로 DXY 수집 경로를 수정해주세요. 이 프로젝트의 다른 지표들처럼 "Stooq 우선 → yfinance fallback" 패턴이 이상적입니다.
4. 수정 범위는 최소화하고, 기존 `MACRO_FALLBACK_TARGETS` 구조와 `build_market_packet()` 로직을 최대한 활용해주세요.

---

## 문제 2: BTC ETF 보유량 데이터 — Perplexity structured query 10/10 빈 배열

**현상**: Perplexity에 IBIT/BITB/GBTC 보유량을 structured JSON으로 요청하면 매번 `{"snapshots": []}` 반환. 반면 direct fetch(공식 issuer 페이지 직접 파싱)는 IBIT+BITB 2건 100% 성공.

**관련 코드**:
- `src/morning_brief/data/sources/btc_etf_official.py` — Perplexity structured query + direct fetch 로직
- `src/morning_brief/data/sources/perplexity_sonar.py` — Perplexity API 호출

**요구사항**:
1. 먼저 BTC ETF 보유량/순유입 데이터가 이 브리핑에서 어떤 역할을 하는지 검토해주세요. 프롬프트 템플릿(`src/morning_brief/prompts/`)과 브리핑 생성 로직(`src/morning_brief/briefing.py`)을 확인해서, 이 데이터가 브리핑 본문에 실제로 얼마나 반영되는지 판단해주세요.
2. **필수 데이터라면**: Perplexity structured query가 왜 빈 배열을 반환하는지 원인을 분석하고, 수집이 성공할 수 있는 대안을 리서치해주세요. 후보:
   - Perplexity 프롬프트/파라미터 조정으로 structured response를 개선할 수 있는지
   - direct fetch 외에 보유량 데이터를 제공하는 다른 API나 소스가 있는지 (CoinGlass, SoSoValue 등)
   - direct fetch(IBIT+BITB)를 primary로 승격하고 Perplexity는 보조로 전환하는 방식
3. **필수가 아니라면**: 수집 우선순위를 낮추거나, direct fetch 2건(IBIT+BITB)만으로 충분한지 판단하고 그에 맞게 정리해주세요.
4. 어떤 방향이든 Perplexity Sonar의 다른 용도(토픽 요약, 뉴스 수집 등)는 건드리지 마세요. BTC ETF structured query만 대상입니다.
5. 기존 캐시 구조(`btc-etf-snapshots-YYYYMMDD`)는 유지해주세요.

---

## 문제 3: GBTC(Grayscale) 보유량 수집 불가

**현상**: Grayscale 공식 사이트가 HTTP 429로 scraping을 차단. Perplexity structured query도 빈 배열. 현재 어떤 경로로도 GBTC 데이터를 가져올 수 없음.

**관련 코드**: `src/morning_brief/data/sources/btc_etf_official.py`에서 GBTC는 이미 direct fetch 대상에서 제외된 상태 (429 차단 때문).

**요구사항**:
1. 먼저 GBTC 보유량 데이터가 이 브리핑에 정말 필수인지 검토해주세요. 확인할 사항:
   - 브리핑 프롬프트에서 GBTC를 명시적으로 언급하거나 요구하는 부분이 있는지
   - IBIT+BITB 2종만으로 BTC ETF 시장 동향을 충분히 전달할 수 있는지
   - GBTC가 빠졌을 때 브리핑 품질에 실질적인 영향이 있는지
2. **필수라고 판단되면**: GBTC 보유량/순유입 데이터를 제공하는 무료 또는 저비용 API를 리서치해주세요. 후보:
   - CoinGlass API (BTC ETF 보유량 데이터 제공 여부)
   - SoSoValue (BTC ETF 트래커)
   - 기타 공개 API
   - 적합한 소스를 찾으면 기존 `btc_etf_official.py`의 패턴에 맞춰 수집기를 추가해주세요.
   - 유료 API를 사용해야 한다면 비용 정보와 함께 제안만 해주세요. 바로 구현하지는 마세요.
3. **필수가 아니라고 판단되면**: IBIT+BITB 2종만으로 운영하는 것을 기본으로 정리하고, 브리핑에서 GBTC 관련 기대치를 조정해주세요 (프롬프트 수정 등).

---

## 공통 제약사항

- 기존 테스트를 수정하지 마세요. 새 코드에 대한 테스트도 명시적으로 요청하기 전까지 작성하지 마세요.
- 코드 변경은 최소한으로. 불필요한 리팩토링이나 구조 변경 금지.
- 변경 후 `make check` (ruff format + ruff check + pytest)가 통과해야 합니다.
- 커밋 메시지는 `type(scope): 한국어 요약` 형식.
- 변경 내용은 `README.md`나 관련 문서에 반영해주세요.
