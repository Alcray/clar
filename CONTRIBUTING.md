# Contributing to CLAR

Use issues and pull requests for reproducible extraction bugs, interface problems, provider integrations and reviewed benchmark cases. Include the CLAR version, provider/model, language, expected behavior and a minimal public or synthetic example. Remove credentials, invitation codes and private Facebook content.

Before a pull request:

Set up Python 3.10+ and Node 24, then install the reproducible test dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-server.txt
npm ci --ignore-scripts
npx playwright install chromium
```

On a fresh Linux machine, use `npx playwright install --with-deps chromium` to install Chromium's system dependencies too.

1. Build shared assets with `python tools/build_extension.py`.
2. Run `python -m unittest discover -s tests -q` and `python -m benchmarks validate`.
3. Run affected browser tests with `npm test` after installing Playwright Chromium.
4. For a model behavior change, record the benchmark configuration and explain changes in quality, failures and latency. Keep live retrieval runs separate from fixed-evidence comparisons.

To check the actual release image with a synthetic model and no network access from the test containers:

```sh
docker build --build-arg CLAR_BACKEND=https://clar.example.test --build-arg CLAR_EXTENSION_PROVIDER=local --tag clar:ci .
python3 tools/smoke_container.py --image clar:ci --backend https://clar.example.test
```

This checks authentication, quotas, complete analysis jobs, downloaded extension configuration, packaged licenses, shutdown and persistent state after restart. It creates and removes its own containers and volume; it does not contact a model provider or existing deployment.

Benchmark labels are editorial judgments. A new case needs provenance, rationale, exact expected spans, and relevant and distracting evidence. Review translations together with their shared semantic cluster. Do not change labels merely to make a model score better. Keep a genuinely unseen, independently reviewed evaluation set separate from development cases.

Do not add a model-written URL to evidence without retrieval. Preserve uncertainty, attribution, dates and the distinction between a quoted claim and the author's position. Source identity, factual accuracy and persuasion cues are separate assessments.

Contributions are provided under Apache-2.0. Use only content you may redistribute and identify external content and model licenses. Generated assets should have a reproducible source/build command.
