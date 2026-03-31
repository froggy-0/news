# Design Document: News Analysis Prompt & Grok Optimization

## Overview

이번 변경은 두 개의 독립적인 문제를 각각의 최소 범위로 해결한다.

**문제 A (Req 1·2):** `public_news_analysis_instructions.j2` 프롬프트를 재작성하여 토픽별 분석 지침과 세계 지식 보완을 허용하고, reasoning effort를 `"minimal"` → `"low"`로 변경한다. `enrich_public_news_packet()`의 입출력 인터페이스와 검증 로직은 유지된다.

**문제 B (Req 3·4·5):** `grok_x_keyword.py`의 `CRYPTO_ETF_GROUP`과 `BTC_ETF_GROUP`을 `BITCOIN_CRYPTO_GROUP`으로 통합하고, `config.py`의 `grok_x_search_max_items`·`official_x_max_items` 기본값을 줄인다. registry JSON에서 해당 엔티티의 `x_search_group`도 함께 변경한다. 두 변경은 서로 독립적이며 파이프라인 인터페이스를 깨지 않는다.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  변경 A: 프롬프트 + reasoning                                   │
│                                                                 │
│  public_news_analysis_instructions.j2  ← 재작성 (토픽별 지침)  │
│  public_news_analysis.py               ← reasoning "low" (1줄) │
│  (입출력 인터페이스 PublicNewsAnalysisInput/Output 변경 없음)   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  변경 B: Grok 그룹 통합 + max_items 감소                        │
│                                                                 │
│  official_signal_registry.json                                  │
│    crypto_and_etf  →  bitcoin_crypto  (10개 엔티티)             │
│    btc_etf_primary →  bitcoin_crypto  (2개 엔티티: Fidelity,    │
│                                        BlackRock)               │
│                                                                 │
│  grok_x_keyword.py                                              │
│    CRYPTO_ETF_GROUP  ─┐                                         │
│    BTC_ETF_GROUP     ─┴→ BITCOIN_CRYPTO_GROUP = "bitcoin_crypto"│
│    search_groups: [MACRO_EQUITY, AI_BIGTECH, BITCOIN_CRYPTO]    │
│                                                                 │
│  config.py                                                      │
│    grok_x_search_max_items: default 6→4, max 10→8              │
│    official_x_max_items:    default 4→3, max 6→5               │
└─────────────────────────────────────────────────────────────────┘

Grok X 키워드 시그널 총량 변화:
  이전: 4 groups × 6 items = 최대 24
  이후: 3 groups × 4 items = 최대 12  (50% 감소)

Grok Official 시그널 총량 변화:
  이전: 3 groups × 4 items = 최대 12
  이후: 3 groups × 3 items = 최대 9   (25% 감소)
```

---

## Components and Interfaces

### 1. `public_news_analysis_instructions.j2` 재작성

**변경 이유:** 기존 규칙 5("부족하면 빈 문자열 반환")가 RSS 기사처럼 `summary`만 짧게 있고 `why_it_matters`가 없는 경우에도 LLM이 빈 응답을 내보내게 만든다. `topic` 필드가 입력에 있음에도 활용되지 않아 카테고리별 분석 깊이가 없다.

**변경 전 핵심 규칙 (8개):**
```
1. 각 기사마다 summary_ko와 interpretation_ko를 생성
2. summary_ko: 1~2문장, 240자 이하
3. interpretation_ko: 1문장, 120자 이하
4. 입력에 없는 수치·기업명·인과관계 추가 금지
5. ← 삭제: "부족하면 빈 문자열 반환"
6. placeholder 금지
7. 숫자·티커·ETF명·출처명 유지
8. JSON schema 준수
```

**변경 후 구조 (세 블록):**

```jinja2
{# 블록 1: 역할 + 세계 지식 허용 #}
공개 브리프용 기사 해설 생성기입니다.
입력이 얇더라도 기사 제목·출처·토픽을 근거로 LLM 배경 지식을 활용해
의미 있는 한국어 해설을 생성하세요.
단, 입력에 없는 구체적 수치·날짜·기업명을 새로 지어내는 것은 금지입니다.

{# 블록 2: 토픽별 분석 지침 #}
기사의 topic 값에 따라 interpretation_ko 초점을 다르게 잡으세요:

- "ai_bigtech": AI 인프라·반도체 공급망·모델 발표·설비투자 맥락의 시장 함의
- "macro":      연준 정책·금리 기대·인플레이션·성장 전망과의 연결
- "bitcoin":    ETF 자금 흐름·규제 동향·기관 수요와의 연결
- "us_equity":  섹터 영향·지수 영향·투자 심리와의 연결
- (기타 topic): 해당 자산군에 미치는 시장 가격 영향 중심

{# 블록 3: 생성 규칙 (기존 1·2·3·4·6·7·8 유지, 5 삭제, 신규 추가) #}
1. 각 기사마다 summary_ko와 interpretation_ko를 모두 생성하세요.
2. summary_ko는 기사 핵심을 한국어 1~2문장, 240자 이하로 정리하세요.
3. interpretation_ko는 시장 함의를 한국어 1문장, 120자 이하로 정리하세요.
4. 입력에 없는 구체적 수치·날짜·기업명을 임의로 추가하지 마세요.
   (배경 지식으로 문맥을 잡는 것은 허용, 없는 사실을 만드는 것은 금지)
5. title과 topic만으로도 최소 1문장의 한국어 해설을 생성하세요.
   빈 문자열을 반환하지 마세요.
6. "해당 없음", "없음", "N/A" 같은 placeholder를 쓰지 마세요.
7. 숫자·티커·ETF 이름·출처명·URL은 필요한 경우 그대로 유지하세요.
8. 출력은 반드시 지정된 JSON schema만 따르세요.
```

> **Design Decision:** 기존 규칙 번호를 최대한 유지하여 향후 diff 가독성을 높인다. 규칙 5만 "빈 문자열 반환" → "최소 1문장 생성"으로 의미를 역전시킨다. 토픽별 지침은 별도 블록으로 분리하여 규칙 번호와 충돌하지 않게 한다.

---

### 2. `public_news_analysis.py` — reasoning effort 변경

**파일:** `src/morning_brief/public_news_analysis.py:298`

```python
# 변경 전
reasoning={"effort": "minimal"},

# 변경 후
reasoning={"effort": "low"},
```

**변경 이유:** `"minimal"`은 가장 낮은 추론 수준으로, 얇은 입력에서 LLM이 빠른 경로(빈 문자열)를 선택하기 쉽다. `"low"`는 짧은 번역·해석 태스크에 적합한 최소 유효 수준이며 `max_output_tokens`는 별도로 계산되므로 변경 불필요.

---

### 3. `grok_x_keyword.py` 내 BITCOIN_CRYPTO 핸들 구성 (registry 불변)

**registry JSON 변경 없음.** `grok_official_signals.py`도 `grouped_verified_x_entities()`를 읽고 `"btc_etf_primary"` 그룹 키로 Fidelity·BlackRock 공식 신호를 수집하므로, registry의 `x_search_group` 값을 변경하면 공식 신호 수집이 조용히 깨진다. 대신 `grok_x_keyword.py` 코드 내에서 두 구 그룹의 핸들을 union하여 `BITCOIN_CRYPTO_GROUP`에 제공한다.

```python
# grok_x_keyword.py 내 핸들 조합 로직 (fetch_x_keyword_signals 내부)
all_handles = grouped_verified_x_handles()

def _bitcoin_crypto_handles(all_handles: dict[str, list[str]]) -> list[str]:
    """CRYPTO_ETF + BTC_ETF 핸들을 union하여 중복 없이 반환한다."""
    seen: set[str] = set()
    result: list[str] = []
    for handle in all_handles.get("crypto_and_etf", []) + all_handles.get("btc_etf_primary", []):
        if handle not in seen:
            seen.add(handle)
            result.append(handle)
    return result
```

기존 `all_handles = grouped_verified_x_handles()` 호출 후, `BITCOIN_CRYPTO_GROUP`에 해당하는 handles 변수만 위 함수로 대체한다. 다른 그룹(`MACRO_EQUITY_GROUP`, `AI_BIGTECH_GROUP`)은 기존대로 `all_handles.get(group, [])` 로직을 그대로 사용한다.

**변경 이유:** registry JSON은 `grok_official_signals.py`와 `grok_x_keyword.py`가 공유하는 진실 소스다. `grok_official_signals.py`의 `GROUP_TOPIC_MAP = {"btc_etf_primary": "bitcoin", ...}`이 registry의 `x_search_group` 키를 그대로 사용하므로, JSON 변경 시 공식 신호 수집 경로가 조용히 깨진다. 코드 내 union이 범위가 더 좁고 안전하다.

---

### 4. `grok_x_keyword.py` — 그룹 통합

**파일:** `src/morning_brief/data/sources/grok_x_keyword.py`

```python
# 변경 전
CRYPTO_ETF_GROUP = "crypto_and_etf"
AI_BIGTECH_GROUP = "ai_bigtech_primary"
BTC_ETF_GROUP = "btc_etf_primary"

# 변경 후
AI_BIGTECH_GROUP = "ai_bigtech_primary"
BITCOIN_CRYPTO_GROUP = "bitcoin_crypto"   # 신규 (CRYPTO_ETF + BTC_ETF 통합)
# CRYPTO_ETF_GROUP, BTC_ETF_GROUP 상수 삭제

# GROUP_PROMPTS 변경
GROUP_PROMPTS = {
    MACRO_EQUITY_GROUP: MACRO_EQUITY_PROMPT,
    AI_BIGTECH_GROUP: AI_BIGTECH_PROMPT,
    BITCOIN_CRYPTO_GROUP: BITCOIN_CRYPTO_PROMPT,   # 신규 병합 프롬프트
}

# GROUP_TOPIC_MAP 변경
GROUP_TOPIC_MAP = {
    MACRO_EQUITY_GROUP: "macro",
    AI_BIGTECH_GROUP: "ai_bigtech",
    BITCOIN_CRYPTO_GROUP: "bitcoin",   # 기존 두 그룹의 topic 통합
}

# search_groups 변경
search_groups = [MACRO_EQUITY_GROUP, AI_BIGTECH_GROUP, BITCOIN_CRYPTO_GROUP]
```

**BITCOIN_CRYPTO_PROMPT 내용 (두 기존 프롬프트 병합):**

```python
BITCOIN_CRYPTO_PROMPT = """Search X for the most significant Bitcoin, crypto, and ETF posts
from the last {lookback_hours} hours.
Focus on:
1. Bitcoin ETF flow data (IBIT, BITB, GBTC, FBTC, ARKB inflows/outflows and AUM)
2. BTC price action and market sentiment
3. Crypto regulatory news (SEC, CFTC decisions and enforcement)
4. Institutional Bitcoin adoption announcements
5. New ETF filings, fee changes, or official operator comments

Return the top {max_items} most impactful posts.
Output format: {{"signals": [{{"headline": "...", "summary": "...",
  "why_it_matters": "...", "sentiment": "bullish|bearish|neutral",
  "source_handle": "...", "posted_at": "ISO8601"}}]}}
Prioritize posts with specific data points. Skip promotional content."""
```

**변경 이유:** CRYPTO_ETF와 BTC_ETF는 커버리지 중심이 동일하다(BTC ETF 운용사, 크립토 분석가, SEC 규제). 두 그룹이 서로 다른 API 호출을 하면서 같은 계정 풀에서 중복 시그널을 수집할 가능성이 높다. 단일 프롬프트로 통합하면 API 호출 1회 절감과 중복 dedup 부담 감소 효과가 있다.

---

### 5. `config.py` — max_items 조정

**파일:** `src/morning_brief/config.py`

```python
# 변경 전
grok_x_search_max_items=_env_bounded_int(
    "GROK_X_SEARCH_MAX_ITEMS", default=6, minimum=1, maximum=10
),
official_x_max_items=_env_bounded_int(
    "OFFICIAL_X_MAX_ITEMS", default=4, minimum=1, maximum=6,
),

# 변경 후
grok_x_search_max_items=_env_bounded_int(
    "GROK_X_SEARCH_MAX_ITEMS", default=4, minimum=1, maximum=8
),
official_x_max_items=_env_bounded_int(
    "OFFICIAL_X_MAX_ITEMS", default=3, minimum=1, maximum=5,
),
```

**변경 이유:** 사용자 요구(현재 24개의 절반). maximum 상한도 비례 감소시켜 환경변수 오버라이드로도 이전 최대치에 도달하지 않도록 한다.

---

## Data Models

변경 없음. 아래 인터페이스는 그대로 유지된다.

```python
# public_news_analysis.py — 변경 없음
@dataclass(frozen=True)
class PublicNewsAnalysisInput:
    id: str
    title: str
    url: str
    source: str
    topic: str | None       # ← 프롬프트에서 이 필드 활용 (기존 존재, 신규 활용)
    published_at: str | None
    summary: str | None
    why_it_matters: str | None
    citations: list[str]

@dataclass(frozen=True)
class PublicNewsAnalysisOutput:
    id: str
    summary_ko: str
    interpretation_ko: str

# grok_x_keyword.py — 반환 타입 변경 없음
def fetch_x_keyword_signals(...) -> tuple[list[XSignal], list[NewsItem], dict[str, list[str]]]:
    ...
```

---

## Correctness Properties

**Property 1 (Req 1·2):** *For any* `PublicNewsAnalysisInput` 항목이 유효한 `title`과 `topic`을 가질 때, `enrich_public_news_packet()`은 `summary_ko`와 `interpretation_ko` 모두 비어 있지 않은 한국어 문자열을 반환해야 한다. (`summary`와 `why_it_matters`가 모두 None이어도)

**Property 2 (Req 3):** *For any* `fetch_x_keyword_signals()` 호출에서 `search_groups`는 정확히 3개 그룹(`MACRO_EQUITY_GROUP`, `AI_BIGTECH_GROUP`, `BITCOIN_CRYPTO_GROUP`)이어야 하며, 각 그룹의 `GROUP_TOPIC_MAP` 매핑이 존재해야 한다.

**Property 3 (Req 4·5):** *For any* `Settings`에서 기본값이 적용될 때, `grok_x_search_max_items == 4`이고 `official_x_max_items == 3`이어야 한다.

**Property 4 (Req 6):** *For any* 변경 이후 파이프라인 실행에서 `fetch_x_keyword_signals()`의 반환 타입은 `tuple[list[XSignal], list[NewsItem], dict[str, list[str]]]`을 유지해야 한다.

---

## Error Handling

| 상황 | 처리 방식 |
|---|---|
| LLM이 `topic` 값을 인식 못하는 경우(unknown topic) | 블록 2의 "(기타 topic)" 규칙이 fallback 처리 |
| `BITCOIN_CRYPTO_GROUP` API 호출 실패 | 기존 per-group `HttpFetchError` catch + log + continue 유지 |
| registry JSON에 `"bitcoin_crypto"` 그룹 엔티티가 없는 경우 | `grouped_verified_x_handles()` 빈 리스트 반환 → tool_handles=None → 핸들 없이 광범위 검색 (기존 동작 유지) |
| `grok_x_search_max_items` 환경변수가 기존 값(>8) 일 때 | `_env_bounded_int` clamp으로 최대 8로 제한 |
| reasoning="low" 적용 시 LLM 응답 오류 | 기존 `except Exception` catch + log + continue 유지 |

---

## Testing Strategy

**테스트 파일 위치:** `tests/test_public_news_analysis.py`, `tests/test_grok_x_keyword.py`

### 프롬프트·reasoning 변경 (Req 1·2)

`tests/test_public_news_analysis.py`에 추가:

- **thin_input_generates_nonempty:** `summary=None`, `why_it_matters=None`인 항목에서도 LLM mock이 비어 있지 않은 한국어 응답을 반환할 때, `enrich_public_news_packet()`이 해당 결과를 패킷에 병합하는지 검증
- **reasoning_effort_is_low:** `client.responses.create()` mock 호출 시 `reasoning={"effort": "low"}`가 전달되는지 검증 (기존 "minimal" 테스트 값 업데이트)

기존 테스트 업데이트:
- 기존 reasoning mock이 `"minimal"`을 기대하는 곳은 `"low"`로 수정

### Grok 그룹 통합 (Req 3)

`tests/test_grok_x_keyword.py`에 추가 (파일 없으면 신규 생성):

- **search_groups_has_three_entries:** `search_groups` 리스트 길이가 3이고 `BITCOIN_CRYPTO_GROUP`이 포함되는지 검증
- **bitcoin_crypto_topic_mapping:** `GROUP_TOPIC_MAP[BITCOIN_CRYPTO_GROUP] == "bitcoin"`인지 검증
- **old_groups_removed:** `CRYPTO_ETF_GROUP`, `BTC_ETF_GROUP` 상수가 모듈에 존재하지 않는지 검증

### config 변경 (Req 4·5)

`tests/test_config.py`에 추가 (또는 기존 config 테스트에 편입):

- **grok_x_search_max_items_default:** 환경변수 미설정 시 `settings.grok_x_search_max_items == 4` 검증
- **official_x_max_items_default:** 환경변수 미설정 시 `settings.official_x_max_items == 3` 검증
- **grok_x_search_max_items_clamp:** 환경변수 `GROK_X_SEARCH_MAX_ITEMS=20` 설정 시 `8`로 클램프되는지 검증
