#!/usr/bin/env bash
# PROJECT=... REGION=... BUDGET_ACCOUNT=... bash infra/setup.sh
set -euo pipefail
: "${PROJECT:?set the dedicated hackathon PROJECT}"; REGION="${REGION:-us-central1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FIREBASE=(env XDG_CONFIG_HOME="$ROOT/.runtime/firebase-config" GOOGLE_CLOUD_QUOTA_PROJECT="$PROJECT" npx --yes firebase-tools@15.32.1)
GCLOUD=(gcloud --project="$PROJECT")
"${GCLOUD[@]}" projects describe "$PROJECT" >/dev/null
"${GCLOUD[@]}" services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com firestore.googleapis.com storage.googleapis.com dlp.googleapis.com \
  cloudtasks.googleapis.com secretmanager.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com billingbudgets.googleapis.com cloudresourcemanager.googleapis.com

if ! "${GCLOUD[@]}" firestore databases describe --database='(default)' >/dev/null 2>&1; then
  "${GCLOUD[@]}" firestore databases create --location="$REGION"
fi
for COLLECTION in cases; do
  "${GCLOUD[@]}" firestore fields ttls update expires_at --collection-group="$COLLECTION" --enable-ttl --async
done
BUCKET="gs://${PROJECT}-gh-evidence"
if ! "${GCLOUD[@]}" storage buckets describe "$BUCKET" >/dev/null 2>&1; then
  "${GCLOUD[@]}" storage buckets create "$BUCKET" --location="$REGION" --uniform-bucket-level-access
fi
LIFECYCLE="$(mktemp)"
trap 'rm -f "$LIFECYCLE"' EXIT
cat > "$LIFECYCLE" <<'EOF'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}
EOF
"${GCLOUD[@]}" storage buckets update "$BUCKET" --lifecycle-file="$LIFECYCLE" \
  --uniform-bucket-level-access --public-access-prevention
if ! "${GCLOUD[@]}" tasks queues describe gh-reminders --location="$REGION" >/dev/null 2>&1; then
  "${GCLOUD[@]}" tasks queues create gh-reminders --location="$REGION"
fi
SA="gh-api@${PROJECT}.iam.gserviceaccount.com"
if ! "${GCLOUD[@]}" iam service-accounts describe "$SA" >/dev/null 2>&1; then
  "${GCLOUD[@]}" iam service-accounts create gh-api --display-name="GoldenHour API"
fi
for ROLE in roles/aiplatform.user roles/datastore.user roles/storage.objectAdmin roles/dlp.user \
            roles/cloudtasks.enqueuer roles/iam.serviceAccountUser; do
  "${GCLOUD[@]}" projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$ROLE" --quiet >/dev/null
done
PROJECT_NUMBER="$("${GCLOUD[@]}" projects describe "$PROJECT" --format='value(projectNumber)')"
"${GCLOUD[@]}" iam service-accounts add-iam-policy-binding "$SA" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudtasks.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null
if ! "${GCLOUD[@]}" secrets describe gh-share-secret >/dev/null 2>&1; then
  openssl rand -hex 32 | "${GCLOUD[@]}" secrets create gh-share-secret --data-file=-
fi
if ! "${GCLOUD[@]}" secrets describe gh-console-key >/dev/null 2>&1; then
  openssl rand -hex 32 | "${GCLOUD[@]}" secrets create gh-console-key --data-file=-
fi
for SECRET in gh-share-secret gh-console-key; do
  "${GCLOUD[@]}" secrets add-iam-policy-binding "$SECRET" --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null
done
if [[ -n "${BUDGET_ACCOUNT:-}" ]]; then
  EXISTING_BUDGET="$("${GCLOUD[@]}" billing budgets list --billing-account="$BUDGET_ACCOUNT" \
    --filter="displayName=goldenhour-${PROJECT}" --format='value(name)')"
  if [[ -z "$EXISTING_BUDGET" ]]; then
    "${GCLOUD[@]}" billing budgets create --billing-account="$BUDGET_ACCOUNT" --display-name="goldenhour-${PROJECT}" \
      --filter-projects="projects/${PROJECT}" --budget-amount="${BUDGET_AMOUNT:-4000INR}" \
      --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
  fi
else
  echo "Budget alert still required: configure it before deployment; BUDGET_ACCOUNT was not supplied."
fi
# Firebase CLI supports Application Default Credentials in CI; interactive login is an alternative.
if ! "${FIREBASE[@]}" apps:list --project "$PROJECT" --non-interactive >/dev/null 2>&1; then
  "${FIREBASE[@]}" projects:addfirebase "$PROJECT" --non-interactive
fi
"${FIREBASE[@]}" deploy --only firestore:rules --project "$PROJECT" --non-interactive
echo "Setup complete. Verify models, then run infra/deploy.sh (browser-owned workspace; no seeded reports)."
