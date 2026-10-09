# Operations measurements and limits

Compiled from the retained benchmark and cloud reports. The current held-out benchmark (p50 42.6 s, p90 98.7 s, about US$0.026 per case) is in [../docs/EVALUATION.md](../docs/EVALUATION.md).

| Measurement | Observed value | Scope and exclusions |
|---|---|---|
| Frozen extraction p50 / p90 | 37.272 s / 72.953 s | 72 completed cases; three interrupted stalls excluded; local service with real Vertex calls, four concurrent cases; not full cloud journey |
| Captured token reference cost | USD 1.6089 total; about USD 0.02235 per completed case | Reference rates/assumptions in baseline; unknown interrupted charges, other cloud services and taxes excluded; not an invoice |
| Public IN text receipt | 13.964 s | Individual extract/classify probe |
| Initial public MY / SG receipts | 233.953 s / 181.113 s | Individual probes before shorter optional-call limits fully deployed; includes observed fallback behavior, not a target |
| Final concurrent pack + acknowledgement | 16.481 s | One real cloud probe; both 200, only acknowledgement writes revision |
| Tracking restoration | 0.396 s | One real cloud probe; deterministic read without model generation |
| Public Live first audio | 1.842 s | One WSS text-initiated probe, 53 audio chunks; not physical microphone/device latency |

Sources: [frozen baseline](report_extraction_test.md), [cloud product checks](product_cloud_2026_10_09.json). The known Malaysian post-client-fix regression returned all 11 cases/21 transfers; it has no token/cost instrumentation and is not a new unseen benchmark.

Current evidence model requests are bounded to 120 seconds with one SDK attempt. Optional classification/draft/priority-explanation calls use 20-second limits and template/guidance fallback; prechecks use 30 seconds. Multiple files/stages and cloud cold starts can make a whole journey longer. A repeated same-model Live setting is not an independent failover.

The prototype uses min 0/max 5 Cloud Run instances and a ₹4,000 monthly alert budget. Budget alerts are not a hard cap. Retention uses 30-day case TTL and evidence lifecycle rules; physical deletion is asynchronous.

Before asserting operational targets, measure representative full journeys, include failed/censored attempts, and record phone network/device/locale, model IDs, region, sample count, concurrency and actual billed costs. Human reporting time and recovered money have not been measured.
