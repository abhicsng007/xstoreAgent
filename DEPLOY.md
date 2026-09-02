# Deploying xStoreAgent to Cloud Run

The hosted service connects to the **same ClickHouse Cloud** database your local
ingest populated, and serves the dashboard (library, repurpose search, dedup
review) at a public URL — the hosted-project URL the hackathon requires. The
sample pack is bundled into the image, so the **Ingest & Organize** button also
works on the hosted app (it ingests `/app/sample_assets`).

## Fastest path — one command

With `gcloud` authenticated (`gcloud auth login`), billing enabled, and your
`.env` filled in:

```bash
bash scripts/deploy.sh
```

It enables the APIs, creates a runtime service account with Vertex AI access,
stores your ClickHouse password in Secret Manager, and deploys from source. It
prints the public URL at the end. Re-run it any time to redeploy.

> On Windows, run it from Git Bash. Prefer PowerShell? Follow the manual steps
> below — the `gcloud` commands are identical.

---

## Manual steps (PowerShell-friendly)

Values assume project **`xstoreagent`** and region **`us-central1`**. Cloud Run
runs in a region; `GOOGLE_CLOUD_LOCATION=global` is only Gemini's endpoint.

### 1. Enable the APIs
```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
  artifactregistry.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com
```

### 2. Runtime service account + Vertex AI access
```powershell
gcloud iam service-accounts create xstoreagent-run --display-name="xStoreAgent Cloud Run runtime"

gcloud projects add-iam-policy-binding xstoreagent `
  --member="serviceAccount:xstoreagent-run@xstoreagent.iam.gserviceaccount.com" `
  --role="roles/aiplatform.user" --condition=None
```

### 3. Store the ClickHouse password in Secret Manager
Write the password to a temp file **with no trailing newline**, add it, then delete the file:
```powershell
gcloud secrets create clickhouse-password --replication-policy=automatic

"YOUR_CLICKHOUSE_PASSWORD" | Out-File -FilePath pw.txt -NoNewline -Encoding ascii
gcloud secrets versions add clickhouse-password --data-file=pw.txt
Remove-Item pw.txt

gcloud secrets add-iam-policy-binding clickhouse-password `
  --member="serviceAccount:xstoreagent-run@xstoreagent.iam.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

### 4. Deploy from source
Fill in your ClickHouse host (and database if not `xstoreAgent`). This builds the
container with Cloud Build (~3–5 min):
```powershell
gcloud run deploy xstoreagent `
  --source . `
  --region us-central1 `
  --service-account xstoreagent-run@xstoreagent.iam.gserviceaccount.com `
  --allow-unauthenticated `
  --memory 2Gi --cpu 2 --timeout 900 `
  --set-env-vars "GOOGLE_CLOUD_PROJECT=xstoreagent,GOOGLE_CLOUD_LOCATION=global,EMBEDDING_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=true,GEMINI_MODEL=gemini-3.7-flash,MULTIMODAL_EMBEDDING_MODEL=multimodalembedding@001,TEXT_EMBEDDING_MODEL=gemini-embedding-001,CLICKHOUSE_HOST=YOUR_HOST.clickhouse.cloud,CLICKHOUSE_PORT=8443,CLICKHOUSE_USER=default,CLICKHOUSE_DATABASE=xstoreAgent,CLICKHOUSE_SECURE=true,USE_CLICKHOUSE_MCP=true,SAMPLE_ASSETS_DIR=/app/sample_assets" `
  --set-secrets "CLICKHOUSE_PASSWORD=clickhouse-password:latest"
```

### 5. Get the URL and test
```powershell
gcloud run services describe xstoreagent --region us-central1 --format="value(status.url)"
```
Open the URL, then check `/<url>/api/health` → `ok`, `clickhouse.ok`, and `mcp.ok`
must all be true (ClickHouse track eligibility). The library and search load from
your ClickHouse data immediately.

Pre-load the sample pack so a judge never sees an empty library:

```bash
python scripts/reset_library.py --yes --ingest sample_assets --project demo
```

That writes to the same ClickHouse the service uses (your `.env`). Then click
**Golden prompt** on the hosted URL — the Librarian should call `list_tables` and
`run_select_query` via mcp-clickhouse.

ClickHouse Cloud trial credits last 30 days. Extend the service so it stays up
through judging (10 Sep–8 Oct 2026).

---

## Notes & troubleshooting
- **No `GOOGLE_APPLICATION_CREDENTIALS`** is set on Cloud Run — the runtime service
  account provides Application Default Credentials automatically. That's why the SA
  needs `roles/aiplatform.user`.
- **Empty library on the hosted app?** Your ClickHouse `CLICKHOUSE_DATABASE` env
  var must match where you ingested locally (your local `.env` uses `xstoreAgent`).
- **Redeploy after code changes:** re-run `scripts/deploy.sh` (or step 4). Env vars
  and the secret binding persist across redeploys.
- **429 / quota during ingest on the hosted app:** the app retries with backoff;
  for a large ingest, prefer running `python scripts/smoke_test.py` locally against
  the same ClickHouse so the hosted app just serves the catalog.
- **ClickHouse MCP is on by default.** The image preinstalls `mcp-clickhouse` and
  sets `USE_CLICKHOUSE_MCP=true`. Do not flip this off for the hackathon deploy —
  catalog chat must go through the official MCP server. Dashboard REST still uses
  `clickhouse-connect` for snappy grids. If `/api/health` shows `mcp.ok: false`,
  the agent chat will 503 until the package/env is fixed.
