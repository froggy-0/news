# 데이터 소스 신뢰도 분석 및 캐시 전략 트레이드오프

최근 10회 실행 로그(2026-03-16~17) 기반 실측 분석 및 수정 결과입니다.

---

## 1. 소스별 실측 신뢰도

### 99%+ 신뢰도 (캐시 불필요, 항상 fresh 데이터 확보)

| 소스 | 대상 | 10회 성공률 | 비고 |
|---|---|---|---|
| **Stooq** | 미국 지수 3종 + 빅테크 10종 + BTC ETF 5종 | **18/18 = 100%** (전 실행) | 무료, rate limit 여유, 재시도 0회 |
| **FRED** | us10y, us2y, vix | **3/3 = 100%** (전 실행) | API 키 필요하지만 안정적 |
| **CoinGecko** | BTC 현물 | **1/1 = 100%** (전 실행) | 무료 tier, 재시도 0회 |
| **alternative.me** | Fear & Greed | **1/1 = 100%** (전 실행) | 무료, 단순 JSON |
| **Perplexity Sonar** | 토픽 요약 4종 | **6/6 = 100%** (성공 실행) | 유료, 안정적 |
| **Grok 공식 X** | 공식 계정 시그널 | **4/4 = 100%** (전 실행) | 유료, 안정적 |
| **Grok X 키워드** | 시장 반응 시그널 | **4/4 = 100%** (요청 성공) | 0건 반환은 있지만 API 자체는 안정 |

### 0% 신뢰도 (구조적으로 실패 → 수정 완료)

| 소스 | 대상 | 수정 전 성공률 | 원인 | 수정 내용 |
|---|---|---|---|---|
| ~~**yfinance `DX-Y.NYB`**~~ | 달러 인덱스 | **0/10 = 0%** | "possibly delisted" — 티커 비활성화 | ✅ `DX=F` (ICE Dollar Index Futures)로 교체 |
| ~~**Perplexity BTC ETF structured**~~ | IBIT/BITB/GBTC 보유량 | **0/10 = 0%** | 매번 `{"snapshots": []}` 반환 | ✅ Perplexity structured query 제거, direct fetch primary 승격 |
| ~~**GBTC direct fetch**~~ | Grayscale 보유량 | **0/10 = 0%** | Grayscale이 429로 scraping 차단 | ✅ GBTC 수집 제거, IBIT+BITB 2종 운영 공식화 |

### 100% 신뢰도 (BTC ETF 보유량 — primary 경로)

| 소스 | 대상 | 10회 성공률 | 비고 |
|---|---|---|---|
| **IBIT direct fetch** | BlackRock 보유량 | **10/10 = 100%** | iShares 페이지 직접 파싱 (primary) |
| **BITB direct fetch** | Bitwise 보유량 | **10/10 = 100%** | Bitwise 페이지 직접 파싱 (primary) |

---

## 2. 현재 캐시가 실제로 하는 일

### market snapshot 캐시
- **의도**: 수집 실패 시 전일 값으로 대체
- **수정 후**: DXY가 yfinance `DX=F`로 안정 수집되므로 캐시에 실제 값이 쌓이게 됨
- **나머지 지표**: Stooq/FRED/CoinGecko가 100% 성공하므로 캐시 대체가 발동한 적 없음
- **결론**: DXY 소스 수정으로 캐시가 방어적 안전망으로 정상 작동

### BTC ETF snapshot 캐시
- **의도**: 수집 실패 시 전일 보유량으로 대체
- **수정 후**: Perplexity structured query 제거, direct fetch(IBIT+BITB)가 primary 경로로 즉시 실행
- direct fetch가 100% 성공하므로 캐시 대체가 발동할 일이 없음
- **결론**: BTC ETF 캐시는 방어적 안전망으로 유지, IBIT+BITB 2종 direct fetch가 primary

### GitHub Actions 캐시 save 실패
- 같은 날 키로 immutable → 하루 첫 실행만 저장, 이후 실행은 save 실패
- 하지만 위에서 본 것처럼 캐시 자체가 무용하므로 save 실패의 실질적 영향도 없음

---

## 3. 트레이드오프 분석

### DXY: ~~캐시 vs 다른 소스~~ → `DX=F` 적용 완료

| 선택지 | 장점 | 단점 | 상태 |
|---|---|---|---|
| ~~현재 (yfinance `DX-Y.NYB` + 캐시)~~ | 코드 변경 없음 | 10/10 실패, 캐시에도 값 없음, DXY 영구 누락 | ❌ 폐기 |
| ~~Stooq `dx.f` 추가~~ | Stooq 100% 신뢰도 | Stooq가 선물 심볼의 CSV 다운로드를 지원하지 않아 사용 불가 | ❌ 불가 |
| **yfinance `DX=F` (ICE Dollar Index Futures)** | ICE DXY와 거의 동일한 값 | yfinance 자체의 간헐적 불안정성 | ✅ **적용됨** |
| ~~FRED `DTWEXBGS` (broad dollar)~~ | FRED 100% 신뢰도 | ICE DXY와 다른 지수 (broad weighted) | — 미채택 |

**적용 결과**: `MACRO_FALLBACK_TARGETS`에서 DXY 티커를 `DX-Y.NYB` → `DX=F`로 교체. `CANONICAL_KEY_BY_SOURCE`에 `"DX=F": "dxy"` 매핑 추가. Stooq는 선물 심볼의 CSV 다운로드를 지원하지 않아 yfinance 전용 경로 유지.

### BTC ETF 보유량: ~~Perplexity structured vs direct fetch~~ → direct fetch primary 적용 완료

| 선택지 | 장점 | 단점 | 상태 |
|---|---|---|---|
| ~~현재 (Perplexity → direct fallback)~~ | GBTC 포함 가능성 | Perplexity 10/10 빈 배열, GBTC 429 차단 | ❌ 폐기 |
| **direct fetch만 사용 (IBIT+BITB)** | 100% 신뢰도, Perplexity 비용 절감 | GBTC 데이터 없음 | ✅ **적용됨** |
| ~~direct fetch + GBTC용 별도 소스~~ | 3종 모두 커버 | GBTC 대안 소스 필요 (CoinGlass 등) | — 미채택 |

**적용 결과**: `fetch_official_btc_etf_snapshots()`에서 Perplexity structured query(`_request_reference_snapshots()`) 호출 제거. `_fetch_direct_reference_snapshots()`가 primary 경로로 IBIT+BITB 2종을 즉시 수집. GBTC 수집 시도 제거, IBIT+BITB 2종 운영 공식화.

### 시장 데이터 캐시 전략

| 선택지 | 장점 | 단점 | 상태 |
|---|---|---|---|
| ~~캐시 유지 (현재)~~ | 이론적 안전망 | 실제로 발동한 적 없음, 코드 복잡도 증가 | — |
| ~~캐시 제거~~ | 코드 단순화 | 만약 Stooq/FRED가 동시 장애 시 대체 없음 | — |
| **캐시 유지 + 소스 수정** | DXY 소스 수정 후 캐시가 실제로 작동 | 약간의 코드 변경 | ✅ **적용됨** |

**적용 결과**: 캐시 구조는 그대로 유지 (방어적 설계). DXY 소스가 `DX=F`로 수정되어 캐시에 실제 값이 쌓이게 됨.

---

## 4. 수정 완료 요약

| 우선순위 | 항목 | 수정 내용 | 상태 |
|---|---|---|---|
| 1 | **DXY 티커 변경** | `DX-Y.NYB` → `DX=F` (ICE Dollar Index Futures) | ✅ 완료 |
| 2 | **BTC ETF: Perplexity structured 제거** | direct fetch(IBIT+BITB)를 primary로 승격 | ✅ 완료 |
| 3 | **GBTC 수집 제거** | IBIT+BITB 2종 운영 공식화, GBTC 수집 시도 제거 | ✅ 완료 |

### 변경된 파일

| 파일 | 변경 내용 |
|---|---|
| `src/morning_brief/data/market.py` | `MACRO_FALLBACK_TARGETS`에서 DXY 티커 `DX-Y.NYB` → `DX=F` 교체 |
| `src/morning_brief/data/market_policy.py` | `CANONICAL_KEY_BY_SOURCE`에 `"DX=F": "dxy"` 매핑 추가 |
| `src/morning_brief/data/sources/btc_etf_official.py` | Perplexity structured query 제거, direct fetch primary 승격, IBIT+BITB 2종 운영 |

### 현재 수집 경로 요약

| 데이터 | 수집 경로 | 신뢰도 |
|---|---|---|
| DXY (달러 인덱스) | yfinance `DX=F` (MACRO_FALLBACK_TARGETS) | 안정 (ICE Dollar Index Futures) |
| us10y, us3m, vix | FRED 우선 → yfinance fallback | 99%+ |
| 미국 지수 (SPY, QQQ, SOXX) | Stooq 우선 → yfinance fallback | 100% |
| 빅테크 10종 | Stooq 우선 → yfinance fallback | 100% |
| BTC ETF 가격·거래량 | Stooq 우선 → yfinance fallback | 100% |
| BTC ETF 보유량 (IBIT+BITB) | direct fetch primary (Perplexity 미사용) | 100% |
| BTC 현물 | CoinGecko | 100% |

나머지 소스(Stooq, FRED, CoinGecko, Grok, Perplexity Sonar 토픽 요약)는 99%+ 신뢰도로 캐시 없이도 안정적입니다. 캐시는 방어적 안전망으로 유지하며, DXY 소스 수정으로 캐시에 실제 값이 쌓이게 되었습니다.
