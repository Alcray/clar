// Installed extension with a disposable profile, synthetic Facebook posts and
// mocked job endpoints only. No account, CLAR server or model provider is used.
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
const id = JSON.parse(fs.readFileSync(path.join(extension, 'identity.json'), 'utf8')).id;
const backend = 'http://127.0.0.1:8765';
const token = 'fake-queue-token-for-isolated-test';
const posts = ['one', 'two', 'three', 'four'];
const texts = Object.fromEntries(posts.map((name, index) => [name,
  `Synthetic report ${index + 1} says the council has ${100 + index} members. This is a distinct claim for a queue test.`]));
const html = `<!doctype html><html><head><meta charset="utf-8"><style>
  body{font:16px/1.5 system-ui;background:#eef1f6;margin:0;padding:20px}
  main{max-width:650px;margin:auto}article{background:white;padding:20px;margin:12px 0}
  h3{margin:0}
  </style></head><body><main role="feed">${posts.map((name, index) => `
  <article id="post-${name}" role="article"><h3><a href="/author-${name}">Author ${name}</a></h3>
    <a href="/author-${name}/posts/${index + 111}">Today</a>
    <div data-ad-preview="message">${texts[name]}</div></article>`).join('')}
  </main></body></html>`;
const settings = {backend, token, provider:'vertex', language:'en', autoScan:false, showHighlights:true};
const resultFor = body => ({provider:'vertex', original_text:body.text,
  summary:'Synthetic queue check complete',
  overall:{label:'FALSE', confidence:'high', summary:'Synthetic queue check complete', is_preliminary:false},
  statements:[{text:body.text, kind:'factual', label:'FALSE', confidence:'high',
    explanation:'Deterministic test result',
    evidence:[{url:'https://example.org/synthetic-evidence', title:'example.org', stance:'contradicts'}]}],
  techniques:[], search_suggestions:[]});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function eventually(predicate, message, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await sleep(40);
  }
  assert.fail(message);
}

async function clickPill(page, name) {
  const host = page.locator(`#post-${name} [data-clar-control=""]`).first();
  await host.waitFor();
  await host.scrollIntoViewIfNeeded();
  const box = await host.boundingBox();
  assert.ok(box, `The content script rendered the ${name} control`);
  await page.mouse.click(box.x + 55, box.y + 16);
}

async function pending(page, name) {
  await page.locator(`#post-${name} [data-clar-control=""][data-clar-state="pending"]`).waitFor();
}

async function checked(page, name) {
  await page.locator(`#post-${name}[data-clar-risk="high"]`).waitFor();
}

async function harness() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'clar-worker-queue-'));
  fs.chmodSync(profile, 0o700);
  let context;
  const requests = [], cancellations = [], unexpected = [], pageErrors = [];
  const jobs = new Map();
  try {
    context = await chromium.launchPersistentContext(profile, {
      channel:'chromium', headless:true, viewport:{width:1200, height:1100},
      args:[`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
    });
    context.on('page', page => page.on('pageerror', error => pageErrors.push(error.message)));
    await context.route('**/*', async route => {
      const request = route.request(), url = request.url();
      if (!/^https?:/.test(url)) return route.continue();
      if (url.startsWith('https://www.facebook.com/'))
        return route.fulfill({contentType:'text/html', body:html});
      if (url === backend + '/api/health')
        return route.fulfill({contentType:'application/json', body:JSON.stringify({vertex_configured:true, local_ready:true})});
      if (url === backend + '/api/jobs') {
        assert.equal(request.method(), 'POST');
        assert.equal(request.headers().authorization, `Bearer ${token}`);
        const body = request.postDataJSON();
        assert.equal(body.task, 'analyze', 'Manual feed checks use full analysis');
        requests.push(body);
        const job = {id:`queue-job-${requests.length}`, body, done:false};
        jobs.set(job.id, job);
        return route.fulfill({contentType:'application/json', body:JSON.stringify(responseFor(job))});
      }
      const match = url.match(/^http:\/\/127\.0\.0\.1:8765\/api\/jobs\/(queue-job-\d+)(\/cancel)?$/);
      if (match) {
        const job = jobs.get(match[1]);
        assert.ok(job, 'Polling and cancellation refer to a mocked job');
        if (match[2]) {
          cancellations.push(job.id);
          return route.fulfill({contentType:'application/json', body:JSON.stringify({status:'cancelled'})});
        }
        return route.fulfill({contentType:'application/json', body:JSON.stringify(responseFor(job))});
      }
      unexpected.push(url);
      return route.abort('blockedbyclient');
    });
    let worker = context.serviceWorkers()[0];
    if (!worker) worker = await context.waitForEvent('serviceworker');
    assert.equal(new URL(worker.url()).hostname, id);
    await worker.evaluate(value => chrome.storage.local.set({settings:value}), settings);
    return {
      context, worker, requests, cancellations, unexpected, pageErrors, jobs,
      async feed() {
        const page = await context.newPage();
        await page.goto('https://www.facebook.com/queue-test');
        await page.locator('#post-four [data-clar-control=""]').waitFor();
        return page;
      },
      async panel() {
        const page = await context.newPage();
        await page.goto(`chrome-extension://${id}/panel.html`);
        await page.getByText('Connected · Gemini via Vertex AI', {exact:true}).waitFor();
        return page;
      },
      release(index) {
        const job = jobs.get(`queue-job-${index}`);
        assert.ok(job, `Mock job ${index} started`);
        job.done = true;
      },
      async close() {
        await context.close();
        fs.rmSync(profile, {recursive:true, force:true});
      },
    };
  } catch (error) {
    if (context) await context.close();
    fs.rmSync(profile, {recursive:true, force:true});
    throw error;
  }
}

function responseFor(job) {
  return job.done
    ? {job_id:job.id, status:'complete', result:resultFor(job.body), progress:{stages:[{id:'done', state:'done'}]}}
    : {job_id:job.id, status:'running', progress:{stages:[{id:'sources', state:'running'}]}};
}

async function fillTwoSlots(h, feed) {
  await clickPill(feed, 'one');
  await eventually(() => h.requests.length === 1, 'First check started');
  await clickPill(feed, 'two');
  await eventually(() => h.requests.length === 2, 'Second check started');
  assert.deepEqual(h.requests.map(request => request.text), [texts.one, texts.two]);
}

async function assertHarnessClean(h) {
  assert.deepEqual(h.pageErrors, [], 'No page errors');
  assert.deepEqual(h.unexpected, [], 'No request escaped the mocked routes');
}

const passed = [];

// A distinct third manual check stays pending. Repeating it in another tab
// joins the same queued work, and completion of the first job opens one slot.
{
  const h = await harness();
  try {
    const blockers = await h.feed(), firstSubscriber = await h.feed(), secondSubscriber = await h.feed();
    await fillTwoSlots(h, blockers);
    await clickPill(firstSubscriber, 'three');
    await pending(firstSubscriber, 'three');
    await clickPill(secondSubscriber, 'three');
    await pending(secondSubscriber, 'three');
    await sleep(300);
    assert.equal(h.requests.length, 2, 'A queued third check must not start or return queue_full');
    h.release(1);
    await checked(blockers, 'one');
    await eventually(() => h.requests.length === 3, 'First completion starts the queued check');
    assert.equal(h.requests[2].text, texts.three);
    assert.equal(h.requests.filter(request => request.text === texts.three).length, 1,
      'Queued duplicate callers share one backend job');
    h.release(3);
    await Promise.all([checked(firstSubscriber, 'three'), checked(secondSubscriber, 'three')]);
    assert.equal(h.requests.length, 3, 'Both subscribers receive the same completed result');
    h.release(2);
    await checked(blockers, 'two');
    await assertHarnessClean(h);
    passed.push('third check waits, advances after completion, and queued duplicates share one result');
  } finally { await h.close(); }
}

// Closing the only subscriber to queued work removes it before a slot opens.
{
  const h = await harness();
  try {
    const blockers = await h.feed(), closing = await h.feed();
    await fillTwoSlots(h, blockers);
    await clickPill(closing, 'three');
    await pending(closing, 'three');
    await sleep(250);
    assert.equal(h.requests.length, 2);
    await closing.close();
    h.release(1);
    await checked(blockers, 'one');
    await sleep(350);
    assert.equal(h.requests.length, 2, 'Closed tab cannot submit its stale queued post');
    h.release(2);
    await checked(blockers, 'two');
    await assertHarnessClean(h);
    passed.push('closing a tab removes its queued check');
  } finally { await h.close(); }
}

// Clearing results cancels queued intent and active jobs. A new post can then
// use the freed worker capacity without reviving the old queued submission.
{
  const h = await harness();
  try {
    const feed = await h.feed(), panel = await h.panel();
    await fillTwoSlots(h, feed);
    await clickPill(feed, 'three');
    await pending(feed, 'three');
    assert.equal(h.requests.length, 2);
    await panel.locator('#settings-toggle').click();
    await panel.locator('#clear-cache').click();
    await panel.locator('#cache-status').filter({hasText:'0 saved checks'}).waitFor();
    await sleep(300);
    assert.equal(h.requests.length, 2, 'Clear must discard the queued post');
    await clickPill(feed, 'four');
    await eventually(() => h.requests.length === 3, 'A fresh check starts after clear');
    assert.equal(h.requests[2].text, texts.four);
    h.release(3);
    await checked(feed, 'four');
    await assertHarnessClean(h);
    passed.push('clear discards queued work and leaves capacity for a fresh check');
  } finally { await h.close(); }
}

// Changing a cache identity setting invalidates queued requests captured under
// the previous setting. Only a new user action may submit with the new value.
{
  const h = await harness();
  try {
    const feed = await h.feed();
    await fillTwoSlots(h, feed);
    await clickPill(feed, 'three');
    await pending(feed, 'three');
    assert.equal(h.requests.length, 2);
    await h.worker.evaluate(async () => {
      const {settings} = await chrome.storage.local.get('settings');
      await chrome.storage.local.set({settings:{...settings, language:'ro'}});
    });
    await sleep(350);
    assert.equal(h.requests.length, 2, 'Settings change discards the old queued post');
    await clickPill(feed, 'four');
    await eventually(() => h.requests.length === 3, 'Fresh check starts with new settings');
    assert.equal(h.requests[2].text, texts.four);
    assert.equal(h.requests[2].language, 'ro');
    h.release(3);
    await checked(feed, 'four');
    await assertHarnessClean(h);
    passed.push('settings change discards stale queued work and uses the new language');
  } finally { await h.close(); }
}

console.log(JSON.stringify({extensionId:id, api:'mocked only', checks:passed}));
