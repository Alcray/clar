import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

vm.runInThisContext(fs.readFileSync(new URL('../shared/presentation.js', import.meta.url), 'utf8'));
const {summarize, copy} = globalThis.CLAR_PRESENTATION;
const source = (stance = 'confirms', url = 'https://gov.md/document') => ({url, stance});
const claim = (label = 'VERIFIED_FACT', evidence = [source()]) => ({kind: 'factual', label, evidence});
const result = (label = 'VERIFIED_FACT', statements = [claim(label)], confidence = 'high') => ({
  original_text: 'The report is available. Everyone must fear them. Buy this product.',
  overall: {label, confidence, is_preliminary: false}, statements,
});
const debunk = (relation, verdict = 'FALSE') => ({url: 'https://stopfals.md/verified', relation,
  verdict, verdict_verified: true, publisher_rating_verified: true});
const tags = value => summarize(value).tags.map(tag => tag.id);

assert.equal(summarize(result()).level, 'low');
assert.equal(summarize(result('VERIFIED_FACT', [claim('VERIFIED_FACT', [])])).level, 'moderate');
assert.equal(summarize(result('VERIFIED_FACT', [claim('VERIFIED_FACT', [source('context')])])).level, 'moderate');
const falseResult = result('FALSE', [claim('FALSE', [source('contradicts')])]);
assert.equal(summarize(falseResult).level, 'high');
assert.equal(summarize({...falseResult, overall: {...falseResult.overall, confidence: 'medium'}}).level, 'moderate');
assert.equal(summarize(result('FALSE', [claim('FALSE', [source('context')])])).level, 'moderate');
assert.equal(summarize(result('FALSE', [claim('FALSE', [])])).level, 'moderate');
assert.equal(summarize(result('MISLEADING', [claim('MISLEADING', [source('context')])])).level, 'moderate');
const checked = result('FALSE', [{...claim('FALSE'), fact_check: debunk(undefined)}]);
assert.equal(summarize(checked).level, 'high');
assert.ok(tags(checked).includes('previously_debunked'));
assert.equal(summarize(checked).source.url, 'https://stopfals.md/verified');
for (const relation of ['related_context', 'related_topic', 'none']) {
  const contextOnly = result('FALSE', [{...claim('FALSE'), fact_check: debunk(relation)}]);
  assert.equal(summarize(contextOnly).level, 'moderate');
  assert.ok(!tags(contextOnly).includes('previously_debunked'));
}
const refutation = result('VERIFIED_FACT', [{...claim(), fact_check: debunk('same_claim')}]);
assert.equal(summarize(refutation).level, 'low');
assert.ok(!tags(refutation).includes('previously_debunked'));
const mixed = result('MIXED', [claim(), claim('FALSE', [source('contradicts', 'https://stopfals.md/check')])]);
assert.equal(summarize(mixed).level, 'high');
assert.equal(summarize(mixed).label, 'Mixed findings');
assert.equal(summarize(mixed).source.domain, 'stopfals.md');
mixed.overall.confidence = 'low';
assert.equal(summarize(mixed).level, 'moderate');

const opinion = result('OPINION', [{kind: 'opinion', label: 'OPINION'}], 'medium');
assert.equal(summarize(opinion).level, 'low');
assert.deepEqual(tags(opinion), ['opinion']);
opinion.techniques = [{type: 'fear_appeal', quote: 'Everyone must fear them.'}];
assert.equal(summarize(opinion).level, 'moderate');
assert.deepEqual(tags(opinion), ['fear_tactics', 'opinion']);
opinion.techniques[0].quote = 'A made up quotation';
assert.equal(summarize(opinion).level, 'low');
assert.deepEqual(tags(opinion), ['opinion']);
const official = {...result('UNVERIFIED_CLAIM', [claim('UNVERIFIED_CLAIM', [])], 'low'),
  origin: {type: 'official', matched_registry: {url: 'https://www.facebook.com/Official'}}};
assert.equal(summarize(official).level, 'moderate');
assert.ok(tags(official).includes('official_source'));
assert.ok(tags(official).includes('no_primary_source'));
assert.equal(summarize(official).source, null);
assert.ok(!tags({...official, origin: {type: 'official'}}).includes('official_source'));
assert.ok(!tags(result('UNVERIFIED_CLAIM', [claim('UNVERIFIED_CLAIM', [source('context', 'https://unfamiliar.example/evidence')])])).includes('no_primary_source'));
assert.ok(!tags(result('UNVERIFIED_CLAIM', [{kind: 'factual', label: 'UNVERIFIED_CLAIM'}])).includes('no_primary_source'));
assert.ok(!tags(result('UNCLEAR', [])).includes('no_primary_source'));
assert.equal(summarize({...result(), original_text: 'Yes.'}).level, 'low'); // Text length is not a verdict.
assert.equal(summarize({...result(), image: 'image data', original_text: ''}).level, 'low'); // OCR evidence can resolve a claim.

for (const label of ['FALSE', 'VERIFIED_FACT', 'OPINION', 'MISLEADING', 'CHECKABLE_CLAIMS']) {
  const precheck = {...result(label), overall: {label, confidence: 'high', is_preliminary: true}};
  assert.ok(['moderate', 'inconclusive'].includes(summarize(precheck).level));
  assert.equal(summarize(precheck).source, null);
  assert.equal(summarize(precheck).preliminary, true);
  assert.ok(!tags(precheck).includes('previously_debunked'));
  assert.ok(!tags(precheck).includes('no_primary_source'));
}
const sell = {...opinion, techniques: [], media_literacy: {purpose: {category: 'sell', quote: 'Buy this product.'}}};
assert.equal(summarize(sell).level, 'moderate');
assert.equal(summarize(sell).label, 'Advertising');
assert.ok(tags(sell).includes('commercial_intent'));
assert.ok(!summarize(sell).label.toLowerCase().includes('scam'));

for (const url of ['javascript:alert(1)', 'data:text/html,x', 'https://name:password@gov.md/x', '/relative', '//gov.md/x']) {
  const unsafe = result('FALSE', [claim('FALSE', [source('contradicts', url)])]);
  assert.equal(summarize(unsafe).source, null);
  assert.equal(summarize(unsafe).level, 'moderate');
}
const evil = {...result(), overall: {...result().overall, intent: 'Visit https://invented.example'},
  origin: {url: 'https://facebook.com/author', type: 'official'}};
assert.equal(summarize(evil).source.url, 'https://gov.md/document');
assert.equal(summarize({...evil, statements: []}).source, null);
const redirect = 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/EXISTING-ID';
const redirected = result('VERIFIED_FACT', [claim('VERIFIED_FACT', [{url: redirect, title: 'www.gov.md', stance: 'confirms'}])]);
assert.deepEqual(summarize(redirected).source, {domain: 'gov.md', url: redirect});
for (const title of ['gov.md announcement', 'https://gov.md', 'gov.md/path', 'gov.md@evil.example',
  'gov.md:443', ' gov.md', 'gov..md', '-gov.md', 'gov-.md', '127.0.0.1', 'gov.md\n', '<gov.md>']) {
  redirected.statements[0].evidence[0].title = title;
  assert.deepEqual(summarize(redirected).source, {domain: 'vertexaisearch.cloud.google.com', url: redirect});
}
const redirectedDebunk = result('FALSE', [{...claim('FALSE', [{url: redirect, title: 'stopfals.md', stance: 'contradicts'}]),
  fact_check: debunk('same_claim')}]);
assert.deepEqual(summarize(redirectedDebunk).source, {domain: 'stopfals.md', url: 'https://stopfals.md/verified'});
redirectedDebunk.statements[0].fact_check.relation = 'related_context';
assert.deepEqual(summarize(redirectedDebunk).source, {domain: 'stopfals.md', url: redirect});
const manyTags = {...checked, origin: {type: 'anonymous_group'}, techniques: [
  {type: 'fear_appeal', quote: 'Everyone must fear them.'}, {type: 'us_vs_them', quote: 'them'},
  {type: 'emotional_language', quote: 'fear'}, {type: 'commercial_pressure', quote: 'Buy this product.'}
]};
assert.equal(summarize(manyTags).tags.length, 3);
for (const language of ['en', 'ro', 'ru']) {
  const c = copy(language);
  assert.ok(c.analyze && c.analyzing && c.feedbackSaved && c.fullAnalysis);
  for (const intent of Object.values(c.intents)) assert.ok(intent.trim().split(/\s+/u).length <= 10, `${language}: ${intent}`);
  const localized = summarize(manyTags, {language});
  assert.equal(localized.levelText, c.high);
  assert.equal(localized.tags[0].text, c.tags.previously_debunked);
  assert.ok(localized.intent.trim().split(/\s+/u).length <= 10);
}
assert.equal(summarize(falseResult, {language: 'unsupported'}).levelText, 'HIGH RISK');
assert.equal(summarize(null).level, 'inconclusive');
assert.equal(summarize({statements: [null, 4, 'invalid']}).level, 'inconclusive');
const original = structuredClone(manyTags);
summarize(manyTags);assert.deepEqual(manyTags, original);
const c = copy();c.tags.opinion = 'changed';assert.equal(copy().tags.opinion, 'Opinion');
console.log('PASS: presentation risk gates, evidence, context/refutations, mixed findings, preliminary guard, safe source URLs, localization, intent budget and input preservation');
