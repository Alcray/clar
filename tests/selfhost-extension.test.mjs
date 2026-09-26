// A generated package, disposable Chromium profile, and mocked HTTPS server.
// No existing Chrome profile, Facebook account, or model service is contacted.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'clar-selfhost-'));
const extension = path.join(temporary, 'extension');
const backend = 'https://clar.example.test:9443';
const secondBackend = 'http://localhost:9000';
const report = JSON.parse(execFileSync('python3', [path.join(root, 'tools/build_extension.py'),
  '--backend', backend, '--backend', secondBackend, '--default-provider', 'local',
  '--output-dir', extension, '--archive', path.join(temporary, 'extension.zip')], {encoding:'utf8'}));
const context = await chromium.launchPersistentContext(path.join(temporary, 'profile'), {
  channel:'chromium', headless:true, viewport:{width:450,height:1050},
  args:[`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
});
const errors = [], requests = [], unexpected = [];
try {
  context.on('page', page => page.on('pageerror', e => errors.push(e.message)));
  await context.route('**/*', async route => {
    const url = route.request().url();
    if (!/^https?:/.test(url)) return route.continue();
    if ([backend, secondBackend].some(origin => url === origin + '/api/health')) {
      requests.push(url);
      assert.equal(route.request().headers().authorization, 'Bearer fake-selfhost-pairing-code');
      return route.fulfill({contentType:'application/json', body:JSON.stringify({local_ready:true,vertex_configured:true,configured:true})});
    }
    unexpected.push(url); return route.abort('blockedbyclient');
  });
  let worker = context.serviceWorkers()[0];
  if (!worker) worker = await context.waitForEvent('serviceworker');
  assert.equal(new URL(worker.url()).hostname, report.extension_id, 'Generated identity loads in Chromium');
  const manifest = await worker.evaluate(() => chrome.runtime.getManifest());
  assert.ok(manifest.host_permissions.includes('https://clar.example.test:9443/*'));
  assert.ok(manifest.host_permissions.includes('http://localhost:9000/*'));
  assert.ok(!JSON.stringify(manifest).includes('tail14ec04'));
  const panel = await context.newPage();
  await panel.goto(`chrome-extension://${report.extension_id}/panel.html`);
  const checks = await panel.evaluate(async ({backend, secondBackend}) => {
    const config = await import(chrome.runtime.getURL('config.js'));
    return {valid:config.validBackend(backend),second:config.validBackend(secondBackend),
      foreign:config.validBackend('https://unconfigured.example.test'),
      wrongPort:config.validBackend('https://clar.example.test:9444'),
      path:config.validBackend(backend + '/attacker'), default:config.DEFAULT_SETTINGS};
  }, {backend, secondBackend});
  assert.equal(checks.valid, true); assert.equal(checks.second, true);
  assert.equal(checks.foreign, false); assert.equal(checks.wrongPort, false); assert.equal(checks.path, false);
  assert.equal(checks.default.backend, backend); assert.equal(checks.default.provider, 'local');

  await panel.getByText('Pair your extension to start', {exact:true}).waitFor();
  assert.deepEqual(await panel.locator('#backend option').evaluateAll(options => options.map(option => option.value)), [backend, secondBackend]);
  assert.equal(await panel.locator('#pair-link').getAttribute('href'), backend + '/#extension');
  await panel.locator('#pair-token').fill('fake-selfhost-pairing-code');
  await panel.getByRole('button', {name:'Save connection',exact:true}).click();
  await panel.getByText('Connected · Local model', {exact:true}).waitFor();
  assert.equal(requests.at(-1), backend + '/api/health');
  assert.equal(await panel.locator('#feedback-link').getAttribute('href'), backend + '/#feedback');
  await panel.locator('#settings-toggle').click();
  await panel.locator('#backend').selectOption(secondBackend);
  assert.equal(await panel.locator('#pair-link').getAttribute('href'), secondBackend + '/#extension');
  await panel.locator('#provider').selectOption('gemini');
  await panel.getByRole('button', {name:'Save connection',exact:true}).click();
  await panel.getByText('Connected · Gemini API', {exact:true}).waitFor();
  assert.equal(requests.at(-1), secondBackend + '/api/health');

  // A stale/sideloaded setting cannot cause a request to an unapproved server.
  await worker.evaluate(() => chrome.storage.local.set({settings:{
    backend:'https://unconfigured.example.test',token:'fake-selfhost-pairing-code',provider:'vertex',language:'en',
  }}));
  await panel.reload();
  await panel.getByText('Pair your extension to start', {exact:true}).waitFor();
  assert.equal(await panel.locator('#backend').inputValue(), backend);
  assert.equal(await panel.locator('#pair-token').inputValue(), '');
  assert.deepEqual(unexpected, []); assert.deepEqual(errors, []);
  console.log('PASS: configured HTTPS and custom-port localhost builds load, pair, preserve identity, and reject unapproved backends.');
} finally {
  await context.close(); fs.rmSync(temporary, {recursive:true,force:true});
}
