# Requirements Document

## Introduction

현재 운영 프론트엔드는 `frontend/`의 Next.js 기반 정적 export 구조를 사용하고 있으며, 이 구조는 배포 안정성과 운영 단순성 측면에서 유지 가치가 높다. 반면 시각적 완성도와 상호작용 경험은 새로 준비된 `sovereign-brief/` 샘플 프론트 수준으로 재설계할 필요가 있다. 이번 작업의 목적은 운영 구조와 JSON 기반 정적 렌더링 모델은 유지하면서, 샘플 프론트의 디자인, 애니메이션, 폰트, 히스토리 메뉴, 홈 히어로와 이메일 입력 UI를 거의 동일한 수준으로 `frontend/`에 마이그레이션하는 것이다.

## Glossary

**운영 프론트**: 실제 마이그레이션 대상인 `frontend/` Next.js 앱
**샘플 프론트**: 디자인 및 인터랙션 참조 기준인 `sovereign-brief/` Vite 앱
**히어로 영역**: 홈 첫 화면 상단의 핵심 비주얼, 카피, 효과, 이메일 입력 UI가 포함된 영역
**히스토리 메뉴**: 상단 메뉴 버튼 클릭 시 열리는 날짜별 브리프 탐색 UI
**브리프 데이터**: 날짜별 JSON으로 제공되는 공개 브리핑 데이터
**정적 생성(SSG)**: 빌드 시점에 JSON을 읽어 HTML을 생성하는 방식
**인터랙션 컴포넌트**: 메뉴 드로어, 애니메이션, 입력폼처럼 클라이언트 hydration이 필요한 요소
**디자인 시스템**: 색상, 폰트, 간격, radius, border, shadow, 애니메이션, 공용 UI primitive 규칙

## Requirements

### Requirement 1: Next.js 정적 생성 운영 구조 유지

**User Story:**
As a 운영자,
I want 새 디자인이 기존 Next.js 정적 export 구조 위에서 구현되길 원한다,
so that 운영 안정성과 정적 배포 모델을 유지할 수 있다.

#### Acceptance Criteria

1. WHEN 새 프론트가 구현될 때, THE 프론트엔드 SHALL 기존 `frontend/` 앱을 실제 운영 대상 코드베이스로 유지한다.
2. WHEN 공개 페이지가 빌드될 때, THE 프론트엔드 SHALL JSON 데이터를 빌드 시점에 읽어 정적으로 렌더링한다.
3. WHEN 사이트가 배포될 때, THE 프론트엔드 SHALL 정적 export 방식과 호환되는 결과물을 생성한다.
4. IF 사용자 상호작용 때문에 클라이언트 동작이 필요한 경우, THEN THE 프론트엔드 SHALL 필요한 컴포넌트 범위에서만 hydration을 적용한다.

### Requirement 2: 샘플 디자인 고충실도 마이그레이션

**User Story:**
As a 제품 오너,
I want 샘플 프론트의 디자인 언어를 거의 동일하게 운영 프론트로 옮기고 싶다,
so that 승인된 새 디자인 경험을 그대로 서비스에 반영할 수 있다.

#### Acceptance Criteria

1. WHEN 새 디자인이 적용될 때, THE 프론트엔드 SHALL 샘플 프론트의 타이포그래피 계층, 색상 언어, 표면 질감, 간격 밀도, 카드/섹션 구성, 전체 분위기를 높은 충실도로 재현한다.
2. WHEN 새 디자인이 적용될 때, THE 프론트엔드 SHALL 샘플 프론트의 진입 애니메이션, hover 반응, 메뉴 전환, hero 시각 효과 등 모션 언어를 높은 충실도로 재현한다.
3. WHEN 폰트가 적용될 때, THE 프론트엔드 SHALL 샘플 프론트와 동일한 폰트 구성과 위계를 사용한다.
4. IF 프레임워크 차이로 인해 샘플 구현을 그대로 이식할 수 없는 경우, THEN THE 프론트엔드 SHALL 사용자 관점에서 동일한 인상과 기능을 제공하는 대체 구현을 제공한다.

### Requirement 3: 홈 히어로 영역 완전 이식

**User Story:**
As a 첫 방문 사용자,
I want 홈 첫 화면이 샘플 프론트와 거의 동일한 인상으로 보이길 원한다,
so that 브랜드 경험과 첫 인상이 새 디자인 기준에 맞게 전달된다.

#### Acceptance Criteria

1. WHEN 사용자가 홈 페이지에 진입할 때, THE 프론트엔드 SHALL 샘플 프론트와 거의 동일한 구성의 히어로 영역을 표시한다.
2. WHEN 히어로 영역이 렌더링될 때, THE 프론트엔드 SHALL 샘플과 동일한 시각 효과, 애니메이션 흐름, 카피 계층, 타이포그래피를 반영한다.
3. WHEN 히어로 영역이 렌더링될 때, THE 프론트엔드 SHALL 이메일 입력 UI를 첫 화면 핵심 요소로 포함한다.
4. IF 사용자 환경에서 애니메이션이 제한되거나 비활성화되는 경우, THEN THE 프론트엔드 SHALL 모션 없이도 동일한 정보 위계와 사용성을 유지한다.
5. WHEN 히어로 headline의 `데이터 인텔리전스` 텍스트가 렌더링될 때, THE 프론트엔드 SHALL 샘플 프론트의 흩어졌다 모이는 텍스트 효과를 핵심 시각 요소로 유지해야 한다.

### Requirement 4: 홈 히어로 이메일 입력 UI 필수 이식

**User Story:**
As a 구독 의향이 있는 방문자,
I want 홈 첫 화면에서 샘플과 동일한 이메일 입력 경험을 보고 싶다,
so that 구독 행동 유도가 새 디자인의 핵심 흐름 안에 유지된다.

#### Acceptance Criteria

1. WHEN 홈 히어로가 표시될 때, THE 프론트엔드 SHALL 샘플 프론트와 동일한 스타일과 배치의 이메일 입력 UI를 포함한다.
2. WHEN 이메일 입력 UI가 렌더링될 때, THE 프론트엔드 SHALL 샘플 프론트의 시각적 디테일과 상호작용 affordance를 가능한 한 동일하게 유지한다.
3. IF 기존 구독 처리 플로우와 연결이 필요한 경우, THEN THE 프론트엔드 SHALL 기존 구독 처리 흐름을 깨지 않는 방식으로 연결한다.
4. IF 이번 마이그레이션 범위에 구독 처리 백엔드 수정이 포함되지 않는 경우, THEN THE 프론트엔드 SHALL 최소한 입력 경험과 시각적 완성도를 유지하고 후속 연결 지점을 명확히 분리한다.
5. WHEN 사용자가 이메일 입력 UI를 제출할 때, THE 프론트엔드 SHALL 기존 운영 플로우와 동일하게 제출 중 상태, 성공 메시지, 오류 메시지를 사용자에게 표시할 수 있어야 한다.
6. WHEN 구독 요청이 성공할 때, THE 프론트엔드 SHALL 현재 운영 동작과 동일하게 입력값 초기화와 후속 안내 상태를 제공해야 한다.

### Requirement 5: 히스토리 메뉴 이식 및 전역 접근성

**User Story:**
As a 반복 방문 사용자,
I want 상단 메뉴를 눌러 이전 브리프 날짜를 탐색하고 싶다,
so that 현재 페이지를 떠나지 않고도 아카이브를 빠르게 이동할 수 있다.

#### Acceptance Criteria

1. WHEN 사용자가 상단 메뉴 버튼을 누를 때, THE 프론트엔드 SHALL 샘플 프론트와 동일한 패턴의 히스토리 메뉴를 연다.
2. WHEN 히스토리 메뉴가 열릴 때, THE 프론트엔드 SHALL 사용 가능한 브리프 날짜 목록을 표시한다.
3. WHEN 날짜 수가 초기 표시 범위를 초과할 때, THE 히스토리 메뉴 SHALL 추가 날짜를 점진적으로 노출할 수 있어야 한다.
4. WHEN 사용자가 날짜를 선택할 때, THE 프론트엔드 SHALL 해당 날짜의 정적 아카이브 상세 페이지로 이동한다.
5. WHEN 사용자가 홈 페이지에 있을 때, THE 프론트엔드 SHALL 동일한 히스토리 메뉴를 제공한다.
6. WHEN 사용자가 `/archive/[date]` 상세 페이지에 있을 때, THE 프론트엔드 SHALL 홈과 동일한 히스토리 메뉴를 상단에서 제공한다.
7. WHEN 사용자가 `/archive` 목록 페이지에 있을 때, THE 프론트엔드 SHALL 홈과 동일한 히스토리 메뉴를 상단에서 제공한다.
8. WHEN 히스토리 메뉴가 열려 있을 때, THE 프론트엔드 SHALL 닫기 동작, 오버레이 처리, 키보드 접근, 포커스 이동을 포함한 기본 접근성 동작을 제공한다.

### Requirement 6: 정보 구조 재설계

**User Story:**
As a 투자자,
I want 브리프 내용을 위에서 아래로 자연스럽게 이해할 수 있는 구조로 보고 싶다,
so that 오늘 시장의 핵심을 빠르게 파악한 뒤 세부 내용을 탐색할 수 있다.

#### Acceptance Criteria

1. WHEN 홈 페이지가 렌더링될 때, THE 프론트엔드 SHALL 다음 순서로 주요 정보를 배치한다: 요약, 정량 지표, 테마, 뉴스, X 시그널, 데이터 기준/상태.
2. WHEN 각 주요 섹션이 렌더링될 때, THE 프론트엔드 SHALL 시각적으로 명확히 분리된 블록 구조를 제공한다.
3. IF 선택적 데이터가 없는 경우, THEN THE 프론트엔드 SHALL 해당 보조 섹션만 숨기고 전체 정보 구조는 유지한다.
4. WHEN 아카이브 상세 페이지가 렌더링될 때, THE 프론트엔드 SHALL 같은 정보 구조를 유지하되 홈보다 더 높은 정보 밀도를 허용한다.

### Requirement 7: 요약 및 해석 레이어 유지

**User Story:**
As a 바쁜 사용자,
I want 원문보다 먼저 오늘의 해석과 핵심 판단을 읽고 싶다,
so that 짧은 시간 안에 시장 맥락을 이해할 수 있다.

#### Acceptance Criteria

1. WHEN 브리프 데이터가 존재할 때, THE 프론트엔드 SHALL `aiJudgment` 및 관련 요약 필드를 사용해 핵심 판단 영역을 렌더링한다.
2. WHEN 요약 영역이 렌더링될 때, THE 프론트엔드 SHALL 주변 섹션과 구분되는 시각적 강조를 제공한다.
3. WHEN 상세 페이지가 렌더링될 때, THE 프론트엔드 SHALL 브리프 본문을 읽기 쉬운 장문 레이아웃으로 렌더링한다.
4. IF 데이터 품질 상태가 `degraded` 또는 `critical` 인 경우, THEN THE 프론트엔드 SHALL 요약 또는 인접 영역에서 신뢰 상태를 함께 노출한다.

### Requirement 8: 정량 지표와 마켓 보드 구성

**User Story:**
As a 시장 중심 사용자,
I want 핵심 수치와 시장 보드를 화면 상단 근처에서 빠르게 훑고 싶다,
so that 서사를 읽기 전에 시장 상태를 즉시 파악할 수 있다.

#### Acceptance Criteria

1. WHEN 시장 스냅샷 데이터가 존재할 때, THE 프론트엔드 SHALL 핵심 지표를 상단부의 고가독성 영역에 렌더링한다.
2. WHEN 비트코인, 시장 지표, 기술주 관련 데이터가 존재할 때, THE 프론트엔드 SHALL 이를 새 디자인 시스템에 맞는 공용 프리미티브로 표현한다.
3. IF 값이 캐시 기반이거나 누락된 경우, THEN THE 프론트엔드 SHALL 그 상태를 사용자에게 식별 가능하게 표시한다.
4. WHEN 아카이브 상세 페이지가 렌더링될 때, THE 프론트엔드 SHALL 홈보다 더 밀도 높은 정량 정보 구성을 허용한다.

### Requirement 9: 테마 섹션 유지

**User Story:**
As a 브리프 사용자,
I want 개별 뉴스 이전에 오늘의 주제를 테마별로 묶어 보고 싶다,
so that 시장을 어떤 축으로 읽어야 하는지 먼저 파악할 수 있다.

#### Acceptance Criteria

1. WHEN `topicSummaries` 데이터가 존재할 때, THE 프론트엔드 SHALL 테마 섹션을 별도 블록으로 렌더링한다.
2. WHEN 각 테마가 렌더링될 때, THE 프론트엔드 SHALL 요약과 핵심 지표를 함께 보여준다.
3. IF 일부 테마가 비어 있는 경우, THEN THE 프론트엔드 SHALL 빈 카드 없이 존재하는 테마만 자연스럽게 배치한다.
4. WHEN 홈과 상세 페이지가 렌더링될 때, THE 프론트엔드 SHALL 동일한 테마 해석 레이어를 유지한다.

### Requirement 10: 뉴스 섹션 재구성

**User Story:**
As a 사용자,
I want 핵심 뉴스와 상세 뉴스 흐름을 새 디자인 안에서 자연스럽게 탐색하고 싶다,
so that 요약을 검증하고 원문으로 이어질 수 있다.

#### Acceptance Criteria

1. WHEN 주요 뉴스가 존재할 때, THE 프론트엔드 SHALL 전용 뉴스 섹션에서 이를 렌더링한다.
2. WHEN 뉴스 아이템이 렌더링될 때, THE 프론트엔드 SHALL 제목, 출처, 발행 시각, 관련 메타데이터를 표시한다.
3. WHEN 뉴스 아이템이 원문 링크를 포함할 때, THE 프론트엔드 SHALL 원문 이동 경로를 제공한다.
4. IF 강조용 뉴스와 전체 뉴스가 구분되는 경우, THEN THE 프론트엔드 SHALL 홈과 상세 페이지에서 그 밀도 차이를 반영한다.

### Requirement 11: X 시그널 섹션 분리

**User Story:**
As a 사용자,
I want 뉴스와 X 시그널을 분리해서 보고 싶다,
so that 공식 기사 성격의 정보와 빠른 시장 반응을 구분할 수 있다.

#### Acceptance Criteria

1. WHEN X 시그널이 존재할 때, THE 프론트엔드 SHALL 뉴스와 별도의 전용 섹션으로 렌더링한다.
2. WHEN X 시그널이 렌더링될 때, THE 프론트엔드 SHALL 내용, 시장 영향, 센티먼트, 게시 시각을 표시한다.
3. IF X 시그널이 존재하지 않는 날이라면, THEN THE 프론트엔드 SHALL 섹션 전체를 숨긴다.
4. WHEN 상세 페이지가 렌더링될 때, THE 프론트엔드 SHALL 홈보다 더 많은 X 시그널을 확인할 수 있게 한다.

### Requirement 12: 데이터 기준 및 상태 노출

**User Story:**
As a 신뢰도에 민감한 사용자,
I want 오늘 페이지의 데이터 수집 상태와 기준 시점을 알고 싶다,
so that 콘텐츠를 얼마나 신뢰할지 판단할 수 있다.

#### Acceptance Criteria

1. WHEN 페이지가 렌더링될 때, THE 프론트엔드 SHALL 생성 시각과 기준 시각 정보를 표시한다.
2. WHEN 데이터 품질 상태가 `ok`, `degraded`, `critical` 중 하나로 주어질 때, THE 프론트엔드 SHALL 그 상태를 일관된 방식으로 표시한다.
3. WHEN 번역 상태, 수집 건수, 품질 메모 등 메타데이터가 존재할 때, THE 프론트엔드 SHALL 이를 데이터 기준/상태 영역 또는 이에 준하는 보조 UI로 표시한다.
4. IF 품질 문제가 존재하는 경우, THEN THE 프론트엔드 SHALL 빈 화면이나 무반응 UI 대신 상태를 명시적으로 드러낸다.
5. WHEN 날짜와 시간을 사용자에게 표시할 때, THE 프론트엔드 SHALL `meta.date`를 발행 기준일로, `meta.generatedAt`을 생성 시각으로 구분해 표시한다.

### Requirement 13: 공개 페이지 범위 포함

**User Story:**
As a 공개 사이트 방문자,
I want 주요 공개 페이지가 모두 같은 새 디자인 체계로 보이길 원한다,
so that 서비스 전반의 경험이 일관되게 유지된다.

#### Acceptance Criteria

1. WHEN 이번 마이그레이션이 수행될 때, THE 구현 범위 SHALL 홈 페이지를 포함한다.
2. WHEN 이번 마이그레이션이 수행될 때, THE 구현 범위 SHALL `/archive` 페이지를 포함한다.
3. WHEN 이번 마이그레이션이 수행될 때, THE 구현 범위 SHALL `/archive/[date]` 페이지를 포함한다.
4. IF 홈과 상세 페이지에 상단 공용 내비게이션이 존재하는 경우, THEN THE 프론트엔드 SHALL 동일한 상단 메뉴 경험을 유지한다.

### Requirement 14: 디자인 시스템 및 재사용 프리미티브 구축

**User Story:**
As a 프론트엔드 개발자,
I want 새 디자인을 공용 토큰과 프리미티브로 정리하고 싶다,
so that 이후 유지보수와 확장이 가능해진다.

#### Acceptance Criteria

1. WHEN 새 디자인이 구현될 때, THE 프론트엔드 SHALL 폰트, 색상, 간격, border, radius, shadow, motion에 대한 공용 토큰을 정의한다.
2. WHEN 반복되는 UI 패턴이 존재할 때, THE 프론트엔드 SHALL 섹션, 카드, 레이블, 데이터 블록 등에 대한 재사용 가능한 프리미티브를 제공한다.
3. WHEN 페이지별 UI가 구현될 때, THE 페이지 컴포넌트 SHALL 공용 프리미티브를 우선 사용한다.
4. IF 특정 스타일이 토큰화되기 어렵다면, THEN THE 프론트엔드 SHALL 예외 범위를 국소화하고 문서화한다.

### Requirement 15: 데이터 렌더링 모델 유지

**User Story:**
As a 유지보수자,
I want 프론트가 계속 JSON 기반 표시 레이어로 동작하길 원한다,
so that 데이터 생산 파이프라인과 프론트의 책임이 분리된다.

#### Acceptance Criteria

1. WHEN 페이지가 빌드될 때, THE 프론트엔드 SHALL 기존 JSON 데이터 모델을 사용해 렌더링한다.
2. WHEN 아카이브 정적 경로가 생성될 때, THE 프론트엔드 SHALL 브리프 인덱스 데이터에서 경로를 파생한다.
3. IF 브리프 데이터가 누락되거나 잘못된 경우, THEN THE 프론트엔드 SHALL 진단 가능한 방식으로 빌드 또는 경로 생성 단계에서 실패를 드러낸다.
4. WHEN 공개 페이지가 정상 동작할 때, THE 프론트엔드 SHALL 일반 렌더링 경로에서 클라이언트 재요청을 필수 전제로 두지 않는다.
5. WHEN 이번 마이그레이션이 수행될 때, THE 프론트엔드 SHALL 현재 파이프라인이 제공하는 `index.json` 및 날짜별 브리프 JSON 계약을 변경하지 않고 소비한다.
6. IF 새 디자인 구현을 위해 데이터 확장이 필요하다고 판단되는 경우, THEN THE 프론트엔드 SHALL 기존 계약 변경을 전제하지 않고 파생 표현 또는 별도 후속 스펙으로 분리한다.

### Requirement 16: 성능 및 접근성 가드레일

**User Story:**
As a 공개 사용자,
I want 시각 효과가 풍부해져도 페이지가 읽기 쉽고 빠르게 동작하길 원한다,
so that 다양한 디바이스와 환경에서 문제 없이 사용할 수 있다.

#### Acceptance Criteria

1. WHEN 애니메이션과 시각 효과가 적용될 때, THE 프론트엔드 SHALL 모바일과 데스크톱 모두에서 콘텐츠 가독성과 조작 가능성을 유지한다.
2. WHEN 상태나 상승/하락을 시각적으로 표현할 때, THE 프론트엔드 SHALL 색상만으로 의미를 전달하지 않는다.
3. WHEN 상호작용 UI가 제공될 때, THE 프론트엔드 SHALL 키보드 접근성과 포커스 표시를 유지한다.
4. IF 특정 섹션에 무거운 클라이언트 동작이 필요하지 않다면, THEN THE 프론트엔드 SHALL 불필요한 클라이언트 번들링 없이 정적 또는 서버 렌더링 상태를 유지한다.

### Requirement 17: 공개 부가 산출물 및 메타데이터 유지

**User Story:**
As a 공개 사이트 운영자,
I want 기존 공개 산출물과 메타데이터가 디자인 마이그레이션 이후에도 유지되길 원한다,
so that 배포 결과물의 활용성과 검색/배포 연동이 깨지지 않는다.

#### Acceptance Criteria

1. WHEN 정적 빌드가 수행될 때, THE 프론트엔드 SHALL 기존과 동일하게 `rss.xml` 과 `llms.txt` 를 생성하고 공개 경로로 노출한다.
2. WHEN 사용자가 브리프 상세 본문을 읽을 때, THE 프론트엔드 SHALL 기존과 동일하게 브리프 마크다운 다운로드 기능을 유지한다.
3. WHEN 홈, 아카이브 목록, 아카이브 상세 페이지가 렌더링될 때, THE 프론트엔드 SHALL 각 페이지의 메타데이터와 공유용 메타 정보를 유지하거나 동등한 수준으로 재구성한다.
4. IF 푸터나 보조 내비게이션 구조가 변경되는 경우, THEN THE 프론트엔드 SHALL `rss.xml`, `llms.txt`, 아카이브, 운영 원칙 등 기존 공개 진입점에 대한 접근 경로를 유지한다.
5. WHEN 홈 페이지 메타데이터가 생성될 때, THE 프론트엔드 SHALL `description`에 `글로벌 마켓 데이터의 정교한 연결, 원본의 무결성으로 완성하는 투자 주권.` 고정 문구를 사용한다.
