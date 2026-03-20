# 구현 계획: 금융 뉴스 데일리 프론트 페이지

## 개요

이 문서는 `docs/specs/requirements.md` 와 `docs/specs/design.md` 를 기준으로, 현재 저장소를 **Vite 프로토타입 + Python 파이프라인** 상태에서 **Next.js 기반 공개 브리핑 프론트 + JSON 계약 + 배포 워크플로우** 상태로 옮기기 위한 구현 체크리스트다.

문서만 읽고 바로 구현할 수 있도록, 단계별 작업 대상과 완료 기준을 고정한다.

이 문서에서 프론트 디자인의 직접 참조 기준은 `/Users/giwon/Downloads/sovereign-brief-terminal` 이다. 단순히 `다크 테마` 정도만 참고하는 것이 아니라, **헤더 위계, ticker rail, terminal 밀도, news feed composition, 정보 여백, hover/scanline 같은 분위기까지 최대한 동일한 인상**을 목표로 한다.

---

## Tasks

- [x] 1. Stage 1: 문서와 계약 기준 정합화
  - [x] 1.1 `schema/brief.types.ts` 신규 생성
    - `BriefIndex`, `BriefData`, `BriefMeta`, `TickerItem`, `TopicSummary`, `TechStock`, `BitcoinSection`, `NewsItem`, `XSignal` 타입 정의
    - `docs/specs/design.md` 의 계약과 1:1로 맞춘다
    - _Requirements: REQ-001, REQ-002, REQ-003, REQ-005, REQ-006, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012_
  - [x] 1.2 파이프라인 packet → 프론트 계약 매핑 문서화
    - 현재 `src/morning_brief` packet 키와 `schema/brief.types.ts` 필드 매핑표를 코드 주석 또는 별도 문서에 남긴다
    - `official_etf_total_btc`, `official_etf_total_aum_usd`, `fear_greed_value`, `fear_greed_label` 같은 현재 실제 필드를 우선 반영한다
    - _Requirements: REQ-008, REQ-011, REQ-012_
  - [x] 1.3 프론트 fixture 초안 추가
    - 최신 브리핑 예시 JSON fixture를 tests 또는 frontend fixture 위치에 추가
    - `ok`, `degraded`, `critical` 예시를 각각 최소 1개 준비
    - _Requirements: REQ-011, REQ-012_

- [x] 2. Stage 1 체크포인트
  - 문서와 타입 계약만 보고 `BriefData` shape 를 설명할 수 있어야 한다
  - fixture 가 계약과 일치해야 한다
  - _검증: 타입 검사 또는 계약 검증 스크립트 실행_

- [x] 3. Stage 2: 프론트 기본 골격 교체
  - [x] 3.1 `frontend/` 를 Next.js App Router 구조로 전환
    - `app/`, `components/`, `lib/`, `public/` 기준으로 재구성
    - Vite 엔트리(`frontend/src/main.tsx`, `frontend/src/App.tsx`) 는 교체 대상으로 표시한다
    - _Requirements: REQ-001, REQ-009, REQ-015_
  - [x] 3.2 프론트 패키지와 빌드 설정 교체
    - `frontend/package.json` 을 Next.js 기준 스크립트로 변경
    - `next.config.*`, `postcss.config.mjs`, `tsconfig.json` 정리
    - 프로토타입 전용 의존성(`@google/genai`, `express`, `dotenv`, Vite 관련 설정`) 제거
    - _Requirements: REQ-015_
  - [x] 3.3 글로벌 스타일과 공통 레이아웃 구성
    - `frontend/app/globals.css`, `layout.tsx` 작성
    - 한국어 중심 다크 테마, 접근성, 반응형 기본값 반영
    - _Requirements: REQ-014, REQ-015_

- [x] 4. Stage 2 체크포인트
  - 메인 페이지와 아카이브 경로가 비어 있어도 라우팅은 동작해야 한다
  - `frontend` 빌드가 가능한 상태여야 한다
  - _검증: `frontend` 개발 서버 실행, 정적 빌드 성공_

- [x] 5. Stage 3: 데이터 계층 구현
  - [x] 5.1 `frontend/lib/r2.ts` 구현
    - `fetchLatest()`, `fetchBriefByDate()`, `fetchIndex()` 작성
    - `latest.json`, 날짜별 JSON, `index.json` 읽기 경로를 고정
    - _Requirements: REQ-001, REQ-009, REQ-013_
  - [x] 5.2 `frontend/lib/brief-schema.ts` 구현
    - runtime validation 함수 작성
    - 필수 필드 누락, 잘못된 품질 상태, 잘못된 날짜 형식 처리
    - _Requirements: REQ-011, REQ-012_
  - [x] 5.3 품질 상태 및 누락값 normalization 구현
    - null 데이터, cached 데이터, 품질 노트, optional 섹션 존재 여부를 프론트 렌더링용으로 정리
    - _Requirements: REQ-011, REQ-012_

- [x] 6. Stage 3 체크포인트
  - fixture 기반으로 `fetch → validate → normalize` 흐름이 동작해야 한다
  - 잘못된 JSON 을 입력했을 때 실패 방식이 일관되어야 한다
  - _검증: 데이터 계층 단위 테스트_

- [x] 7. Stage 4: 메인 페이지 구현
  - [x] 7.1 상단 핵심 수치 영역 구현
    - 주요 지표/자산을 한 줄 티커 또는 스트립 형태로 표시
    - null 값은 상태 문구, cached 값은 별도 표시
    - _Requirements: REQ-002, REQ-012_
  - [x] 7.2 오늘의 판단 + 브리핑 본문 구현
    - 판단 문구, 생성 시각, 본문 마크다운, 품질 경고 표시
    - _Requirements: REQ-003, REQ-011_
  - [x] 7.3 토픽 요약 구현
    - 토픽 카드 4개 영역 구성
    - 없는 토픽은 빈 카드 없이 생략
    - _Requirements: REQ-004_
  - [x] 7.4 뉴스 피드 구현
    - 토픽 필터, 1티어 출처 구분, interpretation 표시
    - 원문 링크 연결
    - _Requirements: REQ-005_
  - [x] 7.5 X 시그널 구현
    - `xSignals === null` 이면 섹션 미노출
    - 시그널 내용, 시장 영향, 센티먼트, 게시 시각 표시
    - _Requirements: REQ-006_
  - [x] 7.6 미국 지수/기술주 보드 구현
    - 대표 지수, 기술주 목록, 등락 방향, cached 표시 구현
    - _Requirements: REQ-007, REQ-012_
  - [x] 7.7 비트코인 섹션 구현
    - BTC 현물, 공포탐욕, 공식 ETF 총 보유량, 총 AUM, 발행사별 공식 스냅샷 표시
    - 신뢰도 낮은 추정치와 stale 값은 사용자에게 노출하지 않음
    - 핵심 BTC 블록은 값이 없어도 상태 문구를 보여줌
    - _Requirements: REQ-008, REQ-012_

- [x] 8. Stage 4 체크포인트
  - 메인 페이지가 `BriefData` 1건으로 완전 렌더링되어야 한다
  - 핵심 블록은 값이 부족해도 사라지지 않아야 한다
  - _검증: 메인 페이지 렌더링 테스트 + 시각 확인_

- [x] 9. Stage 5: 아카이브와 정적 페이지 구현
  - [x] 9.1 `/archive` 구현
    - 날짜 목록 페이지 작성
    - TickerBar 는 넣지 않는다
    - _Requirements: REQ-009_
  - [x] 9.2 `/archive/[date]` 구현
    - 날짜별 상세 브리핑 페이지 작성
    - 메인과 동일한 콘텐츠 구조 유지
    - _Requirements: REQ-009_
  - [x] 9.3 1차 제외 범위 반영
    - `/unsubscribe` 는 실제 처리 페이지를 만들지 않는다
    - 필요하면 “후속 범위” 안내용 플레이스홀더만 둔다
    - _Requirements: REQ-009_

- [x] 10. Stage 5 체크포인트
  - 날짜 목록과 상세 페이지가 정적 경로로 생성되어야 한다
  - `/archive` 는 단순 탐색 페이지여야 하고 메인과 역할이 겹치지 않아야 한다
  - _검증: `generateStaticParams` 및 경로 렌더링 테스트_

- [x] 11. Stage 6: 부가 산출물 구현
  - [x] 11.1 브리핑 Markdown 다운로드 구현
    - 현재 브리핑 본문을 `.md` 파일로 내려받을 수 있어야 한다
    - _Requirements: REQ-010_
  - [x] 11.2 RSS 구현
    - `index.json` 기반 RSS 피드 생성
    - 전체 날짜를 포함한다
    - _Requirements: REQ-010_
  - [x] 11.3 `llms.txt` 구현
    - 서비스 소개, 주요 경로, 업데이트 주기 포함
    - _Requirements: REQ-010_
  - [x] 11.4 페이지 메타데이터 구현
    - 메인/아카이브별 title, description, OG 메타 작성
    - _Requirements: REQ-010, REQ-015_

- [x] 12. Stage 6 체크포인트
  - 다운로드, RSS, `llms.txt`, 메타데이터가 모두 정적으로 동작해야 한다
  - _검증: route 출력 및 메타데이터 테스트_

- [ ] 13. Stage 7: `sovereign-brief-terminal` 디자인 이식
  - [x] 13.1 원본 디자인 구조 감사
    - `/Users/giwon/Downloads/sovereign-brief-terminal/src/App.tsx`
    - `/Users/giwon/Downloads/sovereign-brief-terminal/src/index.css`
    - 위 두 파일을 기준으로 **반드시 유지할 시각 요소**와 **현재 Next 구조에 맞게 치환할 요소**를 분리한다
    - 최소 추출 대상
      - masthead 락업
      - ticker rail
      - serif headline 계층
      - terminal/heatmap 보드 감각
      - news feed composition
      - scanline / glow / hover 언어
    - _Requirements: REQ-001, REQ-014, REQ-015_
  - [x] 13.2 원본 디자인 구현 요소를 그대로 이식할 의존성 확정
    - 원본의 디자인 인상을 결정하는 의존성을 식별하고, Next 구조에 맞게 선별 도입한다
    - 최소 반영 대상
      - `motion`
      - `lucide-react`
      - Google Fonts 기반 `Newsreader`, `Space Grotesk`, `IBM Plex Mono`
    - 가져오지 않을 의존성도 명시한다
      - `@google/genai`
      - `express`
      - `dotenv`
      - `vite`
    - 폰트는 Google Fonts 직접 사용을 기본값으로 한다
    - 배포 환경에서 Google Fonts 접근이 제한될 경우를 대비해, 동일 폰트를 다운로드해 self-host fallback 으로 둘 수 있게 경로와 절차를 함께 남긴다
    - _Requirements: REQ-014, REQ-015_
  - [x] 13.3 디자인 토큰과 타이포그래피를 원본 기준으로 재정렬
    - `frontend/app/globals.css` 를 원본 디자인 언어에 맞게 재구성한다
    - 단순 색상 유사 수준이 아니라 spacing, border density, typography hierarchy 를 원본에 가깝게 맞춘다
    - 원본의 폰트 계층을 그대로 가져간다
      - headline: `Newsreader`
      - label: `Space Grotesk`
      - mono: `IBM Plex Mono`
    - Google Fonts 로딩 방식과 fallback stack 을 실제 코드에 명시한다
    - _Requirements: REQ-014, REQ-015_
  - [x] 13.4 상단 masthead / ticker rail / hero 이식
    - 현재 카드형 헤더를 원본처럼 하나의 연속된 상단 지면으로 바꾼다
    - 상단 핵심 수치는 개별 카드보다 slim rail / strip 구조를 우선한다
    - `오늘의 판단` hero 는 원본의 큰 headline 인상을 유지하면서 실제 `BriefData` 를 바인딩한다
    - 원본의 fixed top ticker, masthead, header metadata 흐름을 가능한 한 그대로 유지한다
    - _Requirements: REQ-002, REQ-003, REQ-013, REQ-014_
  - [x] 13.5 뉴스 피드를 원본 composition 으로 재구성
    - 뉴스를 카드 목록이 아니라 editorial feed 로 재배치한다
    - `출처 → 제목 → 본문 → 시장 의미` 순서를 유지하되, 원본의 시간/우선도/요약 리듬을 최대한 반영한다
    - mock 문구가 아니라 실제 `news[]` 데이터와 `interpretation` 을 사용한다
    - 원본 `NewsItem`의 시각 구조를 직접 참조해 spacing, heading scale, meta row, hover emphasis 를 맞춘다
    - _Requirements: REQ-005, REQ-014_
  - [x] 13.6 시장 / 기술주 / BTC 블록을 terminal board 언어로 통일
    - 현재 분리된 panel 을 원본의 dense terminal grid 감각으로 재구성한다
    - 원본의 `HeatmapCell`, `Sparkline` 과 유사한 컴포넌트를 실제 `BriefData` 구조로 다시 만든다
    - heatmap, sparkline, compact stat cell 은 단순 참고가 아니라 가능한 한 같은 composition 으로 가져간다
    - 핵심 블록의 null/cached 상태 표시는 유지하되, 디자인 인상은 원본과 최대한 가깝게 맞춘다
    - _Requirements: REQ-002, REQ-007, REQ-008, REQ-012, REQ-014_
  - [x] 13.7 모션 / hover / 장식 효과를 실제 구조에 맞게 이식
    - `motion` 기반 진입 애니메이션, hover emphasis, sticky rhythm 을 실제 화면에 반영한다
    - scanline, marquee, glow 같은 원본의 장식 요소를 가능한 한 동일하게 재현한다
    - 단, 정보 전달을 해치지 않아야 하고 모바일 성능을 해치지 않아야 한다
    - _Requirements: REQ-014, REQ-015_
  - [x] 13.8 데이터 바인딩과 디자인 일치 검증
    - 홈, archive, archive detail 모두가 원본과 유사한 인상을 유지하는지 확인한다
    - 디자인 이식 후에도 실제 `BriefData` 기반 섹션 노출/숨김 규칙이 깨지지 않아야 한다
    - _Requirements: REQ-001 ~ REQ-012, REQ-014_

- [x] 14. Stage 7 체크포인트
  - `frontend` 첫 화면이 더 이상 단순 다크 카드 대시보드처럼 보이지 않아야 한다
  - `sovereign-brief-terminal` 과 비교했을 때 정보 위계와 지면 인상이 명확히 유사해야 한다
  - mock 전용 레이아웃이 아니라 실제 `BriefData` 와 품질 상태 규칙이 유지되어야 한다
  - _검증: 로컬 dev 서버 + Playwright 시각 확인 + 스크린샷 비교_

- [ ] 15. Stage 8: CI/CD 및 배포 경로 연결
  - [ ] 15.1 파이프라인 게시 포맷 정리
    - `src/morning_brief` 출력과 `schema/brief.types.ts` 계약 사이 차이를 정리
    - 날짜별 JSON, 최신 JSON, 인덱스 JSON 작성 로직 연결
    - _Requirements: REQ-013, REQ-015_
  - [ ] 15.2 프론트 배포 워크플로우 추가
    - `frontend.yml` 작성
    - JSON fetch → 정적 빌드 → Cloudflare Pages 배포 순서 구성
    - _Requirements: REQ-015_
  - [ ] 15.3 `morning-brief.yml` 과 프론트 배포 연결
    - 게시 완료 후 프론트 배포를 트리거하도록 연결
    - _Requirements: REQ-013, REQ-015_

- [ ] 16. Stage 8 체크포인트
  - 데이터 게시와 프론트 배포가 논리적으로 이어져야 한다
  - 파이프라인 실패 시 기존 공개본 유지 전략이 문서와 코드에 일치해야 한다
  - _검증: 워크플로우 dry review, 필요 시 workflow_dispatch 테스트_

- [ ] 17. Stage 9: 검증과 회귀 테스트
  - [ ] 17.1 계약 테스트
    - JSON fixture 가 `schema/brief.types.ts` 기준을 통과하는지 확인
    - _Requirements: REQ-011, REQ-012_
  - [ ] 17.2 렌더링 테스트
    - 메인, 아카이브, 품질 배너, null/cached 상태, optional 섹션 숨김 검증
    - _Requirements: REQ-001 ~ REQ-012_
  - [ ] 17.3 빌드 테스트
    - Next.js 정적 빌드와 RSS/`llms.txt` 산출 검증
    - _Requirements: REQ-010, REQ-015_
  - [ ] 17.4 디자인 회귀 테스트
    - `sovereign-brief-terminal` 과 비교할 핵심 화면 스냅샷을 고정한다
    - 헤더, ticker rail, 뉴스 피드, market board, BTC 섹션의 시각 회귀를 확인한다
    - _Requirements: REQ-014, REQ-015_
  - [ ] 17.5 접근성/반응형 검토
    - 색상 외 상태 표시, 모바일 뷰, 한국어 중심 표기 확인
    - _Requirements: REQ-014_

- [ ] 18. 최종 체크포인트
  - `requirements → design → tasks` 추적이 가능해야 한다
  - `frontend` 는 더 이상 Vite 프로토타입 전제로 설명되지 않아야 한다
  - 최신 브리핑 JSON 1건만으로 메인 페이지를 정적 렌더링할 수 있어야 한다
  - 디자인은 `sovereign-brief-terminal` 대비 “분위기 참고” 수준이 아니라, 명확히 같은 계열로 인식되어야 한다
  - _검증: 타입 검사, 프론트 빌드, 렌더링 테스트, 워크플로우 검토_

---

## Notes

- 이번 문서는 **전체 마이그레이션** 기준이다.
- 구독/수신거부는 1차 범위에서 제외한다.
- `schema/brief.types.ts` 는 프론트 계약의 단일 기준 파일로 본다.
- 프론트 디자인의 직접 참조 기준은 `/Users/giwon/Downloads/sovereign-brief-terminal` 이다.
- 폰트는 Google Fonts 사용을 허용하며, 필요 시 동일 폰트의 다운로드/self-host fallback 까지 포함해 구현한다.
- 구현 중 현재 저장소와 목표 구조 차이가 발견되면, `design.md` 를 먼저 갱신한 뒤 작업을 이어간다.
