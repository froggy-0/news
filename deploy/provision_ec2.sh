#!/usr/bin/env bash
# EC2 t4g.small (Ubuntu 24.04 arm64, ap-northeast-2) 초기 프로비저닝
# 사용법: ssh ubuntu@<ELASTIC_IP> 'bash -s' < deploy/provision_ec2.sh
set -euo pipefail

# --- 시스템 패키지 ---
sudo apt-get update -q
sudo apt-get install -y -q git curl build-essential

# --- uv 설치 ---
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"

# --- 레포 클론 ---
cd ~
if [ ! -d news ]; then
  git clone https://github.com/rldnjsdlek/news.git
fi
cd news

# --- Python 환경 ---
uv sync
PYTHONPATH=src uv run python -c "import arena.server; print('import OK')"

# --- 환경변수 파일 복사 (로컬에서 미리 scp 필요) ---
# scp .env ubuntu@<IP>:/home/ubuntu/news/.env

# --- systemd 서비스 등록 ---
sudo cp deploy/arena.service /etc/systemd/system/arena.service
sudo systemctl daemon-reload
sudo systemctl enable arena
if [ -f .env ]; then
  sudo systemctl start arena
  sudo systemctl status arena --no-pager
else
  echo ".env 없음 — /home/ubuntu/news/.env 복사 후 sudo systemctl start arena 실행"
fi
