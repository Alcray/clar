// Cache contract tests with Chrome's asynchronous, cloned storage semantics.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'extension/cache.js'), 'utf8');
const backing = {};
globalThis.chrome = {storage: {local: {
  async get(key) { return {[key]: structuredClone(backing[key])}; },
  async set(values) { Object.assign(backing, structuredClone(values)); },
  async remove(key) { delete backing[key]; },
}}};
const cacheModule = version => import('data:text/javascript;base64,' + Buffer.from(source.replace(/import \{ANALYSIS_VERSION\} from '\.\/client\.js';/, `const ANALYSIS_VERSION=${JSON.stringify(version)};`)).toString('base64'));
const cache = await cacheModule('clar-test-v1');
const settings = {backend: 'https://example.test', provider: 'vertex', language: 'en', token: 'private-review-token-never-stored'};
const payload = {text: 'Everyone  knows the truth.', post_url: 'https://www.facebook.com/page/posts/100', origin: {poster_name: 'A', poster_url: 'https://www.facebook.com/a', context: 'page'}};
const result = {original_text: payload.text, overall: {label: 'PERSUASION_CUES'}, statements: [{text: 'Everyone  knows the truth.'}], techniques: [{quote: 'Everyone  knows', start: 0, end: 15}], media_literacy: {purpose: {quote: 'Everyone  knows'}, desired_response: {quote: 'the truth.'}, signals: [{quote: 'Everyone  knows'}]}};
assert.equal((await cache.getCached(payload, settings)).hit, false);
await cache.putCached(payload, settings, result);
assert.equal((await cache.getCached(payload, settings)).hit, true);
assert.equal((await cache.cacheInfo()).entries, 1);
assert.equal((await cache.getCached({...payload,origin:{context:'page',poster_url:'https://www.facebook.com/a',poster_name:'A'}},settings)).hit,true,'Chrome storage can reorder object keys; feed and panel must share a cache key');
const rebased = await cache.getCached({...payload, text: 'Everyone\nknows   the truth.'}, settings);
assert.equal(rebased.hit, true, 'Whitespace-equivalent content should reuse the check');
assert.equal(rebased.result.original_text, 'Everyone\nknows   the truth.');
assert.equal(rebased.result.statements[0].text, 'Everyone\nknows   the truth.');
assert.equal(rebased.result.techniques[0].quote, 'Everyone\nknows');
assert.equal(rebased.result.techniques[0].start, undefined, 'Offsets must not survive whitespace rebasing');
assert.equal(rebased.result.media_literacy.signals[0].quote, 'Everyone\nknows');
assert.equal((await cache.getCached(payload, settings)).result.original_text, payload.text, 'A hit must not mutate the stored result');
for (const changed of [{language: 'ro'}, {provider: 'local'}, {backend: 'http://localhost:8765'}, {token: 'another-private-token'}]) {
  assert.equal((await cache.getCached(payload, {...settings, ...changed})).hit, false, `Separate ${Object.keys(changed)[0]}`);
}
for (const changed of [{post_date: '2026-09-26'}, {post_url: 'https://www.facebook.com/page/posts/101'}, {origin: {...payload.origin, poster_name: 'Other author'}}, {text: 'A substantially different post.'}]) {
  assert.equal((await cache.getCached({...payload, ...changed}, settings)).hit, false, `Separate ${Object.keys(changed)[0]}`);
}
assert.equal((await cache.getCached(payload, settings, 'precheck')).hit, false, 'Preliminary and evidence results must never alias');
assert.equal((await (await cacheModule('clar-test-v2')).getCached(payload, settings)).hit, false, 'An analysis version change invalidates older results');
const saved = JSON.stringify(backing);
assert.ok(!saved.includes(settings.token));
assert.ok(!saved.includes(settings.backend), 'Payload and credential metadata are hashed, not stored beside results');

const image = {text: '', image_url: 'https://example.fbcdn.net/photo.png?private-token=123', image: {mime_type: 'image/png', data: 'RAW_IMAGE_DATA_SHOULD_NOT_BE_STORED'}};
await cache.putCached(image, settings, {original_text: 'Extracted image text', overall: {label: 'UNVERIFIED_CLAIM'}});
assert.equal((await cache.getCached({text: '', image_url: image.image_url}, settings)).hit, true, 'Image results reopen from their image identity without downloading bytes');
assert.ok(!JSON.stringify(backing).includes(image.image.data));
assert.ok(!JSON.stringify(backing).includes(image.image_url));

const realNow = Date.now;
const current = realNow();
Date.now = () => current + 24 * 60 * 60 * 1000 + 1;
try {
  assert.equal((await cache.getCached(payload, settings)).hit, false, 'Results expire after 24 hours');
  assert.equal((await cache.cacheInfo()).entries, 0);
} finally { Date.now = realNow; }

const beforeClear = await cache.getCached({text: 'In flight'}, settings);
await cache.clearCached();
assert.equal(await cache.putCached({text: 'In flight'}, settings, result, 'analyze', beforeClear.epoch), false, 'A late in-flight response cannot restore data after Clear');
assert.equal((await cache.cacheInfo()).entries, 0);
assert.equal(await cache.putCached(payload, settings, result, 'analyze', (await cache.getCached(payload, settings)).epoch), true);
await cache.clearCached();
for (let i = 0; i < 54; i += 1) await cache.putCached({text: `Unique post ${i}`}, settings, {original_text: `Unique post ${i}`});
assert.equal((await cache.cacheInfo()).entries, 50, 'Bound persistent cache size');
assert.equal((await cache.getCached({text: 'Unique post 0'}, settings)).hit, false);
assert.equal(await cache.putCached({text: 'Oversize'}, settings, {original_text: 'x'.repeat(500_001)}), false);
console.log('PASS: cache expiry, identity/language/provider/version/task separation, whitespace quote rebasing, image results without image bytes, clear epoch and bounded storage');
