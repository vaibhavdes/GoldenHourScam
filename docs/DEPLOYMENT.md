# GoldenHour deployment

This file records the live configuration and how to reproduce it.

## Working deployment

| Item | Verified configuration |
|---|---|
| Project | `goldenhour-aicup-2026-vk1007` · number `100812022320` |
| Web | https://goldenhour-aicup-2026-vk1007.web.app |
| API health | https://goldenhour-api-100812022320.us-central1.run.app/health |
| Console | `/console` on the web URL · browser-owned reports; no login or access code |
| AI provider / endpoint | Vertex AI · `us` |
| Main / independent reader | `gemini-3.8-flash` / `gemini-3.1-flash-lite` |
| Voice | `gemini-3.8-live`; fallback is the same model, no independent backup |
| Cloud Run | `goldenhour-api`, `us-central1`, 1 CPU / 1 GiB, concurrency 40, timeout 3600 s, min 0 / max 5 |
| Persistence | Native Firestore `(default)` and uniform-access GCS bucket `goldenhour-aicup-2026-vk1007-gh-evidence` |
| Reminders | Cloud Tasks `gh-reminders`, `us-central1`; hooks scheduled, outbound delivery inactive |
| Credentials | Runtime service account `gh-api`; helper-signing secret from Secret Manager; no console key mounted in open-workspace mode |
| Retention | Native timestamp TTL on `cases.expires_at`; bucket deletion lifecycle at age 30 days; asynchronous cleanup |
| Cost alerts | Project-scoped ₹4,000 monthly budget, thresholds 50%, 90%, 100%; notifications, not a spending cap |

Billing is enabled. Firebase registration and Hosting publication succeeded after account setup. Firestore deny-client rules were deployed. The global gcloud project remains unchanged; use explicit project flags.

## Model checks

Actual text and audio responses are recorded in [`model_smoke.json`](../eval/model_smoke.json), [`voice_smoke.json`](../eval/voice_smoke.json).

The initial `us-central1` text probes returned 404. The shared **`us`** endpoint worked for all three configured models. The old 2.5 Live fallback did not work on that shared endpoint, so the deployment uses the verified 3.8 Live model for both settings and deduplicates connection attempts.

Google's [Flash documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash), [Flash-Lite documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite) and [Live documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-live) list model locations. Keep model location separate from the resource region. Availability probes are not benchmark accuracy results.

## Environment and credentials

`api/.env` is ignored and configured on this machine. [`api/.env.example`](../api/.env.example) has optional key and cloud-resource placeholders. No Gemini API key is needed with `USE_VERTEX=true`: local code uses ADC; Cloud Run uses its service account.

```dotenv
GCP_PROJECT=goldenhour-aicup-2026-vk1007
GCP_LOCATION=us
USE_VERTEX=true
GEMINI_API_KEY=
MODEL_MAIN=gemini-3.8-flash
MODEL_LITE=gemini-3.1-flash-lite
MODEL_LIVE=gemini-3.8-live
MODEL_LIVE_FALLBACK=gemini-3.8-live
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=goldenhour-aicup-2026-vk1007
GOOGLE_CLOUD_LOCATION=us
```

For local memory mode, keep `STORE_BACKEND=memory`, cloud-only fields empty and `USE_DLP=false`. Local signing keys are development-only. Do not copy them into production. The deployment supplies Firestore, bucket, task queue, DLP, public API URL, explicit CORS and Secret Manager values.

ADK also needs its three `GOOGLE_*` variables. Install `api/requirements-eval.txt` locally for evaluation extras; they are not installed by the production Dockerfile. All configured agent/judge model calls use Gemini.

## Reproducible setup

From the repository root, specify `PROJECT` on every operation. Setup provisions APIs, IAM, retention, secrets, a project-scoped budget and Firestore rules. Billing must already be linked. Firebase account terms may need the account owner to complete them; registration cannot be inferred from a Google Cloud project existing.

```bash
PROJECT=goldenhour-aicup-2026-vk1007 REGION=us-central1 \
  BUDGET_ACCOUNT=YOUR_BILLING_ACCOUNT BUDGET_AMOUNT=4000INR bash infra/setup.sh

OPEN_WORKSPACE=true PROJECT=goldenhour-aicup-2026-vk1007 REGION=us-central1 MODEL_LOCATION=us \
  MODEL_MAIN=gemini-3.8-flash MODEL_LITE=gemini-3.1-flash-lite \
  MODEL_LIVE=gemini-3.8-live MODEL_LIVE_FALLBACK=gemini-3.8-live bash infra/deploy.sh
```

Deployment creates no reports. Setup enables TTL on reports and enforces bucket public-access prevention.

The setup/deploy scripts isolate Firebase CLI configuration under ignored `.runtime/firebase-config` and supply the quota project. If the machine's default npm cache is not writable, set `npm_config_cache=/private/tmp/goldenhour-npm-cache`.

Deployment excludes `.env`/venv/test files from the API context, publishes the frontend with a direct Cloud Run API URL, and only updates the callback URL if it changed. It preserves min 0/max 5 unless `WARM=true` is supplied (keeps one instance warm, avoiding cold starts). Synchronous extraction and Live tools run in worker threads. Case writes use optimistic revisions so concurrent requests cannot silently overwrite changes. Cloud Tasks supplies an OIDC token with the runtime service-account email and API URL as audience; the callback verifies both.

## Verified acceptance and remaining integration work

See [evaluation](EVALUATION.md). The real synthetic hero and English/Hindi WSS checks passed. Never treat `/health` model names as proof of model responses.

The 75-case baseline is published with retained stalled attempts and missed targets; currency/timeouts were fixed separately. Physical Android/iPhone microphones, mobile-data/incognito acceptance, representative voice timing and the human study remain required. A fresh separate synthetic split is recorded in current product verification; historical results remain immutable. Reminder delivery, real bank/police/registry adapters, production staff authentication and an independent Live fallback remain unimplemented. Model HTTP requests are bounded to 120 seconds per call with one attempt; multiple files/stages may take longer.

## Browser-owned workspace

An unrelated root `.env` is not imported by deployment. Keep API settings in `api/.env`; Vertex uses service-account credentials. The deployment mounts only `gh-share-secret`. The retained `gh-console-key` is unused here.

`OPEN_WORKSPACE=true` stores reports in `cases`. Each new record has an automatic owner capability; every report endpoint requires it. `/console` endpoints receive the browser's capability map and return only owned cases. No synthetic-case exemption exists. Credentials stay in the current tab's session storage, with in-memory fallback. There is no login or access-code prompt. Institutional mode retains a backend console key and needs a proper staff identity system before real institutional use.

No additional API key or service is needed for the current screenshot, draft, helper and voice workflows. Real SMS/WhatsApp sending and bank/police/registry access require separately approved integrations; none are claimed active. Google's [HTTP task documentation](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks) describes the OIDC callback mechanism used here.

Gemini client initialization is serialized before looking up its shared cache. This prevents simultaneous first requests from creating/discarding SDK clients and closing transports while they are in use. Four real cold-start requests reproduced the prior failure, and the same four requests returned after the fix. Model HTTP requests retain their 120-second bound and one attempt.
