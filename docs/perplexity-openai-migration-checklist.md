# Perplexity + OpenAI 마이그레이션 체크리스트

현재 뉴스 레이어는 무료 RSS, GDELT, 선택적 NewsAPI, OpenAI `web_search` 보강에 기대고 있습니다.
이 구조는 비용은 낮지만, 소스 신뢰도와 수집 일관성이 일정하지 않고, 품질이 약한 날에는 보강 로직이 자주 개입합니다.
이번 문서의 목표는 Perplexity를 뉴스/리서치 메인 레이어로 전환하고, OpenAI는 최종 한국어 브리핑 생성과 검수에 집중하도록 구조를 고정하는 것입니다.
숫자 데이터는 계속 전용 API나 공식 페이지에서만 가져오고, LLM은 숫자 원본 수집에 관여하지 않는 것을 기본 원칙으로 둡니다.

## 목표 아키텍처

- `Numeric providers`
  - `FRED`: 금리, 달러, VIX 같은 거시 지표
  - `Alpha Vantage`: 미국 주식/ETF 일봉
  - `ETF 공식 페이지`: BTC ETF 보유량과 순유입/순유출
  - `Alternative.me Fear & Greed`: BTC 공포탐욕지수
- `Research provider`
  - `Perplexity Search`
- `Language provider`
  - `OpenAI 생성`
  - `OpenAI 검수`
  - `OpenAI 재작성`
- `Fallback providers`
  - `SEC / Fed / Treasury / 기업 IR RSS`
  - `CoinDesk`
  - 기존 `GDELT / Google News RSS`는 마지막 emergency fallback로만 유지

기본 판단:
- Perplexity는 **뉴스/리서치 검색 전용**으로 쓴다.
- OpenAI는 **최종 한국어 브리핑 생성/검수 전용**으로 쓴다.
- 숫자 데이터는 **LLM에서 직접 가져오지 않는다.**

### 구현 고정 결정

- [x] Perplexity는 `Search API`를 기본값으로 고정한다.
- [x] `Sonar`는 이번 마이그레이션 범위에서 기본 구현 대상이 아니다.
- [x] 이유:
  - [x] Search API는 원문 검색 결과와 출처 통제가 더 명확하다.
  - [x] 최종 요약/검수는 이미 OpenAI가 맡고 있으므로, 리서치 단계에서 LLM 요약을 한 번 더 넣지 않는다.
- [x] Perplexity 호출 기본값
  - [x] 토픽당 `max_results=5`
  - [x] 토픽당 메인 질의 1회
  - [x] 품질 미달 시 토픽당 재질의 1회
  - [x] 하루 1회 브리핑 기준 총 요청 수는 `4~8회`
- [x] OpenAI는 Perplexity가 넘긴 결과를 다시 검색하지 않고, 그 결과만 바탕으로 한국어 브리핑을 생성한다.

## Phase 0. 현재 구조 정리

### 현재 뉴스 수집 경로

| 레이어 | 현재 소스 | 역할 | 현재 코드 위치 | 마이그레이션 판단 |
| --- | --- | --- | --- | --- |
| 뉴스 메인 | GDELT | 선호 도메인 우선 기사 수집 | `src/morning_brief/data/news.py` | 제거 후보. 메인 의존에서 내린다. |
| 뉴스 보강 | NewsAPI | 선택적 보강 | `src/morning_brief/data/news.py` | 비용 문제로 기본 경로에서 제외 |
| 뉴스 보강 | Google News RSS | 선호 도메인 RSS 보강 | `src/morning_brief/data/news.py` | emergency fallback로 격하 |
| 뉴스 확장 | GDELT broad + RSS broad | 우선 소스 부족 시 범위 확장 | `src/morning_brief/data/news.py` | 최후 fallback로 축소 |
| 뉴스 검증 | OpenAI `web_search` | degraded 시 허용 도메인 안에서 보강 | `src/morning_brief/research_backfill.py` | Perplexity 전환 후 역할 축소 또는 제거 검토 |

### 현재 숫자 데이터 경로

| 레이어 | 현재 소스 | 역할 | 현재 코드 위치 | 유지 여부 |
| --- | --- | --- | --- | --- |
| 거시 | FRED | 금리, 달러, VIX 계열 공식 소스 | `src/morning_brief/data/market.py` | 유지 |
| 거시 fallback | yfinance | FRED 실패 시 보조 | `src/morning_brief/data/market.py` | 제한적으로 유지 |
| 미국 지수/기술주 | Alpha Vantage | 일봉 가격/등락률/거래량 | `src/morning_brief/data/market.py` | 유지 |
| 주식 fallback | Stooq / yfinance | Alpha Vantage 실패 시 보조 | `src/morning_brief/data/market.py` | 유지하되 후순위화 |
| BTC 현물 | CoinGecko | BTC 현물 가격 | `src/morning_brief/data/market.py` | 유지 |
| BTC 공포탐욕 | Alternative.me | BTC Fear & Greed | `src/morning_brief/data/market.py` | 유지, 기본값으로 명시 |
| BTC ETF | 발행사 공식 페이지 | 보유량/AUM/순유입 | `src/morning_brief/data/market.py`, `src/morning_brief/data/sources/btc_etf_official.py` | 유지 |

### 현재 OpenAI 사용 지점

| 역할 | 현재 동작 | 현재 코드 위치 | 마이그레이션 방향 |
| --- | --- | --- | --- |
| 브리핑 생성 | 패킷 기반 초안 생성 | `src/morning_brief/briefing.py` | 유지 |
| 브리핑 검수 | 쉬운 한국어/숫자 일치 검수 | `src/morning_brief/brief_review.py` | 유지 |
| 브리핑 재작성 | 검수 실패 시 1회 재작성 | `src/morning_brief/brief_review.py` | 유지 |
| 뉴스 검색 보강 | degraded 시 `web_search` 사용 | `src/morning_brief/research_backfill.py` | Perplexity 전환 후 단계적 축소 |

### 유지할 것 / 제거 후보

- [ ] 유지 대상
  - [ ] FRED
  - [ ] Alpha Vantage
  - [ ] ETF 공식 페이지
  - [ ] Alternative.me Fear & Greed
  - [ ] OpenAI 생성 / 검수 / 재작성
- [ ] 제거 후보
  - [ ] GDELT 중심 수집 흐름
  - [ ] Google News RSS 메인 의존
  - [ ] NewsAPI 기반 보강 기본 경로
- [ ] 정리 메모
  - [ ] `뉴스`, `숫자`, `LLM` 세 레이어를 분리한 표를 유지한다
  - [ ] 제거 후보로 `GDELT 중심 흐름`과 `Google RSS 메인 의존`을 명시한다

완료 기준:
- [ ] 현재 구조 표가 채워져 있다
- [ ] 제거 후보가 명확히 적혀 있다

## Phase 1. 설정 / 인터페이스 재설계

- [x] `PERPLEXITY_API_KEY` 환경변수 추가 계획을 적는다
- [x] `RESEARCH_PROVIDER=perplexity` 기본값을 제안한다
- [x] `ENABLE_LEGACY_NEWS_FALLBACK=true` 기본값을 정의한다
- [x] `OPENAI_BRIEF_VALIDATION_*` 계열은 그대로 유지한다고 적는다
- [ ] `OPENAI_WEB_SEARCH_*`는 기본 비활성 후보로 내리고, transitional fallback으로만 둔다
- [x] 연구 결과 공통 스키마를 정의한다

### 현재 코드에 붙는 인터페이스 결정

- [x] `build_news_packet()`는 `build_news_packet(*, settings: Settings) -> list[dict]` 로 바꾼다.
- [x] `pipeline.py`는 `Settings` 전체를 전달하고, 뉴스 provider 선택은 `news.py` 내부에서 처리한다.
- [x] `build_market_packet()` 시그니처는 그대로 유지한다.
- [ ] `Settings`에는 아래 필드를 추가한다.
  - [x] `perplexity_api_key: str`
  - [x] `research_provider: str`
  - [x] `enable_legacy_news_fallback: bool`
- [x] 기존 `newsapi_key`는 transitional fallback 기간에만 유지하고, steady state 기본 경로에서는 사용하지 않는다.
- [x] `OPENAI_WEB_SEARCH_*`는 transitional 마지막 fallback에만 사용한다.

### 연구 결과 공통 스키마 기본값

#### `PerplexitySearchResult` 원본 응답 정규화

| 필드 | 설명 | 규칙 |
| --- | --- | --- |
| `title` | 검색 결과 제목 | 비어 있으면 버림 |
| `url` | 대표 링크 | 정규화 후 사용 |
| `source` | 발행처 | 표시용 |
| `domain` | 정규화 도메인 | 필수 |
| `published_at` | 발행 시각 | 가능하면 UTC ISO 8601 |
| `topic` | 질의 토픽 | 필수 |
| `snippet` | Search API가 제공한 본문 일부 | 없으면 빈 문자열 |
| `provider` | `perplexity_search` | 고정 |
| `citations` | 출처 URL 목록 | 최소 1개 |

#### `ResearchItem` 구현용 공통 스키마

| 필드 | 설명 | 기본값 / 규칙 |
| --- | --- | --- |
| `title` | 기사 제목 | 비어 있으면 버림 |
| `url` | 대표 URL | 정규화 후 사용 |
| `source` | 소스명 | 표시용 |
| `domain` | 정규화 도메인 | 랭킹과 품질 판정용 |
| `published_at` | 발행 시각 | UTC ISO 8601 |
| `topic` | `macro`, `us_equity`, `ai_bigtech`, `bitcoin` 중 하나 | 필수 |
| `summary` | 1~2문장 요약 | Search API의 `snippet`을 정규화해 채운다 |
| `why_it_matters` | 시장 영향 한 줄 | 필수 |
| `provider` | `perplexity`, `rss`, `regulatory`, `legacy` 등 | 필수 |
| `trust_tier` | `official`, `tier_1`, `tier_2`, `tier_3` | 필수 |
| `citations` | 근거 URL 목록 | 최소 1개 |

완료 기준:
- [x] 구현자가 추가 판단 없이 config와 타입을 만들 수 있다
- [x] 필드 정의만으로 provider / ranking / quality 구현이 가능하다

## Phase 2. 뉴스 / 리서치 수집 교체

- [x] Perplexity 전용 research provider를 1순위 메인으로 정의한다
- [x] 토픽을 아래 4개로 분리한다고 명시한다
  - [x] `macro`
  - [x] `us_equity`
  - [x] `ai_bigtech`
  - [x] `bitcoin`
- [x] 각 토픽별 검색 쿼리 전략을 정의한다
- [x] 허용 도메인 정책을 정의한다
- [x] 중복 제거 기준을 정의한다
- [ ] 기존 `news.py`는 수집 / 병합 / 랭킹 / 품질을 분리한다고 적는다

### 허용 도메인 정책

- [x] 우선 허용
  - [x] Reuters
  - [x] Bloomberg
  - [x] WSJ
  - [x] FT
  - [x] CNBC
  - [x] CoinDesk
  - [x] SEC
  - [x] Federal Reserve
  - [x] Treasury
  - [x] ETF 발행사 공식 도메인
- [x] 보조 허용
  - [x] 기업 IR / newsroom
  - [ ] PR Newswire
  - [ ] Business Wire

### Perplexity 쿼리 전략

- [x] 토픽당 1개 메인 질의를 둔다
- [x] 결과가 약하면 토픽당 1개 재질의를 허용한다
- [x] 하루 1회 파이프라인 기준 총 4~8회 검색 안쪽으로 제한한다
- [x] 최신성보다 출처 신뢰도를 우선한다
- [x] 가능하면 시장 영향도가 높은 기사만 반환하도록 유도한다

#### 토픽별 기본 질의

- [x] `macro`
  - [x] `Fed, FOMC, Treasury yields, dollar, VIX, inflation expectations`
- [x] `us_equity`
  - [x] `S&P 500, Nasdaq, semiconductor sector, market breadth`
- [x] `ai_bigtech`
  - [x] `NVIDIA, Microsoft, Apple, Amazon, Google, Meta, AMD, TSM, ASML, AVGO`
- [x] `bitcoin`
  - [x] `Bitcoin, BTC ETF flows, regulation, institutional demand`

#### 질의 실패 / 약한 결과 규칙

- [x] 메인 질의에서 `trust_tier >= tier_2` 결과가 2건 미만이면 재질의를 실행한다.
- [x] 재질의 뒤에도 토픽 결과가 1건 미만이면 legacy fallback 후보에 넘긴다.
- [x] 토픽별 최종 후보는 최대 5건으로 제한한다.

### 중복 제거 기준

- [x] 정규화 URL 기준 중복 제거
- [ ] URL이 다르더라도 제목 유사도가 높으면 2차 중복 후보로 본다
- [ ] 같은 도메인 과다 점유를 막기 위해 도메인별 최대 건수를 둔다
- [ ] 같은 사건의 공식 소스가 있으면 2차 기사보다 우선한다

완료 기준:
- [ ] 구현자가 provider, ranking, merge 책임을 분리해서 바로 만들 수 있다
- [ ] 기존 `news.py`를 분해할 기준이 문서에 있다

## Phase 3. 숫자 데이터 표준화

- [ ] FRED 유지 항목을 명시한다
- [ ] Alpha Vantage 유지 항목을 명시한다
- [ ] ETF 공식 페이지 유지 항목을 명시한다
- [ ] Alternative.me Fear & Greed를 기본값으로 추가한다고 적는다
- [ ] CNN Fear & Greed는 필수 의존성에서 제외한다고 적는다
- [ ] 숫자 데이터 누락 시 fallback 우선순위를 적는다

### 숫자 소스 유지 항목

- [ ] FRED
  - [ ] 미국 금리
  - [ ] 미국 국채
  - [ ] 달러
  - [ ] VIX
- [ ] Alpha Vantage
  - [ ] 미국 기술주 일봉
  - [ ] ETF 프록시 지수 일봉
  - [ ] BTC ETF 일봉과 거래량
- [ ] ETF 공식 페이지
  - [ ] 보유량
  - [ ] AUM
  - [ ] 순유입 / 순유출
- [ ] Alternative.me
  - [ ] BTC 공포탐욕지수

### 숫자 fallback 우선순위

- [ ] 금리 / VIX / 달러: `FRED -> 기존 fallback`
- [ ] 미국 주식 / ETF 일봉: `Alpha Vantage -> 기존 fallback`
- [ ] BTC ETF 보유량 / 순유입: `공식 발행사 페이지 -> 마지막 스냅샷 유지`
- [ ] BTC 공포탐욕: `Alternative.me -> 없음으로 처리`

완료 기준:
- [ ] 숫자 데이터는 “LLM이 아닌 원본 API/공식 페이지” 원칙이 문서에 분명히 적혀 있다

## Phase 4. OpenAI 최종 처리 정리

- [ ] OpenAI 역할을 생성 / 검수 / 재작성으로 고정한다
- [ ] Perplexity 결과를 OpenAI가 다시 사실 수집하지 않도록 적는다
- [ ] 현재 validator / rewrite 흐름을 유지하되, 입력 provenance를 더 넣도록 적는다
- [ ] 브리핑 프롬프트에 `source confidence`, `provider`, `citations`를 포함하도록 계획한다

### OpenAI 입력 정책 고정

- [ ] OpenAI는 Perplexity에서 받은 `ResearchItem`만 입력으로 받는다.
- [ ] OpenAI는 검색 도구를 호출하지 않는다.
- [ ] OpenAI는 숫자 원본 API를 직접 호출하지 않는다.
- [ ] OpenAI의 역할은 아래로 한정한다.
  - [ ] 기사 중요도 반영
  - [ ] 쉬운 한국어 설명
  - [ ] 숫자와 해석 일치 검수
  - [ ] 필요 시 1회 재작성
- [ ] `why_it_matters`가 비어 있으면 OpenAI가 새 사실을 만들지 말고, 기존 `summary`와 `citations`만 바탕으로 짧게 정리한다.

### OpenAI 입력 보강 항목

- [ ] 뉴스별 `provider`
- [ ] 뉴스별 `trust_tier`
- [ ] 뉴스별 `domain`
- [ ] 뉴스별 `citations`
- [ ] Perplexity 요약과 `why_it_matters`
- [ ] 품질 상태(`ok`, `degraded`, `critical`)

완료 기준:
- [ ] OpenAI가 최종 편집자 역할이라는 점이 문서에서 분명하다
- [ ] OpenAI는 숫자 원본 수집을 하지 않는다고 적혀 있다

## Phase 5. 품질 게이트

- [ ] 뉴스 최소 기준을 수치로 정의한다
- [ ] 숫자 데이터 최소 기준을 수치로 정의한다
- [ ] 미달 시 발송 정책을 정의한다
- [ ] degraded / critical 기준을 업데이트한다고 적는다

### 기본 품질 기준

- [ ] 최종 뉴스 4건 이상
- [ ] 도메인 3개 이상
- [ ] 상위 신뢰 출처 또는 공식 소스 2건 이상
- [ ] 24시간 내 기사 2건 이상
- [ ] 숫자 누락률이 임계치 이하

### 미달 시 정책

- [ ] 1차: Perplexity 재질의 또는 legacy fallback
- [ ] 2차: 경고 제목 또는 발송 보류 검토
- [ ] `degraded`는 보내되 강한 품질 경고를 붙인다
- [ ] `critical`은 저장은 하되 이메일 발송은 하지 않는다

### 발송 정책 고정

- [ ] `ok`: 저장 + 이메일 발송
- [ ] `degraded`: 저장 + 경고 문구 포함 이메일 발송
- [ ] `critical`: 저장만 하고 이메일 발송은 건너뛴다
- [ ] `critical`에서 스케줄 작업은 실패 처리하지 않고, 로그와 아티팩트로만 남긴다

완료 기준:
- [ ] 구현자가 품질 기준을 바로 코드화할 수 있다

## Phase 6. 코드 정리

- [ ] `src/morning_brief/data/news.py`를 책임 분리 대상으로 적는다
- [ ] `src/morning_brief/data/market.py`를 공급자 선택 / 포맷 변환 분리 대상으로 적는다
- [ ] `pipeline.py`는 오케스트레이션만 남긴다고 적는다
- [ ] legacy provider 제거 순서를 적는다

### 기본 구조

- [ ] `src/morning_brief/data/sources/perplexity_search.py`
- [ ] `src/morning_brief/data/news.py` 는 facade / orchestrator로 유지
- [ ] `src/morning_brief/data/news_ranking.py`
- [ ] `src/morning_brief/data/news_quality.py`
- [ ] `src/morning_brief/data/news_merge.py`
- [ ] `src/morning_brief/models.py` 확장으로 스키마 추가

### 분리 기준

- [ ] 수집
- [ ] 병합
- [ ] 랭킹
- [ ] 품질 판정
- [ ] 브리핑 생성
- [ ] 메일 발송

### legacy provider 제거 순서

- [ ] 1차: GDELT 메인 경로 제거
- [ ] 2차: Google News RSS 메인 경로 제거
- [ ] 3차: OpenAI `web_search` 뉴스 보강을 보조 경로로 축소
- [ ] 4차: 남은 legacy fallback 최소화

완료 기준:
- [ ] 구현 중 구조 결정을 다시 하지 않아도 된다

## Phase 7. 테스트와 컷오버

- [ ] provider 단위 테스트
- [ ] merge / ranking 테스트
- [ ] 품질 게이트 테스트
- [ ] 브리핑 생성 / 검수 테스트
- [ ] dry-run 검증
- [ ] staged rollout 체크리스트
- [ ] legacy fallback 제거 조건

### 컷오버 기본 순서

- [ ] 1차: Perplexity provider 추가, legacy 병행
- [ ] 2차: 품질 비교 로그 수집
- [ ] 3차: Perplexity 메인 승격
- [ ] 4차: legacy fallback 축소
- [ ] 5차: 필요 없는 무료 수집원 정리

완료 기준:
- [ ] “언제 기존 소스를 끄는지”까지 문서에 있다

### 메인 승격 기준

- [ ] 최근 7회 성공 실행을 기준으로 판단한다
- [ ] 아래 조건을 모두 만족하면 Perplexity를 메인으로 승격한다
  - [ ] `critical`이 0회
  - [ ] `degraded` 횟수가 legacy 단독 대비 같거나 더 적음
  - [ ] 최종 뉴스 수 평균이 4건 이상
  - [ ] 고유 도메인 수 평균이 3개 이상
  - [ ] `official` 또는 `tier_1` 기사 2건 이상인 날이 7회 중 5회 이상
- [ ] 위 조건을 못 채우면 legacy fallback을 메인에서 완전히 제거하지 않는다

## 테스트 계획

- [ ] Perplexity 응답이 비어 있을 때 공식 / legacy fallback이 정상 동작하는지
- [ ] 동일 기사 URL / 제목이 중복 제거되는지
- [ ] 상위 도메인 우선순위가 의도대로 적용되는지
- [ ] 24시간 최신성 기준이 맞는지
- [ ] 숫자 데이터 누락 시 품질 상태가 올바르게 내려가는지
- [ ] OpenAI validator가 어려운 금융 용어를 다시 잡아내는지
- [ ] 메일 발송 전 품질 게이트가 기대대로 작동하는지

## Assumptions / Defaults

- [ ] 기본 방향은 **`Perplexity + OpenAI`** 이다
- [ ] Grok은 이번 문서 범위에서 구현 대상이 아니라 **향후 보조 레이어 후보**로만 한 줄 언급한다
- [ ] `docs/` 디렉토리는 새로 만든다
- [ ] 현재 무료 뉴스 소스는 당장 완전 삭제하지 않고, **비상 fallback**으로 남긴다
- [ ] 숫자 데이터는 LLM으로 대체하지 않는다
- [ ] 비용 최적화보다 **신뢰성 우선**을 기본값으로 둔다
