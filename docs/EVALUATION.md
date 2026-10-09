# Evaluation

All model results use **real Gemini calls on Vertex AI**. Test inputs are **synthetic, watermarked screenshots** produced by [`data-gen/`](../data-gen); they are never loaded into the running product. Results describe this tested distribution, not universal accuracy or real-world recovery.

## 1. Evidence extraction (held-out test)

Fresh seed `20261009`; 40 test cases (33 India, 7 Malaysia), 78 transfers. The pipeline was frozen before the run: no prompt tuning on the test split and no reruns.

| Field | Raw exact | Independently source checked | Internal target |
|---|---|---|---|
| Transaction reference | 78/78 · 100% | 78/78 · 100% | 95% |
| Amount | 78/78 · 100% | 78/78 · 100% | 98% |
| Full recipient (UPI ID / account) | 70/78 · 89.7% | 65/78 · 83.3% | 90% |

- **0 invented references, 0 extra transfers, 0 model errors.**
- 8 receipts mask the recipient's full account number. These remain misses in the denominator; masked digits are never guessed.
- Of 70 visible recipients, 65 passed the independent check (92.9%). The other 5 were correct but sent to human review because the second reading did not confirm them.
- Inputs include six India bank SMS styles, IMPS/NEFT variants, UPI and DuitNow receipts, English/Hindi/Hinglish/Malay chats, and decoys (OTPs, balance alerts, everyday payments) that must not be extracted.

Report: [`eval/report_extraction_product_2026_10_09.md`](../eval/report_extraction_product_2026_10_09.md) · raw: [`extraction_product_2026_10_09.json`](../eval/extraction_product_2026_10_09.json) · method: [`product_benchmark_method_2026_10_09.json`](../eval/product_benchmark_method_2026_10_09.json) · recipient visibility: [`beneficiary_visibility_product_2026_10_09.json`](../eval/beneficiary_visibility_product_2026_10_09.json)

**Earlier baseline (kept for transparency):** a 75-case / 137-transfer run missed internal targets and had three stalled cases, which are kept as misses. These issues led to bounded model timeouts and client fixes. See [`report_extraction_test.md`](../eval/report_extraction_test.md).

## 2. Safety and agent behaviour

| Evaluation | Result | Report |
|---|---|---|
| Prompt injection written by fraudsters in chats | Adversarial text set; outputs never advise paying | [`report_injection.md`](../eval/report_injection.md) |
| ADK guidance agent (helpline first, never pay, never claim filing, never ask for OTP) | `adk eval` with rubric metrics; initial failures retained | [`report_adk.md`](../eval/report_adk.md) |
| Recipient linking across reports | Deterministic; pairwise precision/recall on synthetic clusters | [`report_linking.md`](../eval/report_linking.md) |

## 3. Deployed product checks

| Check | Result | Evidence |
|---|---|---|
| Cloud workflow (India/Malaysia/Singapore receipts, confirmed packs, disputed-debit drafts, owner isolation, Secret Manager signing, masked helper view, OIDC callbacks, Live audio) | 36/36 | [`product_cloud_2026_10_09.json`](../eval/product_cloud_2026_10_09.json) |
| Browser journey (attachments, calendar export, private access, layouts) | 22/22 | [`product_browser_2026_10_09.json`](../eval/product_browser_2026_10_09.json) |
| Gemini Live English/Hindi audio over WSS | Passed | [`voice_smoke.json`](../eval/voice_smoke.json) |
| Credential scan of publishable source and history | No known secrets found | [`product_secret_scan_2026_10_09.json`](../eval/product_secret_scan_2026_10_09.json) |
| Automated regression tests | 76 passing | `cd api && pytest -q` |

## 4. Operations

- Extraction latency on the benchmark (four concurrent cases, local service, real Vertex calls): p50 **42.6 s**, p90 **98.7 s**.
- Deployed walkthrough case (5 screenshots: 2 bank SMS, 2 UPI receipts, 1 Hindi chat), revision `goldenhour-api-00020-lrw`, three sequential runs: **44.5 s, 48.4 s, 45.7 s** end to end (upload, extraction, independent check, classification). All references, amounts and UPI IDs were source checked; scam type was detected as digital arrest in all runs. Independent transcriptions run in parallel with extraction; the main multimodal extraction call dominates.
- A fix in this revision normalises how Gemini names its source file (full label, evidence ID or filename). Before it, multi-file uploads in the cloud could leave correct values unchecked.
- Token cost reference: about **US$0.026 per case** on the 40-case benchmark (reference rates, not an invoice).
- Model calls are bounded to 120 s; optional steps (classification, drafting) fall back to templates.

See [`report_ops.md`](../eval/report_ops.md).

## 5. Next evaluations

- User studies with families and bank teams on report preparation time and errors
- Device testing across Android and iPhone, with native Hindi review
- Pilot outcome tracking with a bank fraud desk
