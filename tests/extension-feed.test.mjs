// Complete content -> worker -> panel/job API -> cache -> content loop, mocked
// backend, synthetic feed and disposable Chromium profile only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),extension=path.join(root,'extension');
const id=JSON.parse(fs.readFileSync(path.join(extension,'identity.json'),'utf8')).id;
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'clar-feed-jobs-'));fs.chmodSync(profile,0o700);
const context=await chromium.launchPersistentContext(profile,{channel:'chromium',headless:true,viewport:{width:1200,height:1100},args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]});
const backend='http://127.0.0.1:8765',requests=[],errors=[],unexpected=[];
const results=body=>({provider:'vertex',original_text:body.text,summary:'Feed check complete',overall:{label:body.task==='precheck'?'PERSUASION_CUES':'FALSE',confidence:body.task==='precheck'?'low':'high',summary:body.task==='precheck'?'Preliminary feed reading':'Feed check complete',is_preliminary:body.task==='precheck'},origin:{type:'unknown',poster_name:body.origin?.poster_name||'',url:body.origin?.poster_url||null,note:'Only rendered metadata.'},statements:body.task==='precheck'?[]:[{text:body.text,kind:'factual',label:'FALSE',confidence:'high',explanation:'Deterministic test result',evidence:[{url:'https://parlament.md/',title:'parlament.md',stance:'contradicts',finding:'Synthetic evidence for the UI test.'}]}],techniques:body.text.includes('Everyone knows')?[{type:'unsupported_certainty',name:'Unsupported certainty',quote:'Everyone knows',explanation:'This wording presents agreement as universal.'}]:[],search_suggestions:[]});
try{
  context.on('page',page=>page.on('pageerror',error=>errors.push(error.message)));
  await context.route('**/*',async route=>{
    const request=route.request(),url=request.url();
    if(!/^https?:/.test(url))return route.continue();
    if(url.startsWith('https://www.facebook.com/'))return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'tests/fixtures/facebook-feed.html'),'utf8').replace('Parlamentul are','Everyone knows Parlamentul are')});
    if(url.startsWith('https://scontent.example.fbcdn.net/'))return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(extension,'icons/128.png'))});
    if(url===backend+'/api/health')return route.fulfill({contentType:'application/json',body:JSON.stringify({vertex_configured:true,local_ready:true})});
    if(url===backend+'/api/jobs'){
      const body=request.postDataJSON();requests.push(body);
      assert.equal(request.headers().authorization,'Bearer fake-feed-pairing-for-isolated-test');
      return route.fulfill({contentType:'application/json',body:JSON.stringify({job_id:'test-job-'+requests.length,status:'complete',progress:{stages:[{id:'done',state:'done'}]},result:results(body)})});
    }
    unexpected.push(url);return route.abort('blockedbyclient');
  });
  let worker=context.serviceWorkers()[0];if(!worker)worker=await context.waitForEvent('serviceworker');
  await worker.evaluate(backend=>chrome.storage.local.set({settings:{backend,token:'fake-feed-pairing-for-isolated-test',provider:'vertex',language:'en',autoScan:false,showHighlights:true}}),backend);
  const panel=await context.newPage();await panel.goto(`chrome-extension://${id}/panel.html`);
  await panel.getByText('Connected · Gemini via Vertex AI',{exact:true}).waitFor();
  const feed=await context.newPage();await feed.goto('https://www.facebook.com/');
  await feed.locator('[data-clar-control]').nth(2).waitFor();await feed.waitForTimeout(350);
  assert.equal(requests.length,0);
  const click=async selector=>{const host=feed.locator(selector+' [data-clar-control=""]').first();await host.scrollIntoViewIfNeeded();const box=await host.boundingBox();await feed.mouse.click(box.x+60,box.y+16);};
  await click('#post-one');
  await feed.locator('#post-one[data-clar-risk=high]').waitFor();
  assert.equal((await worker.evaluate(()=>chrome.storage.session.get('selection'))).selection,undefined,'Initial Analyze keeps side panel closed');
  await click('#post-one');await feed.locator('[data-clar-popover]').waitFor();
  await feed.keyboard.press('Tab');await feed.keyboard.press('Tab');await feed.keyboard.press('Tab');await feed.keyboard.press('Enter');
  await feed.waitForTimeout(120);
  const feedback=await worker.evaluate(()=>chrome.storage.local.get('clarDisagreements'));
  assert.equal(feedback.clarDisagreements.length,1);assert.equal(feedback.clarDisagreements[0].level,'high');
  assert.equal(feedback.clarDisagreements[0].text,undefined,'Disagree stores no raw post');
  await feed.keyboard.press('Escape');assert.equal(await feed.locator('[data-clar-popover]').count(),0);
  await click('#post-one');await feed.keyboard.press('Tab');await feed.keyboard.press('Tab');await feed.keyboard.press('Enter');
  await panel.locator('#results:not([hidden]) .cr-overall').waitFor();
  await feed.locator('#post-one [data-clar-highlight]').waitFor();
  assert.equal(requests.length,1);assert.equal(requests[0].task,'analyze');
  assert.ok(!requests[0].text.includes('comment must'));
  assert.equal(await feed.locator('#post-one [data-clar-highlight]').textContent(),'Everyone knows');
  const selected=(await worker.evaluate(()=>chrome.storage.session.get('selection'))).selection;
  assert.ok(selected.postKey);assert.equal(selected.externalCheck,true);

  await click('#post-one');await feed.locator('[data-clar-popover]').waitFor();await feed.keyboard.press('Tab');await feed.keyboard.press('Tab');await feed.keyboard.press('Enter');await panel.locator('.cr-cache').waitFor({state:'attached'});
  assert.equal(requests.length,1,'Clicking an already checked post restores the cache');
  await panel.close();const reopened=await context.newPage();await reopened.goto(`chrome-extension://${id}/panel.html`);await reopened.locator('.cr-cache').waitFor({state:'attached'});
  assert.equal(requests.length,1);

  await worker.evaluate(async()=>{const {settings}=await chrome.storage.local.get('settings');await chrome.storage.local.set({settings:{...settings,autoScan:true}});});
  await feed.waitForTimeout(400);
  assert.equal(requests.length,1,'Automatic scans should prefer an existing full check');
  await feed.evaluate(()=>{const post=document.createElement('article');post.id='new-auto';post.setAttribute('role','article');post.innerHTML='<h3><a href="/new-author">New author</a></h3><a href="/new-author/posts/999">Today</a><div data-ad-preview="message">Everyone knows this newly visible post has enough words to receive a preliminary reading once optional automatic scanning is explicitly enabled.</div>';document.querySelector('main').prepend(post);});
  await feed.locator('#new-auto [data-clar-control]').waitFor();
  await feed.locator('#new-auto [data-clar-highlight]').waitFor();
  assert.equal(requests.length,2);assert.equal(requests[1].task,'precheck');assert.equal(requests[1].origin.poster_name,'New author');
  await click('#new-auto');await feed.locator('[data-clar-popover]').waitFor();await feed.keyboard.press('Tab');await feed.keyboard.press('Enter');await reopened.waitForFunction(()=>document.querySelector('#post-text').value.includes('newly visible'));await reopened.locator('#results:not([hidden]) .cr-overall').waitFor();
  assert.equal(requests.length,3);assert.equal(requests[2].task,'analyze','Preliminary result must not replace a full check');
  await reopened.locator('#settings-toggle').click();await reopened.locator('#show-highlights').uncheck();
  await feed.waitForFunction(()=>document.querySelectorAll('[data-clar-highlight]').length===0);
  await reopened.locator('#auto-scan').uncheck();await reopened.locator('#clear-cache').click();
  await reopened.locator('#cache-status').filter({hasText:'0 saved checks'}).waitFor();
  await feed.waitForTimeout(300);assert.equal(requests.length,3);
  assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
  console.log('PASS: installed extension pill check, high accent, compact card, local Disagree, keyboard/Esc, cached full panel, opt-in scans and clear');
}finally{await context.close();fs.rmSync(profile,{recursive:true,force:true});}
