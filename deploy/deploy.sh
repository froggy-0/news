#!/usr/bin/env bash
# 코드 업데이트 + 서비스 재시작
# 사용법: ./deploy/deploy.sh <ELASTIC_IP>
set -euo pipefail

HOST="${1:?사용법: $0 <ELASTIC_IP>}"
TARGET="ubuntu@${HOST}"

ssh "$TARGET" bash -s <<'REMOTE'
set -euo pipefail
cd ~/news
git pull --ff-only
source ~/.local/bin/env
uv sync
sudo systemctl restart arena
sudo systemctl status arena --no-pager
REMOTE

echo "Done — arena restarted on ${HOST}"
