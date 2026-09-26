// Public synthetic text, mocked runtime, isolated Chromium. No user browser data.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1000, height: 1200}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const fixture = fs.readFileSync(path.join(root, 'tests/fixtures/facebook-analysis-feed.html'), 'utf8');
  await page.route('https://www.facebook.com/**', route => route.fulfill({contentType: 'text/html', body: fixture}));
  await page.addInitScript(() => {
    window.messages = [];
    window.pending = [];
    window.shadowRoots = new WeakMap();
    const attach = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function(init) { const shadow = attach.call(this, init); shadowRoots.set(this, shadow); return shadow; };
    window.chrome = {runtime: {
      id: 'content-test', onMessage: {addListener(fn) {window.receive = message => fn(message, {id: 'content-test'}, () => {});}},
      sendMessage(message) {
        messages.push(message);
        if (message.type === 'CLAR_GET_PUBLIC_SETTINGS') return Promise.resolve({ok: true, settings: {autoScan: false, language: 'en', showHighlights: true}});
        if (message.type === 'CLAR_SCAN_POST') return new Promise(resolve => pending.push({message, resolve}));
        return Promise.resolve({ok: true});
      }
    }};
    window.badgeText = id => shadowRoots.get(document.querySelector(`#${id} [data-clar-control]`)).querySelector('.label').textContent;
    window.settings = overrides => receive({type: 'CLAR_SETTINGS_CHANGED', settings: {autoScan: true, language: 'en', showHighlights: true, ...overrides}});
  });
  await page.goto('https://www.facebook.com/');
  await page.addScriptTag({path: path.join(root, 'shared/presentation.js')});
  await page.addScriptTag({path: path.join(root, 'extension/selectors.js')});
  await page.addScriptTag({path: path.join(root, 'extension/content.js')});
  await page.waitForFunction(() => document.querySelectorAll('[data-clar-control]').length === 6);
  await page.waitForTimeout(350);
  assert.equal(await page.evaluate(() => messages.filter(x => x.type === 'CLAR_SCAN_POST').length), 0, 'Auto scan must default off');
  await page.evaluate(() => settings({}));
  await page.waitForFunction(() => pending.length === 2);
  await page.waitForTimeout(300);
  assert.equal(await page.evaluate(() => pending.length), 2, 'At most two content requests may be pending');
  const first = await page.evaluate(() => pending[0].message);
  assert.equal(first.post.origin.poster_name, 'Example reader');
  assert.equal(first.post.origin.poster_url, 'https://www.facebook.com/reader');
  assert.equal(first.post.origin.context, 'group');
  assert.equal(first.post.origin.anonymous, false);
  assert.equal(first.post.url, 'https://www.facebook.com/reader/posts/101');
  assert.ok(!first.post.text.includes('Private comment'));
  assert.ok(!first.post.text.includes('Like'));
  await page.evaluate(() => pending[0].resolve({ok: true, result: {
    overall: {label: 'FALSE', confidence: 'high', summary: 'Not an evidence check', is_preliminary: true},
    techniques: [
      {name: '<img src=x onerror=alert(1)>', quote: 'Everyone knows the truth', explanation: '<script>alert(1)</script> A rhetorical cue.'},
      {name: 'Do not change links', quote: 'Linked quotation is interactive', explanation: 'This link stays untouched.'},
      {name: 'Absent', quote: 'words absent from this post', explanation: 'Must not appear.'},
    ]
  }}));
  await page.waitForFunction(() => pending.length === 3);
  await page.waitForFunction(() => document.querySelectorAll('#first [data-clar-highlight]').length === 2);
  assert.match(await page.evaluate(() => badgeText('first')), /MODERATE RISK|INCONCLUSIVE/);
  assert.equal(await page.locator('#first a [data-clar-highlight]').count(), 0);
  assert.equal(await page.locator('[data-commentid] [data-clar-highlight]').count(), 0);
  assert.equal(await page.locator('#first img, #first script').count(), 0, 'Model output must not create HTML');
  assert.equal(await page.locator('#first [data-clar-highlight][title]').count(), 0, 'Highlights must not trigger a second native browser tooltip');
  assert.match(await page.locator('#first [data-clar-highlight]').first().getAttribute('aria-label'), /A rhetorical cue/, 'Screen readers retain the full cue');
  await page.locator('#first [data-clar-highlight]').first().hover();
  await page.locator('[data-clar-tooltip]').waitFor();
  await page.locator('#first [data-clar-highlight]').last().hover();
  assert.equal(await page.locator('[data-clar-tooltip]').count(), 1, 'Hovering another highlight replaces the previous custom tooltip');
  await page.mouse.move(1, 1);
  assert.equal(await page.locator('[data-clar-tooltip]').count(), 0, 'Pointer exit dismisses the custom tooltip');
  await page.locator('#first [data-clar-highlight]').first().focus();
  await page.locator('[data-clar-tooltip]').waitFor();
  await page.locator('#first [data-clar-highlight]').first().blur();
  assert.equal(await page.locator('[data-clar-tooltip]').count(), 0, 'Focus exit dismisses the custom tooltip');
  await page.locator('#first [data-clar-highlight]').first().hover();
  await page.locator('[data-clar-tooltip]').waitFor();
  assert.equal(await page.evaluate(() => shadowRoots.get(document.querySelector('[data-clar-tooltip]')).querySelector('img,script')), null);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('[data-clar-tooltip]').count(), 0);
  const click = async id => { const box = await page.locator(`#${id} [data-clar-control]`).boundingBox(); await page.mouse.click(box.x + 55, box.y + 18); };
  await click('first');
  await page.locator('[data-clar-popover]').waitFor();
  { const box = await page.evaluate(() => { const rect = shadowRoots.get(document.querySelector('[data-clar-popover]')).querySelector('.full').getBoundingClientRect(); return {x: rect.x, y: rect.y, width: rect.width, height: rect.height}; }); await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2); }
  assert.equal(await page.evaluate(() => messages.findLast(x => x.type === 'CLAR_SELECT_POST').post.text), first.post.text, 'Highlight splitting must preserve original extraction');
  await page.evaluate(message => receive({type: 'CLAR_RESULT', postKey: message.postKey, text: message.post.text, result: {overall: {label: 'VERIFIED_FACT', confidence: 'high', summary: 'Sources agree', is_preliminary: false}, techniques: [{name: 'Subword', quote: 'Everyone', explanation: 'Exact text range.'}]}}), first);
  assert.match(await page.evaluate(() => badgeText('first')), /MODERATE RISK/, 'A label without supporting citations is not enough for LOW RISK');
  await page.waitForTimeout(350);
  await click('first');
  await page.locator('[data-clar-popover]').waitFor();
  { const box = await page.evaluate(() => { const rect = shadowRoots.get(document.querySelector('[data-clar-popover]')).querySelector('.full').getBoundingClientRect(); return {x: rect.x, y: rect.y, width: rect.width, height: rect.height}; }); await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2); }
  assert.equal(await page.evaluate(() => messages.findLast(x => x.type === 'CLAR_SELECT_POST').post.text), first.post.text, 'Repeated highlight replacement must preserve text');
  await page.evaluate(() => settings({showHighlights: false}));
  assert.equal(await page.locator('[data-clar-highlight]').count(), 0);
  await page.evaluate(() => settings({showHighlights: true}));
  assert.equal(await page.locator('#first [data-clar-highlight]').count(), 1);

  // Recycled root: ignore its pending result even before the mutation scan runs.
  await page.evaluate(() => {
    document.querySelector('#second [data-ad-preview]').textContent = 'A recycled post has completely different words and should never inherit the label or underlines of the previous item in this container.';
    pending[1].resolve({ok: true, result: {overall: {label: 'FALSE', confidence: 'high', summary: 'Stale result', is_preliminary: false}, techniques: [{quote: 'recycled post', name: 'Incorrect', explanation: 'Never apply this'}]}});
  });
  await page.waitForTimeout(350);
  assert.equal(await page.locator('#second [data-clar-highlight]').count(), 0);
  assert.doesNotMatch(await page.evaluate(() => badgeText('second')), /Contradicted/);
  assert.ok(await page.evaluate(() => messages.filter(x => x.type === 'CLAR_SCAN_POST').every(x => !x.post.text.includes('outside the viewport') && !x.post.text.includes('Too short') && !x.post.text.includes('incomplete visible'))));

  // Opting out cancels queued scans and discards later responses.
  await page.evaluate(() => {
    settings({autoScan: false});
    for (const {resolve} of pending) resolve({ok: true, result: {overall: {label: 'FALSE', is_preliminary: false, summary: 'Canceled'}}});
  });
  await page.waitForTimeout(100);
  assert.ok(await page.evaluate(() => messages.some(x => x.type === 'CLAR_CANCEL_SCANS')));
  const beforeScroll = await page.evaluate(() => messages.filter(x => x.type === 'CLAR_SCAN_POST').length);
  await page.locator('#offscreen').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  assert.equal(await page.evaluate(() => messages.filter(x => x.type === 'CLAR_SCAN_POST').length), beforeScroll);
  await page.evaluate(() => settings({}));
  await page.waitForFunction(() => messages.some(x => x.type === 'CLAR_SCAN_POST' && x.post.text.includes('outside the viewport')));
  await page.evaluate(() => receive({type: 'CLAR_CLEAR_RESULTS'}));
  assert.equal(await page.locator('[data-clar-highlight]').count(), 0);
  assert.equal(await page.evaluate(() => [...document.querySelectorAll('[data-clar-control]')].every(host => shadowRoots.get(host).querySelector('button').dataset.state === 'idle')), true);
  assert.deepEqual(errors, []);
  console.log('PASS: opt-in visible scans, two-request limit, origin metadata, preliminary truth guard, exact highlights, stale results, cancellation, links/comments isolation, tooltip escaping and clear');
} finally { await browser.close(); }
