# Requirements Document

## Introduction

"AI 뉴스 분析" 섹션에 3-5개 기사가 일관되게 표시되지 않는다. **파이프라인 로그 실증 결과**: 24개 후보 → `non_preferred_domain` 필터 21개 제거(88%) → 3개 남음 → `_dedup_and_rank` 0개로 감소 → enrichment skip → 최종 0개. `enrich_public_news_packet()`이 LLM을 아예 호출하지 못하는 구조이며, 근본 원인은 두 가지다: ① `news_policy.py`의 `PREFERRED_DOMAINS`(21개 도메인)가 지나치게 제한적이라 Perplexity가 수집한 기사 대부분이 첫 번째 단계에서 탈락; ② `_dedup_and_rank`가 소수의 후보를 과잉 제거. 이 실패 과정이 output JSON에 전혀 노출되지 않아 운영 중 파악이 불가능하다. 또한 X 시그널이 동일 topic 중복 없이 최대 12개까지 노출되어 콘텐츠 다양성이 낮다.

## Glossary

- **채움률**: 실제 `featuredNews`에 표시된 항목 수 / `_PUBLIC_FEATURED_NEWS_LIMIT(5)` 비율
- **PREFERRED_DOMAINS**: `news_policy.py`에 정의된 공개 브리프 허용 도메인 화이트리스트 (현재 21개)
- **Enrichment**: `enrich_public_news_packet()`이 LLM을 호출해 `summary_ko`, `interpretation_ko`를 생성하는 과정
- **한글 검증**: `_filter_public_news_for_display()`가 `[가-힣]` 포함 여부로 `summaryKo`와 `interpretation` 두 필드를 모두 검사하는 로직
- **PublicNewsAnalysisAudit**: enrichment 결과 집계 (`candidateCount`, `requestedCount`, `successCount`, `failedCount`, `skippedCount`, `status`)
- **X 시그널 topic 중복**: 같은 topic(macro/ai_bigtech/bitcoin) 시그널이 featured에 과다 포함되어 반복되는 현상

---

## Requirements

### Requirement 1: Enrichment 가시성 확보

**User Story:**
As a 운영자,
I want output JSON에서 enrichment 결과를 즉시 확인할 수 있길 원한다,
so that AI 뉴스 분析 섹션이 비거나 부족할 때 원인을 빠르게 진단할 수 있다.

#### Acceptance Criteria

1. WHEN 파이프라인이 실행될 때, THE output JSON SHALL `meta.publicNewsAnalysis` 필드에 아래 필드를 포함한다.
   - `candidateCount`: 도메인 필터링을 통과해 enrichment 파이프라인에 진입한 후보 수 (enrichment 활성화 여부 무관)
   - `requestedCount`: 실제 LLM API를 호출한 수
   - `successCount`: LLM 호출에 성공한 수
   - `failedCount`: LLM 호출에 실패한 수
   - `skippedCount`: enrichment 비활성화 또는 기타 이유로 LLM 호출을 시도하지 않은 후보 수
   - `status`: `"ok"` | `"degraded"` | `"skipped"`
   - 불변식 A: `requestedCount == successCount + failedCount`
   - 불변식 B: `candidateCount == requestedCount + skippedCount`

2. WHEN enrichment가 비활성화(`OPENAI_PUBLIC_NEWS_ANALYSIS_ENABLED=false`)되어 실행될 때, THE output JSON SHALL `meta.publicNewsAnalysis.status == "skipped"`, `requestedCount == 0`, `skippedCount == candidateCount`를 반영한다.

3. WHEN enrichment 중 일부 항목이 실패할 때, THE output JSON SHALL `failedCount`에 해당 수를 기록하여 불변식 A와 B가 성립함을 보장한다.

---

### Requirement 2: AI 뉴스 분析 채움률 목표 ≥3

**User Story:**
As a 공개 브리프 독자,
I want "AI 뉴스 분析" 섹션에 매일 3개 이상 기사가 표시되길 원한다,
so that 단일 기사만 보이는 빈약한 경험을 피할 수 있다.

**근본 원인:** 두 단계에서 후보가 과잉 제거된다.
① `PREFERRED_DOMAINS`(21개)가 지나치게 좁아 88%의 후보가 `non_preferred_domain`으로 탈락
② `_dedup_and_rank`가 소수 남은 후보를 0개로 과잉 제거 → enrichment 입력 0개 → LLM 미호출

#### Acceptance Criteria

1. WHEN `filter_public_article_news_candidates()`가 실행될 때, THE pipeline SHALL 확장된 도메인 목록으로 필터링하여 평균 실행에서 최소 5개 이상의 후보가 `_dedup_and_rank` 단계에 도달할 수 있도록 한다.

2. WHEN `PREFERRED_DOMAINS`가 확장될 때, THE `news_policy.py` SHALL 기존 21개 도메인을 유지하면서 주요 금융·기술·암호화폐 뉴스 도메인(예: `apnews.com`, `axios.com`, `techcrunch.com`, `theblock.co`, `cointelegraph.com`, `fortune.com`, `barrons.com`, `marketwatch.com`)을 추가하여 35개 이상의 화이트리스트를 구성한다.

3. WHEN `_dedup_and_rank()`가 3개 이상의 후보를 입력받을 때, THE function SHALL 최소 3개 이상의 후보를 반환한다.

4. WHEN 파이프라인이 완료될 때, THE `featuredNews` SHALL 3개 이상을 포함한다 (단, 전체 enrichment 성공 후보가 3개 미만인 경우 전체 성공 후보를 포함).

---

### Requirement 3: X 시그널 topic 중복 제거

**User Story:**
As a 공개 브리프 독자,
I want X 시그널 섹션이 다양한 주제를 균형있게 보여주길 원한다,
so that 연준/금리 같은 단일 주제가 반복되어 보이는 경험을 피할 수 있다.

#### Acceptance Criteria

1. WHEN `build_news_packet()`에서 X 시그널이 처리될 때, THE pipeline SHALL topic(`macro`/`ai_bigtech`/`bitcoin`)별 최대 2개 시그널만 `featuredXSignals`에 포함하며 `PUBLIC_FEATURED_X_SIGNALS`를 6으로 설정한다.

2. WHEN featured X 시그널이 선정될 때, THE pipeline SHALL 동일 topic 내에서 2개를 선택할 때 서로 다른 sentiment(bullish/bearish/neutral)의 시그널이 존재하면 다른 sentiment 조합으로 선택한다. 같은 sentiment만 존재하면 score 상위 2개를 선택한다.

3. WHEN `allXSignals`가 구성될 때, THE pipeline SHALL 기존 최대 12개를 유지하되 topic별 최대 4개로 제한한다.

---

### Requirement 4: 뉴스와 X 시그널의 균형 있는 표시

**User Story:**
As a 공개 브리프 독자,
I want 뉴스 분析과 X 시그널이 서로 보완하는 방식으로 표시되길 원한다,
so that 두 섹션을 함께 봤을 때 시장 전반을 고르게 파악할 수 있다.

#### Acceptance Criteria

1. WHEN 홈 페이지가 렌더링될 때, THE frontend SHALL X 시그널 섹션에 `featuredXSignals`(최대 6개)를 표시한다.

2. WHEN 홈 페이지가 렌더링될 때, THE frontend SHALL AI 뉴스 분析 섹션에 `featuredNews`(최대 5개)를 표시한다.

3. WHEN `featuredNews`가 0개일 때, THE frontend SHALL 섹션 전체를 숨긴다(display:none). WHEN `featuredNews`가 1개일 때, THE frontend SHALL 섹션을 표시하되 "분석 기사가 충분하지 않습니다" 안내 메시지를 함께 표시한다.

4. WHEN `allXSignals`가 존재할 때, THE frontend SHALL 홈 화면에서는 `featuredXSignals`(6개)만 기본 표시하고 "전체 보기" 토글로 나머지를 열람할 수 있도록 한다.

---

## 구현 후 필수 확인 로그

이 작업 완료 후 파이프라인을 1회 실행하고 아래 항목을 순서대로 확인한다.

1. **`non_preferred_domain` 필터 탈락률** — 이전 88%에서 50% 이하로 감소했는지 확인
2. **`_dedup_and_rank` 입출력 수** — 입력 N개 → 출력 ≥3개인지 확인 (0개 반환 여부가 핵심)
3. **`meta.publicNewsAnalysis.candidateCount`** — output JSON에서 ≥5인지 확인
4. **`meta.publicNewsAnalysis.requestedCount`** — `candidateCount`와 같은지 확인 (skip 없을 때)
5. **`featuredNews` 길이** — output JSON에서 ≥3인지 확인
6. **`featuredXSignals` topic 분포** — macro/ai_bigtech/bitcoin 각 최대 2개인지 확인
