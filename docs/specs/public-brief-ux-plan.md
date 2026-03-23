# 공개 브리프 UX/데이터 정리 계획

## 요약

현재 공개 페이지는 데이터는 충분히 보이지만, 원시 브리핑과 원시 시그널이 거의 그대로 노출돼 홈과 상세 역할이 겹치고 영어 원문·dict 문자열·중복 섹션이 그대로 보입니다. 이번 정리는 홈은 요약형, 상세는 전체 발행본으로 역할을 분리하고, 공개용 텍스트 정제 책임을 백엔드 serializer에 두는 것이 핵심입니다.

고정 원칙:

- 홈 `/`은 판단, 브리핑 지도, 핵심 뉴스, 공식 X 시그널 중심의 에디토리얼 흐름으로 축약
- 아카이브 상세 `/archive/[date]`는 전체 본문을 유지하되 공개용으로 정제된 한국어 중심 포맷으로 렌더
- 브랜드명, 티커, 출처명을 제외한 공개 문장은 한국어 우선
- 홈은 뉴스 5건, X 시그널 5건, 전체 본문 미노출
- 데이터 정제는 프론트가 아니라 `src/morning_brief/public_site.py`에서 처리

## 설계도

### 홈 `/`

- 유지:
  - 헤더, 품질 배너, 오늘의 판단
  - 토픽 요약, 핵심 뉴스, 공식 X 시그널
- 제거/축약:
  - `TickerBar`, `StocksBoard`, `BitcoinPanel` 홈 노출 제거
  - `aiJudgment.body` 전체 본문 직접 노출 제거
  - X 시그널 전체 목록 제거
  - 상세와 중복되는 설명 제거
- 최종 구성:
  - 오늘의 판단
  - 토픽 요약 4개
  - 핵심 뉴스 5건
  - 공식 X 시그널 5건
  - `/archive/[date]`로 가는 CTA

### 아카이브 상세 `/archive/[date]`

- 전체 구조 유지
- 본문은 공개용으로 정제된 markdown만 렌더
- 뉴스/X 시그널은 한국어 우선 포맷으로 전체 노출
- 원문 영어는 기본 본문이 아니라 보조 정보나 토글 뒤로 이동

### 아카이브 목록 `/archive`

- 날짜, 발행 시각, headline, 품질 상태 유지
- `displayHeadline`을 사용해 leading `-`, bullet prefix를 제거
- 시간과 품질 톤을 홈과 같은 한국어 톤으로 통일

## 실행 항목

### 1. 공개 데이터 모델 확장

- `schema/brief.types.ts`
  - `meta.displayHeadline`
  - `aiJudgment.summaryLead`
  - `aiJudgment.summarySupport`
  - `news.summaryKo`
  - `news.rawTitle`
  - `xSignals.rawContent`
- `frontend/lib/brief-schema.ts`는 새 필드를 backward-compatible 하게 파싱

### 2. 백엔드 공개 serializer 정제

- `src/morning_brief/public_site.py`
  - `displayHeadline` 생성
  - `summaryLead`, `summarySupport` 추출
  - `aiJudgment.body`에서 중복 소제목, dict literal, 기계적 리스트 문자열 제거
  - 뉴스는 `summaryKo`와 한국어 `interpretation` 우선 생성
  - X 시그널은 한국어 `content`, `impact` 우선 생성
  - 영어 원문은 `rawTitle`, `rawContent`로 분리

### 3. 홈 리팩터

- `frontend/app/page.tsx`
  - `TickerBar`, `StocksBoard`, `BitcoinPanel` 제거
  - `JudgmentBlock`은 홈에서 리드 스토리형 variant 사용
  - `TopicGrid`는 홈에서 에디토리얼 variant 사용
  - `NewsFeed`는 5건만 렌더
  - `XSignals`는 사이드바가 아니라 선형 섹션으로 5건만 렌더
  - 전체 발행본 CTA 추가

### 4. 상세/아카이브 정리

- `frontend/app/archive/[date]/page.tsx`
  - 전체 본문 유지
  - `NewsFeed`는 `showRawTitle`
  - `XSignals`는 `showRawToggle`
- `frontend/app/archive/page.tsx`
  - `displayHeadline` 사용

### 5. UX 톤 정리

- 홈은 빠르게 읽는 공개 브리프
- 상세는 전체 발행본
- 영어 원문은 보조 층위로만 노출
- 한국어 UI 문장과 CTA 톤을 우선 유지

## 검증

### 데이터/계약

- `tests/test_public_site.py`
  - `displayHeadline`, `summaryLead`, `summarySupport` 생성 확인
  - 뉴스/X 시그널 한국어 공개 필드 생성 확인
  - 공개 본문에 중복 뉴스 섹션, dict literal이 남지 않는지 확인

### 프론트 렌더링

- 홈:
  - `BriefBody` 미노출
  - 뉴스 5건만 노출
  - X 시그널 5건만 노출
  - CTA가 `/archive/[date]`로 연결
- 상세:
  - 전체 본문 표시
  - 전체 뉴스/시그널 표시
  - 원문은 토글/보조 문구 뒤로 이동

### Playwright

- 대상:
  - `/`
  - `/archive`
  - `/archive/[date]`
- 뷰포트:
  - `390`, `768`, `1440`, `1920`
- 확인:
  - overflow 없음
  - 콘솔 에러 없음
  - 홈의 정보 반복 감소
  - 영어 원문이 홈 메인 본문에 직접 노출되지 않음
  - 아카이브 상세에서만 전체 정보 접근 가능
