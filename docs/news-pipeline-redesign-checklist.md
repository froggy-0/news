# 뉴스 파이프라인 재설계 체크리스트

> 원본: `docs/news-pipeline-redesign.md` (2026-03-16)
> 배경: Perplexity allowlist 6개 도메인 → 주말 수집 0건 문제 해결

---

## Step 1: Perplexity deny list + recency + 키워드 쿼리

> 즉시 효과. 주말 0건 문제의 직접 해결.

- [x] `perplexity_search.py` — `search_domain_filter`를 allowlist → deny list(`SEARCH_DENY_DOMAINS`)로 전환
  - deny 목록: `markets.ft.com`, `data.coindesk.com`, `downloads.coindesk.com`, `sponsored.bloomberg.com`, `cn.wsj.com`, `jp.reuters.com`, `apps.apple.com`, `podcasts.apple.com`, `tv.apple.com`, `status.perplexity.ai`
- [x] `perplexity_search.py` — API 파라미터에 `search_recency_filter: "day"` 추가
- [x] `perplexity_search.py` — 쿼리에 날짜(`%B %d %Y`) + 키워드 주입하는 `build_query()` 구현
- [x] `perplexity_search.py` — `SearchTopic`에서 `domain_filter`, `retry_domain_filter` 필드 제거
- [x] `perplexity_search.py` — `_parse_results()`에서 `_is_allowed_domain()` 호출 제거
- [x] `perplexity_search.py` — `_is_low_quality_source()` deny 필터 추가
  - 대상: `reddit.com`, `twitter.com`, `x.com`, `facebook.com`, `linkedin.com`, `quora.com`, `medium.com`, `tradingview.com`, `investing.com`, `stockanalysis.com`, `finance.yahoo.com`, `google.com/finance`, `wikipedia.org`, `investopedia.com`, `glassdoor.com`, `indeed.com`
- [x] `perplexity_search.py` — `_parse_results()` TO-BE 필터 체인 완성 확인
  - `_is_disallowed_market_data_result()` (기존 유지)
  - `_is_topic_landing_page()` (토픽별 랜딩 페이지 차단)
  - `_is_invalid_news_title()` (비영어/무의미 제목 차단)
  - `_is_low_quality_source()` (신규)
- [x] `perplexity_search.py` — retry 전략 간소화 (15회 → 8회: 4토픽 × 2단계)
- [x] 기존 `news_policy.py`의 `DOMAIN_SCORES` 소프트 랭킹은 변경 없이 유지 확인
- [x] 관련 테스트 업데이트 (allowlist 참조 테스트 제거/수정)

**검증**:
```bash
SEND_EMAIL=false python3 main.py once --print-brief
# perplexity_items_collected 로그에서 FT 데이터 페이지 없음 확인
# 유효 기사 건수 > 0 확인
```

---

## Step 2: 시장 데이터 기반 키워드 자동 추출

> Grok 장애와 무관하게 항상 동작하는 기본 키워드 소스.

- [x] `extract_market_keywords(market_data) -> list[str]` 구현
  - VIX > 25 → `"volatility spike market fear {today}"`
  - US10Y 변동률 > 1.0% → `"treasury yields surge/drop {today}"`
  - S&P 500 변동률 > 1.5% → `"S&P 500 rally/selloff {today}"`
  - 개별 기술주 변동률 > 3.0% → `"{ticker} surge/decline {today}"`
  - BTC 변동률 > 3.0% → `"bitcoin rally/drop {today}"`
- [x] `build_search_keywords(market_keywords, grok_keywords) -> dict[str, list[str]]` 구현
  - 섹터 분류: `macro`, `ai_bigtech`, `bitcoin`, `us_equity`
  - Grok 키워드 `None`이면 시장 데이터 키워드만으로 동작
- [x] `pipeline.py`에서 시장 데이터 수집 후 키워드 추출 → Perplexity 쿼리에 주입하도록 연결
- [x] 테스트: 키워드 추출 로직 단위 테스트

**검증**:
```bash
# 로그에서 market_keywords_extracted 이벤트 확인
# Perplexity 쿼리에 키워드 포함 여부 확인
```

---

## Step 3: Grok X keyword 활성화 + 그룹 확장

> X 실시간 트렌딩 선행 시그널 포착.

- [x] `grok_x_keyword.py` — `GROUP_PROMPTS`에 `ai_bigtech_primary`, `btc_etf_primary` 그룹 추가
- [x] `grok_x_keyword.py` — `GROUP_TOPIC_MAP`에 신규 그룹 → 섹터 매핑 추가
- [x] `grok_x_keyword.py` — AI/빅테크 프롬프트 작성 (반도체/FAANG/AI인프라/실적 포커스)
- [x] `grok_x_keyword.py` — 키워드 추출 출력 구조 추가 (`keywords_by_sector` dict)
- [x] `grok_x_keyword.py` — 주말 맥락 프롬프트 추가 (금요일 장마감 이후 분석 유도)
- [x] `grok_x_keyword.py` — `why_it_matters` 필드 검증 추가
- [x] `provider_runtime.py` — Grok 서킷 브레이커 모듈별 분리
  - `"grok"` → `"grok_official"` + `"grok_keyword"` 분리
- [x] `news.py` — official signals와 keyword 중복 제거 (`source_handle` 기반 dedup)
- [x] 환경변수 기본값 변경: `GROK_X_KEYWORD_SEARCH_ENABLED=true`
- [x] 테스트: 그룹 확장, 키워드 추출, dedup 단위 테스트

**검증**:
```bash
GROK_X_KEYWORD_SEARCH_ENABLED=true SEND_EMAIL=false python3 main.py once --print-brief
# grok_signals_collected, grok_x_keyword 로그 확인
# 키워드 추출 결과 확인
```

---

## Step 4: ~~Claude Haiku 검수 교체~~ → OpenAI 단일 검수 유지

> JSON truncated 문제는 `max_output_tokens` 확보 + `json_schema` strict 모드로 해결.
> Claude 도입 후 비용 대비 효과 재검토 결과, OpenAI 단일 유지로 결정.

- [x] `brief_review.py` — `VALIDATOR_MAX_OUTPUT_TOKENS` 1400→2000 확보
- [x] `brief_review.py` — `json_schema` strict 모드 유지 (truncated 구조적 방지)
- [x] `brief_review.py` — Claude 검수 경로 제거, OpenAI 단일 경로
- [x] `requirements.txt` — `anthropic` SDK 제거
- [x] `config.py` — `anthropic_api_key`, `anthropic_review_model` 제거
- [x] `llm_provider_policy.py` — `ANTHROPIC_PROVIDER` 제거
- [x] `observability.py` — anthropic pricing/순서 제거
- [x] `.github/workflows` — ANTHROPIC 환경변수 제거
- [x] 테스트: JSON parse 오류 없음 확인, fallback 브리핑 미발동 확인

**검증**:
```bash
SEND_EMAIL=false python3 main.py once --print-brief
# brief_review 로그에서 JSON parse 오류 없음 확인
# fallback 브리핑 미발동 확인
```

---

## Step 5: Gemini Flash fallback 추가

> Perplexity 0건 시 안전망.

- [x] `requirements.txt`에 `google-genai` SDK 추가
- [x] `sources/gemini_grounding.py` 신규 모듈 생성
  - `fetch_gemini_grounding(query, keywords)` 구현
  - Google Search grounding 활용
- [x] `config.py` — Gemini 관련 환경변수 추가 (`GEMINI_API_KEY` 등)
- [x] `news.py` — Perplexity 유효 기사 0건 시 Gemini fallback 호출 연결
- [x] `provider_runtime.py` — Gemini provider 등록
- [x] `llm_provider_policy.py` — Gemini 역할 등록 (뉴스 fallback 전담)
- [x] `observability.py` — Gemini 사용량 추적 추가
- [x] Google Search grounding 500 RPD 무료 한도 카운터 모니터링 로직 추가
- [x] 테스트: Perplexity 0건 시나리오에서 Gemini fallback 동작 확인

---

## Step 6: Sonar 맥락 보강 레이어

> 수집된 뉴스 기반 심층 맥락 분석.

- [x] `prompts/sonar_context_system.j2` — Sonar 맥락 분석 시스템 프롬프트 작성
- [x] `prompts/sonar_context_input.j2` — 입력 템플릿 작성 (기사 제목+요약 텍스트만, URL 미포함)
- [x] `perplexity_sonar.py` — Phase 2 상위 N건 기반 맥락 분석 함수 구현
  - 섹터별 상위 3건 × 4섹터 = 최대 12건 입력 제한
  - JSON Schema 구조화 출력 (`analyses[]` + `key_narrative`)
- [x] `perplexity_sonar.py` — 모델 선택: 주말 `sonar-pro` / 평일 `sonar`
- [x] `pipeline.py` — Phase 2 → Phase 3 연결 (수집 결과 → Sonar 입력)
- [x] `prompting.py` — Sonar 분석 결과를 브리핑 렌더링 컨텍스트에 주입하는 연결 구현
- [x] `prompts/brief_input.j2` — 브리핑 생성 입력에 Sonar 맥락 섹션 추가 (맥락, 내러티브, 교차 검증)
- [x] Sonar 실패 시 Phase 2 결과 + 시장 데이터만으로 브리핑 생성 (graceful degradation)
- [x] `config.py` — `PERPLEXITY_USE_SONAR_SUMMARY=true` 기본값 변경
- [x] 테스트: Sonar 입력 건수 제한, 구조화 출력 파싱, 실패 시 fallback

---

## Step 7: 안정화 + 튜닝

> 1~2주 운영 모니터링.

- [ ] observability 로그에서 도메인 다양성 추이 확인
- [ ] 토픽별 커버리지 (유효 기사 건수) 추이 확인
- [ ] 품질 점수 (domain_score, recency_score) 분포 확인
- [ ] deny list 확장 필요 여부 판단 (새로운 저품질 도메인 발견 시)
- [ ] Sonar 입력 건수 최적화 (12건 → 조정)
- [ ] legacy fallback 발동 빈도 추이 확인 → 축소 가능 여부 판단
- [ ] 비용 추이 확인 (목표: ~$0.063/실행 이하)
- [x] `README.md` 업데이트 (변경된 아키텍처, 환경변수, 의존성 반영)
- [ ] `AGENTS.md` 업데이트 (필요 시)

---

## 향후: 섹터 확장 로드맵

> Phase 1~4 구조 유지. Phase 2부터 섹터별 병렬 분기.

- [ ] 섹터별 병렬 파이프라인 설계 (semiconductor, ai, macro, bitcoin)
- [ ] 섹터별 Perplexity + Sonar + OpenAI 독립 실행 구조
- [ ] 구독자 섹터 설정 기반 개별 발송 구현
- [ ] 추가 비용 산정: 섹터당 ~$0.018/실행

---

## 비용 목표

| 항목 | AS-IS | TO-BE |
|------|-------|-------|
| Perplexity Search | 15회 (~$0.075) | 8회 (~$0.040) |
| Perplexity Sonar | 0회 | 1회 (~$0.008) |
| Gemini Flash | 0회 | 0.3회 평균 (~$0.001) |
| Grok | 4회 (~$0.003) | 6회 (~$0.005) |
| OpenAI | 4회 (~$0.007) | 6회 (~$0.009) |
| **총계** | **~$0.085** | **~$0.063** |

---

## 리스크 체크

- [x] deny list 전환 후 저품질 기사 유입 → `_is_low_quality_source()` + 소프트 랭킹으로 방어 확인
- [x] Grok 장애 시 시장 데이터 키워드만으로 Perplexity 독립 실행 확인
- [x] Grok keyword + official signals 중복 → `source_handle` dedup 동작 확인
- [ ] Sonar JSON cold start (10~30초) → 파이프라인 timeout 여유 확보
- [x] Sonar 입력 과다 시 품질 저하 → 섹터별 3건 제한 적용 확인
- [x] Claude Haiku JSON 출력 실패 → OpenAI `json_schema` strict 모드 + `max_output_tokens=2000`으로 대체
- [x] Gemini 500 RPD 초과 → 카운터 모니터링 + Legacy RSS 직행 확인
