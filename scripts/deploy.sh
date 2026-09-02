#!/usr/bin/env bash
# One-command Cloud Run deploy for xStoreAgent.
#
# Reads your local .env (GCP + ClickHouse settings), provisions a runtime service
# account with Vertex AI access, stores the ClickHouse password in Secret Manager,
# and deploys the container from source. Re-runnable (idempotent).
#
#   bash scripts/deploy.sh
#
# Prereqs: gcloud installed & authenticated (gcloud auth login), billing enabled,
# and a filled-in .env at the repo root.
set -euo pipefail

cd "$(dirname "$0")/.."

# --- Load .env ---
if [[ ! -f .env ]]; then echo "ERROR: .env not found at repo root"; exit 1; fi
set -a; source .env; set +a

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT in .env}"
REGION="${DEPLOY_REGION:-us-central1}"          # Cloud Run region (not Gemini's 'global')
SERVICE="${DEPLOY_SERVICE:-xstoreagent}"
SA_NAME="xstoreagent-run"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SECRET="clickhouse-password"

echo "==> Project: $PROJECT | Region: $REGION | Service: $SERVICE"
gcloud config set project "$PROJECT" >/dev/null

# --- 1. Enable APIs ---
echo "==> Enabling APIs..."
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com >/dev/null

# --- 2. Runtime service account + Vertex AI access ---
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  echo "==> Creating service account $SA_EMAIL"
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="xStoreAgent Cloud Run runtime" >/dev/null
fi
echo "==> Granting Vertex AI User to $SA_EMAIL"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" --condition=None >/dev/null

# --- 3. ClickHouse password -> Secret Manager ---
if ! gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  echo "==> Creating secret $SECRET"
  gcloud secrets create "$SECRET" --replication-policy=automatic >/dev/null
fi
echo "==> Adding ClickHouse password version"
printf '%s' "${CLICKHOUSE_PASSWORD:?set CLICKHOUSE_PASSWORD in .env}" \
  | gcloud secrets versions add "$SECRET" --data-file=- >/dev/null
gcloud secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

# --- 4. Deploy from source ---
# Non-secret config as env vars; password injected from Secret Manager.
# GOOGLE_APPLICATION_CREDENTIALS is intentionally unset -> ADC uses the runtime SA.
ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT}"
ENV_VARS="${ENV_VARS},GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-global}"
ENV_VARS="${ENV_VARS},EMBEDDING_LOCATION=${EMBEDDING_LOCATION:-us-central1}"
ENV_VARS="${ENV_VARS},GOOGLE_GENAI_USE_VERTEXAI=true"
ENV_VARS="${ENV_VARS},GEMINI_MODEL=${GEMINI_MODEL:-gemini-3.7-flash}"
ENV_VARS="${ENV_VARS},MULTIMODAL_EMBEDDING_MODEL=${MULTIMODAL_EMBEDDING_MODEL:-multimodalembedding@001}"
ENV_VARS="${ENV_VARS},TEXT_EMBEDDING_MODEL=${TEXT_EMBEDDING_MODEL:-gemini-embedding-001}"
ENV_VARS="${ENV_VARS},CLICKHOUSE_HOST=${CLICKHOUSE_HOST}"
ENV_VARS="${ENV_VARS},CLICKHOUSE_PORT=${CLICKHOUSE_PORT:-8443}"
ENV_VARS="${ENV_VARS},CLICKHOUSE_USER=${CLICKHOUSE_USER:-default}"
ENV_VARS="${ENV_VARS},CLICKHOUSE_DATABASE=${CLICKHOUSE_DATABASE:-xstoreAgent}"
ENV_VARS="${ENV_VARS},CLICKHOUSE_SECURE=${CLICKHOUSE_SECURE:-true}"
# Official mcp-clickhouse must be on for the ClickHouse track (eligibility).
ENV_VARS="${ENV_VARS},USE_CLICKHOUSE_MCP=${USE_CLICKHOUSE_MCP:-true}"
ENV_VARS="${ENV_VARS},SAMPLE_ASSETS_DIR=/app/sample_assets"

echo "==> Deploying to Cloud Run (this builds the container; ~3-5 min)..."
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 900 \
  --set-env-vars "$ENV_VARS" \
  --set-secrets "CLICKHOUSE_PASSWORD=${SECRET}:latest"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo ""
echo "==> Deployed: $URL"
echo "    Health:   $URL/api/health"
