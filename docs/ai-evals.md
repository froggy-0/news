# AI Eval Matrix

이 문서는 AI 에이전트가 이 저장소를 수정할 때 어떤 변경에 어떤 검증을 연결해야 하는지 정리합니다. 목표는 “수정은 했는데 어떤 회귀를 봐야 하는지 모른다”는 상태를 없애는 것입니다.

## 공통 완료 조건

- `make fmt`
- `make lint`
- `make test`

모든 변경은 위 세 단계를 기본으로 통과해야 합니다. 아래 항목은 여기에 추가로 필요한 집중 검증입니다.

## 1. 공급자/수집기 계약 변경

대상:
- `src/morning_brief/data/`
- `src/morning_brief/data/sources/`
- `src/morning_brief/data/news_selection.py`

추가 검증:
- `tests/test_http_client.py`
- `tests/test_btc_etf_official.py`
- `tests/test_market_btc_official_flow.py`
- `tests/test_market_reliability.py`
- `tests/test_news_quality.py`
- `tests/test_grok_official_signals.py`
- `tests/test_perplexity_search.py`

확인 질문:
- 재시도 대상과 비재시도 대상이 분리됐는가
- provider quota 감지 후 동일 실행에서 일관되게 우회하는가
- 한 source 실패가 전체 집계를 무너뜨리지 않는가
- warning 로그만으로 원인 추적이 가능한가

## 2. 브리핑/프롬프트/메일 렌더링 변경

대상:
- `src/morning_brief/briefing.py`
- `src/morning_brief/brief_review.py`
- `src/morning_brief/brief_formatting.py`
- `src/morning_brief/emailer.py`
- `src/morning_brief/prompts/`

추가 검증:
- `tests/test_prompting.py`
- `tests/test_briefing_quality.py`
- `tests/test_emailer.py`

확인 질문:
- 섹션 구조와 숫자 표현이 깨지지 않는가
- 검수/재작성 루프가 과도한 문체 흔들림을 만들지 않는가
- 메일 본문과 저장 브리핑이 같은 규칙으로 해석되는가

## 3. 파이프라인/품질 게이트 변경

대상:
- `src/morning_brief/pipeline.py`
- `src/morning_brief/data/data_quality.py`
- `src/morning_brief/data/news_rollout.py`

추가 검증:
- `tests/test_pipeline_quality.py`
- `tests/test_pipeline_observability.py`
- `tests/test_news_quality.py`
- `tests/test_research_backfill.py`

확인 질문:
- fallback 트리거가 더 정확해졌는가
- Perplexity/Grok/OpenAI 역할 경계가 코드와 로그에 명시됐는가
- 품질 저하 시 보강 경로가 예상대로 열리는가
- OpenAI 실패 시 발송을 건너뛰고 observability 산출물이 남는가
- rollout 판단이 노이즈 없이 작동하는가

## 4. 설정/환경변수/운영 변경

대상:
- `src/morning_brief/config.py`
- `README.md`
- `.github/workflows/`

추가 검증:
- `tests/test_config.py`
- GitHub Actions workflow 문법 확인

확인 질문:
- 기본값과 README 설명이 일치하는가
- CI와 로컬 명령이 다른 기준으로 움직이지 않는가

## 5. 리뷰 루프

최종 제출 전 아래를 짧게 점검합니다.

- 이 변경은 정확성을 높였는가
- 기존 경고를 줄였는가, 아니면 새 경고를 만들어냈는가
- 테스트가 변경 이유를 설명할 만큼 구체적인가
- 문서가 실제 동작과 맞는가
