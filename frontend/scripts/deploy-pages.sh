#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd -- "${FRONTEND_DIR}/.." && pwd)"

required_vars=(
  NEXT_PUBLIC_R2_BASE_URL
  CLOUDFLARE_API_TOKEN
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_PAGES_PROJECT_NAME
)

missing=()
for key in "${required_vars[@]}"; do
  if [ -z "${!key:-}" ]; then
    missing+=("${key}")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "Missing required environment variables: ${missing[*]}" >&2
  exit 1
fi

deploy_target="${1:-preview}"

if [ "${deploy_target}" != "preview" ] && [ "${deploy_target}" != "production" ]; then
  echo "Usage: ./scripts/deploy-pages.sh [preview|production]" >&2
  exit 1
fi

if [ "${deploy_target}" = "preview" ]; then
  current_branch="$(git -C "${REPO_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [ -z "${current_branch}" ] || [ "${current_branch}" = "HEAD" ]; then
    current_branch="local-preview"
  fi
  deploy_branch="${DEPLOY_BRANCH:-$(printf '%s' "${current_branch}" | tr '/' '-' | tr '[:space:]' '-')}"
fi

echo "Building frontend with public data URL: ${NEXT_PUBLIC_R2_BASE_URL}"
(
  cd "${FRONTEND_DIR}"
  npm run build
)

if [ "${deploy_target}" = "preview" ]; then
  echo "Deploying preview branch: ${deploy_branch}"
  (
    cd "${FRONTEND_DIR}"
    npx wrangler@4 pages deploy out --project-name="${CLOUDFLARE_PAGES_PROJECT_NAME}" --branch="${deploy_branch}"
  )
  echo "Preview alias URL is shown in the Wrangler output above."
else
  echo "Deploying production"
  (
    cd "${FRONTEND_DIR}"
    npx wrangler@4 pages deploy out --project-name="${CLOUDFLARE_PAGES_PROJECT_NAME}"
  )
  echo "Production URL is shown in the Wrangler output above."
fi
