// Content-script regression only: a synthetic page in an isolated browser.
// This does not operate or verify the user's installed Chrome extension.
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
  const page = await browser.newPage();
  const fixture = fs.readFileSync(path.join(root, 'tests/fixtures/facebook-feed.html'), 'utf8');
  await page.route('https://www.facebook.com/**', route => route.fulfill({contentType: 'text/html', body: fixture}));
  await page.route('https://scontent.example.fbcdn.net/**', route => route.fulfill({contentType: 'image/png', body: fs.readFileSync(path.join(root, 'extension/icons/128.png'))}));
  await page.addInitScript(() => {
    window.sentPosts = [];
    window.chrome = {runtime: {
      id: 'test', onMessage: {addListener(fn) {window.onClarMessage = fn;}},
      async sendMessage(message) {if (message.post) window.sentPosts.push(message.post); return {ok: true};}
    }};
  });
  await page.goto('https://www.facebook.com/');
  await page.evaluate(() => {
    const wrapper = document.createElement('div');
    wrapper.setAttribute('data-pagelet', 'FeedUnit_virtualized');
    wrapper.innerHTML = `<div id="virtual-post" data-virtualized="false">
      <h4><a href="/test-page">Public page author</a></h4>
      <div data-ad-rendering-role="story_message"><div data-ad-preview="message">Only this virtualized post text.</div></div>
      <article role="article" data-commentid="example"><div data-ad-preview="message">Private comment excluded.</div></article>
      <div data-testid="shared-post" data-virtualized="false"><h4><a href="/nested">Shared author</a></h4><div data-ad-preview="message">Shared post excluded.</div></div>
      <button>Like</button>
    </div>`;
    document.querySelector('main').append(wrapper);
  });
  await page.addScriptTag({path: path.join(root, 'shared/presentation.js')});
  await page.addScriptTag({path: path.join(root, 'extension/selectors.js')});
  await page.addScriptTag({path: path.join(root, 'extension/content.js')});
  await page.locator('[data-clar-control]').nth(3).waitFor();
  assert.equal(await page.locator('[data-clar-control]').count(), 4);
  const click = async selector => {
    const control = page.locator(`${selector} [data-clar-control]`).first();
    await control.scrollIntoViewIfNeeded();
    const box = await control.boundingBox();
    await page.mouse.click(box.x + 65, box.y + box.height / 2);
  };
  await click('#virtual-post');
  assert.equal(await page.evaluate(() => sentPosts.at(-1).text), 'Only this virtualized post text.');
  await page.evaluate(() => {
    document.querySelector('#virtual-post [data-ad-preview]').textContent = 'Recycled virtualized post.';
  });
  await click('#virtual-post');
  assert.equal(await page.evaluate(() => sentPosts.at(-1).text), 'Recycled virtualized post.');
  await click('#post-one');
  const regularText = await page.evaluate(() => sentPosts.at(-1).text);
  assert.ok(regularText.includes('150 de deputați'));
  assert.ok(!regularText.includes('comment'));
  await click('#post-two');
  assert.equal(await page.evaluate(() => sentPosts.at(-1).truncated), true);
  await click('#photo-post');
  assert.equal(await page.evaluate(() => sentPosts.at(-1).text), '');
  assert.ok(await page.evaluate(() => sentPosts.at(-1).imageUrl.endsWith('/clar-test.png')));
  console.log('PASS: virtualized and traditional posts, recycled text, comment/shared-post exclusion, truncation, photo-only extraction');
} finally {
  await browser.close();
}
