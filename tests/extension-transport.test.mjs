// Installed extension, disposable Chromium profile, synthetic feed and mocked
// transport only. No Facebook account or live model service is contacted.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const extension = path.join(root, 'extension');
const backend = 'http://127.0.0.1:8765';
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'clar-transport-'));
fs.chmodSync(profile, 0o700);
const context = await chromium.launchPersistentContext(profile, {
  channel: 'chromium', headless: true, viewport: {width: 1200, height: 1000},
  args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
});
const requests = [], cancellations = [], errors = [], unexpected = [];
const jobs = new Map();
let photoDownloads = 0;
const stalledRoutes = [];
const text = 'The report says the parliament has one hundred and fifty members.';
const html = `<!doctype html><html><head><meta charset="utf-8"><style>
  body{margin:0;padding:25px;background:#eef1f6;font:16px/1.5 system-ui}main{max-width:600px;margin:auto}
  article{background:white;padding:20px;margin:12px 0}h3{margin:0}img{display:block;width:300px;height:150px;object-fit:contain}
  </style></head><body><main role="feed">
  <article id="text-post" role="article"><h3>Example author</h3><a href="/example/posts/111">Today</a><div data-ad-preview="message">${text}</div></article>
  <article id="other-post" role="article"><h3>Other author</h3><a href="/other/posts/222">Today</a><div data-ad-preview="message">This second report says there are two hundred members of parliament.</div></article>
  <article id="photo-post" role="article"><h3>Photo example</h3><a href="/photo?fbid=333"><img src="https://scontent.example.fbcdn.net/transport.png" alt="May be an image of text"></a></article>
  </main></body></html>`;
const resultFor = body => ({original_text: body.text || 'The image has a false factual claim.',
  overall: {label: 'FALSE', confidence: 'high', is_preliminary: false, summary: 'Synthetic evidence contradicts the claim.'},
  statements: [{kind: 'factual', label: 'FALSE', text: body.text || 'The image has a false factual claim.',
    evidence: [{url: 'https://parlament.md/example', stance: 'contradicts', title: 'parlament.md'}]}], techniques: []});
const json = (route, value) => route.fulfill({contentType: 'application/json', body: JSON.stringify(value)});
const completed = job => ({job_id: job.id, status: 'complete', result: resultFor(job.body), progress: {stages: [{id: 'done', state: 'done'}]}});
const running = job => ({job_id: job.id, status: 'running', progress: {stages: [{id: 'sources', state: 'running'}]}});
async function eventually(predicate, message, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.fail(message);
}
async function clickPill(page, selector) {
  const host = page.locator(selector + ' [data-clar-control=""]').first();
  await host.waitFor(); await host.scrollIntoViewIfNeeded();
  const box = await host.boundingBox();
  assert.ok(box, 'The installed content script rendered an inline control');
  await page.mouse.click(box.x + 55, box.y + 16);
}
async function accessibleButtons(page) {
  // Chrome's accessibility tree includes closed shadow controls without
  // changing the installed content script or its DOM isolation.
  const session = await context.newCDPSession(page);
  try {
    const {nodes} = await session.send('Accessibility.getFullAXTree');
    return nodes.filter(node => node.role?.value === 'button').map(node => node.name?.value || '');
  } finally { await session.detach(); }
}
try {
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  await context.route('**/*', async route => {
    const request = route.request(), url = request.url();
    if (!/^https?:/.test(url)) return route.continue();
    if (url.startsWith('https://www.facebook.com/')) return route.fulfill({contentType: 'text/html', body: html});
    if (url.startsWith('https://scontent.example.fbcdn.net/')) {
      if (request.serviceWorker()) {
        photoDownloads++;
        if (photoDownloads === 1) { stalledRoutes.push(route); return; }
      }
      return route.fulfill({contentType: 'image/png', body: fs.readFileSync(path.join(extension, 'icons/128.png'))});
    }
    if (url === backend + '/api/jobs') {
      const body = request.postDataJSON();
      assert.equal(request.headers().authorization, 'Bearer fake-transport-token');
      const job = {id: 'transport-job-' + (requests.length + 1), body, done: Boolean(body.image)};
      requests.push(body); jobs.set(job.id, job);
      return json(route, job.done ? completed(job) : running(job));
    }
    const match = url.match(/^http:\/\/127\.0\.0\.1:8765\/api\/jobs\/(transport-job-\d+)(\/cancel)?$/);
    if (match) {
      const job = jobs.get(match[1]); assert.ok(job, 'Polling targets an existing mocked job');
      if (match[2]) { cancellations.push(job.id); return json(route, {status: 'cancelled'}); }
      return json(route, job.done ? completed(job) : running(job));
    }
    unexpected.push(url); return route.abort('blockedbyclient');
  });
  let worker = context.serviceWorkers()[0];
  if (!worker) worker = await context.waitForEvent('serviceworker');
  await worker.evaluate(backend => chrome.storage.local.set({settings: {
    backend, token: 'fake-transport-token', provider: 'vertex', language: 'en', autoScan: false, showHighlights: true,
  }}), backend);
  const first = await context.newPage(), second = await context.newPage();
  await Promise.all([first.goto('https://www.facebook.com/first'), second.goto('https://www.facebook.com/second')]);
  await clickPill(first, '#text-post');
  await eventually(() => requests.length === 1, 'First check started');
  await clickPill(second, '#text-post');
  await eventually(async () => (await accessibleButtons(second)).includes('Analyzing…'), 'Second tab joined the pending check');
  // Allow the asynchronous cache-key lookup to attach this subscriber before
  // closing the first tab; at least one subsequent job poll proves activity.
  await second.waitForTimeout(750);
  assert.equal(requests.length, 1, 'Identical full checks share one start');
  await first.close();
  await second.waitForTimeout(750);
  assert.deepEqual(cancellations, [], 'Closing the first subscriber must not cancel the second');
  jobs.get('transport-job-1').done = true;
  await second.locator('#text-post[data-clar-risk="high"]').waitFor();
  assert.equal(requests.length, 1);

  // Keep one text job running while a photo download occupies the second slot.
  await clickPill(second, '#other-post');
  await eventually(() => requests.length === 2, 'Independent text job started');
  const photoStarted = Date.now();
  await clickPill(second, '#photo-post');
  await eventually(() => photoDownloads === 1, 'Worker began the deliberately stalled photo download');
  await eventually(async () => (await accessibleButtons(second)).some(name => name.includes("Couldn't analyze") && name.includes('Retry')),
    'Stalled photo must become a retryable failure', 13000);
  assert.ok(Date.now() - photoStarted < 13000, 'Photo timeout is bounded independently of the provider');
  assert.equal(requests.length, 2, 'A timed-out photo never starts a model job');
  assert.deepEqual(cancellations, [], 'Photo timeout does not cancel unrelated work');

  await clickPill(second, '#photo-post');
  await eventually(() => photoDownloads === 2, 'Retry can reacquire the released processing slot');
  await second.locator('#photo-post[data-clar-risk="high"]').waitFor();
  assert.equal(requests.length, 3, 'Successful photo retry starts exactly one model job');
  assert.ok(requests[2].image?.data);
  assert.equal(requests[2].text, '');
  jobs.get('transport-job-2').done = true;
  await second.locator('#other-post[data-clar-risk="high"]').waitFor();
  assert.deepEqual(cancellations, []);
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  console.log('PASS: cross-tab full-check dedupe survives first tab close; photo timeout is retryable, skips API and releases its slot');
} finally {
  for (const route of stalledRoutes) await route.abort().catch(() => {});
  await context.close();
  fs.rmSync(profile, {recursive: true, force: true});
}
