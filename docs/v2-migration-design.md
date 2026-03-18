# V2 브리핑 구조 이관(Migration) 및 설계 개선 (Design Document)

## 1. 개요 및 목적 (Background & Objective)
현재 LLM에게 전달하는 프롬프트(V2. Section 0~6 방식)와 애플리케이션 내부에서 결과를 검증하고 예외 처리를 담당하는 파이썬 코드(V1. `LAYER 1~3` 방식)의 구조가 일치하지 않아, 불필요한 오류(오판)와 빈 이메일 섹션이 발송되는 버그가 발생하고 있습니다. 

본 문서의 목적은 이 불일치를 제거하고, 파이프라인 전체(생성 ➔ 검증 ➔ 폴백 ➔ 파싱 ➔ 렌더링)가 최신 V2 구조를 단일 진실 공급원(Single Source of Truth)으로 삼도록 완전히 이관하는 설계 변경안을 제시하는 것입니다.

---

## 2. 변경 대상 및 구조 설계안 (Architecture Changes)

### 2.1 `src/morning_brief/briefing.py` : 구조 검증 로직 개편
**현재 문제**: `REQUIRED_LAYER_HEADINGS` 상수에 예전 V1 포맷이 하드코딩되어, V2 규격으로 정상 생성된 브리핑을 "불완전하다"고 판단합니다.
**개선 설계**:
- V2 필수 섹션 헤더를 정의하는 상수 `REQUIRED_V2_SECTIONS`를 신설합니다.
  ```python
  REQUIRED_V2_SECTIONS = (
      "section_0",  # 0. 오늘의 핵심
      "section_1",  # 1. 거시 지표 Dashboard
      "section_2",  # 2. 미국 증시
      "section_3",  # 3. BTC & 크립토
      "section_4_2", # 4-2. 핵심 뉴스 5선
  )
  ```
- `_brief_structure_issues(text: str)` 로직을 개편합니다.
  - V1 로직인 `extract_brief_structure` 대신 `extract_sections(text)`를 호출하여 파싱된 `SectionMap`을 가져옵니다.
  - V2 필수 키(`REQUIRED_V2_SECTIONS`)가 맵에 제대로 포함되었는지 검사합니다.
  - 글머리 기호(bullet count) 검증 역시 새로운 키를 바탕으로 실행합니다. (예: `section_2`와 `section_4_2` 항목 내 빈도 분석)

### 2.2 `src/morning_brief/briefing.py` : 폴백(Fallback) 생성 포맷 최신화
**현재 문제**: 실패 시 생성되는 하드코딩 텍스트 `_fallback_brief()`가 예전 V1 포맷인 `1. LAYER 1 | 오늘 한줄 판단` 양식을 사용합니다.
**개선 설계**: 
- `_fallback_brief()` 내부의 멀티라인 스트링(f-string)을 전부 V2 프롬프트와 동일한 양식(`0. 오늘의 핵심`, `1. 거시 지표 Dashboard`...)으로 전면 교체합니다.
- 예시:
  ```markdown
  Morning Market Brief ({date_str})

  0. 오늘의 핵심
  오늘은 {judgement} 국면입니다.
  {judgement_reason}

  1. 거시 지표 Dashboard
  {거시 지표 목록}

  2. 미국 증시
  {주요 종목 등락률}
  ...
  ```

### 2.3 `src/morning_brief/brief_formatting.py` : 레거시 V1 지원 중단
**현재 문제**: 폴백 텍스트가 V1 포맷인 것을 가려내기 위해 잔존한 `_is_legacy_layer_format`과 각종 구형 파싱 처리가 오류를 가중시킵니다.
**개선 설계**:
- `_fallback_brief()`가 V2 텍스트를 출력하도록 수정된 직후, `_is_legacy_layer_format`을 검사하는 분기 처리(`if _is_legacy_layer_format(body):`)와 로컬 폴백 매핑 코드를 완전히 삭제합니다.
- 즉, 모든 LLM 출력 텍스트는 오직 V2 정규식(`SECTION_HEADING_V2_RE = re.compile(r"^(\d+(?:-\d+)?)\.\s+(.+)$")`)에 의해서만 파싱되어 `SectionMap`으로 매핑되도록 처리 구조를 단일화합니다.

---

## 3. 이관 전략 및 테스트 (Migration Strategy)

1. **Phase 1: Validation(검증 함수) 개편**
   - `briefing.py`의 `_brief_structure_issues()`와 내부 상수 규칙을 V2로 변경합니다. 이 단계부터 정상 생성된 LLM 텍스트가 강제 폴백(Fallback)되지 않고 온전히 살아서 메일 렌더러로 전달됩니다.
   
2. **Phase 2: Fallback Generator(폴백 함수) 개편**
   - `briefing.py`의 `_fallback_brief()` 템플릿의 문자열 출력을 V2 양식에 맞춥니다.
   - [검증 방법]: `_brief_structure_issues()`가 일부러 실패하도록 테스트 코드를 수정한 뒤, 강제로 도출된 폴백 브리핑 문자열이 정상적으로 이메일에 렌더링(빈 섹션이 생기지 않는지)되는지 확인합니다.
   
3. **Phase 3: V1 Legacy Code Clean-up**
   - `brief_formatting.py` 내의 `_is_legacy_layer_format()` 및 V1 파서 로직들(`split_section_groups` 등)을 deprecated로 취급하거나 안전하게 삭제하여 파일 크기와 복잡도를 줄입니다.

## 4. 기대 효과 (Impact)
- **일관성 확보**: `LLM 프롬프트 생성 ➔ 결과물 검증 ➔ 파싱 로직 ➔ 폴백 데이터 ➔ UI 렌더링`까지 이어지는 모든 사이클이 V2(Section 번호 기준)라는 일관된 데이터 흐름을 따릅니다.
- **오동작 방지**: LLM이 잘 생성한 결과물도 오판하여 강제 폐기하던 파이프라인 누수를 완벽히 억제합니다.
- **빈 섹션 이슈 해결**: 이메일 템플릿 렌더러(`emailer.py`)가 의도한 모든 V2 섹션 데이터를 정상적으로 수신하여, 누락되거나 비어있는 이슈 브리핑 영역이 완전히 사라집니다.
