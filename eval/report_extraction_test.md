# Held-out extraction — 75 synthetic cases

Frozen baseline commit `359095f`; 75 cases attempted, 72 returned and three provider stalls were interrupted after over 26 minutes without progress (about 41 minutes total process time). All 75 cases and every transfer remain in the accuracy denominator. No test case was substituted or rerun for this primary result.

| Field | Raw hit/total | Raw accuracy | Independently checked | Target |
|---|---|---|---|---|
| utr | 128/137 | 93.4% | 128/137 (93.4%) | 95% |
| amount | 128/137 | 93.4% | 107/137 (78.1%) | 98% |
| beneficiary | 116/137 | 84.7% | 110/137 (80.3%) | 90% |

Unsupported raw UTRs: 1; unsupported accepted UTRs: 0; extra transactions: 1. Three interrupted failures: GH-SYN0071, GH-SYN0149, GH-SYN0037.

Completed-case extraction p50 37.272 s; p90 72.953 s, with **three right-censored stalls excluded**. These percentiles do not describe all 75 attempts. Four concurrent local service requests using real Vertex calls; excludes cloud upload, classification, drafts and voice.

Captured token reference cost USD 1.6089, USD 0.0223 per completed case. [Official pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing), non-global rates as of 8 October 2026, eligible Flash promotional credits assumed. This is not an invoice: interrupted/post-checkpoint charges, taxes and other services are excluded.

This baseline exposed attached `RM` currency prefixes being rejected by the independent amount checker. The deployed fix and an all-Malaysia regression are reported separately; they do not overwrite this result. Provider stalls also exposed missing request timeouts; current calls have a 120-second timeout and no implicit SDK retries. Neither fix establishes overall post-change held-out accuracy; a new unseen split is needed for that claim.

Masked destination accounts remain full-identifier misses. No hidden characters are invented. This measures synthetic extraction, not money recovery or human reporting-time improvements. See extraction_test.json for frozen hashes, usage, source-check diagnostics and retained failures.

## Beneficiary visibility diagnostic

Primary full-identifier results above are unchanged. The generator masks some IMPS destination accounts and supplies no bank receipt with the full number. Secondary visibility groups:

| Group | Transfers | Raw exact | Independently checked |
|---|---|---|---|
| observable | 125 | 116 (92.8%) | 110 (88.0%) |
| masked_full_account | 12 | 0 (0.0%) | 0 (0.0%) |

Visibility is derived from the original renderer/SMS rules, independently of predictions. Masked transfers remain in the primary denominator; asking the bank for the full destination identifier is the correct next action. See beneficiary_visibility_test.json for retained case/reference diagnostics. The test covers 64 India cases and 11 Malaysia cases; no Singapore cases were generated for this split.
