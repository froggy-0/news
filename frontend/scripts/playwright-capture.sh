#!/bin/zsh

set -euo pipefail

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET_URL="${1:-http://localhost:3000}"
CAPTURE_NAME="${2:-home}"
OUTPUT_DIR="${ROOT_DIR}/output/playwright"

mkdir -p "$OUTPUT_DIR"

if ! ls "${HOME}/Library/Caches/ms-playwright"/chromium-* >/dev/null 2>&1; then
  npx playwright install chromium >/dev/null
fi

echo "Capturing ${TARGET_URL}"
npx playwright screenshot -b chromium --device="iPhone 13" "$TARGET_URL" "${OUTPUT_DIR}/${CAPTURE_NAME}-mobile.png"
npx playwright screenshot -b chromium --viewport-size="1440,1200" "$TARGET_URL" "${OUTPUT_DIR}/${CAPTURE_NAME}-desktop.png"

echo "Saved:"
echo "  ${OUTPUT_DIR}/${CAPTURE_NAME}-mobile.png"
echo "  ${OUTPUT_DIR}/${CAPTURE_NAME}-desktop.png"
