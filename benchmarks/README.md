# CLAR model benchmark

Compare model quality, reliability, and complete request latency with a reproducible task and evidence budget. This is a **development benchmark with editorial labels**, not independently human-validated gold, a production certification, or an unbiased held-out leaderboard.

The starter dataset contains **60 original text cases** in English, Romanian, and Russian (20 semantic clusters), **6 synthetic screenshot variants**, and **7 explicitly reused live demo smoke cases**. Each case records its origin, label rationale, and development status. Fixed evidence is invented test data about a fictional town; it does not assert real political, legal, or medical facts.

## Two separate tracks

| Track | What is measured | Evidence | Important limit |
|---|---|---|---|
| `fixed` | Classification, evidence interpretation, persuasion and structured-output quality under the same task | Identical supplied excerpts per case, with dated/irrelevant distractors; search disabled | Tests model behavior, not ability to find web evidence |
| `live` | Complete CLAR extraction → research → assessment → formatting pipeline | Current Google Search or the local pipeline's limited official-source corpus | Retrieval methods differ; results are not a pure model-quality comparison |

Fixed calls use `model_runtime.call_model` once. Malformed JSON and contradictory kind/verdict applicability are recorded as invalid output; the harness does not silently repair them. Live calls use `pipeline_runtime.analyze_with_config(..., use_cache=False)` and retain the application's retry behavior. Both bypass the application result cache; the live local source cache is explicitly bypassed. Provider prompt/KV caching can still occur, so reported cache tokens and model load time are retained when available.

The 7 live cases are the existing StopFals/government **positive demo smoke inputs**, with their reused origin visible in every case. They do not establish the safety of negative/refuted-claim matching, and their purpose/technique labels are not scored. Add independently reviewed live counterexamples before treating them as a matching-quality evaluation. Dated editorial labels and returned URLs make retrieval drift reviewable; a changed source can justify a different answer.

## Validate without making model calls

Python 3.10+ and the repository's standard-library runtime are sufficient for the harness. The local model server is a separate process.

```sh
python3 -m benchmarks validate
python3 -m benchmarks run \
  --matrix benchmarks/matrix.example.json \
  --models flash-low,flash-lite-minimal \
  --track fixed --limit 3 --dry-run \
  --out .runtime/benchmarks/dry-run
```

A dry run validates the dataset, screenshot hashes, model matrix and selection, then writes only `manifest.json`. It does not contact a model or manufacture performance results. Choose a fresh output directory for every run.

## Configure models

Copy `matrix.example.json` and edit the model IDs/endpoints to those available to you. The example includes the deployed Google baseline and proposed comparison:

- `flash-low`: Vertex `gemini-3.5-flash`, `thinking: low`.
- `flash-lite-minimal`: Vertex `gemini-3.5-flash-lite`, `thinking: minimal`.
- `qwen-vl-local`: Ollama `qwen2.5vl:3b` at `http://127.0.0.1:11434`.
- `openai-compatible-local`: a placeholder for an OpenAI-compatible inference server; replace `your-served-model-id`.

Listing an ID does not prove it is available to your account/server. An unavailable model is recorded as a failed request. Choose an image-capable model when selecting screenshots.

Credentials must be supplied by environment variable names such as `VERTEX_API_KEY`; the matrix forbids inline keys and credential-bearing/query-string endpoints. Provision these through your shell or secret manager. The harness does not load or print `.env` files.

Each entry supports `provider`, `model`, `endpoint`, `api_key_env`, `thinking`, `timeout_seconds`, `max_output_tokens`, `context_tokens`, and `temperature`. `temperature: null` leaves provider defaults in effect; local examples set 0. Compare sampling settings explicitly and record them. The manifest expands default settings, and successful adapter construction records its actual public config. Use `--hardware-note` to record the inference device, quantization or managed API region. The manifest records the client Python/OS/CPU architecture; it cannot infer remote model hardware. Model/provider aliases can change; reported model versions are retained when the provider supplies them.

## Run a comparison

Start with a small balanced selection. This example evaluates six semantic cases, covering all three languages, using two models and three repetitions:

```sh
python3 -m benchmarks run \
  --matrix benchmarks/matrix.example.json \
  --models flash-low,flash-lite-minimal \
  --track fixed --repetitions 3 --warmups 1 --concurrency 1 \
  --case-id calendar-en \
  --case-id library-closed-ro \
  --case-id unknown-contract-ru \
  --case-id neutral-titles-en \
  --case-id fear-share-ro \
  --case-id pin-refund-ru \
  --save-responses --out .runtime/benchmarks/google-smoke
```

Remove the `--case-id` arguments to run the complete text corpus. `--language`, `--category`, `--models` and `--limit` can also filter a run. `--limit` takes the first selected cases and is useful for transport smoke tests; it is not a balanced sample.

Requests are interleaved in a seeded random order. `--repetitions` changes measured repetitions. `--warmups` makes separate calls for each model/track and saves them to `warmups.jsonl`, outside all reported quality and latency metrics. Warmups still consume provider/GPU resources. `--concurrency 1` avoids benchmark-created contention; raising it evaluates a different load condition. An Ollama warmup may warm the serving process, but does not guarantee a model remains loaded throughout an interleaved matrix.

The subprocess watchdog defaults to `--case-timeout 180`. It includes worker startup; each HTTP request also has its model's `timeout_seconds`. On deadline, the harness terminates that local worker and records a timeout, preserving completed live-stage telemetry when available. A request already accepted by a remote provider can continue and be billed. A timeout never claims a completed quality assessment.

A fixed case normally makes one model call. A live case can make several research/formatting calls plus retries; the printed measured-case count is **not** a billing call estimate. Start with a small selection before expanding paid runs.

For GPU workstation or cloud execution, follow your operator's compute scheduling policy. The benchmark client can target an already deployed local endpoint; benchmark output does not claim that the model server is isolated from other workloads.

## Screenshots

```sh
python3 -m benchmarks run \
  --matrix benchmarks/matrix.example.json \
  --models flash-low,flash-lite-minimal \
  --track fixed --modality image --repetitions 3 --concurrency 1 \
  --save-responses --out .runtime/benchmarks/screenshots
```

`--modality text` is the default. `image` selects six screenshot cases; `all` includes text and image variants. The model receives screenshot pixels and the same supplied evidence, **without the plaintext post, expected verdicts, or editorial rationale**. It must return `original_text` along with its assessment. Dataset and input hashes include screenshot bytes. PNGs are generated by `tools/render_benchmark_images.mjs`; `data/build_editorial.py` refreshes their recorded hashes after intentional updates.

OCR metrics report character error rate (CER), word error rate (WER), and exact normalized transcription rate. Normalization uses Unicode NFC, case folding, and collapsed whitespace; punctuation remains. Error rates can exceed 100% when a model adds extensive nonexistent text. These legible synthetic screenshots are a regression starter, not evidence of accuracy on cropped, photographic, mixed-script, or low-quality Facebook posts.

## Artifacts and interpretation

Each run writes:

- `manifest.json`: configuration/defaults, selected cases, dataset hash, prompt/schema hashes, source-code and retrieval-configuration hashes, concurrency, timeouts, seed and limitations.
- `records.jsonl`: one measured case/repetition with status, timing, usage when known, scores, error code, and live retrieved URLs/freshness metadata. Full normalized model answers are included only with `--save-responses`. When a parsed fixed-track task answer reaches the benchmark validator but fails it, this option retains only bounded task fields as `invalid_response` (at most 64 KiB), with an explicit truncation flag and a stable safe validation reason/code. Such records remain invalid and receive no quality scores. Raw malformed JSON, provider response envelopes, headers and API error bodies are never saved. Earlier runs that discarded invalid answers cannot recover them retrospectively.
- `warmups.jsonl`: explicitly excluded warmup calls.
- `summary.json`: full metric counts, confusion matrices, language/category/modality groups and paired differences.
- `report.md`: a reviewable comparison table, reliability diagnostics and caveats.

Exit status is 0 only when every measured request completes successfully, 2 when requests fail or configuration is invalid. Quality weaknesses do not change the exit code; choose reviewed application-specific thresholds before using results as a release gate.

| Metric | Definition |
|---|---|
| Kind macro F1 | Factual/opinion/prediction/unclear, after one-to-one quote alignment. Missing and extra statements are penalized. |
| Verdict macro F1 | Supported/contradicted/misleading/conflicting/insufficient for expected factual statements; missing/extra factual claims count. |
| Extraction | Matched expected statements divided by extracted/expected statements, respectively. |
| Decisive coverage | Supported, contradicted or misleading results divided by all expected factual statements. |
| Abstention | Insufficient/conflicting assessments among answered expected factual statements. Missing extraction is reported separately. |
| False accusation rate | Contradicted/misleading assessments on expected non-harmful statements; extra harmful invented claims and false fraud allegations are separate metrics. |
| Citation ID validity | Fraction of returned evidence IDs that exist in the supplied packet. This is not entailment. |
| Citation relevance | Fraction of all citations attached to the editorially associated claim. Citations on unmatched extra claims count against relevance. |
| Citation coverage | Fraction of all expected evidence-requiring claims with a relevant citation. Missing claims stay in the denominator. |
| Exact quote compliance | Statement/cue quotations that are literal spans of the original post. It does not independently prove the cue's interpretation. |
| Purpose and persuasion | Main-purpose accuracy, fraud accuracy and per-technique confusion counts/F1. All seven techniques have positive starter examples. |
| Reliability | Completion rate, invalid-output/failure/timeout counts and error codes. Failed requests have no invented zero-quality score. |
| Latency | Full adapter execution p50/p95/mean/min/max for completed cases; all-attempt latency is separate. Queue waiting and process startup are separate record fields. |

A model that returns no answer can therefore have an empty quality column, not a misleading perfect or zero result. Always read quality alongside completion and coverage. Unknown token usage remains `null`/unavailable, never zero cost. No TTFT is invented from non-streaming calls, and confidence calibration is not measured.

Quote alignment is deterministic and deliberately simple: exact/normalized overlap, one-to-one, threshold 0.45. It is a diagnostic surrogate for human semantic matching. Budget and refutation examples include explicit equivalent compound/atomic segmentations; the chosen variant is based on span alignment, not which labels yield a better score. Audit model outputs when segmentation or paraphrasing drives a failure. Fixed prompts request exact contiguous quotes.

Paired bootstrap intervals compare right minus left on successfully answered shared cases. Repetitions are averaged, then translated/image variants are grouped by their semantic cluster before resampling. This avoids treating translations or screenshot copies as independent examples. The intervals describe this small development set; they are not a claim about population accuracy. There is no arbitrary composite quality leaderboard score.

## Maintain the benchmark

1. Add new cases with provenance, exact expected spans, evidence associations, rationale, dated live labels, and a semantic cluster ID.
2. Include negative controls: neutral titles, harmless advertising, rejected quotations, insufficient evidence, date/scope changes, mixed statements, and untrusted instructions.
3. Keep expected labels and rationale out of adapter inputs. Add relevant and plausible distracting evidence so citing everything cannot pass.
4. Review cases independently with Romanian/Russian speakers and subject experts. Record reviewers and adjudicated disagreements in a new dataset version; do not retroactively call the starter labels validated.
5. Preserve a genuinely separate held-out set that is not used for prompt tuning. Existing demo fixtures must remain visibly identified as reused.
6. Bump dataset/prompt versions for meaning changes; preserve prior artifacts and inspect live source drift before relabeling.

Run the harness checks without credentials or model calls:

```sh
python3 -m unittest discover -s tests -p 'test_benchmark*.py'
python3 -m benchmarks validate
```

The original synthetic fixed cases and rendered text images are dedicated under CC0-1.0 by this project's contributors. Live fixtures contain short editorial claims and links to their existing provenance, not copied articles. Project source licensing is defined by the repository's license.
