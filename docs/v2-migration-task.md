# V2 이메일/브리핑 구조 이관 상세 체크리스트 (Task List)

본 문서는 `docs/v2-migration-design.md`를 바탕으로, V1(레거시) 코드를 V2 코드로 완전히 개편하기 위한 **상세 행동 지침(Actionable Task List)** 입니다.
우선순위가 가장 높은 핵심 오류 부분(파이프라인 오작동 방지)부터 순차적으로 나열되어 있습니다.

---

## 🚀 Priority 1: 구조 검증(Validation) 로직 최신화
**목표:** LLM이 V2 규격(0번~6번 섹션)으로 잘 생성한 브리핑을 `LAYER` 문자열이 없다는 이유로 버리지 않게 만듭니다.

- [ ] `src/morning_brief/briefing.py` 열기
- [ ] 상단에 선언된 하드코딩 상수 `REQUIRED_LAYER_HEADINGS` 삭제
- [ ] V2 필수 섹션 검사용 신규 상수 추가
  ```python
  REQUIRED_V2_SECTIONS = (
      "section_0",    # 0. 오늘의 핵심
      "section_1",    # 1. 거시 지표
      "section_2",    # 2. 미국 증시
      "section_3",    # 3. BTC & 크립토
      "section_4_2",  # 4-2. 핵심 뉴스 5선
      "section_6",    # 6. 이벤트 캘린더
  )
  ```
- [ ] `_brief_structure_issues(text: str)` 함수 리팩터링
  - 기존의 `extract_brief_structure` 대신 `morning_brief.brief_formatting.extract_sections`를 임포트하여 `section_map` 파싱 
  - `REQUIRED_V2_SECTIONS` 내의 키가 `section_map`에 존재하지 않거나 빈 문자열인지 확인하여 `issues` 리스트에 에러 삽입
- [ ] V1용 글머리 기호 수 확인(Bullet count) 로직 완전 제거 (`LAYER 2`, `LAYER 3` 분기문 삭제)
- [ ] V2용 글머리 기호 수 검증 로직 추가 (선택 사항 혹은 필수)
  - `section_4_2`(뉴스 항목)에 ①~⑤ 글머리 텍스트(block)가 최소 2개 이상인지 확인
  - `section_2`(미국 증시)에 주가 등락률 아이템 목록이 충분히 나열되었는지 확인

---

## 🚀 Priority 2: 기본(Fallback) 생성 함수의 텍스트 포맷 교체
**목표:** 파이프라인에서 오류가 나거나 생성 품질이 나쁠 경우 뱉어내는 안전 브리핑 세트가 V1(1. LAYER 1 |)이 아닌 V2 템플릿 양식을 따르도록 맞춥니다.

- [ ] `src/morning_brief/briefing.py` 내부의 `_fallback_brief(packet, timezone)` 함수 찾기
- [ ] `body = f"""..."""` 템플릿 변수를 아래와 같이 완전한 V2 구조 양식에 맞게 맵핑:
  ```markdown
  Morning Market Brief ({date_str})

  0. 오늘의 핵심
  오늘은 {judgement} 국면입니다. {judgement_reason}
  {kospi_impact}

  1. 거시 지표 Dashboard
  {거시 지표 목록 및 VIX/나스닥 선물 흐름}

  2. 미국 증시
  {주요 종목 등락률}

  3. BTC & 크립토
  {BTC 현물 라인}
  {공포탐욕지수 라인}

  ...
  (--> 기존 layer1_easy_summary, layer2_headline 등도 적절한 섹션 내부로 재조합합니다.)
  ```

---

## 📈 Priority 3: 레거시 파서(V1 Legacy Parser) 코드 클린업
**목표:** 잔존한 V1 파서 로직과 문자열 감지 정규식을 지워 코드 복잡도를 낮추고, 모든 본문 텍스트가 V2 하나로만 파싱되도록 합니다. 이를 통해 **이메일이 통째로 텅 비는 오류를 원천 차단**합니다.

- [ ] `src/morning_brief/brief_formatting.py` 열기
- [ ] `_is_legacy_layer_format(body: str)` 함수 완전 삭제
- [ ] `extract_sections(body: str)` 최상단의 `if _is_legacy_layer_format(body):` 폴백 리턴 분기문 삭제
- [ ] 이제 더 이상 사용되지 않는 **V1 전용 상수 및 함수 패키지 전체 삭제**:
  - `CONCLUSION_LABELS`, `METRIC_LABELS`, `INSIGHT_LABELS`, `WATCH_LABELS`, `MACRO_LABELS` 등 집합(Set)
  - `split_section_groups`
  - `extract_brief_structure`
  - `_collect_section_groups`
  - `_backfill_section_groups_without_labels`
- [ ] `src/morning_brief/emailer.py` 확인: `_build_email_context()` (V1 이메일 렌더 메인 함수)가 아직 호출되는 영역이 있는지 점검 및 필요 시 V2 로직(`_build_email_context_v2`) 사용으로 단일화하고 템플릿도 V2 전용(`email_base.html.j2`)으로 고정.

---

## 🛠 Priority 4: 테스트(Unit Test) 수정 및 핫픽스 검수
**목표:** 변경된 구조가 정상 동작하는지 검증합니다. 기존 테스트 코드가 구형 `LAYER 1` 텍스트를 예상했다면 그것부터 갱신해야 합니다.

- [ ] (로컬) `test` 디렉터리 내에 `brief_formatting.py`나 `briefing.py`를 호출하는 단위 테스트 수정 
  - 레거시 텍스트 모듈 삭제로 인해 실패하는 테스트케이스는 삭제하거나 V2 Mock 데이터로 교체
- [ ] 파이프라인 수동 테스트 실행: `python main.py once --print-brief`
- [ ] 콘솔 출력 및 실제 이메일 템플릿에 `section_1` ~ `section_6`의 데이터가 정상적으로 바인딩(표출)되는지 체크
