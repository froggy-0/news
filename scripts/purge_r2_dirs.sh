#!/usr/bin/env zsh
# R2에서 analytics/, curated/, raw/, sentiment_join/ 하위 객체를 모두 삭제합니다.
# zshrc에 설정된 R2_PUBLIC_BUCKET, R2_S3_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY를 사용합니다.
set -euo pipefail

: "${R2_PUBLIC_BUCKET:?R2_PUBLIC_BUCKET 미설정}"
: "${R2_S3_ENDPOINT:?R2_S3_ENDPOINT 미설정}"
: "${R2_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID 미설정}"
: "${R2_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY 미설정}"

export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"

DIRS=(analytics curated raw sentiment_join)

for dir in "${DIRS[@]}"; do
  echo "🗑  s3://${R2_PUBLIC_BUCKET}/${dir}/ 삭제 중..."
  aws s3 rm "s3://${R2_PUBLIC_BUCKET}/${dir}/" \
    --recursive \
    --endpoint-url "$R2_S3_ENDPOINT" \
    2>&1 | tail -1
done

echo "✅ 완료"
