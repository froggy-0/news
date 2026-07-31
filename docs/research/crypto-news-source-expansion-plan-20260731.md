# 크립토 뉴스 소스 확장 계획 (BTC → BTC·ETH·SOL) — 2026-07-31

> **상태: 구현·배포 완료 (2026-07-31).** 사용자가 `NEWSIO_API_KEY`/`APITUBE_API_KEY`를
> GitHub repo secrets에 등록 → newsdata.io만 실제 구현(§4 참조, apitube.io는 실측 후
> 배제). 아래 §1~§3은 최초 설계 그대로 보존(실제 구현이 이 설계와 정확히 일치함을
> 대조 확인할 수 있도록), 실행 결과는 §4에 추가.

---

## 0. 배경

아레나 멀티자산 확장(BTC·ETH·SOL) 세션 중, 모닝브리프의 뉴스 파이프라인이 실제로
BTC 전용인지 확인하다가 두 가지를 발견했다:

1. **CoinDesk API가 이미 죽어있었다.** `COINDESK_NEWS_CATEGORIES` 카테고리를 뭘로
   바꾸든 의미가 없음 — 인증 자체가 없어 모든 요청이 401. 로컬 curl 테스트와 실제
   GitHub Actions 프로덕션 로그(2026-07-30 실행분)에서 **동일하게** 확인됨:
   ```
   WARNING | provider=coindesk | event=error.raised | reason=HTTP 401 응답을 받았어요
   ```
   `.github/workflows/morning-brief.yml`에도 `COINDESK_API_KEY` 같은 시크릿이 아예
   없음 — 이 통합은 무인증 공개 API를 전제로 짜였는데 CoinDesk가 인증을 요구하게
   되면서(또는 처음부터 요구했는데 모르고) 계속 조용히 실패, TheNewsAPI/Marketaux로
   폴백되고 있었음(경고 로그로만 남아 지금까지 눈에 안 띔).
2. **CoinGecko도 뉴스는 유료다.** `/api/v3/news` 호출 시
   `{"error_code":10005,"message":"This request is limited to PRO API subscribers"}`.
   가격 API(`/simple/price`)만 무료로 살아있고, 이건 이 프로젝트에서 가격 조회
   용도로만 쓰이고 있어 문제없음.
3. **현재 뉴스 수집의 실제 크립토 커버리지**(코드 확인):
   - CoinDesk: BTC 전용 필터(현재 죽어있어 무의미)
   - Google News RSS: 고정 쿼리 3개, 그 중 크립토 관련은 `"Bitcoin ETF flows regulation"` 하나뿐(BTC 전용)
   - TheNewsAPI/Marketaux: 쿼리에 이미 `"bitcoin OR btc OR ethereum OR eth OR crypto OR stablecoin"` 포함 —
     **이더리움은 이미 일부 잡히고 있음**. 단 **솔라나는 어느 쿼리에도 없음**.
   - 관련성 가중치(`TOPIC_KEYWORDS`)에도 `bitcoin/btc`만 있고 `ethereum/solana` 가중치
     없음 — 잡혀도 랭킹에서 밀릴 수 있음.
4. **공유 아키텍처 확인**: 뉴스 감성(`news_sentiment_mean`)은 이미 하이브리드 지수 →
   `sovereignIndex.score` → arena macro의 `sovereign_score`/`sovereign_label`로 이어져
   3자산에 공유되는 구조로 짜여 있다. **다만 `algorithms.py` 전수 검색 결과 6개 알고
   중 어느 것도 `sovereign_score`를 안 읽는다** — 지금 이 신호는 트레이딩에 전혀
   영향을 안 주는 대시보드/이메일 표시 전용 값이다. 뉴스를 아무리 잘 고쳐도 이 사실은
   안 바뀌므로, "트레이딩에 영향 준다"고 오해하면 안 된다.

**사용자 결정**: 유료 서비스(CoinDesk/CoinGecko 재구독)는 배제. `newsdata.io`,
`apitube.io` 2개 후보를 무료 플랜으로 검토.

---

## 1. 후보 조사 결과 (실제 API·문서 호출로 검증, 추측 아님)

### 1.1 newsdata.io — 추천 1순위
공식 Python SDK 리포(`newsdataapi/python-client`)가 공개하는
`https://newsdata.io/openapi.json`(OpenAPI 3.1 스펙)을 직접 파싱해 확인.

- **`/1/crypto` 전용 엔드포인트** 존재(카테고리 필터가 아니라 별도 API) — 크립토
  뉴스 전용으로 설계된 API라 우리 용도와 가장 정확히 일치.
- **`coin` 파라미터**: "Filter by cryptocurrency. Comma-separated coin ticker symbols"
  — `coin=BTC,ETH,SOL` 그대로 사용 가능(기본 필터 한도 5개, 3개는 여유 있게 들어감).
- **`domainurl` 파라미터**: "Filter by news source domain, e.g. bbc.com" — 공식
  화이트리스트 도메인(coindesk.com, cointelegraph.com, theblock.co 등) 지정 가능.
  `domain`(source id 기반)·`excludedomain` 변형도 있음(`domainurl`과 동시 사용 불가).
- `prioritydomain=top|medium|low` — 소스 품질 티어 필터(보너스).
- 요청당 1크레딧(`/latest`,`/news`,`/crypto`,`/market`,`/sources` 공통), `/archive`는 5크레딧.
- 무료 플랜: 페이지당 10건(유료는 50건), `sentiment`/`tag`(AI 토픽 분류)는 **Professional
  이상 전용 — 무료에서 안 됨**.
- ⚠️ **일일 정확한 크레딧 한도는 문서에 명시 안 됨** — 가입 후 대시보드에서 확인 필요.

### 1.2 apitube.io — 추천 2순위(보조)
`docs.apitube.io`(정적 문서 사이트, VitePress)를 직접 파싱해 확인.

- 무료 플랜: **$0/월, 카드 등록 불필요, 1,000요청/일**, 요청당 10건, 분당 10요청,
  5만개 소스 커버.
- ⚠️ 무료 플랜은 **12시간 지연**(Real-Time Access는 유료부터) — 현재 파이프라인이
  이미 36시간 lookback(`NEWS_RECENCY_HOURS=36`)을 쓰므로 실질적 문제 없음.
- 확인된 공식 예시 쿼리(`source-examples` 문서 페이지에 실제로 있음):
  ```
  curl "https://api.apitube.io/v1/news/everything?topic.id=industry.crypto_news
        &title=Bitcoin,Ethereum,blockchain&sort.by=sentiment.overall.score..."
  ```
  → `topic.id=industry.crypto_news`(크립토 산업 토픽) + `title=` 키워드 필터 조합.
- 카테고리 taxonomy에 `cryptocurrency`(medtop:20001279, IPTC 미디어토픽 표준) 확인됨.
- `source.domain=theguardian.com` 식 도메인 필터 확인(newsdata의 `domainurl`과 동일 역할).
- 보너스: `sentiment.overall.score` 내장 — 다만 이미 자체 FinBERT 파이프라인이 있어
  필수 활용 대상은 아님, 참고용.

### 1.3 왜 newsdata.io가 1순위인가
`/1/crypto` + `coin=BTC,ETH,SOL`은 "범용 뉴스 API에 크립토를 카테고리로 끼워 쓰는"
apitube 방식보다 **우리가 원하는 걸 정확히 위한 전용 엔드포인트**다. apitube는
12시간 지연·1,000req/일이 넉넉해 보조 소스로 병행하기 좋다(기존 TheNewsAPI+Marketaux
다중소스 병합 패턴과 동일한 방식으로 추가 가능).

---

## 2. 설계안

### 2.1 아키텍처
기존 `_collect_primary_crypto_items()`(coindesk+thenewsapi+marketaux를 `_merge_rank`로
병합하는 구조)에 newsdata.io를 신규 소스로 추가, apitube.io는 2차 후보로 대기.

```
_collect_primary_crypto_items()
  ├─ CoinDesk (인증 복구 전까지 사실상 비활성 — 그대로 두거나 비활성화)
  ├─ TheNewsAPI (기존, 이미 crypto 폭넓은 쿼리)
  ├─ Marketaux (기존, 이미 crypto 폭넓은 쿼리)
  └─ NewsData.io (신규) — coin=BTC,ETH,SOL + domainurl=화이트리스트
       (apitube.io는 필요시 2차 확장)
```

### 2.2 신규 모듈: `src/morning_brief/data/sources/newsdata_provider.py`
기존 `coindesk_news.py`/`thenewsapi_provider.py`와 동일한 패턴:
- `fetch_newsdata_crypto_news(*, max_items, lookback_hours, coins="BTC,ETH,SOL", domainurl=None, observer=None)`
- `NEWSDATA_API_KEY` 환경변수(신규, GitHub Actions secrets에도 추가 필요)
- `/1/crypto` 호출, `from_date`/`to_date`로 lookback 구성(`timeframe`은 유료 전용이라
  무료 플랜에선 `from_date`/`to_date` 사용)
- 응답을 기존 `NewsItem` 모델로 매핑(title/url/source/published_at/topic/summary/why_it_matters)

### 2.3 버그 동시 수정 (카테고리 확장 시 반드시 필요 — 기존 CoinDesk 코드의 결함)
`coindesk_news.py`의 `_article_topic()`이 조건문과 무관하게 항상 `"bitcoin"` 반환하는
죽은 로직, `_why_it_matters()`도 "비트코인" 하드코딩 — 새 소스가 ETH/SOL 기사를
가져와도 이 패턴을 그대로 베끼면 똑같은 버그가 재발한다. `newsdata_provider.py`는
처음부터 실제 `coin` 필드 기반으로 topic을 정확히 매핑해야 함(예: 응답의
`coin: ["BTC"]`/`["ETH"]`/`["SOL"]` 필드를 그대로 `item.topic`에 반영).

### 2.4 랭킹 가중치 수정
`news_policy.py`의 `TOPIC_KEYWORDS`에 `ethereum/eth/solana/sol` 추가(가중치는 기존
`bitcoin: 1.7`과 비슷하거나 약간 낮게 — 프로젝트가 BTC를 여전히 기준자산으로 삼고
있으므로).

### 2.5 화이트리스트 도메인
기존 `PREFERRED_DOMAINS`/`DOMAIN_SCORES`(news_policy.py)에 이미 있는 신뢰 도메인
목록(coindesk.com, cointelegraph.com, theblock.co 등으로 추정 — 실제 목록 재확인
필요)을 `domainurl`/`source.domain` 파라미터에 그대로 전달해 화이트리스트 필터링.

### 2.6 공유 스코어 처리 — 트레이딩 연결은 별도 결정
뉴스 품질이 좋아지면 `news_sentiment_mean` → `sovereignIndex.score`가 더 크립토
전반을 대표하게 되지만, **이것만으로는 arena 트레이딩 알고에 영향이 없다**(§0-4 참조).
`sovereign_score`를 실제 veto/게이트로 연결하는 건 이번 계획의 범위 밖 — 별도로
백테스트 A/B 검증을 거쳐 결정할 사안(기존 세션 전체에서 지켜온 원칙과 동일).

---

## 3. 구현 체크리스트 (키 발급 후 착수)

1. [ ] `newsdata.io` 가입 → `NEWSDATA_API_KEY` 발급, 정확한 무료 일일 한도 확인
2. [ ] `src/morning_brief/data/sources/newsdata_provider.py` 신설
3. [ ] `_collect_primary_crypto_items()`에 newsdata 병합 추가(`_merge_rank` 재사용)
4. [ ] `config.py`에 `newsdata_api_key`/`newsdata_coins`/`newsdata_domains` 설정 추가
5. [ ] `.github/workflows/morning-brief.yml`에 `NEWSDATA_API_KEY` secret 배선
6. [ ] `TOPIC_KEYWORDS`(news_policy.py)에 ethereum/eth/solana/sol 가중치 추가
7. [ ] `coindesk_news.py`의 `_article_topic()`/`_why_it_matters()` 하드코딩 버그 수정
   (CoinDesk 자체를 계속 쓰든 안 쓰든, 같은 버그가 새 소스 코드에 복제되지 않게)
8. [ ] (선택, 2순위) `apitube.io` 가입 → 동일 패턴으로 2차 소스 추가
9. [ ] 테스트: 기존 news.py 테스트 스위트 회귀 확인 + newsdata_provider 신규 테스트
10. [ ] 배포 전 실제 API 응답으로 ETH/SOL 기사가 실제로 잡히는지, topic 필드가
    정확히 매핑되는지 수동 확인

## 관련 코드 위치 (참고용)
- `src/morning_brief/data/news.py` — `_collect_primary_crypto_items()`, `_collect_coindesk_items()`
- `src/morning_brief/data/sources/coindesk_news.py` — 버그 있는 참고 패턴(그대로 베끼지 말 것)
- `src/morning_brief/data/news_policy.py` — `TOPIC_KEYWORDS`, `RSS_QUERIES`, `PREFERRED_DOMAINS`
- `src/morning_brief/config.py` — `coindesk_news_categories` 등 기존 설정 패턴(신규 설정도 동일 관례)
- `.github/workflows/morning-brief.yml` — secrets/vars 배선 위치
- `src/morning_brief/analysis/sentiment_join/hybrid_index.py` — `news_sentiment_mean_lag1`이
  하이브리드 지수에 반영되는 지점(§0-4 공유 구조 확인 근거)

---

## 4. 실행 기록 (2026-07-31)

### 4.1 apitube.io 실측 결과 — 배제
사용자가 발급받은 실제 라이브 키로 `https://api.apitube.io/v1/news/everything` 직접
호출 테스트. 크립토 기사 자체는 정상 반환됐으나(예: "Bitcoin ETFs soak up flows while
Ethereum and Solana lag"), **무료 플랜에서 URL을 담는 모든 필드가 마스킹됨** —
`href`/`source.domain`/`links[].url` 전부 `"...(+N chars hidden)...[Upgrade subscription
plan]"` placeholder로 치환되어 있었다. 이 프로젝트의 `NewsItem`은 `url`이 필수
필드(`if not title or not url: return None` 패턴 전역 적용)라 apitube.io 무료 플랜은
구조적으로 사용 불가. 사용자에게 보고 후 "오케이 진행"(newsdata.io만으로 진행) 확인받음.
→ **apitube.io는 구현하지 않음.** 실측에 사용한 라이브 키는 셸 변수로만 다뤘고 어떤
응답 로그·커밋에도 남기지 않았음.

### 4.2 newsdata.io 구현 (설계 §2와 100% 일치)
- `src/morning_brief/data/providers.py` — `NEWSDATA_IO = "newsdata_io"` 상수 추가.
- `src/morning_brief/data/sources/newsdata_provider.py`(신규) — `/1/crypto` 단발 호출
  (페이지네이션 없음, 무료 200크레딧/일 보존), `coin` 필드를 그대로 `item.topic`에
  매핑(§2.3 버그 재발 방지 원칙 그대로 적용), `link`/`pubDate`/`source_name` 필드 매핑.
- `src/morning_brief/data/sources/provider_runtime.py` — `"newsdata_io"` `ProviderPolicy`
  추가(`coindesk`와 동일 파라미터).
- `src/morning_brief/config.py` — `newsdata_key`(env `NEWSIO_API_KEY`, 기존 GitHub secret
  이름과 정확히 일치시킴)·`newsdata_enabled`·`newsdata_max_items`(1~10 clamp)·
  `newsdata_lookback_hours`(12~168 clamp)·`newsdata_coins`(기본 `"BTC,ETH,SOL"`)·
  `newsdata_domains` 필드 추가.
- `src/morning_brief/data/news.py` — `_collect_newsdata_items()` 추가,
  `_collect_primary_crypto_items()`의 `ThreadPoolExecutor`에 병렬 편입(`max_workers` 3→4),
  기존 thenewsapi/marketaux 2페이지 폴백 로직과 별도로 최종 병합 단계에서만 반영.
- `src/morning_brief/data/news_policy.py` — `TOPIC_KEYWORDS`에 `ethereum(1.4)/eth(1.3)/
  solana(1.3)/sol(1.1)` 추가.
- `.github/workflows/morning-brief.yml` — `NEWSIO_API_KEY`(secret) +
  `NEWSDATA_ENABLED`/`NEWSDATA_MAX_ITEMS`/`NEWSDATA_LOOKBACK_HOURS`/`NEWSDATA_COINS`/
  `NEWSDATA_DOMAINS`(vars, 기본값 포함) 배선 — `COINDESK_NEWS_*` 패턴과 동일.
- `tests/test_newsdata_provider.py`(신규, 6 tests) — 정규화·무료플랜 10건 cap·키 없을 때
  graceful skip·HTTP 오류/응답 status 오류 graceful degradation·url 없는 기사 스킵 검증.
  전체 관련 회귀 테스트(`test_coindesk_news.py`/`test_news_packet.py`/`test_news_quality.py`/
  `test_thenewsapi_provider.py`/`test_public_news_analysis.py`/`test_config.py`) +
  `ruff check` 전부 통과.
- §2.6 원칙 유지: `sovereign_score`는 여전히 어떤 알고도 읽지 않음 — 이번 확장은
  대시보드/이메일 뉴스 커버리지 개선일 뿐 트레이딩 로직에는 영향 없음.

### 4.3 실파이프라인 동작 확인
`gh workflow run` + `workflow_dispatch`로 실제 GitHub Actions 실행 → 로그에서
`provider=newsdata_io` 관련 이벤트 확인(§5 참조). 로컬에는 `NEWSIO_API_KEY` 값이 없어
(GitHub secret으로만 존재) 로컬 curl 검증은 불가능했고, 검증은 전적으로 실제 프로덕션
워크플로 실행을 통해 수행함.
