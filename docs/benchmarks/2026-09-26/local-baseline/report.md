# CLAR model benchmark

Run `2026-09-26T144320.809788+0000-f22a5af8`. Dataset `editorial-v1`. Benchmark `1.0.0`.

**Editorial development cases, not independently validated gold or an unbiased held-out evaluation.** Fixed and live tracks answer different questions and must be compared separately. Quality metrics below are conditional on successful responses; completion rates and failures stay visible.

| Model / track | Completed | Kind macro F1 | Verdict macro F1 | False accusations | Decisive coverage | p50 s | p95 s |
|---|---:|---:|---:|---:|---:|---:|---:|
| qwen-vl-local/fixed | 3/6 | 40.0% | 16.7% | 0.0% | 66.7% | 3.81 | 4.11 |

## Reliability and source discipline

| Model / track | Completion | Source ID validity | Relevant citations | Citation coverage | Statement quotes | Technique quotes | Purpose |
|---|---:|---:|---:|---:|---:|---:|---:|
| qwen-vl-local/fixed | 50.0% | 100.0% | 100.0% | 100.0% | 100.0% | — | 66.7% |

qwen-vl-local/fixed failures: `{"OutputValidationError": 3}`.

## By language

| Model / track | Language | Completed | Kind macro F1 | Verdict macro F1 | p50 s | p95 s |
|---|---|---:|---:|---:|---:|---:|
| qwen-vl-local/fixed | en | 1/2 | 100.0% | 100.0% | 3.81 | 3.81 |
| qwen-vl-local/fixed | ro | 1/2 | 100.0% | 0.0% | 4.14 | 4.14 |
| qwen-vl-local/fixed | ru | 1/2 | 0.0% | 0.0% | 3.56 | 3.56 |

## By category

| Model / track | Category | Completed | Kind accuracy | Verdict accuracy | False accusations |
|---|---|---:|---:|---:|---:|
| qwen-vl-local/fixed | contradicted_fact | 1/1 | 100.0% | 0.0% | — |
| qwen-vl-local/fixed | explicit_persuasion | 0/1 | — | — | — |
| qwen-vl-local/fixed | fraud | 0/1 | — | — | — |
| qwen-vl-local/fixed | insufficient_evidence | 1/1 | 0.0% | 0.0% | 0.0% |
| qwen-vl-local/fixed | neutral_institutional_attribution | 0/1 | — | — | — |
| qwen-vl-local/fixed | supported_fact | 1/1 | 100.0% | 100.0% | 0.0% |

## Screenshot transcription

| Model / track | Screenshot cases | Character error rate | Word error rate | Exact normalized text |
|---|---:|---:|---:|---:|
| qwen-vl-local/fixed | 0 | — | — | — |

OCR uses Unicode NFC, case folding, and whitespace normalization. Screenshots share semantic clusters with their text originals. Character/word error rates may exceed 100% if a response invents substantial text. Images are six synthetic legible fixtures, not a real feed OCR benchmark.


## Interpretation

- Fixed-track duration covers one model request with supplied evidence, with no search or harness retry. Live-track duration covers the full CLAR pipeline: extraction, retrieval, assessment, its retries, and formatting. Process startup and benchmark queue waiting are recorded separately. No time-to-first-token number is inferred.
- Unknown token usage remains unknown. Cost is not estimated without a pinned price sheet and provider billing information.
- An existing evidence ID is not proof of entailment. Relevant-citation scores compare editorial claim/evidence associations; real entailment still needs human review.
- Live cases expose retrieved URLs and dated labels. Search drift, different retrieval corpora, and publisher changes can explain score differences. Live media-purpose scores are disabled because those reused demo labels were not curated for that task.
- Results contain a dataset hash, configuration hash, fixed prompt hash, and pipeline code hashes for reproducibility. Models can change behind aliases; provider-reported model IDs are retained when available.
- Use separate manual review and held-out locally collected cases before making release claims. v1 includes text and six synthetic screenshots; photographic memes, mixed scripts, cropping, and low-quality screenshots need a larger independently reviewed corpus. Confidence calibration is not measured.

Machine-readable records: `records.jsonl`. Warmups: `warmups.jsonl` (excluded). Full metrics and confusion matrices: `summary.json`.
