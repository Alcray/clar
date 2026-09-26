# CLAR

Evidence and media literacy for one Facebook post at a time. CLAR separates checkable claims from opinions, shows retrieved sources, and explains observable persuasion cues with quotations. Use the web app or the Chrome extension, with local models or Google's APIs.

Licensed under [Apache-2.0](LICENSE). Model weights and external publisher content keep their own licenses.

## What is included

- A compact Facebook result card, optional detailed analysis, EN/RO/RU output, and local result caching.
- Per-claim assessments, source stances, explicit uncertainty, and fact-check matching that distinguishes a claim from its refutation.
- Ollama, OpenAI-compatible local endpoints, Gemini API, and Vertex AI Express adapters.
- A Uvicorn application with bounded requests/jobs, invitation authentication, health checks and a non-root Docker deployment.
- A [reproducible model benchmark](benchmarks/README.md): fixed evidence, live retrieval, synthetic screenshots, quality metrics and complete request latency.

## Quick start: Docker and an existing model server

Requires Docker Engine and Compose v2.24+. Install a model on your inference server first; CLAR does not download weights automatically.

```sh
git clone https://github.com/Alcray/clar.git
cd clar
cp .env.example .env
# Edit LOCAL_MODEL and OLLAMA_BASE_URL in .env for your inference server.
docker compose build
docker compose run --rm clar python manage_invites.py create owner
docker compose up -d clar
```

Save the invitation code printed once by the create command. Open [localhost:8765](http://localhost:8765), enter it, and choose **Get CLAR for Chrome** for installation and pairing. The Docker host port is loopback by default. `GET /healthz` checks the app; `GET /readyz` checks model configuration/readiness.

For Docker Desktop with native Ollama, `OLLAMA_BASE_URL=http://host.docker.internal:11434` reaches the host. On Linux, the host model server must listen on an interface reachable from Docker, or use the optional Ollama service below. Do not expose an unauthenticated model server to the public internet.

## Choose your inference provider

| Provider | Configuration | Retrieval used by CLAR |
| --- | --- | --- |
| Ollama | `DEFAULT_PROVIDER=local`, `LOCAL_PROVIDER=ollama`, `LOCAL_MODEL`, `OLLAMA_BASE_URL` | A limited collection of official documents and verified fact-check records |
| OpenAI-compatible local server | `DEFAULT_PROVIDER=local`, `LOCAL_PROVIDER=openai`, `LOCAL_MODEL`, `LOCAL_API_BASE_URL` | The same limited collection |
| Vertex AI Express | `DEFAULT_PROVIDER=vertex`, `VERTEX_MODEL`, `VERTEX_API_KEY` | Google Search grounding and verified fact-check records |
| Gemini API | `DEFAULT_PROVIDER=gemini`, `GEMINI_MODEL`, `GEMINI_API_KEY` | Google Search grounding and verified fact-check records |

For vLLM, llama.cpp or another compatible server, `LOCAL_API_BASE_URL` must end at its API base, for example `http://model-server:8000/v1`. JSON schema output is required. Image input also requires a vision-capable model; text-only models can analyze pasted text. Optional local API credentials use `LOCAL_API_KEY` or the variable named by `LOCAL_API_KEY_ENV`.

Local inference does not mean fully offline fact checking: live local analysis retrieves the allowlisted documents in `local_analysis.SOURCES`. `config/sources.json` defines domain priorities and verified page identities. Source coverage differs from Google Search, so local and cloud live results must be compared with that limitation visible.

For an NVIDIA Docker host, set `OLLAMA_BASE_URL=http://ollama:11434` in `.env`, then:

```sh
docker compose --profile gpu up -d ollama
docker compose exec ollama ollama pull qwen2.5vl:3b
docker compose up -d clar
```

The profile reserves one GPU and does not publish the Ollama port. Choose model size, quantization and context to fit your hardware. On Apple Silicon, run Ollama natively. Full configuration, HTTPS, native installation, backups and operational limits are in [SELF-HOSTING.md](docs/SELF-HOSTING.md).

## Build an extension for your server

The default package targets localhost and selects local inference. A custom build packages its permitted server origins into the settings list, Chrome permissions and CSP together:

```sh
python3 tools/build_extension.py \
  --backend https://clar.example.org \
  --default-provider local \
  --output-dir dist/extension \
  --archive dist/clar-extension.zip
```

For Docker, set `CLAR_BACKEND=https://clar.example.org` before building so the download served by that image targets your address. HTTPS is required for remote extension backends; HTTP is supported for localhost. API keys are never packaged. See the [extension guide](extension/README.md).

## Compare model quality and speed

The benchmark has separate `fixed` and `live` tracks. The fixed track gives every model the same synthetic evidence, including distractors. The live track evaluates the actual pipeline and records its retrieval regime. Neither uses the application result cache.

```sh
python3 -m benchmarks validate
python3 -m benchmarks run \
  --matrix benchmarks/matrix.example.json \
  --models flash-low,flash-lite-minimal \
  --track fixed --repetitions 3 --warmups 1 --concurrency 1 \
  --save-responses --out .runtime/benchmarks/comparison
```

The same harness is included in the image: `docker compose run --rm clar python -m benchmarks validate`. Give container benchmark runs an explicit writable output path such as `--out /data/benchmarks/run-1`.

Export the credentials named by the matrix before running. For existing local inference, select `qwen-vl-local` and edit its endpoint/model first. Use `--dry-run` to validate a plan without model calls, and `--modality image` for the six screenshot cases. Start with a filtered subset before a paid full run.

Initial real measurements are published in [the benchmark results](docs/benchmarks/2026-09-26/README.md), including failures and the exact run configurations.

Results include JSONL records, JSON summaries and a Markdown comparison with completion rate, quality, citations, false accusations, coverage, OCR, p50/p95 latency and paired uncertainty estimates. Failed requests are reported separately from quality. There is no invented first-token latency or calibrated confidence score. The [benchmark guide](benchmarks/README.md) explains dataset provenance, scoring, limits, and how to add independently reviewed cases.

## Development

Python 3.10+ is supported on Linux/macOS. Browser tests use Node 24 and Playwright.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-server.txt
python tools/build_extension.py
# For native Ollama, use http://127.0.0.1:11434 rather than Docker's host name.
python -m app
```

Use `python -m app` for deployment. `python server.py` remains a legacy preview/test entry point.

```sh
python -m unittest discover -s tests -q
python -m benchmarks validate
npm ci
npx playwright install chromium
npm test
```

The normal tests use synthetic posts and mocked providers. The benchmark live track makes real model calls using the operator-configured credentials. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Operational and quality limits

CLAR currently supports one application process and one replica. In-memory jobs and file-backed state are bounded; a shared durable queue/database is needed for horizontal scaling. A restart loses pending jobs. Public mode requires invitations and enforces configured daily limits. Store runtime data and credentials privately and terminate public HTTPS at a reverse proxy.

Assessments are fallible. An official origin does not establish truth, persuasion does not prove coordinated propaganda, and an advertisement is not automatically fraud. The starter benchmark has editorial development labels; it is not independent human validation or a production accuracy certification. Screenshots are transcribed, not authenticated. Facebook can change its DOM and break extraction.

See [PRIVACY.md](PRIVACY.md) for what leaves the browser, what is cached, and what feedback is stored.
