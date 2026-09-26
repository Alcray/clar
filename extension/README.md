# CLAR for Chrome

CLAR adds an **Analyze** pill under recognizable Facebook posts. Click it to check a post, open its compact result card, and choose **Full analysis** for claims, citations, and persuasion cues. The extension connects to a CLAR server that you operate or trust.

## Build for your server

From the repository root, Python 3 builds the extension with no additional packages:

```sh
# Local server: 127.0.0.1:8765 and localhost:8765; Local model selected initially.
python3 tools/build_extension.py

# One remote server, with Vertex AI selected initially.
python3 tools/build_extension.py \
  --backend https://clar.example.org \
  --default-provider vertex

# A separate package for a local server using another port.
python3 tools/build_extension.py \
  --backend http://127.0.0.1:9000 \
  --output-dir dist/extension \
  --archive dist/clar-extension.zip
```

The default outputs are the unpacked `extension/` folder and `public/clar-extension.zip`, served by the CLAR website's download guide. The builder also copies the canonical shared renderer/client assets into `public/`. Repeat `--backend` to permit multiple servers; the first becomes the default. `--default-provider` accepts `local`, `vertex`, or `gemini`. Add `--dry-run` to validate configuration without writing files.

Use an HTTPS origin for a remote server. HTTP is accepted only for `localhost` or `127.0.0.1`, including custom ports. Paths, credentials, wildcard hosts, queries, and fragments are rejected. Configure a reverse proxy at the origin root if needed. Use a hostname or IPv4 address; IPv6 literals are not supported by this builder.

The generated server list, host permissions, and Content Security Policy allow the same configured origins. Settings cannot add a new server at runtime. Rebuild to change the permitted servers and reload Chrome. Provider API keys and pairing tokens must never be embedded in a build.

## Install and pair

1. Start your CLAR server and open its website. For the default local setup, open `http://127.0.0.1:8765/`.
2. Download the extension from **Get CLAR for Chrome** and extract it into a permanent folder, or use the unpacked build directory above.
3. Open `chrome://extensions` in desktop Chrome 141 or later. Enable **Developer mode**, click **Load unpacked**, and select the folder containing `manifest.json`.
4. Open the website's extension guide and copy its pairing code. If the server requires an invitation, sign in first.
5. Open CLAR from Chrome's extensions menu. In **Settings**, choose the matching server, paste the pairing code, and save. Select **Local model**, **Gemini · Vertex AI**, or **Gemini API**, as configured on that server.
6. Refresh Facebook and click **Analyze** on a post.

The pairing code is a CLAR access credential. Model API keys stay on the server. A server reachable at `localhost` must run on the browser's computer, or be forwarded there through a tunnel.

If a pill is missing, expand **See more**, select the post's text, and choose **Check selected post text with CLAR** from the right-click menu. The panel also accepts pasted text. Facebook changes its rendered DOM, so always review the extracted text. This is not a Facebook-supported integration.

## Behavior and privacy

- Auto-scan is **off by default**. Enabling it sends visible post text and displayed source information to the configured server for preliminary readings. Two scans can run at once. Usage limits, if configured by your operator, also apply to these scans.
- Clicking **Analyze** submits the selected post immediately. Two full checks run at once; additional checks enter a bounded queue. A completed check opens a compact card. **Full analysis** reuses the saved result.
- Comments, embedded shared posts, author labels, and reaction controls are excluded where the DOM exposes recognizable boundaries. Truncated posts are marked; CLAR does not expand Facebook posts automatically.
- Photos are downloaded only from HTTPS `*.fbcdn.net` when an image check is submitted. CLAR reads their text; it does not authenticate photos or process video. Post text and attached photos are checked separately.
- Pairing tokens stay in extension local storage, restricted to trusted extension contexts. The Facebook content script never receives the token. Website access cookies are not sent with extension requests.
- Selected posts stay in extension session storage until cleared or the browser restarts. Results, including extracted post text, are cached locally for 24 hours, bounded to 50 entries and 3.5 MB. Image files and provider credentials are not cached. Settings → **Clear saved checks** removes results and feed highlights. Cache entries distinguish server, reviewer, language, provider, input, origin, and analysis version.
- Google providers send selected content to Google. **Local model** uses the model endpoint configured by your server operator; that endpoint may itself be on another machine. Local checks may fetch public evidence pages through the server. Consult your operator about their network and retention configuration.
- After 25 seconds, **Retry** resumes the same server job. **Stop** or Escape requests cancellation; an already running provider call may finish. Finished server jobs expire after 30 minutes and are pruned when the job store is accessed; a server restart discards all jobs and results.
- **Disagree?** stores the post hash, displayed risk/label, time, and UI version locally under `clarDisagreements`, with at most 200 records. It does not include raw post text or send feedback to the server. The website feedback form sends only what you deliberately submit.

High risk requires high evidence confidence and a supported adverse finding. An official origin alone does not imply low risk, and a related fact-check is not automatically a debunk. Preliminary scans remain unverified. Persuasion cues interpret the wording and do not prove the author's private intent. The extension supports English, Romanian, and Russian, plus light and dark themes.

## Permissions and identity

CLAR requests `sidePanel`, `storage`, and `contextMenus`. Its content script runs only on `https://www.facebook.com/*`. Network permissions cover the configured CLAR server origins and Facebook's image CDN. It does not request `all_urls`, `cookies`, `history`, `tabs`, or screenshot capture.

The manifest's public key makes the default unpacked extension ID stable: `ajlgkaeeokegabffalnaoncikpgniaci`. That public key is not a secret and does not authenticate requests; the server also requires a pairing token. The build report and generated `identity.json` show the ID.

A fork can supply a different **public** SubjectPublicKeyInfo key:

```sh
python3 tools/build_extension.py \
  --backend https://clar.example.org \
  --extension-key /path/to/extension-public-key.pem
```

The builder accepts PEM or DER and refuses private key files. Set the server's `CLAR_EXTENSION_ID` to the printed ID. Keep the same public key across updates so Chrome retains the extension identity and settings. Changing the key installs a separate extension.

## Updates and verification

For an extension update, replace the files in its installed folder, click **Reload** on CLAR in `chrome://extensions`, then refresh Facebook. Existing settings are retained when the saved server is still permitted by the new build. A build that removes that server falls back to its default and requires pairing again. Website/server changes do not require an extension reload unless the packaged UI or protocol changes.

The repository includes build validation tests and isolated browser tests. They use temporary Chrome profiles and mock servers; they do not access your Facebook account or incur model usage:

```sh
python3 -m unittest discover -s tests -p test_extension_build.py
node tests/selfhost-extension.test.mjs
```

For the browser test, install Playwright and Chromium as described in the main repository testing guide, or set `PLAYWRIGHT_MODULE` to an existing Playwright package path.
