# Codex Ops Setup

이 문서는 SOVEREIGN BRIEF 저장소에서 Codex의 project config, subagent, repo skill을 어떻게 쓰는지 정리합니다. 기준은 OpenAI 공식 문서의 project `.codex/config.toml`, `AGENTS.md`, subagent, Apps SDK 운영 모델입니다.

참고:
- <https://developers.openai.com/codex/config-basic>
- <https://developers.openai.com/codex/config-reference>
- <https://developers.openai.com/codex/guides/agents-md>
- <https://developers.openai.com/codex/subagents>
- <https://developers.openai.com/apps-sdk/build/chatgpt-ui>

## 1. Project config

- project-level 기본값은 `.codex/config.toml`에서 관리합니다.
- 메인 모델은 `gpt-5.4`, read-heavy helper는 `gpt-5.4-mini`로 나눕니다.
- 이 저장소는 write 충돌을 줄이기 위해 `max_threads = 4`, `max_depth = 1`을 기본으로 둡니다.
- `Context7` MCP는 project config에 remote HTTP server로 등록했습니다. 첫 사용 시 OAuth 로그인이 필요할 수 있습니다.
- 공통 탐색은 repo root `AGENTS.md`와 `docs/development-standards.md`를 먼저 따릅니다.

## 2. Custom subagents

| 이름 | 파일 | 용도 |
| --- | --- | --- |
| `explorer` | `agents/explorer.toml` | 코드, 테스트, 로그를 빠르게 읽고 관련 파일을 먼저 좁힐 때 |
| `pipeline_investigator` | `agents/pipeline-investigator.toml` | GitHub Actions, observability, fallback 회귀를 추적할 때 |
| `docs_researcher` | `agents/docs-researcher.toml` | OpenAI 또는 외부 공급자 문서를 먼저 확인할 때 |
| `brief_reviewer` | `agents/brief-reviewer.toml` | 브리핑 구조, 검수, rewrite, email 품질을 점검할 때 |
| `provider_auditor` | `agents/provider-auditor.toml` | parser, ranking, retry, fallback 계약을 읽기 위주로 점검할 때 |
| `workflow_run_auditor` | `agents/workflow-run-auditor.toml` | run artifact, 저장 브리핑, 메일 원문을 함께 대조할 때 |
| `apps_operator` | `agents/apps-operator.toml` | Apps SDK 기반 운영 UI나 widget tool 구성을 설계할 때 |

## 3. Repo skills

| 이름 | 위치 | 용도 |
| --- | --- | --- |
| `brief-quality-review` | `.agents/skills/brief-quality-review/` | 브리핑 생성, 검수, fallback, email 구조 점검 |
| `pipeline-log-triage` | `.agents/skills/pipeline-log-triage/` | pipeline 실패, degraded, cache, observability 분석 |
| `provider-contract-audit` | `.agents/skills/provider-contract-audit/` | 공급자 계약, parser, ranking, retry 변경 검토 |
| `workflow-run-audit` | `.agents/skills/workflow-run-audit/` | GitHub run artifact, observability, 메일 원문 대조 |
| `news-source-quality` | `.agents/skills/news-source-quality/` | Perplexity/Sonar/Grok/RSS 뉴스 품질과 필터 drift 분석 |
| `email-render-audit` | `.agents/skills/email-render-audit/` | markdown, email context, template, MIME 결과 비교 |
| `brief-ops-app` | `.agents/skills/brief-ops-app/` | SOVEREIGN BRIEF 전용 Apps SDK 운영 UI 설계 |
| `financial-services-research` | `.agents/skills/financial-services-research/` | Anthropic financial-services-plugins를 Codex용 on-demand 리서치 워크플로로 단순 포팅 |

## 4. Frontend / Apps SDK 원칙

- 이 저장소는 제품 UI보다 운영 UI가 먼저입니다.
- ChatGPT Apps SDK를 붙일 때는 `apps/brief-ops/server`와 `apps/brief-ops/web`를 기본 구조로 잡습니다.
- tool은 한 intent당 하나씩 나누고, run summary 같은 작은 데이터만 `structuredContent`에 둡니다.
- 큰 observability payload, raw mail, audit detail은 `_meta`로 분리합니다.
- Apps SDK 작업은 global `openai-docs`, `chatgpt-apps`, `frontend-design` skill을 먼저 사용한 뒤 진행합니다.
- `frontend-design` skill은 user-level 경로 `~/.codex/skills/frontend-design`에 설치되어 있고, repo의 `brief-ops-app` skill과 함께 쓰는 것을 기본으로 봅니다.

## 5. 권장 사용 순서

1. 실패 분석: `pipeline-log-triage` 또는 `workflow-run-audit`
2. 공급자 변경: `provider-contract-audit`
3. 브리핑/이메일 품질: `brief-quality-review`, `email-render-audit`
4. 뉴스 품질: `news-source-quality`
5. 운영 UI 설계: `brief-ops-app` + global `chatgpt-apps`
6. 금융 업무형 리서치: `financial-services-research`

## 5-1. Claude plugin 포팅 메모

- Anthropic의 `financial-services-plugins`는 Claude 전용 plugin 포맷이므로 Codex에 직접 설치하지 않습니다.
- 이 저장소에서는 repo skill + 필요 시 MCP 설정으로 대응합니다.
- 기본 전략은 자동 상시 활성화가 아니라 on-demand 사용입니다.
- 상세 기준은 [docs/codex-financial-services-plugins.md](codex-financial-services-plugins.md)를 따릅니다.

## 6. Frontend QA와 Playwright

- macOS에서 일반 `Google Chrome` 앱이 이미 열려 있으면, Codex 내장 Playwright의 persistent Chrome context가 `기존 브라우저 세션에서 여는 중입니다.` 메시지와 함께 실패할 수 있습니다.
- 원인:
  - 내장 Playwright는 설치된 `Google Chrome.app`을 직접 띄우고
  - macOS는 같은 앱 번들을 별도 persistent GUI 인스턴스로 띄우지 않고 기존 세션으로 요청을 넘기기 때문입니다.
- 이 저장소에서는 로컬 프론트 QA 시 내장 Playwright보다 `Chromium` 기반 CLI 경로를 기본값으로 둡니다.
- 사용:
  - `cd frontend && npm run qa:playwright`
  - 특정 URL: `cd frontend && npm run qa:playwright -- http://localhost:3000 archive`
- 산출물:
  - `output/playwright/<name>-mobile.png`
  - `output/playwright/<name>-desktop.png`
- 내장 Playwright를 꼭 써야 하면 먼저 일반 `Google Chrome` 앱을 종료한 뒤 다시 시도합니다.
