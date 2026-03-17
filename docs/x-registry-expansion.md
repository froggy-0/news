# X 시그널 레지스트리 확장 계획

최근 10회 실행 분석 및 웹 검증 기반, 2026-03-17 작성.

---

## 현재 레지스트리 현황

| 그룹 | 현재 수 | 등록 계정 |
|---|---|---|
| macro_and_equity | 9 | @DeItaone, @FirstSquawk, @NickTimiraos, @markets, @lisaabramowicz1, @DivesTech, @CNBC, @federalreserve, @USTreasury |
| ai_bigtech_primary | 5 | @AMD, @nvidia, @Microsoft, @Meta, @ASMLcompany |
| crypto_and_etf | 6 | @EricBalchunas, @CoinDesk, @NateGeraci, @BitwiseInvest, @Grayscale, @ARKInvest, @SECGov |
| btc_etf_primary | 2 | @Fidelity, @BlackRock |

**문제**: 빅테크 10종을 추적하면서 X 검색 대상은 5개뿐. BTC ETF 운용사도 주요 3곳이 누락.

---

## 추가 대상 (9건)

### ai_bigtech_primary (+4건, 5→9)

| 핸들 | 이름 | 티커 | priority | 검증 방법 | 검증 근거 |
|---|---|---|---|---|---|
| `@Google` | Google | GOOGL | 2 | 공식 사이트 | abc.xyz IR 페이지 존재. AI(Gemini) 발표 채널 |
| `@AmazonNews` | Amazon News | AMZN | 2 | 공식 사이트 안내 | amazon.com 메인 계정(@amazon)이 "Use @AmazonNews for the latest"로 안내 |
| `@Tesla` | Tesla | TSLA | 2 | 공식 사이트 | ir.tesla.com IR 페이지 존재. X verified |
| `@Broadcom` | Broadcom | AVGO | 2 | 공식 사이트 문서 | broadcom.com 자체 KB 문서에서 twitter.com/Broadcom 직접 언급. NASDAQ: AVGO 명시 |

**참고**: Apple은 공식 X 계정 없음, TSMC도 공식 X 미검증 — 기존 레지스트리에서 이미 확인된 사항.

### crypto_and_etf (+3건, 6→9)

| 핸들 | 이름 | 티커 | priority | 검증 방법 | 검증 근거 |
|---|---|---|---|---|---|
| `@vaneck_us` | VanEck | HODL | 2 | **공식 소셜 페이지** | vaneck.com/social 에서 "VanEck sponsors the VanEck Twitter page at https://twitter.com/vaneck_us" 명시. 검증 강도 최상 |
| `@FTI_US` | Franklin Templeton | EZBC | 2 | 공식 프로필 | "Official Franklin Templeton account. For US investors only" 프로필 설명 |
| `@InvescoUS` | Invesco | BTCO | 2 | 공식 프로필 | "Invesco is dedicated to helping investors rethink possibility" 프로필 설명 |

### macro_and_equity (+2건, 9→11)

| 핸들 | 이름 | priority | 검증 방법 | 검증 근거 |
|---|---|---|---|---|
| `@WhiteHouse` | White House | 1 | **정부 공식** | whitehouse.gov 공식 행정부 계정. X grey checkmark (정부 기관 배지) |
| `@POTUS` | President of the United States | 1 | **정부 공식** | 2025년 1월 취임 시 트럼프로 이관 확인. 관세/무역 정책 발표 채널 |

---

## 보류 항목

| 핸들 | 이름 | 판단 | 이유 |
|---|---|---|---|
| `@realDonaldTrump` | Donald Trump (개인) | 보류 | 시장 영향력은 크지만 개인 계정. @POTUS + @WhiteHouse로 공식 정책 발표는 커버 가능. 개인 계정 추가는 별도 정책 판단 필요 |

## 추가 불필요 (확인 완료)

| 후보 | 이유 |
|---|---|
| Apple (@Apple) | 공식 X 계정 없음 |
| TSMC | 공식 X 계정 미검증 |

---

## 그룹별 한도 영향

`MAX_X_HANDLES_PER_GROUP = 10` 제약 적용 시:

| 그룹 | 추가 후 | 한도 초과 | 대응 |
|---|---|---|---|
| ai_bigtech_primary | 9 | ❌ | 없음 |
| crypto_and_etf | 9 | ❌ | 없음 |
| macro_and_equity | **11** | ⚠️ **1건 초과** | priority 기반 컷 — 아래 참고 |
| btc_etf_primary | 2 | ❌ | 없음 |

### macro_and_equity priority 조정 필요

추가 후 11건이므로 priority가 가장 높은(숫자가 큰) 1건이 탈락합니다.

현재 priority 배치:

| priority | 계정 |
|---|---|
| 1 | @DeItaone, @FirstSquawk, @NickTimiraos, **@WhiteHouse (신규)**, **@POTUS (신규)** |
| 2 | @markets, @lisaabramowicz1, @DivesTech, @CNBC |
| 3 | @federalreserve, @USTreasury |

priority 3인 @federalreserve 또는 @USTreasury 중 1건이 탈락합니다.

**권장 대응**:
- 옵션 A: `MAX_X_HANDLES_PER_GROUP`를 11로 올림 (코드 1줄 수정)
- 옵션 B: @WhiteHouse와 @POTUS 중 하나만 추가 (POTUS가 정책 발표 중심이므로 POTUS 우선)
- 옵션 C: @federalreserve를 priority 2로 올려서 @USTreasury만 탈락 (Fed가 Treasury보다 시장 영향 큼)

---

## 구현 방법

`official_signal_registry.json`에 엔티티를 추가하면 코드 변경 없이 자동 반영됩니다:

1. `grouped_verified_x_handles()` → 그룹별 핸들 목록에 자동 포함
2. `fetch_x_keyword_signals()` → Grok `x_search(allowed_x_handles=...)` 에 전달
3. `grok_official_signals` → 공식 시그널 검색에도 반영

각 엔티티에 필요한 필드:
```json
{
  "entity_id": "google",
  "entity_name": "Google",
  "ticker": "GOOGL",
  "category": "ai_bigtech_primary",
  "primary_domain": "abc.xyz",
  "newsroom_or_ir_url": "https://abc.xyz/investor/",
  "x_handle": "Google",
  "x_verified": true,
  "verification_source_url": "https://abc.xyz/",
  "verification_method": "official_site_social_link",
  "verified_at": "2026-03-17",
  "x_search_group": "ai_bigtech_primary",
  "x_search_priority": 2,
  "enabled": true,
  "notes": "검색/AI/클라우드 발표"
}
```
