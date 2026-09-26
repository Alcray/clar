# CLAR model benchmark

Run `2026-09-26T144634.034540+0000-8e7634f1`. Dataset `editorial-v1`. Benchmark `1.0.0`.

**Editorial development cases, not independently validated gold or an unbiased held-out evaluation.** Fixed and live tracks answer different questions and must be compared separately. Quality metrics below are conditional on successful responses; completion rates and failures stay visible.

| Model / track | Completed | Kind macro F1 | Verdict macro F1 | False accusations | Decisive coverage | p50 s | p95 s |
|---|---:|---:|---:|---:|---:|---:|---:|
| flash-lite-minimal/fixed | 6/6 | 85.7% | 87.5% | 0.0% | 100.0% | 2.31 | 2.50 |
| flash-low/fixed | 6/6 | 100.0% | 100.0% | 0.0% | 100.0% | 2.87 | 4.78 |

## Reliability and source discipline

| Model / track | Completion | Source ID validity | Relevant citations | Citation coverage | Statement quotes | Technique quotes | Purpose |
|---|---:|---:|---:|---:|---:|---:|---:|
| flash-lite-minimal/fixed | 100.0% | 100.0% | 75.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| flash-low/fixed | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 83.3% |

## By language

| Model / track | Language | Completed | Kind macro F1 | Verdict macro F1 | p50 s | p95 s |
|---|---|---:|---:|---:|---:|---:|
| flash-lite-minimal/fixed | en | 2/2 | 100.0% | 100.0% | 2.36 | 2.38 |
| flash-lite-minimal/fixed | ro | 2/2 | 80.0% | 83.3% | 2.02 | 2.26 |
| flash-lite-minimal/fixed | ru | 2/2 | 80.0% | 83.3% | 2.29 | 2.52 |
| flash-low/fixed | en | 2/2 | 100.0% | 100.0% | 2.29 | 2.47 |
| flash-low/fixed | ro | 2/2 | 100.0% | 100.0% | 4.24 | 5.13 |
| flash-low/fixed | ru | 2/2 | 100.0% | 100.0% | 2.72 | 3.37 |

## By category

| Model / track | Category | Completed | Kind accuracy | Verdict accuracy | False accusations |
|---|---|---:|---:|---:|---:|
| flash-lite-minimal/fixed | fraud | 3/3 | 60.0% | 60.0% | — |
| flash-lite-minimal/fixed | supported_fact | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-low/fixed | fraud | 3/3 | 100.0% | 100.0% | — |
| flash-low/fixed | supported_fact | 3/3 | 100.0% | 100.0% | 0.0% |

## Screenshot transcription

| Model / track | Screenshot cases | Character error rate | Word error rate | Exact normalized text |
|---|---:|---:|---:|---:|
| flash-lite-minimal/fixed | 6 | 0.0% | 0.0% | 100.0% |
| flash-low/fixed | 6 | 0.0% | 0.0% | 100.0% |

OCR uses Unicode NFC, case folding, and whitespace normalization. Screenshots share semantic clusters with their text originals. Character/word error rates may exceed 100% if a response invents substantial text. Images are six synthetic legible fixtures, not a real feed OCR benchmark.


## Paired differences

Differences are **right minus left**, using successful paired cases. Repetitions are averaged per case, then EN/RO/RU variants are grouped by semantic cluster before bootstrap resampling. Lower latency and false-accusation rates are better. Intervals describe this small development set, not population performance.

| Track | Left | Right | Metric | Difference | 95% cluster interval | Clusters |
|---|---|---|---|---:|---|---:|
| fixed | flash-lite-minimal | flash-low | kind_accuracy | 0.17 | [0.00, 0.33] | 2 |
| fixed | flash-lite-minimal | flash-low | verdict_accuracy | 0.17 | [0.00, 0.33] | 2 |
| fixed | flash-lite-minimal | flash-low | false_accusation_rate | 0.00 | — | 1 |
| fixed | flash-lite-minimal | flash-low | purpose_accuracy | -0.17 | [-0.33, 0.00] | 2 |
| fixed | flash-lite-minimal | flash-low | duration_seconds | 0.86 | [0.70, 1.02] | 2 |

## Interpretation

- Fixed-track duration covers one model request with supplied evidence, with no search or harness retry. Live-track duration covers the full CLAR pipeline: extraction, retrieval, assessment, its retries, and formatting. Process startup and benchmark queue waiting are recorded separately. No time-to-first-token number is inferred.
- Unknown token usage remains unknown. Cost is not estimated without a pinned price sheet and provider billing information.
- An existing evidence ID is not proof of entailment. Relevant-citation scores compare editorial claim/evidence associations; real entailment still needs human review.
- Live cases expose retrieved URLs and dated labels. Search drift, different retrieval corpora, and publisher changes can explain score differences. Live media-purpose scores are disabled because those reused demo labels were not curated for that task.
- Results contain a dataset hash, configuration hash, fixed prompt hash, and pipeline code hashes for reproducibility. Models can change behind aliases; provider-reported model IDs are retained when available.
- Use separate manual review and held-out locally collected cases before making release claims. v1 includes text and six synthetic screenshots; photographic memes, mixed scripts, cropping, and low-quality screenshots need a larger independently reviewed corpus. Confidence calibration is not measured.

Machine-readable records: `records.jsonl`. Warmups: `warmups.jsonl` (excluded). Full metrics and confusion matrices: `summary.json`.
