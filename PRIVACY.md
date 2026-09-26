# Data handled by CLAR

Clicking Analyze sends the selected post's text, visible source metadata and optional selected image to the configured CLAR server. Automatic scanning is off by default; enabling it sends visible text posts for preliminary readings. Content scripts receive results and public settings, not model API keys or pairing tokens.

Google modes send inputs to the configured Google provider and use Google Search for evidence. Local mode sends inputs to the operator-configured Ollama or OpenAI-compatible endpoint. It also retrieves a limited list of public documents. An endpoint may run on your computer or on another machine; verify your installation's configuration.

The app holds jobs/results in server memory with a 30-minute reuse lifetime. It does not write analyzed posts, images or provider responses to disk logs. Provider retention is governed by that provider. Server restarts lose pending jobs.

The extension caches extracted text and results on the device for 24 hours, bounded to 50 entries and 3.5 MB. Image files and provider credentials are not part of this result cache. Settings → Clear saved checks removes cached checks and feed annotations. The current selection is held in browser session storage. Pairing credentials are in extension storage restricted to trusted extension contexts.

Disagree saves a local record containing a post hash, displayed level/label, time and extension version, bounded to 200 entries. It does not submit feedback to the server. The website feedback form sends only fields the reader explicitly enters; it does not automatically attach the analyzed post. The operator stores submitted feedback privately in the runtime directory.

Benchmark runs intentionally store evaluation records and optional normalized model answers. Use public or synthetic test cases, choose access-controlled output directories, and review artifacts before sharing. Credentials are supplied through environment variables and excluded from benchmark records.
