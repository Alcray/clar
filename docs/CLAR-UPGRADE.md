# CLAR 0.4.1 — feature upgrade

## Implemented

| Feature | Behavior |
| --- | --- |
| Claims and overall assessment | Each statement has a category, evidence strength, explanation and attributable sources. A mixed post retains its individual findings. |
| Visible origin | Canonical Facebook URLs are matched against an editable, verified registry. Names alone do not establish identity. Unknown and visibly anonymous posts are described without inferring an account's history. |
| Fact-checks | Dedicated publisher search plus four verified StopFals articles. A same-claim match requires the original author's stance and scope to agree. Related context is labeled separately. Publisher ratings are never invented. |
| Media literacy | Apparent purpose, encouraged response, exact quoted persuasion cues, reader questions and a practical tip. Includes conspiracy appeals, ad hominem, whataboutism and unsupported calls to action. |
| Feed badges | Auto-scan is off by default. When enabled, visible, nontruncated text posts of at least 15 words receive a preliminary reading. At most two scans run at once; quota exhaustion pauses scanning. |
| One-click full analysis | The existing Facebook button selects the post, opens the panel and starts its full check. The badge opens the same flow. |
| Highlights | Exact quoted phrases are underlined in the original post, with accessible explanations. Recycled post containers and stale responses are checked before annotation. |
| Shared results | Website and extension use the same packaged renderer, colors, cards, source links and real progress stages. |
| Cache and settings | Bounded 24-hour device cache; reopening a completed post uses it immediately. Language, origin, provider, reviewer and version separate entries. Clear cache, highlight toggle, Auto-scan and RO/RU/EN output settings are available. Image files are not cached. |
| Retry and cancellation | A 25-second waiting limit exposes Retry. Retry resumes the active/latest server job; forced re-analysis creates a fresh job. Explicit Stop requests cancellation; Escape closes the panel. |
| Evaluation inputs | Four StopFals examples and an official control can be loaded from the website. These are labeled constructed inputs, and checks run through the live provider. |

## Decisions that improve the proposed specification

- Truth, persuasion and commercial intent remain separate. Persuasive wording cannot establish coordinated propaganda; advertising alone cannot establish fraud.
- A statement about political motives may remain an opinion with relevant legal context. An expected demo label is not forced onto it.
- A topic match is not automatically a fact-check match. Refutations, quotations, differing periods and differing measurements need separate treatment.
- Evidence strength is not a calibrated probability of truth.
- Auto-scan requires an explicit setting because it sends visible post text and consumes the reviewer's allowance.

## Files to edit

- `analysis.py`, `local_analysis.py`, `media_literacy.py`: provider pipeline and validated assessments.
- `factchecks.py`, `origins.py`, `config/sources.json`, `fixtures/`: source matching, visible provenance and evaluation inputs.
- `jobs.py`, `server.py`: bounded jobs, progress, owner-scoped retry and quota.
- `shared/`: canonical result renderer, styles and job client.
- `extension/`: Facebook selectors/content integration, service worker, panel and local result cache.
- `tools/build_extension.py`: copies shared assets to both surfaces and builds the downloadable ZIP.

## Install or update

Open [CLAR](http://localhost:8765/) with your existing invitation. Select **Get CLAR for Chrome**, download and unzip the package. New users load the folder containing `manifest.json` through `chrome://extensions` → Developer mode → Load unpacked, then pair through the guide.

Existing users replace the files in their current extension folder, press **Reload** in `chrome://extensions`, and refresh Facebook. Chrome 141+ is required. Website/backend updates appear immediately; packaged extension code requires this reload. Settings and pairing remain local to the profile.

## Verification — 26 September 2026

119 Python tests pass. Isolated Chromium tests cover the installed extension's feed click, service worker, side panel, automatic scans, inline highlights, cached reopening, clear cache, forced re-analysis and timeout retry. Shared renderer tests cover safe text/links, publisher-rating attribution, progress, RO/RU labels and narrow layouts. The protected Funnel website and a real Vertex extension check were also exercised.

Live Vertex results on the constructed case set:

| Input | Observed result | Published context |
| --- | --- | --- |
| Democracy collapsed across all indicators | MISLEADING | Same-claim StopFals match |
| Romanian requirement is a filter to exclude candidates | OPINION | Related StopFals legal context; no factual verdict imposed on motive |
| Moldova gas prices exceed most EU countries | FALSE | Same-claim StopFals match |
| Otifonex restores hearing overnight | FALSE; sales purpose | Same-claim StopFals match |
| Official CNMC supply-continuity announcement | VERIFIED_FACT; official origin | Government citation |
| Romanian and Russian gas variants | FALSE | Same-claim StopFals matches and explanations in the selected language |
| Post rejecting the gas claim | VERIFIED_FACT | Does not inherit the rejected claim's FALSE rating |

The Gagauzia outcome intentionally differs from the teammate's suggested fixed label. The live checks exposed and led to fixes for ambiguous author-versus-publisher stance, missing later grounded passages, language drift, and stale cached results after forced retry. Model/retrieval output remains variable; these runs do not establish general accuracy.

## Limits

The live evaluation is a small constructed case set, not an accuracy benchmark. Facebook changes its DOM; quotation, satire, mixed language and dates can still be misunderstood. The origin registry starts small and needs editorial maintenance. Local inference has narrower retrieval coverage than Vertex. No video, photo authentication, account reputation scoring or inference of secret intent is included.

Checks expire from the server job API after 30 minutes; job data is held only in memory. The extension saves extracted text and results on the device for 24 hours, bounded to 50 entries and 3.5 MB, with a Clear cache control. The public preview still requires individual invitations and enforces its daily allowance.
