# 뉴스 파이프라인 재설계 — 작업 체크리스트

> 기준 문서: `docs/news-pipeline-redesign.md`
> 작성일: 2026-03-16
> 최종 검증: 2026-03-16 (코드 대조 완료)
> 원칙: 각 Step은 독립 배포 가능. Step 완료 후 반드시 검증 통과 확인 후 다음 진행.

---

## 사전 준비

- [ ] 현재 테스트 베이스라인 확인
  ```bash
  make check   # ruff format + ruff check + pytest
  ```
- [ ] 작업 브랜치 생성
  ```bash
  git checkout -b feat/news-pipeline-redesign
  ```

---

## Step 1: Perplexity Search API — allowlist → deny list 전환

> 목표: 검색 자유도 확보로 주말 0건 문제 해결
> 대상 파일: `src/morning_brief/data/sources/perplexity_search.py`
> 테스트 파일: `tests/test_perplexity_search.py`

### 1-1. 공통 deny list 상수 정의

- [ ] `SEARCH_DENY_DOMAINS` 튜플 추가 (기존 `DISALLOWED_MARKET_DATA_DOMAINS` 근처)
  ```python
  SEARCH_DENY_DOMAINS = (
      "-markets.ft.com",
      "-data.coindesk.com",
      "-downloads.coindesk.com",
      "-sponsored.bloomberg.com",
      "-cn.wsj.com",
      "-jp.reuters.com",
      "-apps.apple.com",
      "-podcasts.apple.com",
      "-tv.apple.com",
      "-status.perplexity.ai",
  )
  ```
  > 검증 완료: `_search_domain_filter_values()`는 `-` prefix를 이미 지원함 (`:497-510`). Sonar 모듈에서 동일 패턴 사용 중.

### 1-2. 저품질 소스 deny 필터 추가

- [ ] `LOW_QUALITY_DOMAINS` set 추가
  ```python
  LOW_QUALITY_DOMAINS = {
      "reddit.com", "twitter.com", "x.com", "facebook.com",
      "linkedin.com", "quora.com", "medium.com",
      "tradingview.com", "investing.com", "stockanalysis.com",
      "finance.yahoo.com",
      "wikipedia.org", "investopedia.com",
      "glassdoor.com", "indeed.com",
  }
  ```
- [ ] `_is_low_quality_source(url: str) -> bool` 함수 추가
- [ ] 테스트: `test_is_low_quality_source()` — 각 도메인 매칭 + `www.` prefix 케이스 확인

### 1-3. SearchTopic dataclass 변경

> 주의: `domain_filter`는 **required 필드** (기본값 없음). 제거 불가, 값 변경 필요.

- [ ] `domain_filter` 필드: 토픽별 allowlist 값 → 공통 `SEARCH_DENY_DOMAINS` 값으로 변경
- [ ] `retry_domain_filter` 필드: 모든 토픽에서 제거 (None으로)
- [ ] `retry_recency_filter` 필드: 유지 (retry 시 recency 확장에 사용)
- [ ] 4개 `TOPIC_SPECS` 항목 전부 수정:
  - `domain_filter=SEARCH_DENY_DOMAINS`
  - `retry_domain_filter=None` (또는 필드 생략)
  - 쿼리 텍스트는 유지 (검색 품질 유도 역할)

### 1-4. _search_once() 호출부 확인

- [ ] `_search_topic_items()` 내 `_search_once()` 호출 4곳 확인 (`:961, :999, :1044, :1080`)
  - 모두 `domain_filter=topic.domain_filter` → deny list가 자동 전달됨
- [ ] broad retry 단계(`:1080`)의 `topic.retry_domain_filter or topic.domain_filter` → `retry_domain_filter=None`이면 `topic.domain_filter` (deny list) 사용 → 정상

### 1-5. _parse_results() 필터 체인 변경

> 검증 완료: `_parse_results()`는 4곳에서 호출, 모두 `_search_topic_items()` 내부 (`:978, :1018, :1060, :1098`)

- [ ] `allowed_domains` 파라미터 제거
- [ ] 4개 호출부에서 `allowed_domains=...` 키워드 인자 제거
- [ ] `_is_allowed_domain(url, domain_allowlist)` 호출 (`:696`) 제거
- [ ] 남은 필터 체인:
  1. `_is_disallowed_market_data_result(title, url)` — 유지
  2. `_is_topic_landing_page(topic, url, title)` — 유지
  3. `_is_invalid_news_title(title)` — 유지
  4. `_is_low_quality_source(url)` — **추가**
- [ ] `_is_allowed_domain()` 함수 삭제
  > 검증 완료: `_parse_results` 내부에서만 사용, 다른 호출자 없음
- [ ] `_matches_source_filter()` 함수 삭제
  > 검증 완료: `_is_allowed_domain` 내부에서만 사용, 다른 호출자 없음

### 1-6. allowlist 제거 보완 — FT/Apple 경로 보호

> 검증 발견: 기존 `_is_allowed_domain()`이 FT content 경로 제한(`https://www.ft.com/content/` prefix)과 Apple newsroom 제한(`/newsroom/`)을 담당. allowlist 제거 시 이 보호가 사라짐.

- [ ] `EXCLUDE_URL_PATTERNS`에 FT 비기사 경로 추가:
  ```python
  "/stream/",
  "www.ft.com/markets",
  ```
  > 참고: `/data/`는 이미 `EXCLUDE_URL_PATTERNS`에 있어 `markets.ft.com/data/*`는 차단됨. `www.ft.com/stream/` 등 추가 필요.
- [ ] `_is_disallowed_market_data_result()`에 Apple 비뉴스룸 차단 조건 추가:
  ```python
  if domain_matches(domain, "apple.com") and "/newsroom/" not in normalized_url:
      return True
  ```

### 1-7. retry 전략 간소화

> 검증 완료: 현재 4단계 retry는 allowlist 안에서 결과를 찾기 위한 것. deny list 전환 후 중간 2단계(last_updated, date_range) 불필요.

- [ ] `_search_topic_items()` 수정:
  - AS-IS: 1차 → last_updated retry → date_range retry → broad retry (4단계, 최대 4 API 호출/토픽)
  - TO-BE: 1차 → recency 확장 retry (2단계, 최대 2 API 호출/토픽)
- [ ] 제거: `retry_last_updated_days` 분기 (`:983-1026`)
- [ ] 제거: `retry_range_days` 분기 (`:1028-1067`)
- [ ] 유지: broad retry (`:1069-1101`) → recency를 `week`로 확장하는 역할
- [ ] `SearchTopic` dataclass에서 `retry_last_updated_days`, `retry_range_days` 필드 제거

### 1-8. SOURCE_LABELS 확장 + fallback 개선

> 검증 발견: 알 수 없는 도메인은 `"www.barrons.com"` 같은 raw 도메인 문자열이 라벨로 표시됨. `www.` prefix 포함.

- [ ] `SOURCE_LABELS`에 새 도메인 추가:
  ```python
  "barrons.com": "Barron's",
  "seekingalpha.com": "Seeking Alpha",
  "theblock.co": "The Block",
  "techcrunch.com": "TechCrunch",
  "theverge.com": "The Verge",
  "apnews.com": "AP News",
  ```
- [ ] `_source_label()` fallback에서 `www.` prefix 제거:
  ```python
  return domain.removeprefix("www.") or "Unknown"
  ```

### 1-9. 테스트 수정

- [ ] `test_perplexity_search.py` — 도메인 필터 관련 테스트 전면 수정:
  - `_is_allowed_domain` 관련 테스트 제거
  - `_is_low_quality_source` 테스트 추가
  - `_parse_results`에서 비신뢰 도메인(barrons.com 등) 기사가 통과하는지 확인
  - deny list가 API 파라미터에 정상 전달되는지 확인
  - retry 2단계로 축소된 흐름 테스트
- [ ] `test_news_quality.py` — 새 도메인 유입에 따른 랭킹 테스트 확인
- [ ] `test_pipeline_quality.py` — fallback 판단 로직 테스트 확인

### 1-10. 검증

- [ ] 단위 테스트 통과
  ```bash
  pytest tests/test_perplexity_search.py tests/test_news_quality.py tests/test_pipeline_quality.py -v
  ```
- [ ] 전체 품질 게이트 통과
  ```bash
  make check
  ```
- [ ] 로컬 1회 실행으로 실제 수집 확인
  ```bash
  SEND_EMAIL=false python3 main.py once --print-brief
  ```
  확인 항목:
  - [ ] observability 로그에서 `perplexity_items_collected` > 0건
  - [ ] 수집된 기사의 도메인이 기존 6개 외 도메인도 포함
  - [ ] `perplexity_result_filter_empty` 이벤트가 발생하지 않음
  - [ ] 저품질 도메인(reddit, medium 등) 기사가 필터링됨
- [ ] 커밋
  ```bash
  git commit -m "feat(news): Perplexity Search API allowlist → deny list 전환"
  ```

---

## Step 2: Grok X keyword + web search 활성화

> 목표: X 실시간 시그널 + 웹 뉴스 커버리지 확대
> 대상 파일: `grok_x_keyword.py`, `grok_web_search.py`, `grok_official_signals.py`, `provider_runtime.py`, `observability.py`, `llm_provider_policy.py`
> 테스트 파일: `tests/test_grok_new_sources.py`, `tests/test_news_quality.py`

### 2-1. 서킷 브레이커 분리

> 검증 발견: provider 이름은 **2개 레이어**로 분리되어 있음.
> - 서킷 브레이커/런타임 레이어: 3개 모듈 전부 `"grok"` 공유 (문제)
> - NewsItem/품질 레이어: 이미 분리됨 (`"grok_official_x"`, `"grok_x_keyword"`, `"grok_web_search"`)
> 따라서 서킷 브레이커 레이어만 분리하면 됨. 랭킹/품질 코드는 변경 불필요.

- [ ] `grok_official_signals.py:26`: `GROK_PROVIDER = "grok"` → `"grok_official"`
- [ ] `grok_x_keyword.py:31`: `GROK_PROVIDER = "grok"` → `"grok_keyword"`
- [ ] `grok_web_search.py:29`: `GROK_PROVIDER = "grok"` → `"grok_web"`
- [ ] `provider_runtime.py`: `PROVIDER_POLICIES` dict에 3개 policy 추가
  > 검증 발견: 미등록 provider는 기본 policy(min_interval=0, base_backoff=1.2s)를 받음.
  > 기존 `"grok"` policy는 `min_interval=0.5s, base_backoff=1.5s, max_backoff=10.0s`.
  > 3개 신규 provider에도 동일한 튜닝값 적용 필요.
  ```python
  _grok_policy_base = {"min_interval_seconds": 0.5, "base_backoff_seconds": 1.5, "max_backoff_seconds": 10.0}
  "grok_official": ProviderPolicy(name="grok_official", **_grok_policy_base),
  "grok_keyword": ProviderPolicy(name="grok_keyword", **_grok_policy_base),
  "grok_web": ProviderPolicy(name="grok_web", **_grok_policy_base),
  ```
- [ ] `observability.py:14`: `PREFERRED_PROVIDER_ORDER`에 `"grok"` → 3개 이름으로 교체, 또는 prefix 매칭 적용
- [ ] `observability.py:29`: `LLM_PRICING_USD_PER_1M`에 3개 이름 추가 (기존 `"grok"` 값은 전부 None이므로 동일하게)
- [ ] `llm_provider_policy.py:15,38`: Grok role policy — 단일 `"grok"` 유지할지 3개 분리할지 결정
  > 권장: role policy는 논리적 역할이므로 `"grok"` 단일 유지. 서킷 브레이커만 분리.
- [ ] ~~`data_quality.py`: provider 이름 상수 업데이트~~ — **불필요** (이미 분리된 이름 사용 중)
- [ ] ~~`news_selection.py`: provider 이름 변경 반영~~ — **불필요** (NewsItem의 provider 필드는 별도)

### 2-2. grok_x_keyword — 그룹 확장

- [ ] `AI_BIGTECH_PROMPT` 상수 추가
  ```
  Focus: NVIDIA, AMD, TSMC, ASML, Microsoft, Apple, Amazon, Google, Meta
  AI 인프라, 데이터센터 capex, 모델 발표, 실적 가이던스
  ```
- [ ] `BTC_ETF_PRIMARY_PROMPT` 상수 추가
  ```
  Focus: IBIT, BITB, GBTC 공식 운용사 발신, ETF 수수료, 보유량
  ```
- [ ] `GROUP_PROMPTS` dict에 2개 그룹 추가
- [ ] `GROUP_TOPIC_MAP` dict에 2개 그룹 추가
- [ ] `fetch_x_keyword_signals()` 함수: `grouped_verified_x_handles()`가 반환하는 그룹 키 확인
  - `official_signal_registry.py`에서 4개 그룹이 모두 나오는지 확인
  - 빈 handles 그룹은 자동 skip되는지 확인

### 2-3. grok_x_keyword — 주말 대응

- [ ] `_is_weekend()` 유틸 함수 추가 (또는 기존 것 재사용)
- [ ] 프롬프트에 주말 맥락 힌트 추가
- [ ] `lookback_hours`: 주말 72h 확장 고려 (설정 레벨에서)

### 2-4. grok_web_search — 품질 보강

- [ ] `WEB_SEARCH_PROMPT` 수정: `{time_window}`, `{weekend_hint}` placeholder 추가
- [ ] `_build_prompt(max_items)` 함수 신규 (주말 감지 포함)
- [ ] `_article_to_news_item()` 수정:
  - `why_it_matters` 필드 파싱 및 `NewsItem`에 반영
  - `citations` 필드 설정 (URL 자체를 citation으로)
- [ ] API 호출에 `include=["inline_citations"]` 추가
- [ ] 반환된 `topic` 값 정규화:
  ```python
  VALID_TOPICS = {"macro", "us_equity", "ai_bigtech", "bitcoin"}
  if topic not in VALID_TOPICS:
      topic = "macro"
  ```

### 2-5. official signals ↔ keyword 중복 제거

- [ ] `news.py`의 `build_news_packet()`에서 병합 시 중복 제거 로직 추가
  - 같은 `source_handle` + 유사 `headline` → official signals 우선 유지
- [ ] 또는 `news_selection._dedup_and_rank()`에 handle 기반 dedup 추가

### 2-6. config.py 기본값 변경

- [ ] `GROK_X_KEYWORD_SEARCH_ENABLED` 기본값: `False` → `True`
- [ ] `GROK_WEB_SEARCH_ENABLED` 기본값: `False` → `True`
- [ ] `.env.example` 업데이트

### 2-7. 테스트 수정

- [ ] `test_grok_new_sources.py`:
  - 새 그룹 프롬프트 생성 확인 테스트
  - `why_it_matters` 필드 파싱 테스트 (web search)
  - `citations` 필드 설정 테스트 (web search)
  - 토픽 정규화 테스트
  - 주말 프롬프트 힌트 테스트
- [ ] `test_news_quality.py`:
  - Grok 중복 제거 테스트

### 2-8. 검증

- [ ] 단위 테스트 통과
  ```bash
  pytest tests/test_grok_new_sources.py tests/test_news_quality.py -v
  ```
- [ ] 전체 품질 게이트 통과
  ```bash
  make check
  ```
- [ ] 로컬 1회 실행 (Grok 모듈 활성화)
  ```bash
  GROK_X_KEYWORD_SEARCH_ENABLED=true GROK_WEB_SEARCH_ENABLED=true SEND_EMAIL=false python3 main.py once --print-brief
  ```
  확인 항목:
  - [ ] `grok_keyword` provider 로그에 시그널 수집 확인
  - [ ] `grok_web` provider 로그에 기사 수집 확인
  - [ ] 서킷 브레이커가 모듈별로 독립 동작하는지 확인 (한 모듈 실패 시 나머지 계속)
  - [ ] official signals와 keyword 간 중복이 제거되는지 확인
  - [ ] 총 뉴스 건수가 이전보다 증가했는지 확인
- [ ] 커밋
  ```bash
  git commit -m "feat(news): Grok X keyword + web search 활성화 및 그룹 확장"
  ```

---

## Step 3: Perplexity Sonar 맥락 보강 레이어

> 목표: Phase 1 수집 결과에 심층 맥락 + 교차 검증 추가
> 대상 파일: `perplexity_sonar.py`, `news.py`, `pipeline.py`, `briefing.py`, `prompting.py`, 프롬프트 템플릿
> 테스트 파일: `tests/test_perplexity_sonar.py`, `tests/test_news_quality.py`, `tests/test_pipeline_observability.py`

### 3-1. 전략: 기존 TopicSummary와 병행 도입

> 검증 발견: `TopicSummary`는 `pipeline.py:69` → `packet["topic_summaries"]` → `prompting.py` → `brief_input.j2` → `brief_instructions.j2`까지 깊이 연결되어 있음.
> 한번에 교체하면 리스크가 높으므로, **ContextAnalysis를 병행 추가** 후 안정화되면 TopicSummary 제거.

- [ ] 방침: `ContextAnalysis`를 `TopicSummary`와 **병렬로** 추가. 기존 Sonar 코드는 유지.
- [ ] 새 함수 `analyze_news_context()`를 `perplexity_sonar.py`에 추가 (기존 함수 삭제하지 않음)

### 3-2. ContextAnalysis 데이터 모델

- [ ] `ContextAnalysis` dataclass 정의
- [ ] `SignalAnalysis` dataclass 정의
  ```python
  @dataclass
  class SignalAnalysis:
      signal_ref: str
      background: str
      market_impact: str
      confidence: str  # high / medium / low
      cross_references: list[str] = field(default_factory=list)

  @dataclass
  class ContextAnalysis:
      analyses: list[SignalAnalysis]
      key_narrative: str
      citations: list[str] = field(default_factory=list)
  ```

### 3-3. 맥락 분석 함수 구현

- [ ] `analyze_news_context()` 함수 신규
- [ ] 입력 포맷팅: `_format_signals_for_sonar(items: list[NewsItem]) -> str`
  - URL 없이 제목+요약+출처 텍스트만 전달 (Sonar 공식 가이드: 프롬프트 내 URL 비권장)

### 3-4. Sonar 프롬프트 + JSON Schema

- [ ] `SONAR_CONTEXT_PROMPT` 상수 (또는 새 Jinja 템플릿 `sonar_context.j2`)
- [ ] `SONAR_CONTEXT_SCHEMA` JSON Schema
  > 주의: Sonar JSON Schema 첫 사용 시 cold start 10~30초. 이후 캐싱됨.
- [ ] `search_domain_filter`: 기존 `SONAR_DENY_DOMAINS` 유지
- [ ] `search_recency_filter`: 평일 `"day"` / 주말 `"week"`

### 3-5. Sonar 모델 선택 로직

- [ ] 평일: `settings.perplexity_sonar_model` (기본 `sonar`)
- [ ] 주말: `sonar-pro`
- [ ] 설정: `PERPLEXITY_SONAR_WEEKEND_MODEL` 환경변수 추가 (선택)

### 3-6. news.py 오케스트레이션 수정

> 검증 발견: `build_news_packet()` 반환 3-tuple을 unpack하는 곳:
> - `pipeline.py:59` — 1곳
> - `tests/test_news_quality.py` — 10곳 (`packet, _, _ = ...`)
> - `tests/test_pipeline_observability.py` — 4곳 (mock 반환값 `([], {}, [])`)

- [ ] `build_news_packet()` 반환 타입 확장: 3-tuple → 4-tuple
  ```python
  -> tuple[list[dict], dict[str, TopicSummary], list[XSignal], ContextAnalysis | None]
  ```
- [ ] Phase 1 수집 완료 후, Sonar 분석 호출 추가:
  ```python
  context_analysis = None
  if settings.perplexity_use_sonar and items:
      context_analysis = analyze_news_context(
          api_key=settings.perplexity_api_key,
          model=_select_model(settings),
          collected_signals=items,
          observer=observer,
      )
  ```
- [ ] 반환값에 `context_analysis` 추가

### 3-7. pipeline.py 수정

- [ ] `run_pipeline()`: 4번째 반환값 `context_analysis` 처리
- [ ] `context_analysis`가 있으면 `packet["context_analysis"]`로 삽입
  ```python
  if context_analysis is not None:
      packet["context_analysis"] = {
          "key_narrative": context_analysis.key_narrative,
          "analyses": [vars(a) for a in context_analysis.analyses],
          "citations": context_analysis.citations,
      }
  ```

### 3-8. prompting.py + 프롬프트 템플릿 수정

> 검증 발견: 현재 데이터 흐름:
> `pipeline.py` → `packet["topic_summaries"]` → `prompting.py:_build_news_focus()` → `news_focus_json` → `brief_input.j2` → `brief_instructions.j2`

- [ ] `prompting.py:_build_news_focus()`: `packet.get("context_analysis")` 추가 추출
- [ ] `brief_input.j2`: `context_analysis` 필드 문서화 추가
- [ ] `brief_instructions.j2`: 조건부 맥락 활용 지시 추가
  ```jinja
  {% if context_analysis %}
  [시장 맥락 분석]에 포함된 key_narrative를 LAYER 1의 핵심 논조로 활용하세요.
  각 analyses의 background와 market_impact를 LAYER 2 관련 뉴스 항목에 반영하세요.
  {% endif %}
  ```

### 3-9. 기존 TopicSummary 흐름 유지 (이 단계에서는 삭제하지 않음)

> 검증 발견: `brief_instructions.j2:8-9`에서 `topic_summaries[].why_it_matters`를 참조하지만, `TopicSummary`에는 `market_implication` 필드만 있고 `topic_summaries_to_dict()`도 `market_implication`으로 직렬화. **기존 불일치 존재** — 이번 작업에서 수정하지 않음 (범위 외).

- [ ] `fetch_sonar_summaries()` — 유지 (기존 호출 경로 보존)
- [ ] `TopicSummary` — 유지
- [ ] 기존 Sonar 토픽 프롬프트 (`sonar_topic_*.j2`) — 유지
- [ ] 추후 ContextAnalysis 안정화 후 별도 작업으로 TopicSummary 제거

### 3-10. Sonar 실패 처리

- [ ] API 에러 시 `None` 반환
- [ ] observability에 `sonar_context_analysis_failed` 이벤트 기록
- [ ] 파이프라인은 Phase 1 결과만으로 계속 진행 (graceful degradation)

### 3-11. 테스트 수정

- [ ] `test_perplexity_sonar.py`: 기존 테스트 유지 + 신규 테스트 추가
  - `analyze_news_context()` 입력/출력 테스트
  - JSON Schema 파싱 테스트
  - 빈 시그널 입력 시 처리 테스트
  - API 실패 시 None 반환 테스트
  - 주말 모델 선택 테스트
- [ ] `test_news_quality.py`: 10곳 `packet, _, _ = ...` → `packet, _, _, _ = ...` 수정
- [ ] `test_pipeline_observability.py`: 4곳 mock 반환값 `([], {}, [])` → `([], {}, [], None)` 수정
- [ ] `test_briefing_quality.py`: 맥락 섹션 포함/미포함 브리핑 테스트

### 3-12. 설정 업데이트

- [ ] `config.py`:
  - `PERPLEXITY_USE_SONAR_SUMMARY` 기본값: `False` → `True`
  - `PERPLEXITY_SONAR_WEEKEND_MODEL` 추가 (선택, 기본 `sonar-pro`)
- [ ] `.env.example` 업데이트
- [ ] `README.md` 환경변수 섹션 업데이트

### 3-13. 검증

- [ ] 단위 테스트 통과
  ```bash
  pytest tests/test_perplexity_sonar.py tests/test_news_quality.py tests/test_pipeline_observability.py tests/test_briefing_quality.py -v
  ```
- [ ] 전체 품질 게이트 통과
  ```bash
  make check
  ```
- [ ] 로컬 1회 실행
  ```bash
  PERPLEXITY_USE_SONAR_SUMMARY=true SEND_EMAIL=false python3 main.py once --print-brief
  ```
  확인 항목:
  - [ ] Sonar 맥락 분석 로그 확인 (`sonar_context_analysis` 이벤트)
  - [ ] 브리핑에 맥락이 반영되었는지 확인
  - [ ] Sonar citations 목록 확인
  - [ ] 전체 파이프라인 소요 시간이 허용 범위 내인지 확인 (3분 이내)
  - [ ] Sonar 실패 시에도 브리핑이 정상 생성되는지 확인
- [ ] 커밋
  ```bash
  git commit -m "feat(news): Perplexity Sonar 맥락 보강 레이어 구현"
  ```

---

## Step 4: 통합 검증 + 문서 업데이트

> 목표: 전체 파이프라인 안정성 확인 및 문서 정비

### 4-1. 통합 테스트

- [ ] 전체 테스트 스위트 통과
  ```bash
  make check
  ```
- [ ] 로컬 전체 파이프라인 실행 (이메일 발송 포함)
  ```bash
  python3 main.py once --print-brief
  ```
  확인 항목:
  - [ ] 브리핑 품질 육안 확인
  - [ ] observability 로그에서 전체 provider 상태 확인
  - [ ] 뉴스 건수 / 도메인 다양성 / 토픽 커버리지 확인

### 4-2. GitHub Actions 설정 업데이트

- [ ] `.github/workflows/morning-brief.yml`:
  - `GROK_X_KEYWORD_SEARCH_ENABLED: true` 추가
  - `GROK_WEB_SEARCH_ENABLED: true` 추가
  - `PERPLEXITY_USE_SONAR_SUMMARY: true` 추가
- [ ] GitHub Variables 업데이트 (필요시)

### 4-3. README.md 업데이트

- [ ] 환경변수 섹션: 새 변수 / 변경된 기본값 반영
- [ ] 프로젝트 구조 섹션: 변경된 모듈 역할 반영
- [ ] 수집 신뢰성 운영 원칙 섹션: 새 아키텍처 반영
  - Perplexity: 뉴스 수집(deny list) + 맥락 분석(Sonar)
  - Grok: 공식 X 시그널 + 키워드 X 검색 + 웹 뉴스 수집

### 4-4. docs/news-pipeline-redesign.md 업데이트

- [ ] "현재 뉴스 수집 흐름 (AS-IS)" → 구현 완료 상태로 업데이트
- [ ] 각 Phase 상세에 실제 구현 결과 반영

### 4-5. 모니터링 (1~2주)

- [ ] 매일 observability 로그 확인:
  - `perplexity_items_collected` 건수 추이
  - `grok_keyword`, `grok_web` provider 건수 추이
  - `sonar_context_analysis` 성공률
  - 데이터 품질 상태 (`ok` / `degraded` / `critical`)
- [ ] 주말 실행 특별 확인:
  - Perplexity deny list 전환으로 주말 0건 문제 해소되었는지
  - Grok 주말 프롬프트 힌트가 효과적인지
  - Sonar 주말 모델 (`sonar-pro`) 품질 차이
- [ ] 필요시 deny list 확장 (`LOW_QUALITY_DOMAINS`에 추가)
- [ ] 필요시 프롬프트 튜닝
- [ ] legacy fallback 사용 빈도 확인 → 안정적이면 rollout 기준 강화
