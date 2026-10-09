#!/usr/bin/env bash
# PROJECT=... REGION=... [WARM=true] bash infra/deploy.sh
set -euo pipefail
: "${PROJECT:?set the dedicated hackathon PROJECT}"; REGION="${REGION:-us-central1}"
MODEL_LOCATION="${MODEL_LOCATION:-us}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIN_INSTANCES=0
if [[ "${WARM:-false}" == "true" ]]; then MIN_INSTANCES=1; fi
: "${MODEL_MAIN:?set smoke-tested MODEL_MAIN}"
: "${MODEL_LITE:?set smoke-tested MODEL_LITE}"
: "${MODEL_LIVE:?set smoke-tested MODEL_LIVE}"
: "${MODEL_LIVE_FALLBACK:?set smoke-tested MODEL_LIVE_FALLBACK}"
OPEN_WORKSPACE="${OPEN_WORKSPACE:-true}"
CASE_COLLECTION="cases"
SECRETS="SHARE_SECRET=gh-share-secret:latest"
if [[ "$OPEN_WORKSPACE" != "true" ]]; then
  SECRETS+=",CONSOLE_KEY=gh-console-key:latest"
fi
# Runtime never imports benchmark fixtures.
rm -f "$ROOT/api/seed/cases.json"
# A custom delimiter preserves both comma-separated Firebase origins.
EXISTING_URL="$(gcloud run services describe goldenhour-api --project "$PROJECT" --region "$REGION" --format='value(status.url)' 2>/dev/null || true)"
ENV_VARS="^~^GCP_PROJECT=${PROJECT}~GCP_LOCATION=${MODEL_LOCATION}~USE_VERTEX=true~STORE_BACKEND=firestore~EVIDENCE_BUCKET=${PROJECT}-gh-evidence~USE_DLP=true~TASKS_QUEUE=projects/${PROJECT}/locations/${REGION}/queues/gh-reminders~TASKS_SERVICE_ACCOUNT=gh-api@${PROJECT}.iam.gserviceaccount.com~CORS_ORIGINS=https://${PROJECT}.web.app,https://${PROJECT}.firebaseapp.com~MODEL_MAIN=${MODEL_MAIN}~MODEL_LITE=${MODEL_LITE}~MODEL_LIVE=${MODEL_LIVE}~MODEL_LIVE_FALLBACK=${MODEL_LIVE_FALLBACK}"
ENV_VARS+="~OPEN_WORKSPACE=${OPEN_WORKSPACE}~CASE_COLLECTION=${CASE_COLLECTION}"
if [[ -n "$EXISTING_URL" ]]; then ENV_VARS+="~PUBLIC_BASE_URL=${EXISTING_URL}"; fi
gcloud run deploy goldenhour-api --quiet --source "$ROOT/api" --region "$REGION" --project "$PROJECT" \
  --service-account "gh-api@${PROJECT}.iam.gserviceaccount.com" \
  --allow-unauthenticated --timeout 3600 --concurrency 40 --min-instances "$MIN_INSTANCES" --max-instances 5 \
  --memory 1Gi --cpu 1 --set-env-vars "$ENV_VARS" \
  --set-secrets "$SECRETS"
API_URL="$(gcloud run services describe goldenhour-api --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
if [[ "$API_URL" != "$EXISTING_URL" ]]; then
  gcloud run services update goldenhour-api --project "$PROJECT" --region "$REGION" --update-env-vars "PUBLIC_BASE_URL=${API_URL}"
fi
cd "$ROOT/web"
export npm_config_cache="${npm_config_cache:-$ROOT/.runtime/npm-cache}"
npm ci
VITE_API_BASE="$API_URL" npm run build
cd "$ROOT"
XDG_CONFIG_HOME="$ROOT/.runtime/firebase-config" GOOGLE_CLOUD_QUOTA_PROJECT="$PROJECT" npx --yes firebase-tools@15.32.1 deploy --only hosting --project "$PROJECT" --non-interactive
curl --fail --silent --show-error "$API_URL/health"
printf '\nWeb: https://%s.web.app\nAPI: %s\nBrowser-owned workspace: %s\n' "$PROJECT" "$API_URL" "$OPEN_WORKSPACE"
