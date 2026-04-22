# Implementation Plan: FinBERT Sentiment

## Overview

Req 12의 Phase 정의에 따라 Phase A → B → C 순서로 구현한다. 각 Phase는 독립 배포 가능하며, Phase 경계마다 `make check` 통과를 확인한다.

## Tasks

### Phase A: 영문 원본 보존

- [x]   1. `public_site.py` — 뉴스 영문 원본 보존
    - [x] 1.1 `_news_items_v2()`에 `rawSummary` 필드 추가
        - **주의:** `summaryKo` 변수는 `_best_korean_text()`로 한국어 우선 선택된 값이므로 영문 원본이 아님
        - 소스는 `item["summary"]` (NewsPacketItem의 영문 원본 summary 필드)를 사용
        - `item["summary"]`가 비어있지 않고 `_contains_korean(item["summary"])`이 False일 때 원본 저장, 그 외 `None`
        - 기존 `rawTitle` 패턴(`public_site.py:1206`) 동일 방식
        - _Requirements: 6.1_
    - [x] 1.2 `_news_items_v2()`에 `rawInterpretation` 필드 추가
        - **주의:** `interpretation_ko` 변수도 `_best_korean_text()`로 한국어 우선 선택된 값
        - 소스는 `item["why_it_matters"]` (NewsPacketItem의 영문 원본 필드)를 사용
        - `item["why_it_matters"]`가 비어있지 않고 `_contains_korean(item["why_it_matters"])`이 False일 때 원본 저장
        - _Requirements: 6.2_
    - [x] 1.3 `_apply_public_translation()`에서 번역 시 `rawSummary`/`rawInterpretation` 보존 로직 추가
        - 현재 `summaryKo`(line 1343)와 `interpretation`(line 1344-1347)은 번역 시 **단순 덮어쓰기** — rawX 보존 패턴 없음
        - `rawTitle` 보존 패턴(`public_site.py:1338-1341`)을 참고하여 동일하게 추가:
            - `rawSummary`: 번역 전 `summaryKo` 원본이 있고, `rawSummary`가 미설정이고, 번역값과 다르면 저장
            - `rawInterpretation`: 번역 전 `interpretation` 원본이 있고, `rawInterpretation`이 미설정이고, 번역값과 다르면 저장
        - _Requirements: 6.1, 6.2, 6.5_

- [x]   2. `public_site.py` — 토픽 요약 영문 원본 보존
    - [x] 2.1 `_topic_summaries()`(line 788-821)에 `rawSummary` 필드 추가
        - **주의:** 실제 코드(line 800-803)에서 `summary`는 `market_implication or summary_text` (or 선택, 결합이 아님)
        - `rawSummary`의 소스: 현재 `summary` 변수에 들어가는 값 (= `market_implication` 우선, 없으면 `summary_text`)의 영문 원본
        - `_contains_korean(summary)`이 False일 때 원본 저장, 그 외 `None`
        - _Requirements: 6.3_

- [x]   3. `schema/brief.types.ts` — Phase A 스키마 업데이트
    - [x] 3.1 `NewsItem` 인터페이스에 `rawSummary: string | null`, `rawInterpretation: string | null` 추가
        - _Requirements: 6.4_
    - [x] 3.2 `TopicSummary` 인터페이스에 `rawSummary: string | null` 추가
        - _Requirements: 6.4_

- [x]   4. Phase A 테스트
    - [x] 4.1 `tests/test_public_site.py`에 영문 원본 보존 테스트 추가
        - 영문 입력 → `rawSummary`/`rawInterpretation` 값 존재 확인
        - 한국어 입력 → `null` 확인 (`_contains_korean` 동작)
        - 번역 후에도 원본 보존 확인
        - _Requirements: 6.1, 6.2, 6.3, 6.5_
    - [x] 4.2 프론트엔드 `npm run lint` 통과 확인 — TS 스키마 추가만이므로 lint 대상 아님
        - _Requirements: 6.4_

- [x]   5. Checkpoint A — `make check` + 기존 테스트 전체 통과 (557 passed, mypy success)
    - 기존 브리핑 JSON 출력에 `rawSummary`, `rawInterpretation` 필드만 추가됨을 확인
    - 기존 필드(`rawTitle`, `rawContent`)에 영향 없음 확인

---

### Phase B: FinBERT 통합

#### B-1: 설정 및 의존성

- [x]   6. `config.py` — FinBERT 설정 추가
    - [x] 6.1 `Settings` dataclass에 7개 필드 추가: `finbert_enabled`, `finbert_model`, `finbert_model_revision`, `finbert_model_path`, `finbert_batch_size`, `finbert_bullish_threshold`, `finbert_bearish_threshold`
        - _Requirements: 9.1, 9.2, 10.1, 11.1, 11.4_
    - [x] 6.2 `load_settings()`에 환경변수 로딩 추가
        - `_env_bool("FINBERT_ENABLED", True)`, `_env_bounded_int("FINBERT_BATCH_SIZE", ...)` 등 기존 헬퍼 활용
        - _Requirements: 9.2, 10.1_

- [x]   7. `requirements-ml.txt` 생성
    - [x] 7.1 `transformers>=5.0.0`, `torch>=2.4.0` 기재
        - transformers 5.x는 `torch>=2.4` 필요 — 하한 일치시킴
        - Python 3.11 호환성(CI 기준): 양쪽 모두 ≥3.10 → 충족
        - `requirements.txt`에는 추가하지 않음
        - _Requirements: 4.2_

- [x]   8. Checkpoint B-1 — `make check` 통과 (FinBERT 코드 없이 설정만 추가된 상태)

#### B-2: 데이터 모델 확장

- [x]   9. Python 데이터 모델 확장
    - [x] 9.1 `models.py` — `NewsItem`에 `sentiment_score: float | None = None`, `sentiment_label: str = ""`, `sentiment_confidence: float | None = None` 추가
        - 기존 기본값 필드(`citations`) 뒤에 배치
        - _Requirements: 2.1_
    - [x] 9.2 `grok_x_keyword.py` — `XSignal`에 `sentiment_score: float | None = None`, `sentiment_confidence: float | None = None` 추가
        - 기존 `sentiment: str = "neutral"` 유지, 맨 뒤에 추가
        - _Requirements: 2.2_
    - [x] 9.3 `grok_x_keyword.py` — `x_signals_to_dict()`(line 465-479)에 `sentiment_score`, `sentiment_confidence` 직렬화 추가
        - 현재 `headline, summary, why_it_matters, sentiment, source_handle, posted_at, topic, citations`만 매핑
        - `s.sentiment_score`, `s.sentiment_confidence` 키 추가 필요
        - `pipeline.py`에서 `x_signals_to_dict(x_signals)`로 `packet["x_market_signals"]`에 저장되므로, 직렬화 누락 시 sentiment 정보 소실
        - _Requirements: 2.2, 3.2_
    - [x] 9.4 `news_packet.py` — `NewsPacketItem` TypedDict에 `sentiment_score: float | None`, `sentiment_confidence: float | None` 추가
        - _Requirements: 2.3_
    - [x] 9.5 `news_packet.py` — `news_items_to_packet()`(line 65-95)에서 NewsItem → NewsPacketItem 변환 시 `sentiment_score`, `sentiment_confidence` 매핑 추가
        - 현재 14개 필드만 매핑 중 — `item.sentiment_score`, `item.sentiment_confidence` 추가 필요
        - _Requirements: 2.3_

- [x]   10. 데이터 모델 테스트
    - [x] 10.1 `NewsItem` 기본값 테스트: `sentiment_score=None`, `sentiment_label=""`, `sentiment_confidence=None`
        - _Requirements: 2.1_
    - [x] 10.2 `XSignal` 기본값 테스트: 기존 `sentiment="neutral"` 유지 + 새 필드 `None`
        - _Requirements: 2.2, 5.2_
    - [x] 10.3 `x_signals_to_dict()` 직렬화 테스트: `sentiment_score`/`sentiment_confidence` 키 포함 확인
        - _Requirements: 2.2_
    - [x] 10.4 `NewsPacketItem` 직렬화 테스트: `news_items_to_packet()` 출력에 `sentiment_score`/`sentiment_confidence` 포함 확인
        - _Requirements: 2.3_

- [x]   11. Checkpoint B-2 — `make check` 통과

#### B-3: FinBERT 추론 모듈

- [x]   12. `src/morning_brief/data/finbert_sentiment.py` — 핵심 모듈 생성
    - [x] 12.1 `SentimentResult` dataclass 정의
        - `score: float | None`, `confidence: float | None`, `label: str | None`
        - _Requirements: 1.1, 1.6_
    - [x] 12.2 `_check_deps()` — `transformers`/`torch` import 가능 여부 lazy 체크
        - 전역 `_TORCH_AVAILABLE` 변수, 1회만 체크
        - _Requirements: 4.1, 10.2_
    - [x] 12.3 `FinBertScorer.__init__()` — settings 저장, `_model=None`, `_tokenizer=None`
        - _Requirements: 4.3_
    - [x] 12.4 `FinBertScorer._ensure_loaded()` — lazy 모델 로드
        - `settings.finbert_model_path` 우선, 없으면 HF Hub (`settings.finbert_model` + `revision=settings.finbert_model_revision`)
        - 실패 시 WARNING 1회, `_available=False` 설정
        - _Requirements: 4.3, 11.1, 11.2, 11.3, 11.4_
    - [x] 12.5 `FinBertScorer.combine_fields()` — 필드별 토큰 상한 적용 + 결합
        - `max_tokens_per_field=(64, 224, 224)` 기본값
        - 총합 512토큰 truncation
        - tokenizer 사용하여 토큰 단위 자르기
        - _Requirements: 7.1, 7.2_
    - [x] 12.6 `FinBertScorer.score_texts()` — 배치 추론 구현
        - 빈 문자열/None → `SentimentResult(None, None, None)`
        - `settings.finbert_batch_size` 단위 분할
        - softmax → `P(pos) - P(neg)` = score, `max(P)` = confidence
        - `settings.finbert_bullish_threshold` / `finbert_bearish_threshold` 기반 라벨 매핑
        - 예외 발생 시 WARNING + 전체 None 반환
        - `observer.log_event()` + `observer.phase("finbert")`로 관측성 기록
        - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 7.3, 8.1, 8.2_
    - [x] 12.7 `enrich_news_packet()` — 편의 함수
        - `settings.finbert_enabled` 체크 → False면 "skipped" 반환
        - `_check_deps()` → False면 WARNING 1회 + "skipped" 반환
        - 120건 초과 시 sourceTier + 카테고리 비례 할당 선정 로직
        - 각 item의 `title`, `summary`, `why_it_matters`를 `combine_fields()`로 결합
        - **실 데이터 참고:** `pipeline.py`에서 호출 시점에 `summary`/`why_it_matters`는 번역 전 영문 원본 상태. 단, `summary`/`why_it_matters`가 빈 문자열인 경우도 있으므로 `combine_fields()`는 비어있지 않은 필드만 결합해야 함. 최소 `title`(rawTitle)은 항상 영문 존재 (실 데이터 67/67건 확인)
        - `score_texts()` 호출 후 결과를 각 dict에 `sentiment_score`, `sentiment_confidence` 키로 할당
        - 반환: "ok" | "skipped" | "failed"
        - _Requirements: 3.1, 7.4, 10.1_
    - [x] 12.8 `enrich_x_signals()` — 편의 함수
        - XSignal 슬롯 (전체의 20%, 최대 24건) 적용
        - 각 signal의 `headline`, `summary`, `why_it_matters`를 결합
        - 결과를 `XSignal.sentiment_score`, `XSignal.sentiment_confidence`에 직접 할당
        - _Requirements: 3.2_

- [x]   13. FinBERT 추론 모듈 테스트
    - [x] 13.1 `tests/test_finbert_sentiment.py` — `combine_fields()` 단위 테스트
        - 빈 필드 건너뛰기, 토큰 상한 적용, 512토큰 총합 truncation
        - ML 의존성 불필요 (순수 문자열 처리)
        - _Requirements: 7.1, 7.2_
    - [x] 13.2 `tests/test_finbert_sentiment.py` — 의존성 미설치 시 동작 테스트
        - `_check_deps()` False일 때 `enrich_news_packet()` → "skipped" 반환
        - WARNING 로그 1회만 출력
        - _Requirements: 4.1, 8.2_
    - [x] 13.3 `tests/test_finbert_sentiment.py` — feature flag 테스트
        - `FINBERT_ENABLED=false` 시 enrich 함수가 import 없이 "skipped" 반환
        - _Requirements: 10.1, 10.2_
    - [x] 13.4 `tests/test_finbert_sentiment.py` — 빈 입력 테스트
        - `["", None, ""]` → 모든 결과가 `SentimentResult(None, None, None)`
        - _Requirements: 1.3_
    - [x] 13.5 `tests/test_finbert_sentiment.py` — 120건 초과 선정 로직 테스트
        - 150건 입력 → 120건만 처리, 나머지 None, WARNING 로그
        - sourceTier 우선순위 + 카테고리 비례 할당 검증
        - _Requirements: 7.4_
    - [x] 13.6 `tests/test_finbert_sentiment.py` — 실제 추론 테스트 (ML 의존성 필요)
        - `@pytest.mark.skipif(not _check_deps(), reason="ML deps not installed")`
        - 간단한 영문 금융 텍스트 3건으로 score 범위(-1.0~1.0), confidence 범위(0.0~1.0) 검증
        - "Stock market crashes" → score < 0, "Revenue beats expectations" → score > 0
        - _Requirements: 1.1, 1.5, 1.6_

- [x]   14. Checkpoint B-3 — `make check` 통과 (ML 미설치 환경에서도 통과)

#### B-4: 파이프라인 통합

- [x]   15. `pipeline.py` — FinBERT enrichment 삽입
    - [x] 15.1 `build_news_packet()` 반환 직후(line 120 부근)에 `enrich_news_packet()`, `enrich_x_signals()` 호출 추가
        - `sentiment_status` 반환값을 `public_context["sentiment_status"]`에 저장
        - `observer.phase("finbert")` 컨텍스트 매니저로 감싸기
        - _Requirements: 3.1, 3.2, 3.3, 8.1_
    - [x] 15.2 **`public_context["all_news"]` 경로에도 sentiment 전파 확인**
        - **핵심:** `_news_items_v2()`는 `unified.narrative.news`(= `public_context` 경로)를 읽음
        - `news_packet`(email용)과 `public_context["all_news"]`(public용)는 **별도 리스트**
        - `enrich_news_packet(news_packet)`만으로는 `public_context["all_news"]` 항목에 sentiment가 안 붙음
        - 해결: (A) `public_context["all_news"]` 항목에도 `enrich_news_packet()` 적용, 또는 (B) `_news_items_v2()`에서 `unified` 객체의 news dict에서 sentiment 읽도록 연결
        - 구현 시 `build_news_packet()` 내부에서 `public_context["all_news"]`가 어떤 시점의 snapshot인지 확인 필요
        - _Requirements: 3.1, 3.4_

- [x]   16. 파이프라인 통합 테스트
    - [x] 16.1 `tests/test_pipeline_sentiment.py` — FinBERT 비활성 시 기존 동작 보존
        - `FINBERT_ENABLED=false`로 설정 후 파이프라인 부분 실행
        - 뉴스 수집, packet 생성, quality 평가 등 기존 흐름에 영향 없음 확인
        - 모든 `sentiment_score`가 `None`
        - _Requirements: 3.3, 5.1_
    - [x] 16.2 `tests/test_pipeline_sentiment.py` — `public_context`에 `sentiment_status` 전달 확인
        - _Requirements: 8.3_

- [x]   17. Checkpoint B-4 — `make check` 통과

#### B-5: 출력 및 집계

- [x]   18. `public_site.py` — 감성 점수 출력
    - [x] 18.1 `_news_items_v2()`에 `sentimentScore`, `sentimentConfidence`, `sentimentLabel` 필드 추가
        - `sentimentLabel`은 `_score_to_label()` 헬퍼로 서버에서 계산
        - _Requirements: 3.4, 2.4_
    - [x] 18.2 `_x_signals_v2()`에 `sentimentScore`, `sentimentConfidence`, `sentimentLabel` 필드 추가
        - 기존 `sentiment` 필드(Grok 라벨)는 그대로 유지
        - _Requirements: 3.4, 2.4, 5.2_
    - [x] 18.3 `_score_to_label()` 헬퍼 함수 구현
        - `settings.finbert_bullish_threshold` / `finbert_bearish_threshold` 사용
        - `score=None` → `None` 반환
        - _Requirements: 9.1_

- [x]   19. `public_site.py` — 집계 지표 및 meta
    - [x] 19.1 `_compute_sentiment_aggregate()` 함수 구현
        - null 제외 후 mean, median, std, bullishRatio, bearishRatio, count 계산
        - 유효 0건 → 모든 필드 null, count=0
        - _Requirements: 13.1, 13.2_
    - [x] 19.2 `_compute_sentiment_by_category()` 함수 구현
        - 카테고리별 2건 미만 제외, NewsItem만 대상
        - _Requirements: 13.3_
    - [x] 19.3 `build_public_brief()` 내 `meta` dict에 4개 필드 추가
        - `sentimentStatus`, `newsSentiment`, `signalSentiment`, `sentimentByCategory`
        - _Requirements: 8.3, 13.1_

- [x]   20. `schema/brief.types.ts` — Phase B 스키마 업데이트
    - [x] 20.1 `SentimentAggregate` 인터페이스 신규 생성
        - _Requirements: 13.4_
    - [x] 20.2 `NewsItem`에 `sentimentScore`, `sentimentConfidence`, `sentimentLabel` 추가
        - _Requirements: 2.4_
    - [x] 20.3 `XSignal`에 `sentimentScore`, `sentimentConfidence`, `sentimentLabel` 추가
        - _Requirements: 2.4_
    - [x] 20.4 `BriefMeta`에 `sentimentStatus`, `newsSentiment`, `signalSentiment`, `sentimentByCategory` 추가
        - _Requirements: 8.3, 13.4_

- [x]   21. Phase B 출력/집계 테스트
    - [x] 21.1 `tests/test_public_site.py` — 뉴스 출력에 `sentimentScore`/`sentimentConfidence`/`sentimentLabel` 존재 확인
        - score=None일 때 label=null 확인
        - _Requirements: 3.4, 5.3_
    - [x] 21.2 `tests/test_public_site.py` — X시그널 출력에 감성 필드 존재 + 기존 `sentiment` 필드 유지 확인
        - _Requirements: 3.4, 5.2_
    - [x] 21.3 `tests/test_public_site.py` — 분리 집계 테스트 (`_compute_sentiment_aggregate` 직접 호출)
        - 정상 케이스: 뉴스 5건 score [0.5, -0.4, 0.1, 0.8, -0.2] → mean/median/std/ratio 검증
        - null 포함: 일부 None → 제외 후 계산
        - 전체 null: 0건 → 모든 필드 null, count=0
        - 기존 `test_public_site.py` 패턴(직접 함수 호출, mock 없음)과 일치
        - _Requirements: 13.1, 13.2_
    - [x] 21.4 `tests/test_public_site.py` — 카테고리별 집계 테스트 (`_compute_sentiment_by_category` 직접 호출)
        - macro 3건, bigtech 1건 → macro만 포함, bigtech 제외 (2건 미만)
        - _Requirements: 13.3_
    - [x] 21.5 `tests/test_public_site.py` — `meta.sentimentStatus` 필드 존재 확인
        - "ok" / "skipped" / "failed" 각 케이스
        - _Requirements: 8.3_
    - [x] 21.6 프론트엔드 `npm run lint` 통과 확인
        - _Requirements: 2.4, 13.4_

- [x]   22. 데이터 계약 및 운영 절차 문서화
  - [x] 22.1 `XSignal.sentiment`(Grok 문자열) ≡ `NewsItem.sentiment_label`(FinBERT 문자열) 매핑 관계를 design.md 또는 schema 주석에 명시
    - 두 필드는 동일한 의미(`bullish/bearish/neutral`)이나, 소스가 다름 (Grok LLM vs FinBERT)
    - 기존 호환성을 위해 필드명 통일하지 않는 이유 문서화
    - _Requirements: 2.5_
  - [x] 22.2 모델 버전 업데이트 시 score drift 검증 절차를 `docs/specs/finbert-sentiment/` 또는 로컬 Claude 지침에 문서화
    - 기존 데이터 샘플 최소 50건으로 score drift 검증
    - 평균 절대 편차 ≥ 0.05이면 변경 사유·영향 문서화
    - _Requirements: 11.5_

- [x]   23. Checkpoint B-5 — `make check` + `npm run lint` 통과

---

### Phase C: 검증 및 품질

- [x]   24. 기존 동작 보존 통합 테스트
    - [x] 23.1 기존 테스트 전체 통과 확인 (`make check`)
        - _Requirements: 5.1_
    - [x] 23.2 FinBERT 비활성(`FINBERT_ENABLED=false`) 상태에서 기존 브리핑 JSON 출력 diff 확인
        - 변경: `rawSummary`, `rawInterpretation`, `sentimentScore`(null), `sentimentConfidence`(null), `sentimentLabel`(null), 집계 필드(null) 추가만
        - 기존 필드 값 변경 없음
        - _Requirements: 5.1, 5.2, 5.3, 12.3_
    - [x] 23.3 `XSignal.sentiment`(Grok 라벨) 기존 동작 보존 확인
        - 프론트엔드 렌더링에서 기존 `sentiment` 필드 사용 코드에 영향 없음
        - _Requirements: 5.2_

- [x]   25. Checkpoint C-1 — 기존 동작 보존 확인 완료

- [x]   26. 모델 품질 검증 (ML 의존성 필요)
    - [x] 26.1 실제 브리핑 데이터로 FinBERT 실행
        - `docs/test-datas/` 하위 JSON 6개 파일 활용 (4/1~4/6, 총 뉴스 67건 + 시그널 68건)
        - `rawTitle`(67건), `rawContent`(68건) 영문 텍스트 추출 → FinBERT score 산출
        - **주의:** `summaryKo`/`interpretation`은 전부 한국어 — Phase A 구현 전까지 `rawSummary`/`rawInterpretation`은 미존재. 검증은 현재 가용한 `rawTitle` + `rawContent`로 수행
        - _Requirements: 14.1_
    - [x] 26.2 Grok 라벨 vs FinBERT 라벨 일치율 확인 (≥ 55%)
        - `XSignal.sentiment`(Grok)과 FinBERT `sentiment_label` 비교
        - _Requirements: 14.1_
    - [x] 26.3 부정 키워드 spot check
        - `crash`, `plunge`, `recession`, `default` 포함 텍스트 5건 이상 → score < 0 확인
        - _Requirements: 14.2_
    - [x] 26.4 Score 분포 skewness 확인 (|skewness| ≤ 1.5)
        - _Requirements: 14.3_
    - [x] 26.5 임계값 calibration
        - 기본 임계값(±0.3)이 모델 argmax 라벨과 일치율 ≥ 80% 달성하는지 확인
        - 미달 시 임계값 조정 + 조정 근거 문서화
        - _Requirements: 9.3_
    - [x] 26.6 품질 검증 실패 시 대응
        - AC 1~3 중 하나라도 실패 → 원인 분석, 임계값/입력 전략/모델 재선정 검토
        - `FINBERT_ENABLED=false` 유지
        - _Requirements: 14.4_

- [x]   27. Checkpoint C-2 — 품질 검증 통과, `FINBERT_ENABLED=true` 활성화 가능

- [x]   28. 최종 검증
    - [x] 28.1 `make check` 전체 통과
    - [x] 28.2 `npm run lint` + `npm test` 통과
    - [x] 28.3 `FINBERT_ENABLED=true` 상태에서 `python main.py once --print-brief` 1회 실행, 정상 출력 확인
