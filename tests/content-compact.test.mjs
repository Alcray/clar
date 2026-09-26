// Content UI contract: synthetic Facebook markup in isolated Chromium.
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
  const page = await browser.newPage({viewport: {width: 1050, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://www.facebook.com/**', route => route.fulfill({contentType: 'text/html', body: fs.readFileSync(path.join(root, 'tests/fixtures/facebook-analysis-feed.html'), 'utf8')}));
  await page.addInitScript(() => {
    window.messages = [];
    window.pendingChecks = [];
    window.shadowRoots = new WeakMap();
    const attach = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function(init) { const shadow = attach.call(this, init); shadowRoots.set(this, shadow); return shadow; };
    window.chrome = {runtime: {id: 'compact-test', onMessage: {addListener(fn) {window.receive = message => fn(message, {id: 'compact-test'}, () => {});}}, sendMessage(message) {
      messages.push(message);
      if (message.type === 'CLAR_GET_PUBLIC_SETTINGS') return Promise.resolve({ok: true, settings: {autoScan: false, language: 'en', showHighlights: true}});
      if (message.type === 'CLAR_ANALYZE_POST') return new Promise(resolve => pendingChecks.push({message, resolve}));
      return Promise.resolve({ok: true});
    }}};
    window.control = id => shadowRoots.get(document.querySelector(`#${id} [data-clar-control=""]`));
    window.popup = () => shadowRoots.get(document.querySelector('[data-clar-popover]'));
    window.result = (confidence = 'high') => ({
      original_text: 'Everyone knows the truth and we should read the original evidence',
      overall: {label: 'FALSE', confidence, is_preliminary: false, summary: 'The claim contradicts the cited evidence.', intent: 'Pressure readers to accept the claim without checking primary sources first'},
      statements: [{text: 'Everyone knows the truth', kind: 'fact', verdict: 'contradicted', label: 'FALSE', confidence, evidence: [{title: 'Primary evidence', url: 'https://gov.md/ro/example-evidence', stance: 'contradicts'}], fact_check: {url: 'https://stopfals.md/ro/article/example', title: 'Claim checked', outlet: 'StopFals', match_note: 'Same claim', verdict: 'FALSE', verdict_verified: true}}],
      media_literacy: {purpose: {category: 'persuade', quote: 'Everyone knows the truth'}, likely_goal: 'Pressure readers to accept the claim without checking primary sources first', signals: [{type: 'fear_appeal', name: 'Fear tactics', quote: 'Everyone knows the truth', explanation: 'Emotional pressure'}]},
      techniques: [{type: 'fear_appeal', name: 'Fear tactics', quote: 'Everyone knows the truth', explanation: 'Emotional pressure'}]
    });
  });
  await page.goto('https://www.facebook.com/');
  await page.evaluate(() => { document.querySelector('#first').style.boxShadow = '0px 2px 4px rgb(1, 2, 3)'; });
  for (const script of ['shared/presentation.js', 'extension/selectors.js', 'extension/content.js']) await page.addScriptTag({path: path.join(root, script)});
  await page.waitForFunction(() => document.querySelectorAll('[data-clar-control=""]').length === 6);
  const click = async id => {
    const host = page.locator(`#${id} [data-clar-control=""]`);
    await host.scrollIntoViewIfNeeded();
    const box = await host.boundingBox();
    await page.mouse.click(box.x + 55, box.y + box.height / 2);
  };
  const clickPopup = async selector => {
    const box = await page.evaluate(selector => {const r = popup().querySelector(selector).getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height};}, selector);
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  };
  assert.match(await page.evaluate(() => control('first').querySelector('.label').textContent), /ANALYZE/i);
  const before = await page.locator('#first').boundingBox();
  const originalShadow = await page.locator('#first').evaluate(node => node.style.boxShadow);
  await click('first');
  await page.waitForFunction(() => pendingChecks.length === 1);
  assert.equal(await page.evaluate(() => control('first').querySelector('.pill').dataset.state), 'pending');
  assert.equal(await page.evaluate(() => control('first').querySelector('.pill').disabled), true);
  await page.evaluate(() => { const {postKey, post} = pendingChecks[0].message; receive({type: 'CLAR_POST_PROGRESS', postKey, text: post.text, progress: {queued: true, position: 1}}); });
  assert.equal(await page.evaluate(() => control('first').querySelector('.label').textContent), 'Queued…');
  await page.evaluate(() => { const {postKey, post} = pendingChecks[0].message; receive({type: 'CLAR_POST_PROGRESS', postKey, text: post.text, progress: {phase: 'analyzing'}}); });
  assert.equal(await page.evaluate(() => control('first').querySelector('.label').textContent), 'Analyzing…');
  assert.equal(await page.evaluate(() => messages.filter(m => m.type === 'CLAR_SELECT_POST').length), 0, 'Initial check must not open the full side panel');
  await page.evaluate(() => pendingChecks[0].resolve({ok: true, result: result()}));
  await page.waitForFunction(() => control('first').querySelector('.pill').dataset.state === 'result');
  assert.match(await page.evaluate(() => control('first').querySelector('.label').textContent), /HIGH RISK/);
  assert.equal(await page.locator('#first[data-clar-risk="high"] [data-clar-banner]').count(), 1);
  const after = await page.locator('#first').boundingBox();
  assert.equal(before.width, after.width, 'Accent must not change post width');
  await click('first');
  await page.locator('[data-clar-popover]').waitFor();
  assert.equal(await page.evaluate(() => pendingChecks.length), 1, 'Opening a result must not start another check');
  assert.equal(await page.evaluate(() => popup().querySelector('.card').getAttribute('role')), 'dialog');
  assert.equal(await page.locator('#first [data-clar-highlight][title]').count(), 0, 'Persuasion underlines must not show native title tooltips');
  await page.evaluate(() => document.querySelector('#first [data-clar-highlight]').dispatchEvent(new PointerEvent('pointerover', {bubbles: true})));
  await page.locator('[data-clar-tooltip]').waitFor();
  const tooltipLayout = await page.evaluate(() => {
    const tip = document.querySelector('[data-clar-tooltip]').getBoundingClientRect();
    const card = document.querySelector('[data-clar-popover]').getBoundingClientRect();
    return {tip: {left: tip.left, right: tip.right, top: tip.top, bottom: tip.bottom}, card: {left: card.left, right: card.right, top: card.top, bottom: card.bottom}, width: innerWidth, height: innerHeight};
  });
  assert.ok(tooltipLayout.tip.left >= 8 && tooltipLayout.tip.right <= tooltipLayout.width - 8 && tooltipLayout.tip.top >= 8 && tooltipLayout.tip.bottom <= tooltipLayout.height - 8, 'Custom tooltip stays inside the viewport');
  assert.ok(tooltipLayout.tip.right <= tooltipLayout.card.left || tooltipLayout.tip.left >= tooltipLayout.card.right || tooltipLayout.tip.bottom <= tooltipLayout.card.top || tooltipLayout.tip.top >= tooltipLayout.card.bottom, 'Custom tooltip must not cover the open result card');
  await page.evaluate(() => document.querySelector('#first [data-clar-highlight]').dispatchEvent(new PointerEvent('pointerout', {bubbles: true})));
  assert.equal(await page.locator('[data-clar-tooltip]').count(), 0);
  const tags = await page.evaluate(() => [...popup().querySelectorAll('.tag')].map(x => x.textContent));
  assert.ok(tags.length <= 3);
  assert.ok(await page.evaluate(() => (popup().querySelector('.intent')?.textContent || '').split(/\s+/).length <= 10));
  const source = await page.evaluate(() => popup().querySelector('.source')?.href);
  assert.ok(['https://gov.md/ro/example-evidence', 'https://stopfals.md/ro/article/example'].includes(source), 'Source must come from analysis evidence');
  const initialTop = await page.locator('[data-clar-popover]').evaluate(node => parseFloat(node.style.top));
  await page.evaluate(() => scrollBy(0, 25));
  await page.waitForTimeout(50);
  if (await page.locator('[data-clar-popover]').count()) {
    const movedTop = await page.locator('[data-clar-popover]').evaluate(node => parseFloat(node.style.top));
    assert.notEqual(initialTop, movedTop, 'Card must follow the post when the page scrolls');
  }
  await clickPopup('.feedback');
  await page.waitForFunction(() => messages.some(m => m.type === 'CLAR_DISAGREE'));
  assert.equal(await page.evaluate(() => popup().querySelector('.feedback').disabled), true);
  const feedback = await page.evaluate(() => messages.find(m => m.type === 'CLAR_DISAGREE'));
  assert.equal(feedback.level, 'high');
  assert.ok(!Object.hasOwn(feedback, 'text'), 'Local disagreement need not duplicate post text');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('[data-clar-popover]').count(), 0);
  await click('first');
  await clickPopup('.full');
  await page.waitForFunction(() => messages.some(m => m.type === 'CLAR_SELECT_POST'));
  assert.equal(await page.locator('[data-clar-popover]').count(), 0);
  assert.equal(await page.evaluate(() => messages.find(m => m.type === 'CLAR_SELECT_POST').post.text), await page.evaluate(() => pendingChecks[0].message.post.text), 'Underlines must preserve extraction');
  await click('first');
  await page.mouse.click(3, 3);
  assert.equal(await page.locator('[data-clar-popover]').count(), 0);

  // Dark theme follows the page, regardless of the operating system setting.
  await page.evaluate(() => { const style = document.createElement('style'); style.textContent = 'body.dark,body.dark article{background:#181b21;color:#e7eaf0}'; document.head.append(style); document.body.classList.add('dark'); });
  await page.waitForFunction(() => document.querySelector('#first [data-clar-control=""]').dataset.theme === 'dark');
  await click('first');
  assert.equal(await page.locator('[data-clar-popover]').getAttribute('data-theme'), 'dark');
  assert.equal(await page.evaluate(() => getComputedStyle(popup().querySelector('.eyebrow')).color), 'rgb(239, 152, 142)', 'Dark risk text must use a readable lighter accent');
  const screenshotDir = path.join(root, '.runtime/qa-compact'); fs.mkdirSync(screenshotDir, {recursive: true});
  await page.waitForTimeout(180);
  await page.screenshot({path: path.join(screenshotDir, 'feed-dark.png')});
  await page.locator('[data-clar-popover]').screenshot({path:path.join(screenshotDir,'card-dark.png')});
  await page.evaluate(() => document.body.classList.remove('dark'));
  await page.waitForFunction(() => document.querySelector('[data-clar-popover]').dataset.theme === 'light');
  await page.waitForTimeout(180);
  await page.screenshot({path: path.join(screenshotDir, 'feed-light.png')});
  await page.locator('[data-clar-popover]').screenshot({path:path.join(screenshotDir,'card-light.png')});

  // Clear removes all CLAR decoration and restores the site's exact inline style.
  await page.evaluate(() => receive({type: 'CLAR_CLEAR_RESULTS'}));
  assert.equal(await page.locator('[data-clar-popover], [data-clar-banner], [data-clar-highlight], [data-clar-risk]').count(), 0);
  assert.equal(await page.locator('#first').evaluate(node => node.style.boxShadow), originalShadow);
  await click('first');
  await page.waitForFunction(() => pendingChecks.length === 2);
  await page.evaluate(() => pendingChecks[1].resolve({ok: true, result: result('medium')}));
  await page.waitForFunction(() => control('first').querySelector('.pill').dataset.state === 'result');
  assert.match(await page.evaluate(() => control('first').querySelector('.label').textContent), /MODERATE RISK/);
  assert.equal(await page.locator('[data-clar-banner]').count(), 0, 'Medium-confidence result must not mark a post high risk');

  // Failures offer Retry, and a late result after clear cannot repaint the feed.
  await click('second');
  await page.waitForFunction(() => pendingChecks.length === 3);
  await page.evaluate(() => pendingChecks[2].resolve({ok: false, error: 'Temporary error'}));
  await page.waitForFunction(() => control('second').querySelector('.pill').dataset.state === 'error');
  assert.match(await page.evaluate(() => control('second').querySelector('.label').textContent), /Retry/);
  await click('second');
  await page.waitForFunction(() => pendingChecks.length === 4);
  await page.evaluate(() => { receive({type: 'CLAR_CLEAR_RESULTS'}); pendingChecks[3].resolve({ok: true, result: result()}); });
  await page.waitForTimeout(80);
  assert.equal(await page.evaluate(() => control('second').querySelector('.pill').dataset.state), 'idle');
  assert.equal(await page.locator('[data-clar-banner]').count(), 0);

  // Pairing recovery opens Settings from the second explicit user click.
  await click('second');
  await page.waitForFunction(() => pendingChecks.length === 5);
  await page.evaluate(() => pendingChecks[4].resolve({ok: false, code: 'pairing_required', error: 'Open CLAR Settings to pair this extension'}));
  await page.waitForFunction(() => control('second').querySelector('.pill').dataset.state === 'error');
  const openedBefore = await page.evaluate(() => messages.filter(m => m.type === 'CLAR_SELECT_POST').length);
  await click('second');
  assert.equal(await page.evaluate(() => messages.filter(m => m.type === 'CLAR_SELECT_POST').length), openedBefore + 1);

  // Facebook recycles containers. The new post must not inherit the old warning.
  await page.evaluate(() => {
    const message = pendingChecks[0].message;
    receive({type: 'CLAR_RESULT', postKey: message.postKey, text: message.post.text, result: result()});
  });
  assert.equal(await page.locator('#first [data-clar-banner]').count(), 1);
  await page.evaluate(() => document.querySelector('#first [data-clar-highlight]').dispatchEvent(new PointerEvent('pointerover', {bubbles: true})));
  await page.locator('[data-clar-tooltip]').waitFor();
  await page.evaluate(() => { document.querySelector('#first [data-ad-preview]').textContent = 'A newly recycled post must never inherit the previous warning, evidence, or persuasion underlines from this same container.'; });
  await page.waitForFunction(() => control('first').querySelector('.pill').dataset.state === 'idle');
  assert.equal(await page.locator('[data-clar-tooltip]').count(), 0, 'Recycling a post dismisses its old cue');
  assert.equal(await page.locator('#first [data-clar-banner], #first [data-clar-highlight]').count(), 0);
  assert.equal(await page.locator('#first').evaluate(node => node.style.boxShadow), originalShadow);
  await page.evaluate(() => receive({type: 'CLAR_SETTINGS_CHANGED', settings: {autoScan: false, language: 'ro', showHighlights: true}}));
  assert.equal(await page.evaluate(() => control('first').querySelector('.label').textContent), 'ANALIZEAZĂ');
  await page.evaluate(() => receive({type: 'CLAR_SETTINGS_CHANGED', settings: {autoScan: false, language: 'ru', showHighlights: true}}));
  assert.equal(await page.evaluate(() => control('first').querySelector('.label').textContent), 'АНАЛИЗИРОВАТЬ');
  assert.deepEqual(errors, []);
  console.log('PASS: single pill, full check without panel, confidence gate, compact card, supported source, local feedback, anchor, Esc/outside dismissal, themes, cache open, clear, retry, stale guards and pairing recovery');
} finally { await browser.close(); }
