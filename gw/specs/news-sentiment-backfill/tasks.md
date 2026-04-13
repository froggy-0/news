# Implementation Plan: news-sentiment-backfill

## Overview

`scripts/backfill/` 패키지와 CLI 진입점(`scripts/backfill_news_sentiment.py`)을 신규 생성하고, `sources/binance.py`의 ValueError 가드를 페이지네이션 루프로 교체한다. 의존성 순서: 공유 dataclass → CoinDesk 수집기 → Alpaca 수집기 → 병합기 → FinBERT 스코어러 → R2 업로더 → 리포터 → CLI 진입점 → Binance 수정. 각 구현 태스크 직후에 테스트를 배치하고, 3~5개 태스크마다 Checkpoint를 삽입한다.

완료 일시: 2026-04-13

---

## Tasks

- [x] 1. 패키지 스캐폴드 및 공유 데이터 모델 구현
  - [x] 1.1 패키지 초기화 파일 생성
    - `scripts/backfill/__init__.py` 빈 파일 생성
    - `scripts/backfill/sources/__init__.py` 빈 파일 생성
    - `tests/backfill/__init__.py` 빈 파일 생성 (pytest 패키지 인식 필수)
    - _Requirements: 10.1_
  - [x] 1.2 `RawArticle` dataclass 구현
    - 파일: `scripts/backfill/sources/coindesk.py` 상단에 정의 (두 수집기 모두 import)
    - 필드: `source: Literal["coindesk", "alpaca"]`, `article_id: str`, `date: str`, `title: str`, `body: str`, `published_ts: int`
    - `date` 필드는 UTC 기준 `YYYY-MM-DD` 문자열임을 docstring에 명시
    - _Requirements: 10.1_
  - [x] 1.3 `DailyAggregate` dataclass 구현
    - 파일: `scripts/backfill/scorer.py`에 정의
    - 필드: `date: str`, `mean: float | None`, `std: float | None`, `count: int`, `status: Literal["ok", "degraded", "skipped"]`, `coindesk_count: int`, `alpaca_count: int`
    - `std` 주의사항 주석: `count < 2`이면 `std=None` (numpy.std([x], ddof=1)=NaN → None 변환 필요)
    - _Requirements: 4.5, 4.6, 5.1, 5.2, 5.3_

- [x] 2. CoinDesk 수집기 구현
  - [x] 2.1 `fetch_coindesk_articles()` 함수 구현
    - 파일: `scripts/backfill/sources/coindesk.py`
    - `BASE_URL = "https://data-api.coindesk.com/news/v1/article/list"` 상수 정의
    - 파라미터: `lang=EN`, `categories=BTC`, `limit=50`, `to_ts={cursor}`
    - 인증 헤더 없음 (무인증)
    - `to_ts` 커서: `end_date`를 Unix timestamp로 변환하여 초기 커서로 사용
    - _Requirements: 1.1_
  - [x] 2.2 역방향 페이지네이션 루프 구현
    - 종료 조건 1: `Data` 배열이 빈 리스트
    - 종료 조건 2: 배치에 `start_ts` 이전 기사가 하나라도 포함된 경우
    - 다음 커서: `min(PUBLISHED_ON) - 1` (to_ts inclusive이므로 -1 필수)
    - 루프 종료 후 `start_ts` 이전 기사 필터링
    - 동일 `ID` 중복 제거: `seen_ids: set[str]` 사용
    - _Requirements: 1.2, 1.4_
  - [x] 2.3 날짜 변환 및 필드 추출 구현
    - `PUBLISHED_ON`(Unix timestamp) → `datetime.fromtimestamp(ts, tz=timezone.utc)` → UTC `YYYY-MM-DD`
    - `BODY` null/빈 문자열이면 `body=""` 설정
    - 호출 간 `time.sleep(delay_seconds)` 적용 (기본값 0.3초)
    - _Requirements: 1.3, 1.7_
  - [x] 2.4 재시도 및 에러 핸들링 구현
    - `429` 응답: 지수 백오프 3회 재시도 (2s → 4s → 8s)
    - `404`: 재시도 없이 즉시 skip
    - 3회 재시도 후 실패 시: `WARNING` 로그 (`event=page.skip | source=coindesk | cursor={} | reason={}`) 출력 후 다음 커서 진행
    - _Requirements: 1.5, 1.6_
  - [x] 2.5 CoinDesk 수집기 단위 테스트 작성
    - 파일: `tests/backfill/test_coindesk.py`
    - _Requirements: 1.2, 1.3, 1.4_

- [x] 3. Checkpoint — CoinDesk 테스트 통과 확인 ✅

- [x] 4. Alpaca 수집기 구현
  - [x] 4.1 `fetch_alpaca_articles()` 함수 구현
    - 파일: `scripts/backfill/sources/alpaca.py`
    - _Requirements: 2.1_
  - [x] 4.2 `next_page_token` 페이지네이션 구현
    - _Requirements: 2.2_
  - [x] 4.3 날짜 변환 및 필드 추출 구현
    - _Requirements: 2.3, 2.6_
  - [x] 4.4 Alpaca 자격증명 누락 처리 구현
    - _Requirements: 2.4, 2.5_
  - [x] 4.5 Alpaca 수집기 단위 테스트 작성
    - 파일: `tests/backfill/test_alpaca.py`
    - _Requirements: 2.2, 2.3, 2.4_

- [x] 5. 소스 병합기 구현
  - [x] 5.1 `merge_articles()` 함수 구현
    - _Requirements: 3.1, 3.2_
  - [x] 5.2 병합 완료 로그 구현
    - _Requirements: 3.3_
  - [x] 5.3 병합기 단위 테스트 작성
    - 파일: `tests/backfill/test_merge.py`
    - _Requirements: 3.1, 3.2_

- [x] 6. Checkpoint — 수집·병합 파이프라인 통합 확인 ✅

- [x] 7. FinBERT 스코어러 및 집계기 구현
  - [x] 7.1 FinBERT import 및 단일 인스턴스 초기화 구현
    - _Requirements: 4.1, 4.7, 4.8_
  - [x] 7.2 전체 일괄 배치 추론 구현
    - _Requirements: 4.2, 4.3, 4.4_
  - [x] 7.3 날짜별 집계 및 `sentimentStatus` 결정 구현
    - _Requirements: 4.5, 4.6, 5.1, 5.2, 5.3_
  - [x] 7.4 스코어러 단위 테스트 작성
    - 파일: `tests/backfill/test_scorer.py`
    - _Requirements: 4.1, 4.5, 4.6, 5.1, 5.2, 5.3_

- [x] 8. Checkpoint — FinBERT 스코어러 통과 확인 ✅

- [x] 9. R2 업로더 구현
  - [x] 9.1 최소 브리프 JSON 빌더 구현
    - _Requirements: 5.4, 6.1_
  - [x] 9.2 boto3 S3 호환 클라이언트 설정 구현
    - _Requirements: 6.2_
  - [x] 9.3 파일 존재 확인 및 보호 로직 구현
    - _Requirements: 6.2, 6.3, 6.4_
  - [x] 9.4 업로드 실행 및 병렬화 구현
    - _Requirements: 6.5, 6.6, 6.7_
  - [x] 9.5 업로더 단위 테스트 작성
    - 파일: `tests/backfill/test_uploader.py`
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.6_

- [x] 10. Checkpoint — 업로더 테스트 통과 확인 ✅

- [x] 11. 리포터 구현
  - [x] 11.1 날짜별 진행 로그 구현
    - _Requirements: 9.1_
  - [x] 11.2 dry-run 커버리지 리포트 구현
    - _Requirements: 9.2_
  - [x] 11.3 최종 완료 요약 구현
    - _Requirements: 9.3, 9.4_

- [x] 12. CLI 진입점 구현
  - [x] 12.1 argparse 인수 파싱 구현
    - _Requirements: 8.1, 8.2_
  - [x] 12.2 환경변수 검증 구현
    - _Requirements: 8.3, 8.4_
  - [x] 12.3 `main()` 오케스트레이션 구현
    - 실행 순서: 수집 → 병합 → FinBERT(always) → dry-run 분기 → 업로드 → 요약
    - _Requirements: 8.3, 9.2, 9.3, 10.1, 10.4_
  - [x] 12.4 파이프라인 독립성 확인
    - _Requirements: 10.1, 10.2_

- [x] 13. Checkpoint — CLI 진입점 동작 확인 ✅

- [x] 14. Binance 페이지네이션 수정
  - [x] 14.1 ValueError 가드 제거 및 페이지네이션 로직 추가
    - `_call_klines()` 헬퍼 추출, `total_days ≤ 1000`: 단발 호출, `> 1000`: while 루프
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [x] 14.2 Binance 수정 회귀 테스트 작성
    - 파일: `tests/analysis/test_sentiment_join/test_binance.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 15. Checkpoint — Binance 수정 회귀 확인 ✅ (12 tests passed)

- [x] 16. 전체 통합 검증
  - [x] 16.1 전체 백필 테스트 스위트 실행 ✅ (50 tests passed)
  - [x] 16.2 make check 통과 확인 ✅ (809 passed, fmt/lint/typecheck all green)
  - [x] 16.3 dry-run 실제 동작 확인 ✅ (2026-04-13 실행 확인)
    - `./.venv/bin/python scripts/backfill_news_sentiment.py --start 2026-04-10 --end 2026-04-13 --dry-run --skip-alpaca`

- [x] 17. Checkpoint — 최종 완료 ✅
