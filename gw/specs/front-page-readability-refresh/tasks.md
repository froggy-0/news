# Implementation Plan: front-page-readability-refresh

## Overview

이 작업은 홈 화면의 표현 레이어를 semantic token, seeded hero motion, 카드 패밀리, 상태 UI 구조 중심으로 재정렬하는 구현 계획이다. 구현은 전역 시스템 정리 → 히어로/상단 배치 → 상태 UI 구조 → 카드 패밀리 수렴 → 모션 축소 → 회귀 검증 순서로 진행한다.

완료 시각: 2026-03-31 00:07 KST

## Tasks

- [x] 1. Stage 1: semantic token과 typography 하한을 전역 시스템에 반영한다
  - [x] 1.1 `frontend/app/globals.css`에 semantic token alias를 추가한다
    - 최소 `accent`, `surface`, `label`, `status`, `card-radius`, `card-padding`, `meta-type` token을 정의한다
    - 기존 하드코딩 색상과 알파값을 직접 쓰는 구간을 단계적으로 alias로 치환할 준비를 한다
    - _Requirements: 7.1_
  - [x] 1.2 typography/spacing 하한을 전역 토큰으로 고정한다
    - 본문 `16px` 이상, 보조 `12px` 이상, line-height `1.4` 이상 기준을 CSS 계층으로 반영한다
    - 일반 텍스트 대비가 WCAG 2.2 AA `4.5:1` 이상을 만족하도록 토큰 조합을 정리한다
    - 섹션 라벨, 메타 정보, 영어 티커 표기의 크기/자간/스타일 규칙을 semantic token 기준으로 통일한다
    - _Requirements: 4.2, 4.3, 4.5, 4.6, 4.10, 4.11_
  - [x] 1.3 typography와 token consistency 테스트를 추가한다
    - 테스트 파일 후보: `frontend/tests/ui-system.test.ts`
    - semantic token 최소 목록, typography 하한, 카드 관련 token 존재 여부를 검증한다
    - _Requirements: 4.2, 4.3, 4.5, 7.1_

- [x] 2. Stage 1: 홈 히어로와 첫 스크린 배치를 재구성한다
  - [x] 2.1 `frontend/app/page.tsx`와 `frontend/components/hero/HomeHero.tsx`에서 히어로 seed 전달 구조를 추가한다
    - `brief.meta.date`를 단일 시드 원천으로 사용해 `heroSeed`를 계산하고 전달한다
    - 첫 스크린 안에 가치 제안, CTA, 핵심 브리프 진입 요소가 보이도록 조합 순서를 고정한다
    - _Requirements: 1.3, 1.5, 1.7, 6.1_
  - [x] 2.2 `HomeHero`의 모바일 레이아웃 규칙을 요구사항 수치에 맞게 재배치한다
    - 고정 헤더 `64px` 이하 기준을 고려해 첫 스크린 배치를 맞춘다
    - 주요 CTA와 메뉴 트리거가 `375px` 폭 기준 첫 스크린 하단 `60%` 영역 안에서 우선 인지되도록 정리한다
    - 터미널 패널은 모바일에서 축약 높이 프로필을 사용하거나 첫 스크린 핵심 콘텐츠 이후에만 노출되도록 후순위 배치한다
    - 장식 요소가 터치 가능한 컨트롤처럼 오인되지 않도록 비상호작용 장치의 affordance를 낮춘다
    - _Requirements: 1.3, 1.5, 3.3, 3.4, 6.5_
  - [x] 2.3 히어로 배치와 접근성 회귀 테스트를 추가한다
    - 테스트 파일 후보: `frontend/tests/public-brief-ui.test.ts`
    - 히어로 seed source 전달, 핵심 브리프 진입 요소 렌더 순서, CTA 노출 여부를 검증한다
    - _Requirements: 1.3, 1.5, 1.7, 6.1_

- [x] 3. Stage 1: seeded generative hero를 구현한다
  - [x] 3.1 `frontend/components/hero/ScatterText.tsx`를 시드 기반 PRNG 구조로 변경한다
    - `Math.random()` 직접 사용을 제거하고 동일 seed에서 동일 결과를 만드는 PRNG로 대체한다
    - `text`, `seed`, `density`, `spread`, `durationMs`를 props 기반으로 제어한다
    - _Requirements: 1.6, 1.7, 1.8_
  - [x] 3.2 reduced motion과 fallback 동작을 명시적으로 정리한다
    - `prefers-reduced-motion`에서는 정적 anchor 텍스트만 렌더링한다
    - canvas/context 실패 시 정적 타이포로 안전하게 fallback한다
    - _Requirements: 1.2, 1.6, 8.4_
  - [x] 3.3 deterministic motion 테스트를 추가한다
    - 테스트 파일 후보: `frontend/tests/scatter-text.test.ts`
    - 같은 seed 동일 결과, 다른 seed 다른 결과, reduced motion fallback을 검증한다
    - _Requirements: 1.2, 1.7, 1.8_

- [x] 4. Checkpoint - 전역 시스템과 히어로 기반 완료
  - [x] 4.1 1차 검증을 수행한다
    - `cd frontend && npm run lint`
    - `cd frontend && npm test`
    - semantic token, typography 하한, seeded hero, 첫 스크린 배치가 동시에 깨지지 않는지 확인한다
    - 검증 결과: 통과
    - _Requirements: 1.1, 1.7, 4.2, 7.1, 8.6_

- [x] 5. Stage 2: 상태 UI 구조를 공용 컴포넌트로 정리한다
  - [x] 5.1 `frontend/components/ui/`에 공용 상태 프레임 구조를 추가한다
    - `DataState`를 `empty`, `partial`, `error`까지 다루도록 확장한다
    - `SectionSkeleton` 또는 동등 구조를 추가해 loading 상태의 reserved space를 제공한다
    - _Requirements: 8.4, 8.5_
  - [x] 5.2 홈 히어로와 핵심 섹션의 reserved space 정책을 반영한다
    - hero auxiliary panel `120px`, home data card group `160px`, reading card list 카드당 `220px`, utility drawer status block `96px` 최소 높이 프로필을 적용한다
    - content jumping이 생기지 않도록 skeleton 또는 placeholder 높이를 고정한다
    - _Requirements: 2.1, 8.5_
  - [x] 5.3 상태 UI 공용 구조에 대한 렌더링 테스트를 추가한다
    - 테스트 파일 후보: `frontend/tests/public-brief-ui.test.ts`, `frontend/tests/ui-system.test.ts`
    - loading/partial/empty/error 상태에서 공용 상태 프레임이 일관되게 렌더링되는지 검증한다
    - _Requirements: 8.3, 8.4, 8.5_

- [x] 6. Stage 2: 카드 패밀리를 3종으로 수렴시킨다
  - [x] 6.1 `reading card` family를 뉴스/토픽 계층에 적용한다
    - `frontend/components/news/NewsFeedList.tsx`, `frontend/components/brief/TopicGrid.tsx`에 reading card 규칙을 적용한다
    - `24px` radius, `24px` padding, 낮은 메타 비중, line-length `65자` 이내를 유지한다
    - 뉴스, 토픽, 시그널 섹션이 데이터 나열보다 해석 가능한 순서를 유지하도록 reading card 계층을 맞춘다
    - _Requirements: 5.5, 6.2, 7.2_
  - [x] 6.2 `data card` family를 시장/비트코인 보드에 적용한다
    - `frontend/components/market/StocksBoard.tsx`, `frontend/components/bitcoin/BitcoinPanel.tsx`에 data card 규칙을 적용한다
    - 모바일 기본 `1열`, 핵심 2개만 첫 그룹 허용, 숫자/라벨 우선 규칙을 반영한다
    - 홈 화면의 정보 밀도만 재배치하고 상세 맥락의 수치 밀도와 비홈 레이아웃은 변경 대상에서 제외한다
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 7.2_
  - [x] 6.3 `utility card` family를 히스토리/상태/보조 액션에 적용한다
    - `frontend/components/layout/HistoryDrawerClient.tsx`, `frontend/components/layout/SiteFooter.tsx` 등 utility 계층을 정리한다
    - `20px` radius, `16px` padding, 12px 메타 하한을 유지한다
    - _Requirements: 4.3, 7.2_
  - [x] 6.4 카드 family 수렴 테스트를 추가한다
    - 테스트 파일 후보: `frontend/tests/ui-system.test.ts`
    - 카드 family가 `reading/data/utility` 3종으로 제한되고, 각 family가 지정 token을 사용하는지 검증한다
    - _Requirements: 5.2, 7.2_

- [x] 7. Stage 2: 모션 계층을 3종으로 축소한다
  - [x] 7.1 전역 배경 모션을 `site-noise` 단일 구조로 정리한다
    - `scanline`을 제거하고 배경층은 `site-noise`만 유지한다
    - _Requirements: 7.3_
  - [x] 7.2 강조 모션과 상태 피드백 모션을 정리한다
    - `ScatterText`만 대표 강조 모션으로 유지한다
    - `ScrollProgressBar`만 상태 피드백 모션으로 유지하고 card bloom, sweep, line draw, 반복 점멸을 제거한다
    - `RevealSection`은 8px 이하 이동 + opacity 중심 reveal만 허용한다
    - _Requirements: 1.8, 7.3_
  - [x] 7.3 모션 축소와 reduced motion 회귀 테스트를 추가한다
    - 테스트 파일 후보: `frontend/tests/ui-system.test.ts`
    - 금지된 모션 계층이 남아 있지 않은지, reduced motion에서 비필수 모션이 비활성화되는지 검증한다
    - _Requirements: 1.2, 7.3_

- [x] 8. Checkpoint - 카드/모션/상태 구조 완료
  - [x] 8.1 2차 검증을 수행한다
    - `cd frontend && npm run lint`
    - `cd frontend && npm test`
    - 카드 family 수렴, 상태 UI 공용화, 모션 축소가 동시에 유지되는지 확인한다
    - 검증 결과: 통과
    - _Requirements: 5.2, 7.2, 7.3, 8.5, 8.6_

- [x] 9. Stage 3: 홈 읽기 흐름과 상단 크롬을 마무리한다
  - [x] 9.1 `SiteHeader`, `HomeHero`, `JudgmentBlock`의 읽기 흐름을 최종 정렬한다
    - 헤더 높이 `64px` 이하를 보장한다
    - 브랜드 진입 이후 핵심 판단, 핵심 숫자, 해석 콘텐츠 순서를 최종 고정한다
    - 홈 화면은 요약과 전환에 집중하고 상세 밀도는 상세 화면 또는 후속 맥락에 유지한다
    - _Requirements: 1.3, 6.1, 6.5_
  - [x] 9.2 터치 타깃과 focus state를 상단 크롬/구독 폼/드로어에 최종 적용한다
    - `SubscriptionForm`, `HistoryDrawerClient`, 상단 버튼류에 `44px` hit area와 최소 `8px` 간격을 보장한다
    - outline 제거 시 대체 focus indicator를 모두 반영한다
    - tab 이동 순서가 시각적 읽기 순서와 일치하도록 포커스 이동 순서를 정리한다
    - _Requirements: 3.1, 3.2, 4.7, 4.8, 4.9_
  - [x] 9.3 홈 흐름과 상호작용 회귀 테스트를 추가한다
    - 테스트 파일 후보: `frontend/tests/public-brief-ui.test.ts`
    - 읽기 순서, 헤더 높이 규칙, focus state, tab 순서, CTA/메뉴 접근성을 검증한다
    - _Requirements: 3.1, 4.7, 4.8, 6.1, 6.5_

- [x] 10. Stage 3: 최종 검증과 시각 QA를 수행한다
  - [x] 10.1 자동 검증을 수행한다
    - `cd frontend && npm run lint`
    - `cd frontend && npm test`
    - `cd frontend && npm run build:fixture`
    - 검증 결과: 순차 실행 기준 통과
    - _Requirements: 8.1, 8.2, 8.6_
  - [x] 10.2 반응형 및 시각 QA를 수행한다
    - `375px`, `768px`, `1024px`, `1440px`에서 홈 화면을 점검한다
    - 첫 스크린, data card 1열, seeded hero 재현성, focus state, partial data 상태, content jumping 여부를 확인한다
    - 검증 결과: 4개 뷰포트에서 가로 overflow 없이 CTA, hero, brief 진입 요소 확인
    - _Requirements: 1.3, 5.2, 7.3, 8.5, 8.7_

- [x] 11. Checkpoint - 최종 완료 기준 확인
  - [x] 11.1 최종 완료 조건을 기록한다
    - semantic token, seeded hero, 카드 3종, 모션 3종, 상태 UI 구조가 모두 반영되어야 한다
    - 홈 화면이 `375px` 기준 첫 스크린 가독성을 확보하고, 기존 데이터 계약 및 fixture 빌드와 호환되어야 한다
    - 체크포인트 결과: `npm test`, `npm run build:fixture`, `npm run lint` 통과
    - _검증: `npm run lint`, `npm test`, `npm run build:fixture`, 반응형 수동 QA_
