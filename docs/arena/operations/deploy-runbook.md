# BTC Signal Arena 배포 Runbook 초안

> 작성일: 2026-06-21
> 원칙: 시크릿 값은 출력하지 않고, zsh 로그인 환경에 있는 값을 파일/서비스에 주입한다.

## 0. 운영 방식 선택

권장 기본값은 **EC2 상시 프로세스**다.

- EC2: 4H 신호 실행 + Binance WebSocket 실시간 스톱로스 감지
- Lambda: 4H 배치 fallback 용도. EC2와 동시에 활성화하면 같은 DB에 중복/경합 거래가 생길 수 있으므로 기본은 비활성 권장

## 1. Supabase migration 실행

로컬에 `psql` 또는 Supabase CLI가 없으면 Supabase Dashboard의 SQL Editor에서 아래 파일 전체를 실행한다.

```bash
supabase/migrations/20260619_paper_positions.sql
```

실행 후 확인 쿼리:

```sql
select column_name, data_type, is_nullable
from information_schema.columns
where table_name = 'paper_positions'
order by ordinal_position;
```

필수 컬럼:

- `status`
- `open_time`
- `open_price`
- `stop_loss_price`
- `close_time`
- `close_price`
- `hold_hours`
- `is_stop_loss`

## 2. 환경변수 파일 생성

현재 zsh 로그인 환경에 아래 3개는 있어야 한다.

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `NEXT_PUBLIC_R2_BASE_URL`

로컬에서 값 출력 없이 EC2용 `.env` 초안을 만든다.

```bash
cd /Users/giwon/code/news
umask 077
{
  printf 'SUPABASE_URL=%s\n' "$SUPABASE_URL"
  printf 'SUPABASE_SERVICE_ROLE_KEY=%s\n' "$SUPABASE_SERVICE_ROLE_KEY"
  printf 'NEXT_PUBLIC_R2_BASE_URL=%s\n' "$NEXT_PUBLIC_R2_BASE_URL"
  printf 'FEE_BPS=5.0\n'
  printf 'ATR_MULTIPLE=2.5\n'
  printf 'STOP_LOSS_PCT=0.05\n'
  printf 'STOP_LOSS_MIN_PCT=0.02\n'
  printf 'STOP_LOSS_MAX_PCT=0.08\n'
  printf 'MACRO_STALE_HOURS=48.0\n'
  printf 'POSITION_UNIT=1.0\n'
  printf 'MAX_OPEN_POSITIONS_TOTAL=3\n'
  printf 'MAX_LONG_POSITIONS=2\n'
  printf 'MAX_SHORT_POSITIONS=0\n'
  printf 'MAX_NET_LONG_EXPOSURE=2.0\n'
  printf 'MAX_NET_SHORT_EXPOSURE=0.0\n'
  printf 'DAILY_LOSS_LIMIT_PCT=0.05\n'
  printf 'ALGO_MAX_DRAWDOWN_KILL_PCT=0.10\n'
  printf 'COOLDOWN_AFTER_KILL_HOURS=24.0\n'
  printf 'ENABLE_ARENA_REALTIME_COLLECTOR=true\n'
  printf 'ENABLE_ARENA_EXECUTION_GATE_SHADOW=true\n'
  printf 'ENABLE_ARENA_EXECUTION_GATE_LIVE=false\n'
  printf 'ENABLE_ARENA_REALTIME_RISK=true\n'
  printf 'ENABLE_ARENA_REALTIME_RISK_LIVE=false\n'
} > .env
```

Lambda를 fallback으로 쓸 때만 별도 env 파일도 만든다.

```bash
cd /Users/giwon/code/news
umask 077
{
  printf 'SUPABASE_URL=%s\n' "$SUPABASE_URL"
  printf 'SUPABASE_SERVICE_ROLE_KEY=%s\n' "$SUPABASE_SERVICE_ROLE_KEY"
  printf 'NEXT_PUBLIC_R2_BASE_URL=%s\n' "$NEXT_PUBLIC_R2_BASE_URL"
  printf 'FEE_BPS=5.0\n'
  printf 'ATR_MULTIPLE=2.5\n'
  printf 'STOP_LOSS_MIN_PCT=0.02\n'
  printf 'STOP_LOSS_MAX_PCT=0.08\n'
  printf 'MACRO_STALE_HOURS=48.0\n'
  printf 'POSITION_UNIT=1.0\n'
  printf 'MAX_OPEN_POSITIONS_TOTAL=3\n'
  printf 'MAX_LONG_POSITIONS=2\n'
  printf 'MAX_SHORT_POSITIONS=0\n'
  printf 'MAX_NET_LONG_EXPOSURE=2.0\n'
  printf 'MAX_NET_SHORT_EXPOSURE=0.0\n'
  printf 'DAILY_LOSS_LIMIT_PCT=0.05\n'
  printf 'ALGO_MAX_DRAWDOWN_KILL_PCT=0.10\n'
  printf 'COOLDOWN_AFTER_KILL_HOURS=24.0\n'
} > lambda/arena/.env.arena
```

## 3. Terraform 변수 파일 생성

SSH 없이 SSM만 쓸 경우:

```bash
cd /Users/giwon/code/news
cat > terraform/terraform.tfvars <<'EOF'
region_code = "kr"
env         = "pr"
app_name    = "arena"
version_tag = "v1a"

instance_type       = "t4g.small"
availability_zone   = "ap-northeast-2a"
root_volume_size_gb = 20

ssh_public_key   = ""
allowed_ssh_cidr = []
EOF
```

SSH 접속을 열 경우에는 본인 IP만 허용한다.

```bash
export MY_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')"
export SSH_PUB="$(cat ~/.ssh/id_rsa.pub)"
python3 - <<'PY'
import os
from pathlib import Path

Path("terraform/terraform.tfvars").write_text(f'''region_code = "kr"
env         = "pr"
app_name    = "arena"
version_tag = "v1a"

instance_type       = "t4g.small"
availability_zone   = "ap-northeast-2a"
root_volume_size_gb = 20

ssh_public_key   = {os.environ["SSH_PUB"]!r}
allowed_ssh_cidr = ["{os.environ["MY_IP"]}/32"]
''')
PY
```

## 4. EC2 생성

Terraform 로컬 설치가 없으면 Docker로 실행한다.

```bash
cd /Users/giwon/code/news
docker run --rm -v "$PWD/terraform:/workspace" -w /workspace hashicorp/terraform:1.12.2 init
docker run --rm -v "$PWD/terraform:/workspace" -w /workspace hashicorp/terraform:1.12.2 plan
docker run --rm -v "$PWD/terraform:/workspace" -w /workspace hashicorp/terraform:1.12.2 apply
```

생성 후 Elastic IP 확인:

```bash
docker run --rm -v "$PWD/terraform:/workspace" -w /workspace hashicorp/terraform:1.12.2 output
```

## 5. EC2 초기 프로비저닝

Elastic IP를 `ARENA_IP`에 넣고 실행한다.

```bash
cd /Users/giwon/code/news
export ARENA_IP="<ELASTIC_IP>"
ssh "ubuntu@${ARENA_IP}" 'bash -s' < deploy/provision_ec2.sh
scp .env "ubuntu@${ARENA_IP}:/home/ubuntu/news/.env"
ssh "ubuntu@${ARENA_IP}" 'cd ~/news && sudo systemctl start arena && sudo systemctl status arena --no-pager'
```

현재 운영 EC2의 `/home/ubuntu/news`는 Git checkout이 아니라 경량 배포 디렉터리다. 따라서 아래 `deploy/deploy.sh` 방식은 원격에 Git repo가 있을 때만 쓴다.

```bash
cd /Users/giwon/code/news
./deploy/deploy.sh "$ARENA_IP"
```

현재 서버 구조에서 검증된 코드 갱신 방식:

```bash
cd /Users/giwon/code/news
rsync -az --delete --exclude='__pycache__/' --exclude='*.pyc' \
  -e 'ssh -i ~/.ssh/arena_ed25519' \
  src/arena/ ubuntu@${ARENA_IP}:/home/ubuntu/news/src/arena/

rsync -az -e 'ssh -i ~/.ssh/arena_ed25519' \
  requirements.txt ubuntu@${ARENA_IP}:/home/ubuntu/news/requirements.txt

ssh -i ~/.ssh/arena_ed25519 ubuntu@${ARENA_IP} \
  'cd /home/ubuntu/news && .venv/bin/python -m compileall -q src/arena && sudo systemctl restart arena.service && systemctl is-active arena.service'
```

상태 확인:

```bash
ssh "ubuntu@${ARENA_IP}" 'systemctl status arena --no-pager'
ssh "ubuntu@${ARENA_IP}" 'journalctl -u arena -n 100 --no-pager'
ssh -i ~/.ssh/arena_ed25519 ubuntu@${ARENA_IP} \
  'cd /home/ubuntu/news && PYTHONPATH=src .venv/bin/python -m arena.roster_diagnostics --source live --limit 5'
```

최신 배포 확인 기준:

- `systemctl is-active arena.service` = `active`
- `ExecMainStatus=0`
- latest `arena_runs.status=completed`
- latest `capture_status=ok`, `capture_error_count=0`
- latest decisions에 `reason.diagnostics`가 존재

## 5A. Arena Dashboard 배포

`arena.sovereignwon.com`은 `arena/index.html` 단일 CSR 대시보드다.

```bash
cd /Users/giwon/code/news
node - <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('arena/index.html', 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
  .map(m => m[1])
  .filter(s => s.includes('const SUPABASE_URL'));
if (scripts.length !== 1) throw new Error(`expected 1 app script, got ${scripts.length}`);
new Function(scripts[0]);
console.log('arena inline js ok');
NODE
npx wrangler pages deploy arena/ --project-name arena --commit-dirty=true
```

대시보드 최신 반영 확인:

- 상단: `BTCUSDT · 4H · 현물 LONG/FLAT`
- 중간: `LATEST DECISION DIAGNOSTICS`
- 카드: skip/veto hint 표시
- 하단: `현물 long/flat 모의투자 전용 — 선물 주문 없음`

## 6. Lambda fallback 배포 (선택)

EC2를 메인 운영으로 켰다면 Lambda EventBridge 스케줄은 기본적으로 만들지 않는다.

Lambda를 fallback으로 별도 운영할 때만:

```bash
cd /Users/giwon/code/news
bash lambda/arena/deploy.sh
```

배포 후 스케줄을 끄려면:

```bash
aws events disable-rule --name arena-trader-4h --region ap-northeast-2
```

수동 1회 테스트:

```bash
aws lambda invoke \
  --function-name arena-trader \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-northeast-2 \
  /tmp/arena_response.json
cat /tmp/arena_response.json
```

## 7. 배포 전 최종 체크

```bash
cd /Users/giwon/code/news
ruff check src/arena lambda/arena
python3 -m compileall -q src/arena lambda/arena
docker buildx build --platform linux/arm64 --provenance=false --sbom=false -t arena-trader:local lambda/arena
```

AWS 존재 확인:

```bash
aws sts get-caller-identity
aws ec2 describe-instances --region ap-northeast-2 \
  --filters 'Name=tag:Name,Values=kr-pr-ec2-arena-v1a' \
  --query 'Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,PublicIp:PublicIpAddress}'
aws lambda get-function --function-name arena-trader --region ap-northeast-2
aws events describe-rule --name arena-trader-4h --region ap-northeast-2
```
