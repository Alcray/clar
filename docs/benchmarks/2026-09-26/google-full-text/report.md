# CLAR model benchmark

Run `2026-09-26T144127.326429+0000-c9fe6db7`. Dataset `editorial-v1`. Benchmark `1.0.0`.

**Editorial development cases, not independently validated gold or an unbiased held-out evaluation.** Fixed and live tracks answer different questions and must be compared separately. Quality metrics below are conditional on successful responses; completion rates and failures stay visible.

| Model / track | Completed | Kind macro F1 | Verdict macro F1 | False accusations | Decisive coverage | p50 s | p95 s |
|---|---:|---:|---:|---:|---:|---:|---:|
| flash-lite-minimal/fixed | 57/60 | 80.7% | 86.7% | 10.9% | 85.0% | 1.46 | 1.81 |
| flash-low/fixed | 59/60 | 79.9% | 51.4% | 7.0% | 80.5% | 1.87 | 4.07 |

## Reliability and source discipline

| Model / track | Completion | Source ID validity | Relevant citations | Citation coverage | Statement quotes | Technique quotes | Purpose |
|---|---:|---:|---:|---:|---:|---:|---:|
| flash-lite-minimal/fixed | 95.0% | 100.0% | 80.0% | 97.1% | 97.3% | 96.2% | 86.0% |
| flash-low/fixed | 98.3% | 100.0% | 85.7% | 94.3% | 95.1% | 100.0% | 86.4% |

flash-lite-minimal/fixed failures: `{"OutputValidationError": 3}`.

flash-low/fixed failures: `{"incomplete_output": 1}`.

## By language

| Model / track | Language | Completed | Kind macro F1 | Verdict macro F1 | p50 s | p95 s |
|---|---|---:|---:|---:|---:|---:|
| flash-lite-minimal/fixed | en | 19/20 | 82.2% | 82.9% | 1.46 | 1.82 |
| flash-lite-minimal/fixed | ro | 18/20 | 72.2% | 87.1% | 1.56 | 1.85 |
| flash-lite-minimal/fixed | ru | 20/20 | 85.8% | 84.7% | 1.36 | 1.71 |
| flash-low/fixed | en | 20/20 | 80.0% | 56.2% | 1.89 | 3.30 |
| flash-low/fixed | ro | 19/20 | 76.6% | 64.2% | 1.85 | 4.78 |
| flash-low/fixed | ru | 20/20 | 82.1% | 82.8% | 1.86 | 3.14 |

## By category

| Model / track | Category | Completed | Kind accuracy | Verdict accuracy | False accusations |
|---|---|---:|---:|---:|---:|
| flash-lite-minimal/fixed | conflicting_evidence | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-lite-minimal/fixed | conspiracy_and_certainty | 3/3 | 75.0% | 100.0% | 0.0% |
| flash-lite-minimal/fixed | contradicted_fact | 3/3 | 100.0% | 100.0% | — |
| flash-lite-minimal/fixed | emotional_group_framing | 2/3 | 50.0% | 0.0% | 0.0% |
| flash-lite-minimal/fixed | explicit_authority_appeal | 2/3 | 100.0% | — | 0.0% |
| flash-lite-minimal/fixed | explicit_persuasion | 2/3 | 100.0% | — | 0.0% |
| flash-lite-minimal/fixed | fraud | 3/3 | 75.0% | 75.0% | — |
| flash-lite-minimal/fixed | harmless_advertising | 3/3 | 60.0% | 100.0% | 0.0% |
| flash-lite-minimal/fixed | harmless_opinion | 3/3 | 100.0% | — | 0.0% |
| flash-lite-minimal/fixed | insufficient_evidence | 3/3 | 100.0% | 0.0% | 100.0% |
| flash-lite-minimal/fixed | misleading_scope | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-lite-minimal/fixed | mixed | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-lite-minimal/fixed | negation | 3/3 | 100.0% | 80.0% | 20.0% |
| flash-lite-minimal/fixed | neutral_institutional_attribution | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-lite-minimal/fixed | prediction | 3/3 | 33.3% | — | 0.0% |
| flash-lite-minimal/fixed | prompt_injection | 3/3 | 100.0% | 100.0% | — |
| flash-lite-minimal/fixed | quotation_stance | 3/3 | 100.0% | — | 0.0% |
| flash-lite-minimal/fixed | satire | 3/3 | 0.0% | — | 66.7% |
| flash-lite-minimal/fixed | supported_fact | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-lite-minimal/fixed | unclear | 3/3 | 100.0% | — | 0.0% |
| flash-low/fixed | conflicting_evidence | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-low/fixed | conspiracy_and_certainty | 3/3 | 33.3% | 50.0% | 0.0% |
| flash-low/fixed | contradicted_fact | 3/3 | 100.0% | 100.0% | — |
| flash-low/fixed | emotional_group_framing | 3/3 | 50.0% | — | 0.0% |
| flash-low/fixed | explicit_authority_appeal | 3/3 | 14.3% | 0.0% | 0.0% |
| flash-low/fixed | explicit_persuasion | 3/3 | 100.0% | — | 0.0% |
| flash-low/fixed | fraud | 3/3 | 50.0% | 60.0% | — |
| flash-low/fixed | harmless_advertising | 3/3 | 60.0% | 100.0% | 0.0% |
| flash-low/fixed | harmless_opinion | 3/3 | 100.0% | — | 0.0% |
| flash-low/fixed | insufficient_evidence | 3/3 | 100.0% | 0.0% | 100.0% |
| flash-low/fixed | misleading_scope | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-low/fixed | mixed | 2/3 | 100.0% | 100.0% | 0.0% |
| flash-low/fixed | negation | 3/3 | 100.0% | 50.0% | 16.7% |
| flash-low/fixed | neutral_institutional_attribution | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-low/fixed | prediction | 3/3 | 100.0% | — | 0.0% |
| flash-low/fixed | prompt_injection | 3/3 | 100.0% | 100.0% | — |
| flash-low/fixed | quotation_stance | 3/3 | 100.0% | — | 0.0% |
| flash-low/fixed | satire | 3/3 | 33.3% | — | 0.0% |
| flash-low/fixed | supported_fact | 3/3 | 100.0% | 100.0% | 0.0% |
| flash-low/fixed | unclear | 3/3 | 100.0% | — | 0.0% |

## Screenshot transcription

| Model / track | Screenshot cases | Character error rate | Word error rate | Exact normalized text |
|---|---:|---:|---:|---:|
| flash-lite-minimal/fixed | 0 | — | — | — |
| flash-low/fixed | 0 | — | — | — |

OCR uses Unicode NFC, case folding, and whitespace normalization. Screenshots share semantic clusters with their text originals. Character/word error rates may exceed 100% if a response invents substantial text. Images are six synthetic legible fixtures, not a real feed OCR benchmark.


## Paired differences

Differences are **right minus left**, using successful paired cases. Repetitions are averaged per case, then EN/RO/RU variants are grouped by semantic cluster before bootstrap resampling. Lower latency and false-accusation rates are better. Intervals describe this small development set, not population performance.

| Track | Left | Right | Metric | Difference | 95% cluster interval | Clusters |
|---|---|---|---|---:|---|---:|
| fixed | flash-lite-minimal | flash-low | kind_accuracy | -0.02 | [-0.12, 0.08] | 20 |
| fixed | flash-lite-minimal | flash-low | verdict_accuracy | -0.07 | [-0.15, 0.00] | 12 |
| fixed | flash-lite-minimal | flash-low | false_accusation_rate | -0.04 | [-0.12, 0.00] | 17 |
| fixed | flash-lite-minimal | flash-low | purpose_accuracy | -0.00 | [-0.13, 0.12] | 20 |
| fixed | flash-lite-minimal | flash-low | duration_seconds | 0.64 | [0.47, 0.83] | 20 |

## Interpretation

- Fixed-track duration covers one model request with supplied evidence, with no search or harness retry. Live-track duration covers the full CLAR pipeline: extraction, retrieval, assessment, its retries, and formatting. Process startup and benchmark queue waiting are recorded separately. No time-to-first-token number is inferred.
- Unknown token usage remains unknown. Cost is not estimated without a pinned price sheet and provider billing information.
- An existing evidence ID is not proof of entailment. Relevant-citation scores compare editorial claim/evidence associations; real entailment still needs human review.
- Live cases expose retrieved URLs and dated labels. Search drift, different retrieval corpora, and publisher changes can explain score differences. Live media-purpose scores are disabled because those reused demo labels were not curated for that task.
- Results contain a dataset hash, configuration hash, fixed prompt hash, and pipeline code hashes for reproducibility. Models can change behind aliases; provider-reported model IDs are retained when available.
- Use separate manual review and held-out locally collected cases before making release claims. v1 includes text and six synthetic screenshots; photographic memes, mixed scripts, cropping, and low-quality screenshots need a larger independently reviewed corpus. Confidence calibration is not measured.

Machine-readable records: `records.jsonl`. Warmups: `warmups.jsonl` (excluded). Full metrics and confusion matrices: `summary.json`.
