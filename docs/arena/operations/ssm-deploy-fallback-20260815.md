# EC2 배포 — SSH 포트 22 막혔을 때 AWS SSM 우회 절차 (2026-08-15)

`access-runbook.md`/`deploy-runbook.md`가 문서화한 표준 배포(`ssh -i
~/.ssh/arena_ed25519 ubuntu@3.39.201.112` + `rsync`)는 **실행 환경에 따라 포트 22
아웃바운드가 막혀 있을 수 있다**(예: 일부 샌드박스/CI 환경 — 2026-08-15 세션에서
실측: 일반 HTTPS(GitHub·Binance·Cloudflare)는 전부 정상 응답하는데 `ssh`/`nc`는
포트 22에서만 타임아웃). 이 문서는 그럴 때 쓸 수 있는 대체 경로다.

## 전제 조건

- EC2 인스턴스에 **SSM Agent가 이미 설치·구동 중**이어야 한다(이 프로젝트의 EC2는
  이미 그렇다 — `terraform/modules/iam/main.tf`에 SSM용 IAM role이 이미 프로비저닝돼
  있고, `terraform/outputs.tf`의 `ssm_connect` output이 그 존재를 알려준다).
- 로컬에 `aws` CLI가 설치·인증돼 있어야 한다(`aws sts get-caller-identity`로 확인).
- IAM 사용자/역할에 `ssm:SendCommand`, `ssm:GetCommandInvocation`,
  `ssm:DescribeInstanceInformation`, `ec2:DescribeInstances` 권한이 있어야 한다.
- **`session-manager-plugin`(대화형 SSH-오버-SSM 터널용 CLI 도구)은 설치 시 sudo
  비밀번호를 요구**해 비대화형(non-interactive) 세션에서는 설치 실패한다(2026-08-15
  세션에서 확인) — 즉 `aws ssm start-session`으로 진짜 SSH 터널을 여는 건 이런 환경에서
  안 되고, **`aws ssm send-command`(비대화형 원격 명령 실행)만 쓸 수 있다.**

## 1. 인스턴스 ID 확인

```bash
aws ec2 describe-instances --region ap-northeast-2 \
  --filters "Name=ip-address,Values=3.39.201.112" \
  --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name}" \
  --output table
```
(2026-08-15 기준 `i-080675ad97e459f49`, `kr-pr-ec2-arena-v1a`)

## 2. SSM 연결 상태 확인 (읽기 전용)

```bash
aws ssm describe-instance-information --region ap-northeast-2 \
  --filters "Key=InstanceIds,Values=<INSTANCE_ID>" \
  --query "InstanceInformationList[].{PingStatus:PingStatus,Platform:PlatformName}" \
  --output table
```
`PingStatus=Online`이어야 아래 단계가 동작한다.

## 3. 원격 명령 실행 + 결과 대기 (재사용 가능한 패턴)

`AWS-RunShellScript` 문서로 임의 셸 명령을 root 권한으로 실행할 수 있다(이 인스턴스는
`whoami` 결과가 `root`로 나옴 — sudo 불필요). 명령이 크거나 특수문자(따옴표, 개행)를
포함하면 CLI의 `commands=[...]` shorthand 대신 **JSON 파라미터 파일**을 쓴다:

```bash
cat > /tmp/params.json <<'EOF'
{"commands":["<셸 명령>"]}
EOF

CMD_ID=$(aws ssm send-command --region ap-northeast-2 --instance-ids <INSTANCE_ID> \
  --document-name "AWS-RunShellScript" \
  --parameters file:///tmp/params.json \
  --query "Command.CommandId" --output text)

# 완료 대기(폴링) — 몇 초 후 상태 확인
sleep 5
aws ssm get-command-invocation --region ap-northeast-2 \
  --command-id "$CMD_ID" --instance-id <INSTANCE_ID> \
  --query "{Status:Status,StdOut:StandardOutputContent,StdErr:StandardErrorContent}" --output json
```
`Status`가 `InProgress`면 더 기다렸다가 같은 `get-command-invocation`을 재호출.

## 4. 파일 배포 (rsync/scp 대체)

SSM `send-command`엔 파일 전송 기능이 없다 — **파일 내용을 명령 안에 통째로 실어
보낸다.** Python 소스 정도 크기(수십 KB)는 gzip+base64로 압축하면 여유 있게
들어간다(2026-08-15 실측: `backtest.py` 70KB → gzip+base64 22KB, `scheduler.py`
70KB → 23KB, `parameters.py` 59KB → 32KB — 전부 SSM 명령 크기 제한 내):

```bash
LOCAL=src/arena/positions.py
REMOTE=/home/ubuntu/news/src/arena/positions.py
B64=$(gzip -c "$LOCAL" | base64 | tr -d '\n')

python3 -c "
import json
print(json.dumps({'commands':[$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" \
  "set -e; echo '$B64' | base64 -d | gunzip > ${REMOTE}.new && mv ${REMOTE}.new $REMOTE && chown ubuntu:ubuntu $REMOTE && wc -c $REMOTE")]}))
" > /tmp/params.json

CMD_ID=$(aws ssm send-command --region ap-northeast-2 --instance-ids <INSTANCE_ID> \
  --document-name "AWS-RunShellScript" --parameters file:///tmp/params.json \
  --query "Command.CommandId" --output text)
```
`chown ubuntu:ubuntu`가 중요 — SSM 명령이 root로 실행되므로 안 붙이면 기존
`ubuntu:ubuntu` 소유 파일들과 소유자가 어긋난다.

여러 파일을 배포할 땐 파일마다 위 과정을 반복(각 파일 하나가 SSM 명령 하나) —
큰 디렉터리 전체를 통째로 옮기는 용도는 아니고, **바뀐 파일 몇 개를 핀포인트로
갱신**하는 용도다. `rsync --delete`처럼 원격의 잉여 파일을 지우는 기능은 없으므로,
정말 전체 동기화가 필요하면(파일 삭제 포함) 이 방법 대신 SSH가 뚫리길 기다리거나
S3 프리사인드 URL 같은 별도 경로가 필요하다.

## 5. 재시작 + 검증

```bash
cat > /tmp/restart.json <<'EOF'
{"commands":["cd /home/ubuntu/news && .venv/bin/python -m compileall -q src/arena && sudo systemctl restart arena.service && sleep 5 && systemctl is-active arena.service && systemctl show arena.service -p ActiveState -p SubState -p ExecMainStatus --no-pager"]}
EOF
# send-command + get-command-invocation은 위와 동일 패턴
```

에러 로그 확인:
```bash
cat > /tmp/errcheck.json <<'EOF'
{"commands":["journalctl -u arena.service --since '5 minutes ago' --no-pager -p err..alert | tail -30 || true"]}
EOF
```

## 이 방식의 한계 (알고 쓸 것)

- **대화형 아님** — `top`처럼 실시간 반응이 필요한 디버깅은 안 된다. 명령 하나 보내고
  완료까지 폴링하는 식.
- **rsync `--delete` 의미론 없음** — 파일 삭제·전체 동기화는 지원 안 됨, 바뀐 파일만
  핀포인트로 갱신.
- **명령 크기 제한 있음**(정확한 바이트 한도는 AWS 문서 참조 필요 — 이번 세션에서
  실측한 22~32KB 범위는 문제없이 통과했다는 것만 확인됨) — 아주 큰 파일(수백 KB
  이상)은 청크 분할이 필요할 수 있다.
- `session-manager-plugin` 설치가 안 되므로 **`aws ssm start-session`(진짜 SSH급
  대화형 세션·포트포워딩)은 이 환경에서 못 씀** — 그게 필요해지면 사용자가 직접
  `brew install --cask session-manager-plugin`(sudo 필요)을 실행해줘야 한다.

## 실제 사용 사례

2026-08-15, [session-summary-spot-to-perp-live-20260815.md](../research/session-summary-spot-to-perp-live-20260815.md)
§3~4 — spot→perp Phase A2 배포(`src/arena/` 11개 파일) + 이어서
`ARENA_PERP_LIVE_ENABLED` 활성화(`parameters.py` 1개 파일) 재배포, 둘 다 이 절차로
완료·검증(서비스 active, 에러 로그 없음, 재시작 직후 정상 트레이딩 사이클 확인).
