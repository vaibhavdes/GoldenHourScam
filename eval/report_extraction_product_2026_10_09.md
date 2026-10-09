# Held-out extraction — 40 synthetic cases

Frozen pipeline; all selected test cases retained. See extraction_product_2026_10_09.json for hashes, predictions, source-check issues, exact denominators and token usage.

| Field | Raw hit/total | Raw accuracy | Independently checked | Target |
|---|---|---|---|---|
| utr | 78/78 | 100.0% | 78/78 (100.0%) | 95% |
| amount | 78/78 | 100.0% | 78/78 (100.0%) | 98% |
| beneficiary | 70/78 | 89.7% | 65/78 (83.3%) | 90% |

Unsupported raw UTRs: 0; unsupported independently accepted UTRs: 0; extra transactions: 0; model-error cases: 0.

Extraction p50 42.636 s; p90 98.672 s. Four concurrent local service requests using real Vertex calls; excludes cloud upload, classification, drafts and voice.

Token-based reference cost: USD 1.0368 total, USD 0.0259 per case. [Official pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing), 8 October 2026, non-global rates with eligible Flash promotional credits assumed; not an invoice. Unknown failed-call charges and other services excluded.

Masked destination accounts are retained as full-identifier misses in the primary denominator. No hidden characters are invented to reach the target. This measures synthetic extraction, not money recovery or human reporting-time improvements.

## Beneficiary visibility diagnostic

Primary full-identifier results above are unchanged. The generator masks some IMPS destination accounts and supplies no bank receipt with the full number. Secondary visibility groups:

| Group | Transfers | Raw exact | Independently checked |
|---|---|---|---|
| observable | 70 | 70 (100.0%) | 65 (92.9%) |
| masked_full_account | 8 | 0 (0.0%) | 0 (0.0%) |

Visibility is derived from the original renderer/SMS rules, independently of predictions. Masked transfers remain in the primary denominator; asking the bank for the full destination identifier is the correct next action. See the matching visibility JSON for retained case/reference diagnostics. This generator covers India and Malaysia; Singapore is covered by separate functional cloud probes.

## Interpretation

Seed 20261009 generated 80 cases; the 40-case test half contains 33 India and 7 Malaysia cases. No generated artifact hash matches an artifact in the earlier frozen benchmark. This is new-instance evaluation with the same generator/templates, not an independent real-world distribution. Prompts and validators were frozen before this run.

All 78 references and amounts matched and independently checked. The primary full-recipient target remains unmet: eight recipients are unobservable masked accounts and five correct visible extractions were conservatively rejected by the independent source check. Those five require user review; they are retained as misses. No masked digits were guessed, no test-based tuning was applied, and no successful cases were rerun.
