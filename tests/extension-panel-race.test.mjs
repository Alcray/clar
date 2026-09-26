// Reproduce worker completion between panel cache and selection reads.
// Disposable Chromium, synthetic post and mocked health; no model calls.
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
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'clar-panel-race-'));
const context = await chromium.launchPersistentContext(profile, {
  channel:'chromium', headless:true, viewport:{width:450,height:1050},
  args:[`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
});
const backend = 'http://127.0.0.1:8765';
const unexpected = [], errors = [];
try {
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  await context.route('**/*', route => {
    const url = route.request().url();
    if (!/^https?:/.test(url)) return route.continue();
    if (url === backend + '/api/health') return route.fulfill({contentType:'application/json',
      body:JSON.stringify({local_ready:true,vertex_configured:true,configured:true})});
    unexpected.push(url); return route.abort('blockedbyclient');
  });
  let worker = context.serviceWorkers()[0];
  if (!worker) worker = await context.waitForEvent('serviceworker');
  const id = new URL(worker.url()).hostname;
  const seeded = await worker.evaluate(async backend => {
    const settings = {backend,token:'synthetic-race-pairing-only',provider:'vertex',language:'en'};
    const selection = {selectionId:'completion-race',text:'A synthetic post for a completion race.',url:null,
      imageUrl:null,visibleDate:null,truncated:false,tabId:1,autoCheck:false,externalCheck:true,externalStatus:'complete'};
    await chrome.storage.local.clear();
    await chrome.storage.session.clear();
    await chrome.storage.local.set({settings});
    return {settings, selection};
  }, backend);
  const bootstrap = await context.newPage();
  await bootstrap.goto(`chrome-extension://${id}/panel.html`);
  await bootstrap.getByText('Connected · Gemini via Vertex AI', {exact:true}).waitFor();
  await bootstrap.evaluate(async ({settings, selection}) => {
    const {postPayload} = await import(chrome.runtime.getURL('config.js'));
    const {putCached} = await import(chrome.runtime.getURL('cache.js'));
    await putCached(postPayload(selection, settings), settings, {
      original_text:selection.text,summary:'Completed during initial cache read.',
      overall:{label:'UNVERIFIED_CLAIM',confidence:'low',summary:'Completed during initial cache read.',is_preliminary:false},
      statements:[],search_suggestions:[],
    });
  }, seeded);
  await bootstrap.close();
  await worker.evaluate(selection => chrome.storage.session.set({selection}), seeded.selection);
  const panel = await context.newPage();
  await panel.addInitScript(() => {
    const original = chrome.runtime.sendMessage.bind(chrome.runtime);
    let cacheReads = 0;
    chrome.runtime.sendMessage = (message, ...rest) => {
      if (message?.type === 'CLAR_CACHE_GET') {
        cacheReads++;
        window.__clarCacheReads = cacheReads;
        if (cacheReads === 1) return Promise.resolve({ok:true,hit:false});
      }
      return original(message, ...rest);
    };
  });
  await panel.goto(`chrome-extension://${id}/panel.html`);
  await panel.locator('#results:not([hidden]) .cr-assessment-summary')
    .filter({hasText:'Completed during initial cache read.'}).waitFor({state:'attached'});
  await panel.locator('#results:not([hidden]) .cr-overall').waitFor();
  assert.equal(await panel.evaluate(() => window.__clarCacheReads), 2,
    'A completed selection rechecks the cache after an initial miss');
  assert.equal(await panel.locator('#loading').isVisible(), false);
  assert.equal(await panel.locator('#analyze-button').isEnabled(), true);
  assert.deepEqual(unexpected, [], 'Restoration must not submit another analysis');

  // A completion marker can outlive cache clearing. Leave the user able to run
  // a fresh check, without silently submitting one merely by opening the panel.
  await panel.close();
  await worker.evaluate(() => chrome.storage.local.remove('clarResultCacheV4'));
  const cleared = await context.newPage();
  await cleared.goto(`chrome-extension://${id}/panel.html`);
  await cleared.getByText('Connected · Gemini via Vertex AI', {exact:true}).waitFor();
  await cleared.waitForTimeout(150);
  assert.equal(await cleared.locator('#results').isVisible(), false);
  assert.equal(await cleared.locator('#loading').isVisible(), false);
  assert.equal(await cleared.locator('#analyze-button').isEnabled(), true);
  assert.deepEqual(unexpected, []);
  assert.deepEqual(errors, []);
  console.log('PASS: completion race restores the second cache read; cleared completion permits manual retry without resubmission');
} finally {
  await context.close();
  fs.rmSync(profile, {recursive:true,force:true});
}
