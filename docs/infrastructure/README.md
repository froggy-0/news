# Infrastructure Docs

이 문서는 SOVEREIGNWON 운영에 필요한 배치, 배포, Lambda, Supabase, Cloudflare 경로를 정리합니다.

## GitHub Actions

| Workflow | 파일 | 역할 |
| --- | --- | --- |
| Generate Sovereign Briefing | `.github/workflows/morning-brief.yml` | 매일 Sentiment Join, 브리핑 생성, public JSON 발행, frontend 배포 |
| Build Sentiment Time Join | `.github/workflows/sentiment-join.yml` | 수동 Sentiment Join 실행 |
| Deploy Frontend to Production | `.github/workflows/frontend-pages.yml` | 수동 Cloudflare Pages production 배포 |
| Replay Realtime Risk Gate | `.github/workflows/replay-risk-gate.yml` | 월 1회 realtime risk gate 리플레이 |
| Repository Checks | `.github/workflows/ci.yml` | Python format/lint/test/typecheck |

## Runtime 인프라

| 영역 | 경로 | 설명 |
| --- | --- | --- |
| EC2 Arena | `deploy/`, `src/arena/server.py` | Arena 상시 프로세스 실행 대상 |
| Binance futures Lambda | `lambda/binance_futures/` | GitHub Actions US IP의 Binance FAPI 제한을 우회하는 Seoul Lambda 프록시 |
| Cloudflare Pages | `frontend/wrangler.toml`, `frontend/out/` | public frontend 정적 배포 |
| R2 public JSON | `src/morning_brief/public_site.py`, Sentiment Join storage | 브리핑/분석 JSON 공개 저장소 |
| Supabase | `supabase/migrations/`, `src/morning_brief/subscriptions/`, `src/arena/positions.py` | 구독, signal_log, arena ledger/storage |

## 보안 기준

- `.env`, `.env.*` 파일은 읽거나 문서에 값으로 남기지 않습니다.
- GitHub Actions secrets/vars는 이름과 역할만 문서화합니다.
- Supabase service role key, R2 secret, AWS key, API token은 환경변수로만 전달합니다.
- 배포 전에는 관련 workflow가 실제로 참조하는 환경변수 이름과 코드의 설정명을 대조합니다.

## 관련 문서

| 문서 | 내용 |
| --- | --- |
| [../arena/operations/access-runbook.md](../arena/operations/access-runbook.md) | Arena 서버/DB 접근과 상태 확인 |
| [../arena/operations/deploy-runbook.md](../arena/operations/deploy-runbook.md) | Arena EC2 배포/재시작/검증 |
| [../arena/operations/dashboard-runbook.md](../arena/operations/dashboard-runbook.md) | Arena 대시보드 배포 |
| [../logging-ops.md](../logging-ops.md) | 로깅 운영 |
| [../subscriptions-ops.md](../subscriptions-ops.md) | 구독 운영 |
| [../data-sources.md](../data-sources.md) | Lambda futures fallback 등 데이터 소스 |
