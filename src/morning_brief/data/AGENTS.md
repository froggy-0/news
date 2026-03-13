# AGENTS.md

`src/morning_brief/data/`는 외부 공급자 계약과 품질 게이트를 다루는 영역입니다.

- fallback, retry, ranking, parser 변경은 반드시 관련 pytest를 함께 수정합니다.
- 공급자별 요청 간격과 quota 처리는 `provider_runtime` 계층으로 모읍니다.
- 수집기는 가능한 한 부분 성공을 허용하고, 한 provider 장애가 전체 결과를 무너뜨리지 않도록 유지합니다.
- warning 로그는 후속 조치가 가능한 문맥을 담아야 합니다.
- 새 provider를 추가하면 신뢰도, rate, retry 기준을 README나 관련 문서에 기록합니다.
