# Self-host CLAR

The supported server entry point is **`python -m app`**, using Uvicorn and the same request/authentication logic as the existing preview. Use one application process and one replica (a runtime-directory lock rejects a second process): jobs and results live in memory and the file-backed quota lock is process-local. Restarting discards all server jobs and results; completed extension results remain in its 24-hour browser cache. Multiple replicas require an external shared queue and transactional state store before deployment.

## Native install with an existing Ollama server

For native Linux/macOS installation, Python 3.10 or newer is required. Use a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-server.txt
cp .env.example .env
python tools/build_extension.py
```

Choose a model already installed on your inference server and set these `.env` values:

```dotenv
HOST=127.0.0.1
PORT=8765
ALLOWED_HOSTS=localhost,127.0.0.1,::1
DEFAULT_PROVIDER=local
LOCAL_PROVIDER=ollama
LOCAL_MODEL=qwen2.5vl:3b
OLLAMA_BASE_URL=http://127.0.0.1:11434
CLAR_RUNTIME_DIR=.runtime
```

Run `python -m app` and open `http://localhost:8765`. Loopback mode permits the local web app; its extension pairing token is generated in `.runtime/owner.env` with owner-only permissions. The setup page returns this token to the local app. Keep the runtime directory private.

CLAR does not install a model automatically. Pull your chosen model on the machine that runs Ollama before checking `/readyz`. Local factual analysis also fetches a small configured set of public evidence sources; local inference alone does not make the complete fact-check pipeline offline. The fetched document list is `SOURCES` in `local_analysis.py`. `config/sources.json` separately defines domain and Facebook-page registries used for origin and fact-check handling.

## An existing OpenAI-compatible model server

For llama.cpp, vLLM or another compatible `/v1/chat/completions` service, set:

```dotenv
DEFAULT_PROVIDER=local
LOCAL_PROVIDER=openai
LOCAL_MODEL=your-served-model-name
LOCAL_API_BASE_URL=http://127.0.0.1:8080/v1
LOCAL_API_KEY_ENV=LOCAL_API_KEY
LOCAL_API_KEY=
```

Model names must match the inference server. Use an image-capable model for screenshot input; a text-only model can benchmark and analyze pasted post text. The endpoint is administrator configuration, never a URL accepted from an analyzed post. Keep a remote model endpoint on a private network or use HTTPS and authentication.

## Docker Compose

Docker Engine and Compose v2.24 or newer are required. The CLAR container runs as UID/GID 10001, uses a read-only root filesystem and writes only to its named runtime volume. The host port defaults to loopback. The build context excludes `.env`, runtime records, private deployment scripts and repository history.

```sh
cp .env.example .env
# For Ollama already on the host, set in .env:
# OLLAMA_BASE_URL=http://host.docker.internal:11434
# For a remote server, use its reachable private address instead.
docker compose build
docker compose run --rm clar python manage_invites.py create owner
docker compose up -d clar
```

Save the access code printed by the invitation command. The container always enables invitation authentication, even when its published port is loopback. It refuses to start if no active invitation exists. Open `http://localhost:8765`, enter the access code and get the extension download/pairing code from the app.

`host.docker.internal` reaches the host on Docker Desktop. Linux host services must listen on an address reachable from the Docker bridge; a service bound only to host `127.0.0.1` cannot be reached from a container. Bind the inference server to the required private interface and restrict access with the host firewall, or use the optional Ollama container below.

### Optional NVIDIA Ollama container

Install NVIDIA drivers and the NVIDIA Container Toolkit on the Docker host. Set `OLLAMA_BASE_URL=http://ollama:11434` in `.env`, then:

```sh
docker compose --profile gpu up -d ollama
docker compose exec ollama ollama pull qwen2.5vl:3b
docker compose up -d clar
```

The GPU profile reserves one NVIDIA GPU, loads one model at a time, and exposes no inference port to the host. The Ollama image is version-pinned in `compose.yaml`; change `OLLAMA_IMAGE` deliberately when upgrading. Model weights live in the separate `ollama-models` volume. Choose model/quantization/context settings to fit your GPU; CLAR does not assume a 16 GB device.

For Apple Silicon, run Ollama natively and point the CLAR container at it. Docker on macOS does not provide this NVIDIA GPU path.

## Public HTTPS deployment

The application refuses an unauthenticated non-loopback bind. Configure:

```dotenv
PUBLIC_MODE=1
PUBLIC_HOST=clar.example.org
ALLOWED_HOSTS=localhost,127.0.0.1,clar.example.org
CLAR_BACKEND=https://clar.example.org
CLAR_INVITE_DAILY_LIMIT=30
CLAR_GLOBAL_DAILY_LIMIT=90
```

Self-host defaults are 30 checks per invitation and 90 overall per UTC day. Set either daily limit to `0` to disable that cap.

Create invitations before startup. Keep the application port private and put an HTTPS reverse proxy in front. `deploy/Caddyfile.example` is a starting configuration. Preserve the original public Host header. The application does not trust forwarded headers. `PUBLIC_MODE=1` enforces authentication on all sensitive endpoints regardless of the supplied Host header.

Web sessions use signed, Secure, HttpOnly, SameSite=Lax cookies. HTTPS is required for remote browser sessions. Extension tokens are separate per invitation and scoped to the configured `CLAR_EXTENSION_ID`; revocation also blocks existing jobs and sessions.

Download and package the extension for your own backend address using the build instructions in the project README. The app and manifest must agree on `CLAR_EXTENSION_ID`, and the extension manifest must allow your backend origin.

For Compose, `CLAR_BACKEND` is the public origin baked into the downloadable extension. `DEFAULT_PROVIDER` also determines its initial provider. After changing either setting in `.env`, rebuild and recreate the application:

```sh
docker compose build clar
docker compose up -d clar
```

Users must download the rebuilt extension and reload it in Chrome. Runtime environment changes alone cannot change an extension's permitted origins. For a native installation, rebuild with `python tools/build_extension.py --backend https://clar.example.org --default-provider local` before restarting the app.

On native installations, `manage_invites.py` reads the exported `CLAR_INVITES_FILE` variable rather than loading `.env` or reading `CLAR_RUNTIME_DIR`. If you customize the runtime directory, explicitly export `CLAR_INVITES_FILE=/path/to/your/runtime/invites.json` before creating, listing or revoking invitations, matching the application's invitation path. Compose passes the container's configured values automatically.

## Operation and limits

- `GET /healthz`: process liveness; no provider call. Docker checks this endpoint.
- `GET /readyz`: default provider configuration/readiness. Local providers must list the configured model; cloud readiness confirms a configured key and does not make a billable validation request. Returns 503 while unavailable.
- `GET /api/health`: existing UI capability discovery.
- `POST /api/jobs`: starts a bounded, owner-scoped job. Poll its returned ID; retrying identical input reuses work. Prefer this over the legacy synchronous `/api/analyze` endpoint.
- Maximum request body: 8,000,000 bytes, including base64 image expansion. Body read deadline: 15 seconds. HTTP work: at most 16 threads and 64 connections by default. Busy admission returns 503, never an unbounded queue.
- `MODEL_TIMEOUT_SECONDS` controls model network timeouts, not a total pipeline deadline. `CLAR_REQUEST_TIMEOUT` limits how long a transport request waits. Work already inside a model request can finish after a client disconnects; it retains its bounded slot until completion.
- Finished jobs expire after 30 minutes and are pruned when the job store is accessed; the store also bounds the number of retained results. This is not a timer that guarantees physical removal at exactly 30 minutes.
- Shutdown stops admission and cancels queued/active jobs between model stages. Docker grants 45 seconds before process termination. Use a supervisor with restart behavior for native deployments.
- Access logging is disabled so post URLs, invite links and credentials are not written to request logs. Unexpected internal errors return generic messages.

Environment overrides: `CLAR_MAX_BODY_BYTES` (up to 8,000,000), `CLAR_BODY_TIMEOUT`, `CLAR_REQUEST_TIMEOUT`, `CLAR_HTTP_THREADS`, `CLAR_CONNECTION_LIMIT`, `CLAR_SHUTDOWN_TIMEOUT`, `CLAR_RUNTIME_DIR`, `CLAR_INVITES_FILE`, `CLAR_USAGE_FILE`, `CLAR_FEEDBACK_FILE`, `CLAR_EXTENSION_ID`. `CLAR_LOAD_DOTENV=0` disables `.env` loading when a process manager injects environment values; the container sets it automatically. Do not use multiple Uvicorn workers or replicas.

Back up the runtime volume privately: it contains invitation secrets, quota records and submitted feedback. Stop writes for a consistent backup. Do not publish this volume or commit its files. `docker compose down` preserves data; adding `-v` deletes volumes and should only be used when deliberately discarding the installation.

## Validation

Run `python -m unittest discover -s tests -p 'test_*.py'`. Production transport coverage includes authentication, origin/host restrictions, job ownership, quotas, bounded chunked bodies, timeout/disconnect handling, health/readiness, shutdown and fail-closed public startup. Tests use fake model responses and do not require cloud credentials or GPUs.

References: [Uvicorn settings](https://uvicorn.dev/settings/), [Docker Compose GPU reservations](https://docs.docker.com/compose/how-tos/gpu-support/), [Ollama Docker installation](https://docs.ollama.com/docker).
