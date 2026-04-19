#!/usr/bin/env bash
# Binance 선물 Lambda — 로컬 ARM 빌드 후 ECR 배포 스크립트
# 실행: bash lambda/binance_futures/deploy.sh
set -euo pipefail

ACCOUNT="254849613915"
REGION="ap-northeast-2"
ECR_REPO="news"
IMAGE_TAG="binance-futures-fetcher"
FUNC_NAME="binance-futures-fetcher"
LAMBDA_ROLE="kr-pr-lambda-binance-futures-v1"
GHA_ROLE="kr-pr-ses-news-v1a"

IMAGE_URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"

echo "=== 1. ECR 로그인 ==="
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo "=== 2. ARM64 이미지 빌드 & ECR 직접 푸시 (linux/arm64) ==="
# --provenance=false : Lambda가 지원하지 않는 manifest list 생성 방지
docker buildx build \
  --platform linux/arm64 \
  --provenance=false \
  --sbom=false \
  -t "${IMAGE_URI}" \
  --push \
  "$(dirname "$0")"

echo "=== 4. Lambda 실행 역할 생성 (이미 존재하면 skip) ==="
if ! aws iam get-role --role-name "${LAMBDA_ROLE}" --region "${REGION}" &>/dev/null; then
  aws iam create-role \
    --role-name "${LAMBDA_ROLE}" \
    --assume-role-policy-document '{
      "Version":"2012-10-17",
      "Statement":[{
        "Effect":"Allow",
        "Principal":{"Service":"lambda.amazonaws.com"},
        "Action":"sts:AssumeRole"
      }]
    }'
  aws iam attach-role-policy \
    --role-name "${LAMBDA_ROLE}" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "  역할 생성 완료. IAM 전파 대기 10초..."
  sleep 10
else
  echo "  역할 이미 존재 — skip"
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${LAMBDA_ROLE}"

echo "=== 5. Lambda 함수 생성 or 업데이트 ==="
if aws lambda get-function --function-name "${FUNC_NAME}" --region "${REGION}" &>/dev/null; then
  echo "  함수 존재 → 코드 업데이트"
  aws lambda update-function-code \
    --function-name "${FUNC_NAME}" \
    --image-uri "${IMAGE_URI}" \
    --region "${REGION}"
else
  echo "  함수 신규 생성"
  aws lambda create-function \
    --function-name "${FUNC_NAME}" \
    --package-type Image \
    --code "ImageUri=${IMAGE_URI}" \
    --role "${ROLE_ARN}" \
    --architectures arm64 \
    --timeout 30 \
    --memory-size 256 \
    --region "${REGION}"
fi

echo "=== 6. GHA 역할에 Lambda invoke 권한 추가 ==="
aws iam put-role-policy \
  --role-name "${GHA_ROLE}" \
  --policy-name "invoke-binance-futures-lambda" \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{
      \"Effect\":\"Allow\",
      \"Action\":\"lambda:InvokeFunction\",
      \"Resource\":\"arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNC_NAME}\"
    }]
  }"

echo ""
echo "=== 배포 완료 ==="
echo "Lambda ARN: arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNC_NAME}"
echo ""
echo "GitHub Actions 변수에 추가하세요:"
echo "  FUTURES_LAMBDA_ARN = arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNC_NAME}"
echo ""
echo "=== Smoke test ==="
aws lambda invoke \
  --function-name "${FUNC_NAME}" \
  --payload '{"lookback_days": 3}' \
  --cli-binary-format raw-in-base64-out \
  --region "${REGION}" \
  /tmp/lambda_response.json
cat /tmp/lambda_response.json
