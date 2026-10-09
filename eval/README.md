# Evaluation files

Summary and interpretation: [../docs/EVALUATION.md](../docs/EVALUATION.md).

| File | Purpose |
|---|---|
| `extraction_eval.py`, `heldout_run.py` | Run the extraction benchmark on generated synthetic screenshots (dev split for iteration, test split once) |
| `visibility_report.py` | Separate masked vs visible recipient identifiers without changing the primary metric |
| `linking_eval.py` | Recipient-linking precision/recall |
| `injection_eval.py` | Fraudster-written prompt-injection checks |
| `adk_report.py` | Summarise `adk eval` results |
| `model_smoke.py` | Check that the configured Gemini models respond in your project |
| `report_extraction_product_2026_10_09.md` + `extraction_product_2026_10_09.json` | Current held-out benchmark (40 cases / 78 transfers) |
| `product_benchmark_method_2026_10_09.json`, `beneficiary_visibility_product_2026_10_09.json` | Benchmark method and recipient visibility |
| `report_extraction_test.md` + `extraction_test.json` | Earlier 75-case baseline with its misses |
| `report_injection.md` + `injection_results.json` | Injection results |
| `report_adk.md` + `adk_results.json` | ADK agent results |
| `report_linking.md` | Linking results |
| `report_ops.md` | Latency and cost |
| `product_cloud_2026_10_09.json`, `product_browser_2026_10_09.json`, `voice_smoke.json`, `model_smoke.json`, `product_secret_scan_2026_10_09.json` | Deployed product, browser, voice, model and secret-scan checks |

```bash
cd data-gen && python generate.py --cases 300 --render 150   # synthetic inputs (ignored by git)
cd .. && python eval/extraction_eval.py --split dev --limit 20
python eval/linking_eval.py
python eval/injection_eval.py
```
