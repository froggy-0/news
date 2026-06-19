# Arena Access Runbook

작성일: 2026-06-19

이 문서는 현재 운영 중인 Arena EC2와 Supabase 상태를 확인하는 최소 절차다. 시크릿 값은 출력하지 않는다.

## 현재 운영 접속 정보

| 항목 | 값 |
| --- | --- |
| EC2 public IP | `3.39.201.112` |
| SSH user | `ubuntu` |
| SSH key | `~/.ssh/arena_ed25519` |
| remote app dir | `/home/ubuntu/news` |
| systemd service | `arena.service` |
| DB | Supabase |
| env source | local zsh login env 또는 remote `/home/ubuntu/news/.env` |

## 서버 접속

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112
```

원격에서 앱 디렉터리로 이동:

```bash
cd /home/ubuntu/news
```

## 서버 상태 확인

로컬에서 한 번에 확인:

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'systemctl is-active arena.service && systemctl show arena.service -p ActiveState -p SubState -p ExecMainStatus -p NRestarts --no-pager'
```

최근 로그:

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'journalctl -u arena.service -n 120 --no-pager --output=short-iso'
```

실시간 로그 tail:

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'journalctl -u arena.service -f --output=short-iso'
```

## 서버 재시작

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'sudo systemctl restart arena.service && systemctl is-active arena.service'
```

재시작 직후에는 앱이 즉시 1회 cycle을 실행한다. 같은 4H candle의 `data_timestamp`에 run이 여러 개 생길 수 있으므로 분석 시 대표 run 선택 정책이 필요하다.

## 배포

현재 운영 EC2의 `/home/ubuntu/news`는 Git checkout이 아니라 경량 배포 디렉터리다. 따라서 `deploy/deploy.sh`의 `git pull` 방식은 현재 서버에서는 그대로 동작하지 않는다.

현재 검증된 배포 방식:

```bash
cd /Users/giwon/code/news
rsync -az --delete --exclude='__pycache__/' --exclude='*.pyc' \
  -e 'ssh -i ~/.ssh/arena_ed25519' \
  src/arena/ ubuntu@3.39.201.112:/home/ubuntu/news/src/arena/

rsync -az -e 'ssh -i ~/.ssh/arena_ed25519' \
  requirements.txt ubuntu@3.39.201.112:/home/ubuntu/news/requirements.txt

ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'cd /home/ubuntu/news && .venv/bin/python -m compileall -q src/arena && sudo systemctl restart arena.service && systemctl is-active arena.service'
```

배포 후 확인:

```bash
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'systemctl is-active arena.service && journalctl -u arena.service -n 80 --no-pager --output=short-iso'
```

## DB 접속 원칙

- Supabase Dashboard SQL Editor를 기본 수동 접속 경로로 둔다.
- 로컬 자동 조회는 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 zsh 로그인 환경에서 읽는다.
- `.env`, `.env.*`, service role key 값은 출력하지 않는다.
- 문서나 터미널 캡처에 credential 값을 남기지 않는다.

환경변수 존재 여부만 확인:

```bash
zsh -ic 'test -n "$SUPABASE_URL" && echo SUPABASE_URL=present || echo SUPABASE_URL=missing; test -n "$SUPABASE_SERVICE_ROLE_KEY" && echo SUPABASE_SERVICE_ROLE_KEY=present || echo SUPABASE_SERVICE_ROLE_KEY=missing'
```

## Supabase SQL Editor 확인 쿼리

최신 run:

```sql
select
  run_id,
  started_at,
  completed_at,
  status,
  runtime,
  symbol,
  interval,
  data_timestamp,
  strategy_version,
  params_version,
  risk_model_version,
  capture_status,
  capture_error_count,
  capture_warnings
from arena_runs
order by started_at desc
limit 5;
```

최신 run의 decision:

```sql
select
  algo_id,
  signal,
  action,
  current_position_id,
  resulting_position_id,
  created_at,
  reason,
  risk_decision,
  risk_snapshot
from arena_decisions
where run_id = '<RUN_ID>'
order by algo_id;
```

최근 포지션:

```sql
select
  id,
  algo_id,
  direction,
  status,
  open_time,
  close_time,
  open_price,
  close_price,
  ret_pct,
  stop_loss_price,
  strategy_version,
  params_version,
  risk_snapshot,
  data_timestamp
from paper_positions
order by id desc
limit 10;
```

최근 risk event:

```sql
select
  algo_id,
  event_type,
  created_at,
  risk_decision,
  risk_snapshot
from arena_risk_events
order by created_at desc
limit 10;
```

최신 백테스트 검증:

```sql
select
  validation_run_id,
  backtest_run_id,
  checked_at,
  status,
  pass_count,
  warn_count,
  fail_count,
  na_count
from arena_backtest_validation_summary_v1
order by checked_at desc
limit 1;
```

## 로컬에서 Supabase API로 조회

SQL Editor가 느리거나 `Failed to fetch`가 날 때는 로컬에서 API로 상태만 확인한다.

```bash
cd /Users/giwon/code/news
zsh -ic 'PYTHONPATH=src .venv/bin/python - <<'"'"'PY'"'"'
import asyncio
import json
import os
from supabase import acreate_client

async def main():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        print(json.dumps({"ok": False, "error": "missing_supabase_env"}))
        return

    db = await acreate_client(url, key)
    runs = (
        await db.table("arena_runs")
        .select("run_id,started_at,completed_at,status,runtime,symbol,interval,data_timestamp,strategy_version,params_version,risk_model_version,capture_status,capture_error_count,capture_warnings")
        .order("started_at", desc=True)
        .limit(5)
        .execute()
    ).data or []

    latest_run_id = runs[0]["run_id"] if runs else None
    decisions = []
    if latest_run_id:
        decisions = (
            await db.table("arena_decisions")
            .select("algo_id,signal,action,created_at,current_position_id,resulting_position_id,risk_decision,risk_snapshot")
            .eq("run_id", latest_run_id)
            .order("algo_id")
            .execute()
        ).data or []

    positions = (
        await db.table("paper_positions")
        .select("id,algo_id,direction,status,open_time,close_time,open_price,close_price,ret_pct,stop_loss_price,strategy_version,params_version,risk_snapshot,data_timestamp")
        .order("id", desc=True)
        .limit(10)
        .execute()
    ).data or []

    risk_events = (
        await db.table("arena_risk_events")
        .select("algo_id,event_type,created_at,risk_decision")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []

    print(json.dumps({
        "ok": True,
        "latest_runs": runs,
        "latest_run_decision_count": len(decisions),
        "latest_run_decisions": decisions,
        "recent_positions": positions,
        "recent_risk_events": risk_events,
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
PY'
```

## 정상 판정 기준

| 영역 | 정상 기준 |
| --- | --- |
| service | `active`, `SubState=running`, `ExecMainStatus=0` |
| run | 최신 `arena_runs.status = completed` |
| capture | `capture_status = ok`, `capture_error_count = 0` |
| ohlcv | 최신 run에 `arena_run_ohlcv_bars`가 연결됨 |
| decisions | 최신 run에 알고리즘 5개 decision 저장 |
| positions | open/closed 상태와 stop_loss_price가 `paper_positions`에 저장 |
| risk layer | 최신 run이 `risk_model_version=portfolio-risk-v1` |
| risk events | 신규 open/risk block 발생 이후 `risk_snapshot` 또는 `arena_risk_events` 확인 |
| validation | 최신 `arena_backtest_validation_summary_v1.fail_count = 0` |

## 주의 사항

- EC2와 Lambda arena schedule을 동시에 켜면 같은 DB에 중복/경합 거래가 생길 수 있다.
- service restart는 즉시 cycle을 만들 수 있다.
- 기존 open position 중 `strategy_version = legacy`인 것은 snapshot hardening 이전에 열린 포지션이다.
- 기존 open position은 `risk_snapshot = {}`일 수 있다. portfolio risk snapshot은 신규 open/risk block부터 채워진다.
- 백테스트 표본이 충분해지기 전까지 파라미터 튜닝 결과를 전략 성능으로 해석하지 않는다.
