# Initial model measurements — 26 September 2026

These are actual provider runs on the versioned editorial development dataset. They measure one structured fixed-evidence task per call. They do not measure the complete web-search fact-check pipeline or independent real-world accuracy. Labels have not received independent human review.

## Full text set

60 cases per model, 20 semantic clusters across EN/RO/RU, one measured repetition and one excluded warmup per model. Requests were interleaved in seeded random order with concurrency 1. Google inference hardware is managed and undisclosed; the client was an Apple M4 with 16 GB RAM.

| Model / thinking | Completed | Verdict macro F1 | False accusation rate | Median seconds | p95 seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.5 Flash / low | 59/60 | 0.514 | 7.0% | 1.87 | 4.07 |
| Gemini 3.5 Flash-Lite / minimal | 57/60 | 0.867 | 10.9% | 1.46 | 1.81 |

Quality and latency columns are conditional on successful responses; completion is shown alongside them. Flash-Lite was faster in this run and had a higher verdict F1, while Flash completed more cases and had fewer false accusations. This is a tradeoff on this dataset, not an overall ranking. No application default was changed by this benchmark.

## Screenshots and local model smoke test

Both Google models completed all six legible synthetic screenshots. Their median request times were 2.87s for Flash and 2.31s for Flash-Lite. Read the OCR and verdict metrics together in the image report.

Native Ollama `qwen2.5vl:3b` on Apple M4 / 16 GB was tested on a separate six-case subset with one repetition and one warmup. It produced valid task outputs on 3/6 cases; successful calls had a 3.81s median. Its quality scores are conditional on those three responses, so they are not comparable to the full 60-case table. This tests the strict benchmark contract, not every local CLAR workflow.

## Full artifacts

- [Full Google text comparison](google-full-text/report.md) — 120 measured calls.
- [Repeated Google subset](google-baseline/report.md) — six cases × three repetitions × two models.
- [Google screenshots](google-images/report.md) — six screenshots × two models.
- [Local Ollama subset](local-baseline/report.md) — six measured calls.

Each directory includes the manifest, measured records, excluded warmups, summary and report. Records preserve provider errors and invalid output instead of silently retrying or discarding failures. All posts and screenshots are synthetic or explicitly documented dataset inputs; no private Facebook data or credentials are included.

Use the [benchmark guide](../../../benchmarks/README.md) to reproduce or extend the runs. Match model availability, thinking/sampling settings, dataset hashes, repetitions and concurrency. Client workloads were not exclusively reserved; provider routing/load and local model residency may change latency. The published live demo fixtures have not been run as part of these reported comparisons.
