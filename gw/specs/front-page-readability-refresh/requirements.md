# Requirements Document

## Introduction

현재 홈 화면은 브랜드 연출이 강한 반면, 한국어 뉴스레터형 제품에서 가장 중요한 첫 화면 가독성과 정보 우선순위가 충분히 확보되지 않았다. 이번 작업은 홈 화면의 시각적 정체성은 유지하되, 핵심 브리프를 더 빨리 읽고 신뢰할 수 있도록 정보 구조, 타이포그래피, 모바일 카드 밀도를 재정렬하는 데 목적이 있다. 범위는 홈 화면(`/`)의 읽기 경험 개선으로 한정하며, 데이터 계약이나 이메일 템플릿 변경은 포함하지 않는다.

## Glossary

**홈 히어로**: 페이지 최상단의 브랜드 메시지, 구독 폼, 장식 패널이 포함된 진입 구간

**핵심 브리프**: 오늘의 판단, 핵심 인사이트 등 사용자가 가장 먼저 읽어야 하는 요약 정보

**마이크로 타이포**: 섹션 라벨, 메타 정보, 보조 설명에 쓰이는 작은 글자 시스템

**홈 보드**: 시장 주요 지표와 비트코인 요약 카드처럼 수치를 압축해 보여주는 카드 영역

**뉴스레터형 UX**: 대시보드보다 읽기 흐름과 해석 순서를 우선하는 정보 소비 경험

## Requirements

### Requirement 1: 홈 첫 화면의 핵심 메시지 우선순위 재정렬

**User Story:**
As a 한국어 브리프 독자,
I want 첫 화면에서 서비스 가치와 오늘의 핵심 판단을 즉시 이해하고 싶다,
so that 몇 초 안에 읽을 가치가 있는 뉴스레터인지 판단할 수 있다.

#### Acceptance Criteria

1. WHEN 사용자가 홈 화면에 처음 진입할 때, THE home hero SHALL 브랜드 카피보다 핵심 메시지의 가독성을 우선하는 정적 텍스트 계층을 제공한다.
2. WHEN 모바일 뷰포트에서 히어로 타이틀이 렌더링될 때, THE home hero SHALL 장식 효과가 없어도 한 번에 읽히는 형태와 대비를 유지한다.
3. WHEN 홈 화면이 375px 폭의 모바일 뷰포트에서 처음 표시될 때, THE home page SHALL 고정 헤더 아래의 첫 스크린 안에서 핵심 브리프 진입 요소를 확인할 수 있게 배치한다.
4. IF 장식 요소가 핵심 메시지보다 먼저 시선을 강하게 끄는 경우, THEN THE home hero SHALL 장식 강도를 축소하거나 보조 위치로 이동한다.
5. WHEN 모바일 사용자가 한 손으로 홈 화면에 진입할 때, THE home page SHALL 첫 행동에 필요한 주요 조작 요소를 375px 폭 기준 첫 스크린과 하단 60% 영역 안에서 우선 인지할 수 있게 배치한다.
6. WHEN 히어로의 생성적 타이포 효과가 표시될 때, THE home hero SHALL 효과를 제거하지 않고 유지하되 핵심 카피 가독성을 해치지 않는 보조 계층으로 제어한다.
7. WHEN 동일한 발행본이 다시 렌더링될 때, THE home hero SHALL `brief.meta.date` 값을 단일 시드 원천으로 사용해 동일한 파티클 전개 결과를 재현한다.
8. IF 생성 효과가 활성화되는 경우, THEN THE home hero SHALL 입자 수, 퍼짐, 밝기, 지속 시간을 제한해 랜덤 장식보다 브랜드 시그니처 모션으로 인식되도록 유지한다.

### Requirement 2: 홈 히어로의 장식 패널 역할 축소

**User Story:**
As a 빠르게 시장을 파악하려는 사용자,
I want 장식성 패널이 핵심 정보보다 앞서 공간을 차지하지 않길 원한다,
so that 첫 화면에서 바로 읽기 행동으로 진입할 수 있다.

#### Acceptance Criteria

1. WHEN 홈 화면이 모바일에서 표시될 때, THE home hero SHALL 장식 패널이 핵심 브리프보다 앞선 세로 공간을 과도하게 점유하지 않도록 구성한다.
2. WHEN 장식 패널이 유지될 때, THE home hero SHALL 이를 보조 정보 또는 브랜드 장치로 인식할 수 있는 시각적 비중으로 제한한다.
3. IF 홈 첫 화면의 세로 공간이 제한되는 경우, THEN THE home page SHALL 핵심 브리프 관련 정보가 장식 패널보다 먼저 노출되도록 우선순위를 조정한다.

### Requirement 3: 모바일 터치 상호작용 안정성 보장

**User Story:**
As a 모바일 사용자,
I want 홈 화면의 주요 조작 요소를 실수 없이 누를 수 있길 원한다,
so that 읽기 흐름이 끊기지 않고 필요한 행동을 바로 수행할 수 있다.

#### Acceptance Criteria

1. WHEN 모바일 화면에서 사용자가 홈의 주요 조작 요소를 터치할 때, THE home page SHALL 주요 버튼, 입력, 메뉴 트리거에 대해 최소 44px 이상의 터치 가능 영역을 제공한다.
2. WHEN 두 개 이상의 조작 요소가 인접해 배치될 때, THE home page SHALL 오동작을 줄이기 위해 조작 요소 간 최소 8px 이상의 간격을 유지한다.
3. WHEN 주요 CTA가 배치될 때, THE home page SHALL 375px 폭 기준 첫 스크린의 하단 60% 영역 안에서 우선 인지 가능한 위치를 사용한다.
4. IF 장식 요소가 터치 가능한 컨트롤처럼 오인될 수 있는 경우, THEN THE home page SHALL 상호작용 요소와 비상호작용 요소를 명확히 구분한다.

### Requirement 4: 한국어 중심 마이크로 타이포 시스템 개선

**User Story:**
As a 한국어 사용자,
I want 작은 라벨과 보조 설명도 무리 없이 빠르게 읽고 싶다,
so that 화면 전체를 훑을 때 피로감 없이 정보 계층을 이해할 수 있다.

#### Acceptance Criteria

1. WHEN 섹션 라벨과 메타 텍스트가 모바일에서 표시될 때, THE typography system SHALL 현재보다 높은 판독성과 대비를 제공한다.
2. WHEN 한국어 본문이 모바일에서 표시될 때, THE typography system SHALL 기본 본문 크기를 16px 이상으로 유지한다.
3. WHEN 한국어 보조 카피와 메타 정보가 모바일에서 표시될 때, THE typography system SHALL 12px 미만의 글자 크기를 사용하지 않는다.
4. WHEN 한국어 보조 카피가 표시될 때, THE typography system SHALL 과도한 자간과 지나치게 작은 글자 크기를 사용하지 않는다.
5. WHEN 일반 텍스트가 홈 화면에 표시될 때, THE typography system SHALL WCAG 2.2 AA 기준에 맞춰 최소 4.5:1 이상의 대비를 유지한다.
6. WHEN 본문과 보조 카피가 표시될 때, THE typography system SHALL 모바일 읽기 피로를 줄이기 위해 1.4 이상의 line-height를 유지한다.
7. WHEN 포커스 가능한 상호작용 요소가 표시될 때, THE home page SHALL 키보드 탐색 사용자를 위해 시각적으로 명확한 focus state를 제공한다.
8. WHEN 키보드 탐색으로 홈 화면을 이동할 때, THE home page SHALL 시각적 읽기 순서와 논리적으로 일치하는 tab 순서를 유지한다.
9. IF 기본 outline 스타일을 제거하는 경우, THEN THE home page SHALL 동일하거나 더 명확한 대체 focus indicator를 제공한다.
10. WHEN 동일한 역할의 라벨이 여러 섹션에 반복될 때, THE typography system SHALL 일관된 크기, 대비, spacing 규칙을 유지한다.
11. IF 영어 또는 티커 표기가 필요한 경우, THEN THE typography system SHALL 한국어 본문 가독성을 해치지 않는 범위에서만 모노/대문자 스타일을 사용한다.

### Requirement 5: 홈 숫자 카드 영역의 모바일 밀도 재설계

**User Story:**
As a 모바일 독자,
I want 수치 카드에서 값과 라벨을 한 번에 읽고 싶다,
so that 대시보드처럼 확대해서 보지 않아도 핵심 숫자를 빠르게 파악할 수 있다.

#### Acceptance Criteria

1. WHEN 홈 화면의 시장 주요 지표와 비트코인 카드가 모바일에서 표시될 때, THE home boards SHALL 현재보다 낮은 정보 밀도로 핵심 값 위주로 노출한다.
2. WHEN 카드 수가 많은 경우, THE home boards SHALL 1열 구성 또는 핵심 카드 우선 노출 방식으로 스캔성을 보장한다.
3. WHEN 결측 상태가 존재할 때, THE home boards SHALL 정상 데이터 카드와 동일한 시각적 무게로 결측 카드를 반복 노출하지 않는다.
4. IF 상세한 수치 구성이 필요한 경우, THEN THE detailed layouts SHALL 홈 화면이 아닌 상세 맥락에서 유지된다.
5. WHEN 모바일 카드가 표시될 때, THE home boards SHALL 카드 내부 숫자와 라벨이 확대 없이 함께 읽히는 수준의 크기와 줄 수를 유지한다.

### Requirement 6: 홈 화면의 읽기 중심 정보 구조 유지

**User Story:**
As a 뉴스레터형 브리프 사용자,
I want 홈 화면이 대시보드보다 읽는 흐름에 가깝길 원한다,
so that 해석과 숫자를 자연스러운 순서로 소비할 수 있다.

#### Acceptance Criteria

1. WHEN 홈 화면이 구성될 때, THE home page SHALL 브랜드 진입 이후 핵심 판단, 핵심 숫자, 해석 콘텐츠 순으로 읽기 흐름을 제공한다.
2. WHEN 뉴스, 토픽, 시그널 섹션이 표시될 때, THE home page SHALL 데이터 나열보다 해석 가능한 순서를 우선한다.
3. WHEN 홈 화면과 상세 화면의 역할이 비교될 때, THE home page SHALL 요약과 전환에 집중하고 상세 밀도는 상세 페이지 또는 후속 섹션으로 남긴다.
4. WHEN 기존 데이터 계약을 사용해 화면을 렌더링할 때, THE home page SHALL 현재 JSON 구조와 호환되는 범위 안에서 레이아웃만 재조정한다.
5. WHEN 모바일에서 상단 헤더가 고정될 때, THE home page SHALL 첫 스크린의 핵심 콘텐츠 가시성을 보존하기 위해 헤더 높이를 64px 이하로 유지한다.

### Requirement 7: UI 시스템 일관성 정리

**User Story:**
As a 제품 디자이너와 개발자,
I want 홈 화면 UI를 의미 기반 규칙으로 정리하고 싶다,
so that 이후 개선에서도 시각적 일관성과 유지보수성을 함께 유지할 수 있다.

#### Acceptance Criteria

1. WHEN 홈 화면 스타일 규칙을 정리할 때, THE design system SHALL 색상과 간격, 텍스트 규칙을 최소 `accent`, `surface`, `label`, `status`, `card-radius`, `card-padding`, `meta-type` semantic token으로 정의한다.
2. WHEN 카드 컴포넌트를 정리할 때, THE home page SHALL 카드 계층을 `reading card`, `data card`, `utility card` 3종으로 정의하고 각 카드의 radius, padding, label 규칙을 문서화한다.
3. WHEN 모션 시스템을 정리할 때, THE home page SHALL 홈 화면에서 동시에 유지되는 모션 계층을 전역 배경 모션 1종, 강조 모션 1종, 상태 피드백 모션 1종으로 제한한다.

### Requirement 8: 모바일 상태 처리와 회귀 방지 검증

**User Story:**
As a 유지보수 담당자,
I want 이번 개선이 시각 품질만 바꾸고 데이터 동작은 깨지지 않길 원한다,
so that 홈 화면 개선 후에도 기존 공개 브리프 기능을 안정적으로 유지할 수 있다.

#### Acceptance Criteria

1. WHEN 홈 화면 레이아웃과 타이포가 수정될 때, THE frontend tests SHALL 주요 섹션 렌더링과 빈 상태 처리를 계속 검증한다.
2. WHEN fixture 기반 빌드를 수행할 때, THE frontend SHALL 빌드 가능 상태를 유지한다.
3. IF 특정 섹션 데이터가 비어 있는 fixture를 렌더링할 때, THEN THE home page SHALL 빈 화면 대신 기존 상태 메시지 규칙을 유지한다.
4. WHEN 모바일 네트워크 또는 데이터 상태가 불완전할 때, THE home page SHALL 로딩, 오류, 부분 데이터 상태를 사용자가 이해할 수 있는 방식으로 표시한다.
5. WHEN 로딩 또는 부분 데이터 상태가 발생할 때, THE home page SHALL 주요 섹션의 높이와 읽기 흐름이 급격히 점프하지 않도록 reserved space, skeleton, 또는 최소 높이 전략을 사용한다.
6. WHEN 이번 변경이 완료될 때, THE verification plan SHALL 최소 `npm run lint`, `npm test`, `npm run build:fixture` 를 포함한다.
7. WHEN 반응형 품질을 검증할 때, THE verification plan SHALL 최소 375px, 768px, 1024px, 1440px 폭 기준으로 홈 화면 가독성과 주요 상호작용을 확인한다.
