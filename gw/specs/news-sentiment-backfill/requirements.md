# Requirements Document

## Introduction

현재 `sentiment-time-join` 파이프라인은 R2에 저장된 일별 감성 점수(`briefs/{date}.json`)를 소스로 사용하는데, 파이프라인 최초 가동 이전 기간에는 R2에 파일이 존재하지 않아 Granger 인과성 검정에 필요한 최소 180일 이상의 유효 행을 확보할 수 없다. 이 기능은 **CoinDesk Data API**(1차)와 **Alpaca Markets News API**(보완)로 과거 460일치 BTC 관련 뉴스 헤드라인·본문을 수집하고, **FinBERT를 로컬에서 실행**하여 일별 감성 집계값(mean/std/count)을 계산한 뒤, `fetch_r2_sentiment()`가 읽는 최소 스키마 JSON을 R2에 업로드하는 **일회성 로컬 백필 스크립트**(`scripts/backfill_news_sentiment.py`)를 제공한다. Perplexity, Grok, GPT-4 등 유료 API를 일절 사용하지 않으며 추가 비용은 $0이다. 운영 파이프라인 코드는 단 한 줄도 수정하지 않는다.

---

## Glossary

- **백필(Backfill)**: 과거 날짜에 대해 소급하여 데이터를 생성·업로드하는 작업
- **최소 브리프 JSON**: `fetch_r2_sentiment()`가 읽는 `meta.sentimentStatus`, `meta.newsSentiment` 필드만 포함한 경량 JSON — 브리핑 본문·마켓데이터 없음
- **to_ts 커서**: CoinDesk API의 역방향 페이지네이션 포인터 — 현재 배치의 `min(PUBLISHED_ON) - 1`을 다음 호출의 `to_ts`로 사용 (to_ts inclusive 확인됨)
- **날짜 기준**: 모든 날짜는 **UTC** 기준 `YYYY-MM-DD`로 통일한다. `PUBLISHED_ON`(Unix timestamp) 변환 및 R2 파일명(`briefs/{date}.json`) 모두 UTC 기준
- **워밍업 구간**: 롤링 IQR 계산을 위해 수집하되 통계 분석에서 제외되는 초기 30일
- **유효 행**: inner join 후 `news_sentiment_mean`이 non-null인 날짜 — `sentimentStatus`가 `"ok"` 또는 `"degraded"`인 경우(count ≥ 2)에 해당
- **dry-run**: 업로드 없이 날짜별 기사 수와 예상 유효 행 수만 출력하는 검증 모드
- **_backfill 마커**: 파이프라인이 생성한 파일과 구별하기 위해 백필 JSON에만 포함하는 `"_backfill": true` 필드
- **운영코드 패턴 복사**: `finbert_sentiment.py`의 함수 시그니처를 참조하여 백필 스크립트 내에 동등 로직을 독립 구현하는 방식 — import는 허용하나 운영 파일 자체는 수정 금지

---

## Requirements

### Requirement 1: CoinDesk API 뉴스 수집 (1차 소스)

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 엔지니어,
I want CoinDesk Data API로 460일치 BTC 뉴스를 인증 없이 수집하기를,
so that 별도 API 키 발급 없이 즉시 백필을 실행할 수 있다.

#### Acceptance Criteria

1. WHEN CoinDesk 수집기를 실행할 때, THE 수집기 SHALL `https://data-api.coindesk.com/news/v1/article/list?lang=EN&categories=BTC&limit=50&to_ts={cursor}` 엔드포인트를 인증 헤더 없이 호출해야 한다
2. WHEN 페이지를 순회할 때, THE 수집기 SHALL 현재 배치의 `min(PUBLISHED_ON) - 1`을 다음 요청의 `to_ts`로 사용하는 역방향 커서 루프를 실행해야 한다. 루프 종료 조건은 반환된 `Data` 배열이 비어 있거나, 배치에 `start_ts` 이전 기사가 하나라도 포함된 경우이다. 루프 종료 후 `start_ts` 이전 기사는 결과에서 필터링한다
3. WHEN API가 기사를 반환할 때, THE 수집기 SHALL 각 기사에서 `TITLE`과 `BODY` 필드를 추출하고 `PUBLISHED_ON`(Unix timestamp)을 **UTC 기준** `YYYY-MM-DD`로 변환하여 날짜별로 그룹화해야 한다. `BODY`가 null이거나 빈 문자열인 경우 해당 기사는 `title`만으로 FinBERT 입력을 구성한다
4. WHEN 동일한 `ID`의 기사가 여러 페이지에서 중복 반환될 때, THE 수집기 SHALL `ID` 기준으로 중복을 제거하고 한 번만 포함해야 한다
5. WHEN API가 `429`를 반환할 때, THE 수집기 SHALL 최대 3회 지수 백오프(초기 2초, 최대 16초)로 재시도해야 한다. `404`는 재시도하지 않는다
6. WHEN 개별 페이지 호출이 3회 재시도 후에도 실패할 때, THE 수집기 SHALL 해당 페이지를 건너뛰고 `WARNING` 로그(`event=page.skip | source=coindesk | cursor | reason`)를 출력한 뒤 다음 커서로 계속해야 한다. 단일 페이지 실패가 전체 수집을 중단시키지 않는다
7. WHEN 페이지 호출을 반복할 때, THE 수집기 SHALL 호출 간 최소 `0.3`초 지연을 적용해야 한다

---

### Requirement 2: Alpaca Markets News API 수집 (보완 소스)

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 엔지니어,
I want Alpaca API로 Benzinga 기반 BTC 관련 금융 뉴스를 보완 수집하기를,
so that CoinDesk에서 누락된 거시 경제 맥락(금리·달러 강세 등) 기사를 합산하여 일별 기사 수를 늘릴 수 있다.

#### Acceptance Criteria

1. WHEN Alpaca 수집기를 실행할 때, THE 수집기 SHALL `https://data.alpaca.markets/v1beta1/news?symbols=BTC%2FUSD&start={start_date}T00%3A00%3A00Z&end={end_date}T23%3A59%3A59Z&limit=50&sort=desc` 엔드포인트를 `ALPACA_API_KEY_ID`와 `ALPACA_API_SECRET_KEY` 헤더로 호출해야 한다
2. WHEN 페이지를 순회할 때, THE 수집기 SHALL 응답의 `next_page_token` 필드가 non-null인 동안 `page_token={next_page_token}` 파라미터를 추가하여 다음 페이지를 요청해야 한다
3. WHEN API가 기사를 반환할 때, THE 수집기 SHALL `headline`과 `summary` 필드를 추출하고 `created_at`(ISO 8601 UTC)을 **UTC 기준** `YYYY-MM-DD`로 변환하여 날짜별로 그룹화해야 한다. `content` 필드가 non-empty이면 HTML 태그를 제거한 뒤 `summary`를 대체한다
4. WHEN `ALPACA_API_KEY_ID` 또는 `ALPACA_API_SECRET_KEY` 환경변수가 누락된 상태로 실행될 때, THE 수집기 SHALL Alpaca 수집 단계를 건너뛰고 `INFO` 로그(`event=source.skip | source=alpaca | reason=missing_credentials`)를 출력해야 한다. Alpaca 미사용이 전체 스크립트를 실패시키지 않는다
5. WHEN Alpaca API가 `429`를 반환할 때, THE 수집기 SHALL 최대 3회 지수 백오프로 재시도해야 한다
6. WHEN 페이지 호출을 반복할 때, THE 수집기 SHALL 호출 간 최소 `0.2`초 지연을 적용해야 한다

---

### Requirement 3: 소스 병합 및 중복 제거

**카테고리:** 비즈니스 로직/분류/판단

**User Story:**
As a 데이터 엔지니어,
I want CoinDesk와 Alpaca의 기사를 날짜별로 합산하고 중복을 제거하기를,
so that FinBERT 추론 전 동일 기사가 감성 점수에 이중 반영되지 않는다.

#### Acceptance Criteria

1. WHEN 두 소스의 기사를 병합할 때, THE 병합기 SHALL 각 기사에 `source` 필드(`"coindesk"` 또는 `"alpaca"`)를 추가한 뒤 날짜별로 합산해야 한다
2. WHEN 동일 날짜에 두 소스에서 동일한 제목의 기사가 존재할 때, THE 병합기 SHALL `title`의 소문자 정규화 후 정확 일치 기준으로 중복을 제거하고 `coindesk` 기사를 우선 보존해야 한다
3. WHEN 병합이 완료될 때, THE 병합기 SHALL 날짜별 소스별 기사 수를 `INFO` 로그(`event=merge.complete | date | coindesk_count | alpaca_count | total_after_dedup`)로 출력해야 한다

---

### Requirement 4: FinBERT 로컬 감성 추론

**카테고리:** 비즈니스 로직/분류/판단

**User Story:**
As a 데이터 과학자,
I want FinBERT를 로컬에서 배치 실행하여 날짜별 감성 집계값을 계산하기를,
so that 추론 비용 $0으로 감성 점수를 생성할 수 있다.

#### Acceptance Criteria

1. WHEN FinBERT 추론을 실행할 때, THE 추론기 SHALL `src/morning_brief/data/finbert_sentiment.py`의 `build_news_sentiment_text(item)`과 `FinBertScorer().score_texts(texts)` 함수를 직접 import하여 재사용해야 한다. FinBERT 추론 로직을 별도로 재구현하지 않는다. `FinBertScorer` 인스턴스는 스크립트 실행 중 **단 한 번만** 생성하여 모델 가중치 중복 로딩을 방지한다
2. WHEN CoinDesk 기사를 입력으로 전달할 때, THE 추론기 SHALL `TITLE`을 `title` 필드로, `BODY`를 `summary` 필드로 매핑하고 `why_it_matters`는 빈 문자열로 전달해야 한다
3. WHEN Alpaca 기사를 입력으로 전달할 때, THE 추론기 SHALL `headline`을 `title` 필드로, `summary`를 `summary` 필드로 매핑하고 `why_it_matters`는 빈 문자열로 전달해야 한다
4. WHEN 전체 기사를 추론할 때, THE 추론기 SHALL 모든 날짜의 기사를 하나의 리스트로 합산한 뒤 최대 `BACKFILL_FINBERT_BATCH_SIZE`(기본값: `32`)건씩 배치로 처리해야 한다. 날짜별 분리 추론이 아닌 전체 일괄 배치 처리로 GPU 활용률을 최대화한다. 추론 후 결과를 `article_id` 기준으로 날짜별 집계에 매핑한다
5. WHEN 날짜별 추론이 완료될 때, THE 추론기 SHALL 유효한 `score`(non-null)를 가진 기사들의 `mean`, `std`, `count`를 계산해야 한다. `score`가 null인 기사는 집계에서 제외하고 `count`에 포함하지 않는다
6. WHEN 날짜의 유효 기사 수(`count`)가 0일 때, THE 추론기 SHALL 해당 날짜의 `mean`과 `std`를 `NaN`으로, `count`를 `0`으로 설정해야 한다
7. WHEN torch 또는 transformers 패키지가 설치되지 않은 환경에서 실행될 때, THE 스크립트 SHALL `ImportError`를 발생시키고 `pip install -r requirements-ml.txt` 안내 메시지를 출력해야 한다
8. WHEN GPU(CUDA 또는 MPS)가 감지될 때, THE 추론기 SHALL 자동으로 GPU를 사용해야 한다. GPU 미감지 시 CPU로 폴백한다

---

### Requirement 5: sentimentStatus 결정 로직

**카테고리:** 비즈니스 로직/분류/판단

**User Story:**
As a 데이터 엔지니어,
I want 유효 기사 수에 따라 sentimentStatus가 자동 결정되기를,
so that `fetch_r2_sentiment()`가 기존 파이프라인과 동일한 품질 판단 기준으로 데이터를 처리할 수 있다.

#### Acceptance Criteria

1. WHEN 날짜별 유효 기사 수(`count`)가 5 이상일 때, THE 결정기 SHALL `sentimentStatus`를 `"ok"`로 설정해야 한다
2. WHEN 날짜별 유효 기사 수가 2 이상 5 미만일 때, THE 결정기 SHALL `sentimentStatus`를 `"degraded"`로 설정해야 한다
3. WHEN 날짜별 유효 기사 수가 1 이하일 때, THE 결정기 SHALL `sentimentStatus`를 `"skipped"`로 설정해야 한다. `fetch_r2_sentiment()`에서 NaN으로 처리되어 inner join 탈락 대상임을 인식한다
4. WHEN 백필 스크립트가 실행될 때, THE 스크립트 SHALL `signalSentimentStatus`를 항상 `"skipped"`로, `signalSentiment`를 `null`로 설정해야 한다. X 시그널 데이터 없이 생성된 백필이므로 임의 생성하지 않는다

---

### Requirement 6: 최소 브리프 JSON 생성 및 R2 업로드

**카테고리:** 출력/리포트/UI

**User Story:**
As a 데이터 엔지니어,
I want 날짜별 최소 브리프 JSON을 생성하여 R2의 `briefs/{date}.json`에 업로드하기를,
so that 기존 `fetch_r2_sentiment()`가 코드 수정 없이 백필 데이터를 읽을 수 있다.

#### Acceptance Criteria

1. WHEN 날짜별 JSON을 생성할 때, THE 생성기 SHALL 다음 최소 스키마를 준수해야 한다:
   ```json
   {
     "meta": {
       "date": "YYYY-MM-DD",
       "generatedAt": "YYYY-MM-DDT08:00:00+09:00",
       "sentimentStatus": "ok" | "degraded" | "skipped",
       "signalSentimentStatus": "skipped",
       "newsSentiment": {
         "mean": float | null,
         "std": float | null,
         "count": int
       },
       "signalSentiment": null,
       "_backfill": true,
       "_backfillSource": "coindesk+alpaca+finbert",
       "_backfillGeneratedAt": "ISO8601 UTC timestamp"
     }
   }
   ```
   `_backfill: true` 필드를 포함하여 파이프라인 생성 데이터와 구별 가능하게 한다

2. WHEN R2에 업로드하기 전, THE 업로더 SHALL boto3 S3 호환 클라이언트(`R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` 환경변수 사용)로 `HEAD` 요청을 보내 해당 날짜 파일의 존재 여부를 확인해야 한다

3. WHEN 파일이 이미 R2에 존재하고 `--force` 플래그가 없을 때, THE 업로더 SHALL 해당 날짜를 건너뛰고 `INFO` 로그(`event=upload.skip | date | reason=exists`)를 출력해야 한다

4. WHEN `--force` 플래그가 설정된 경우, THE 업로더 SHALL 기존 파일의 `_backfill` 필드를 확인해야 한다. `_backfill: true`인 파일만 덮어쓸 수 있으며, `_backfill` 필드가 없는 파일(파이프라인 생성 원본)은 `--force`에서도 덮어쓰지 않고 `WARNING` 로그(`event=upload.skip | date | reason=pipeline_file_protected`)를 출력해야 한다

5. WHEN R2 업로드가 성공할 때, THE 업로더 SHALL `INFO` 로그(`event=upload.ok | date | status | count`)를 출력해야 한다

6. WHEN R2 업로드가 실패할 때, THE 업로더 SHALL 해당 날짜를 건너뛰고 `WARNING` 로그(`event=upload.fail | date | reason`)를 출력한 뒤 다음 날짜로 계속해야 한다. 단일 날짜 실패가 전체 스크립트를 중단시키지 않는다

7. WHEN `BACKFILL_R2_MAX_CONCURRENCY`(기본값: `5`) 환경변수가 설정된 경우, THE 업로더 SHALL `ThreadPoolExecutor`를 사용하여 해당 수만큼 병렬로 업로드해야 한다

---

### Requirement 7: Binance Spot 페이지네이션 한도 해제

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 엔지니어,
I want `SENTIMENT_JOIN_LOOKBACK_DAYS=460` 이상 설정 시 BTC 종가 수집이 정상 동작하기를,
so that 백필 완료 후 sentiment-join 파이프라인을 460일 lookback으로 실행할 수 있다.

#### Acceptance Criteria

1. WHEN `SENTIMENT_JOIN_LOOKBACK_DAYS`가 1000 이하로 설정될 때, THE BTC 수집기 SHALL 기존과 동일하게 `data-api.binance.vision/api/v3/klines` 단발 호출로 수집해야 한다 (460 < 1000이므로 페이지네이션 불필요, 기존 동작 완전 보존)
2. WHEN 현재 코드의 `if limit > 1000: raise ValueError(...)` 가드를 제거할 때, THE 수집기 SHALL 1000일 이하 기존 동작(단발 호출)은 동일하게 유지해야 한다
3. WHEN `SENTIMENT_JOIN_LOOKBACK_DAYS`가 1000 초과로 설정될 때, THE BTC 수집기 SHALL `startTime` 커서 기반 while 루프로 1000건 단위 페이지네이션을 수행해야 한다. 루프 종료 조건은 응답이 빈 리스트이거나 마지막 캔들의 `open_time`이 `end_ms`를 초과한 경우이다
4. WHEN 페이지네이션 루프를 실행할 때, THE 수집기 SHALL 페이지 간 `time.sleep(0.05)`를 적용하여 Binance 공개 API weight 한도(분당 1200) 내에서 동작해야 한다

---

### Requirement 8: CLI 인터페이스

**카테고리:** 설정/환경

**User Story:**
As a 데이터 엔지니어,
I want 백필 스크립트를 CLI 인수로 제어하기를,
so that 수집 기간·검증 모드·강제 덮어쓰기 여부를 유연하게 지정할 수 있다.

#### Acceptance Criteria

1. WHEN 스크립트를 실행할 때, THE 스크립트 SHALL 다음 CLI 인수를 지원해야 한다:

   | 인수 | 타입 | 기본값 | 설명 |
   |------|------|--------|------|
   | `--start` | `YYYY-MM-DD` | 필수 | 백필 시작 날짜 |
   | `--end` | `YYYY-MM-DD` | 오늘 | 백필 종료 날짜 |
   | `--dry-run` | flag | False | 업로드 없이 커버리지 분석만 출력 |
   | `--force` | flag | False | 기존 백필 파일 덮어쓰기 허용 |
   | `--batch-size` | int | 32 | FinBERT 배치 크기 |
   | `--skip-alpaca` | flag | False | Alpaca 수집 건너뜀 (CoinDesk만 사용) |

2. WHEN `--start`와 `--end` 간격이 460일을 초과할 때, THE 스크립트 SHALL `ValueError("백필 최대 기간 460일 초과")`를 발생시켜야 한다

3. WHEN `--dry-run` 플래그가 설정된 경우, THE 스크립트 SHALL R2 환경변수(`R2_ENDPOINT_URL` 등)를 검증하지 않아야 한다. `ALPACA_API_KEY_ID`도 dry-run에서는 필수가 아니다. dry-run은 수집과 FinBERT 추론까지 실제로 실행하여 정확한 날짜별 status를 확인하되, R2 업로드만 생략한다

4. WHEN 필수 환경변수가 누락된 채 일반 모드로 실행될 때, THE 스크립트 SHALL 누락된 변수명을 모두 열거한 `EnvironmentError`를 발생시켜야 한다:
   - 필수: `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`
   - CoinDesk: 인증 불필요 (항상 시도)
   - Alpaca: `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` 누락 시 Alpaca 단계 건너뜀(오류 아님)

---

### Requirement 9: 진행 상태 출력 및 완료 요약

**카테고리:** 옵저버빌리티

**User Story:**
As a 데이터 엔지니어,
I want 백필 진행 상태와 완료 요약을 실시간으로 확인하기를,
so that 장시간 실행 중 문제 날짜를 즉시 인지하고 완료 후 품질을 검증할 수 있다.

#### Acceptance Criteria

1. WHEN 날짜 단위 처리가 완료될 때, THE 스크립트 SHALL `INFO` 로그(`event=date.processed | date | coindesk_count | alpaca_count | total | status | duration_ms`)를 출력해야 한다

2. WHEN `--dry-run` 모드로 실행될 때, THE 스크립트 SHALL 수집과 FinBERT 추론을 실제로 완전히 실행한 뒤 다음을 포함한 커버리지 리포트를 표준 출력으로 출력해야 한다:
   - 날짜별 실제 기사 수 테이블 (상위 5개·하위 5개, FinBERT 추론 기반 실제 count)
   - `ok` / `degraded` / `skipped` 실제 날짜 수
   - 실제 유효 행 수 및 Granger 검정 충족 여부 (`ok`+`degraded` ≥ 180)
   - 총 수집 기사 수 및 소스별 분포

3. WHEN 스크립트가 정상 종료될 때, THE 스크립트 SHALL 다음을 포함한 최종 요약을 출력해야 한다:
   - 전체 대상 날짜 수
   - 업로드 성공 / 건너뜀(기존 존재) / `skipped_protected`(파이프라인 원본 보호) / 실패 날짜 수
   - `ok` + `degraded` 유효 날짜 수
   - 평균 기사 수/일 (coindesk / alpaca / 합산)
   - 총 소요 시간
   - 다음 실행 안내: `SENTIMENT_JOIN_LOOKBACK_DAYS=460 make sentiment-join` 명령어 출력

4. WHEN 유효 날짜 수(`ok` + `degraded`)가 180 미만일 때, THE 스크립트 SHALL 요약 출력 시 `WARNING: 유효 행 {N}개 — Granger 검정 권장치(180) 미달. CryptoPanic 등 추가 소스를 검토하세요.` 메시지를 출력해야 한다

---

### Requirement 10: 파이프라인 독립성

**카테고리:** 설정/환경

**User Story:**
As a 데이터 엔지니어,
I want 백필 스크립트가 운영 파이프라인 코드를 수정하지 않기를,
so that 백필 실행이 기존 브리핑 발송 파이프라인에 영향을 주지 않는다.

#### Acceptance Criteria

1. WHEN 백필 스크립트를 실행할 때, THE 스크립트 SHALL `pipeline.py`, `main.py`, `emailer.py`, `briefing.py`, `brief_review.py`를 import하지 않아야 한다
2. WHEN 백필 스크립트가 FinBERT를 사용할 때, THE 스크립트 SHALL `src/morning_brief/data/finbert_sentiment.py`의 공개 함수만 import해야 한다. 해당 파일을 수정하지 않는다
3. WHEN Requirement 7(Binance 가드 제거)을 구현할 때, THE 구현 SHALL `src/morning_brief/analysis/sentiment_join/sources/binance.py`만 수정하며, 수정 범위는 `raise ValueError(f"lookback이 klines 단일 요청 한도를 초과합니다...")` 한 줄 제거와 페이지네이션 루프 추가에 한정한다
4. WHEN 백필 스크립트가 실행될 때, THE 스크립트 SHALL `SENTIMENT_JOIN_LOOKBACK_DAYS` 환경변수와 sentiment-join 파이프라인의 실행 여부에 무관하게 독립적으로 동작해야 한다

---

## Non-Functional Requirements

### Requirement 11: 성능

**카테고리:** 성능/확장성

**User Story:**
As a 데이터 엔지니어,
I want 460일 백필이 CPU 환경에서 3시간, GPU 환경에서 1시간 이내에 완료되기를,
so that 로컬 환경에서 일회성 실행이 가능하다.

#### Acceptance Criteria

1. WHEN 460일 백필을 CPU 환경에서 실행할 때, THE 스크립트 SHALL CoinDesk 수집(속도 제한 포함) 약 30분 + FinBERT 추론 약 90분 + R2 업로드 약 5분으로 총 **3시간 이내**에 완료되어야 한다 (일평균 25건 기준: 11,500건 총 처리)
2. WHEN GPU(CUDA/MPS) 환경에서 실행할 때, THE 스크립트 SHALL FinBERT 추론 시간이 약 5~10분으로 단축되어 총 **1시간 이내**에 완료되어야 한다
3. WHEN 460일 × 25건/일 기준 예상 API 호출 수를 계산할 때, THE 수집기 SHALL CoinDesk 230회 + Alpaca 185회로 총 약 415회 호출로 완료되어야 한다 (rate limit 여유 충분)
