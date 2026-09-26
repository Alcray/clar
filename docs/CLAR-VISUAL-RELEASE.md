# CLAR 0.5.1 — compact visual release

## User flow

1. On Facebook, click **Analyze** beneath a post. The pill shows a spinner while the existing analysis runs.
2. Click its result pill to open a compact, anchored card: risk level, finding, supported tags, retrieved source and short intent.
3. Choose **Full analysis** for the detailed side panel. A completed result opens from the existing 24-hour cache without another model request.
4. Escape, the close icon or an outside click dismisses the card. Scrolling keeps it attached to its post; leaving the viewport closes it.

Errors show **Couldn't analyze · Retry**. An unpaired extension directs the reader to setup. Auto-scan remains optional and displays a clear preliminary notice rather than claiming that facts were checked.

## Visuals and data

- Neutral slate/off-white surfaces, 4–6px corners, 1px borders, line SVG icons and 150ms transitions with reduced-motion support.
- Light/dark feed styling follows the Facebook post background; the detailed panel follows the system theme. Dark risk text uses lighter equivalents for readability.
- Four presentation levels: Low, Moderate, High and Inconclusive. High requires the existing high confidence and a supported adverse finding. It gets a slim banner and a 3px red inset accent that does not change post width.
- Up to three supported tags from the requested fixed vocabulary. Tags are not invented to fill empty slots. Labels, tags and short intent support English, Romanian and Russian.
- Compact intent uses localized templates of at most ten words, derived from existing purpose/cues. Full wording remains available in the detailed panel.
- Source chips preserve a retrieved URL. The displayed publisher domain comes from a verified fact-check URL, an existing retrieved hostname title, or the URL hostname. The source chip does not invent a URL or imply that official provenance proves truth.
- **Disagree?** saves a bounded local record in `chrome.storage.local.clarDisagreements`, without raw post text, credentials or any network submission. Confirmation says it was saved on this device. The website form still sends deliberate feedback for Mariam and Alex.

The model prompts, extraction, factual verdicts, confidence rules, source research and media analysis are unchanged. The risk display is a deterministic presentation layer. Existing Vertex results generally carry medium evidence confidence, so they remain Moderate even when a matched debunk is displayed; the UI does not inflate confidence.

## Changed files

| Files | Change |
| --- | --- |
| `shared/presentation.js` | Shared presentation mapping, tags, intent, source choice and localization |
| `shared/results.js`, `shared/results.css` | Compact summary and clean detailed results, light/dark themes |
| `extension/content.js` | Single pill, popover, post accents, local feedback UI and theme handling |
| `extension/background.js` | Feed checks through the existing job API, worker-owned selected checks, shared in-flight requests, bounded photo downloads and local feedback storage |
| `extension/cache.js` | Stable cache identity despite Chrome reordering origin object keys |
| `extension/panel.js` | Restore worker-owned progress/results and failed checks across panel recreation |
| `extension/panel.html`, `extension/panel.css` | Restyled panel shell and updated instructions |
| `extension/manifest.json`, `tools/build_extension.py` | Version 0.5.1 and packaged presentation module |
| `server.py` | Serve the new static presentation asset; analysis endpoints unchanged |
| `public/index.html`, generated shared assets and ZIP | Updated result UI and install instructions |
| `README.md`, extension/reviewer documentation, affected tests | New flow, limitations and verification |

## 0.5.1 reliability fixes

A third manual analysis now waits in a bounded FIFO queue when two checks are running. The pill shows **Queued…** and starts automatically as a slot opens; the waiting limit is eight. A repeated request for the same post joins its current check. Tab close, changed connection settings and Clear cache remove stale queued work. A prior **Couldn't analyze** state stays visible until Retry, so it does not show whether the two earlier checks remain active.

Persuasion highlights now use one CLAR tooltip. The native browser tooltip was caused by a `title` on each highlighted span; the accessible label remains, and the custom tooltip stays within the viewport and avoids the compact card.

## Install and test

Open [CLAR](http://localhost:8765/) with your existing invitation, choose **Get CLAR for Chrome**, and download the new ZIP. Replace the contents of the installed extension folder, click **Reload** in `chrome://extensions`, then refresh Facebook. Pairing and settings remain in the profile. No model key needs to be entered again.

Try one post, open its result card, then open Full analysis. Reopen it to check that the saved result appears without another request. Test Escape, outside click and scrolling. Switch output language in Settings. Try Facebook light/dark mode and a system dark detailed panel. Click Disagree and check the local confirmation. Website/backend updates appear on refresh; unpacked Chrome updates require Reload.

Developer checks (set `PLAYWRIGHT_MODULE` if Playwright is installed outside the default module path):

```sh
python3 tools/build_extension.py
node tests/presentation.test.mjs
node tests/extension-cache.test.mjs
node tests/content-compact.test.mjs
node tests/extension-feed.test.mjs
node tests/extension-transport.test.mjs
node tests/extension-autocheck.test.mjs
node tests/results-ui.test.mjs
node tests/media-literacy-ui.test.mjs
node tests/share-ui.test.mjs
python3 -m unittest discover -s tests -q
```

These browser tests use disposable profiles and synthetic posts. They exercise high/medium confidence, source/HTML safety, keyboard and outside dismissal, recycled posts, local feedback, cached detail reuse, overlapping tabs and photo timeouts. The benchmark live track can exercise the real pipeline using operator-configured providers; these runs may incur API charges.
