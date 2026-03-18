# V2 브리핑 구조 이관(Migration) 버그 및 개선 요구사항

## 1. 개요
현재 발송 중인 이메일 브리핑에서 일부 데이터 섹션이 비어 있거나 일관되지 않으며, 예전(V1) 레거시 텍스트 포맷 (예: `LAYER 1 | 오늘 한줄 판단`)이 그대로 노출되는 문제가 발생하고 있습니다.

## 2. 명확한 문제점(Root Cause)

이 문제는 파이프라인의 **프롬프트 템플릿은 최신(V2)** 으로 업데이트되었으나, 생성된 문자열을 확인하는 **파이썬 내부 구조 검증 및 폴백 로직은 여전히 구버전(V1)** 에 머물러 있어 발생되는 충돌입니다.

1. **V1/V2 구조 불일치**:
   - `src/morning_brief/prompts/brief_instructions.j2`는 `0. 오늘의 핵심`부터 `6. 이벤트 캘린더`까지 V2 기반 구조 생성을 지시합니다.
   - 하지만 `src/morning_brief/briefing.py`의 함수 `_brief_structure_issues()`는 아직 V1 구조(`LAYER 1`, `LAYER 2`, `LAYER 3`)를 찾도록 하드코딩(`REQUIRED_LAYER_HEADINGS`)되어 있습니다.

2. **잘못된 오류 감지 및 강제 롤백(Fallback)**:
   - LLM이 알맞게 V2 형식의 브리핑을 작성하더라도, 파이프라인 검증 로직은 `LAYER 1` 텍스트를 찾지 못해 इसे 불량(Incomplete)으로 간주합니다.
   - 검증 실패 트리거가 작동하여 `_fallback_if_incomplete()`를 호출하게 되고, 파이프라인은 폴백 브리핑(`_fallback_brief()`) 문자열로 원본 메시지를 덮어씁니다.

3. **레거시 폴백 데이터와 V2 이메일 템플릿의 파싱 오류**:
   - 새로 덮어쓰인 폴백 문자열 역시 구버전인 `1. LAYER 1 | 오늘 한줄 판단` 형식으로 하드코딩되어 반환됩니다.
   - 이후 `src/morning_brief/brief_formatting.py`의 `extract_sections()`가 이 폴백 텍스트를 파싱할 때 V1 레거시 구조임을 감지해 본문 데이터 전체를 단순히 `section_0`에 통째로 밀어 넣습니다.
   - 이로 인해 `section_1`부터 `section_6`까지는 모두 **빈 문자열** 상태가 됩니다.
   - 마지막으로 `src/morning_brief/emailer.py`의 `_build_email_context_v2()`가 V2 이메일 발송용 HTML 구성을 위해 `section_1`, `section_2` 등의 배열 항목에 접근하지만, 텍스트가 텅 비었기 때문에 이메일 템플릿에는 총 항목과 글머리 기호만 뜨는 '빈 섹션 에러'가 발생합니다.

## 3. 세부 요구사항 (Action Items)

비어있는 이메일 섹션 오류를 올바르게 해결하고, 레거시 이관 작업을 마무리하기 위해 다음 코드를 수정해야 합니다.

### [필수: 파이프라인 검증 로직 업데이트]
- **Target**: `src/morning_brief/briefing.py` 내 `_brief_structure_issues()`
- **Action**: V2 구조의 헤더("0. 오늘의 핵심", "1. 거시 지표 Dashboard", "2. 미국 증시" 등)를 기반으로 브리핑 누락 여부를 판단하도록 상수를 새롭게 정의합니다.
- 기존 상수인 `REQUIRED_LAYER_HEADINGS` 배열을 V2 구조용으로 대체하거나 변경해야 합니다.
- 또한 `MIN_LAYER_TWO_BULLETS` 확인 로직들을 `Section 4-2` (핵심 뉴스)나 `Section 2` (미국 증시)의 항목 수를 카운팅하는 방식으로 변경해야 합니다.

### [필수: 폴백(Fallback) 생성 로직 V2 포맷 매핑]
- **Target**: `src/morning_brief/briefing.py` 내 `_fallback_brief()`
- **Action**: 코드로 직접 생성하는 레거시 폴백 스트링도 더 이상 `1. LAYER 1`이 아닌, `brief_instructions.j2`의 V2 약속과 동일한 `1. 거시 지표 Dashboard...` 양식으로 출력되도록 전체 템플릿 리터럴을 재작성합니다.

### [권장: V1 지원 중단(Deprecation) 및 클린업]
- **Target**: `src/morning_brief/brief_formatting.py`
- **Action**: 상단에 하드코딩되어 남아 있는 `_is_legacy_layer_format`과 V1 구조를 후방 호환해 주던 파싱 로직(`extract_brief_structure`, `split_section_groups` 등)을 필요 없다면 제거합니다. (단, 기존 이메일 렌더러가 완전히 제거된 이후 진행)
