// Isolated Chromium and mocked API only; never connects to CLAR or a model provider.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const extension=path.join(root,'extension');
const id=JSON.parse(fs.readFileSync(path.join(extension,'identity.json'),'utf8')).id;
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'clar-autocheck-test-'));
fs.chmodSync(profile,0o700);
const context=await chromium.launchPersistentContext(profile,{
  channel:'chromium',headless:true,viewport:{width:450,height:1050},
  args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]
});
const backend='http://127.0.0.1:8765';
const settings={backend,token:'fake-test-pairing-code-never-real',provider:'vertex',language:'en'};
const requests=[],errors=[],unexpected=[],jobs=new Map(),jobFingerprints=new Map(),heldJobs=new Set(),jobTitles=new Map();
let nextJobHeld=false;
let healthCount=0,healthGate=null;
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
const selection=(selectionId,text)=>({selectionId,text,url:null,imageUrl:null,visibleDate:null,
  truncated:false,tabId:1,selectedAt:Date.now(),autoCheck:true});
const passed=[];

try{
  let worker=context.serviceWorkers()[0];
  if(!worker)worker=await context.waitForEvent('serviceworker');
  assert.equal(new URL(worker.url()).hostname,id);
  context.on('page',page=>page.on('pageerror',e=>errors.push(e.message)));
  await context.route('**/*',async route=>{
    const request=route.request(),url=request.url();
    if(!/^https?:/.test(url))return route.continue();
    const headers={'access-control-allow-origin':`chrome-extension://${id}`,
      'access-control-allow-headers':'Authorization, Content-Type, X-CLAR-Extension',
      'access-control-allow-methods':'GET, POST, OPTIONS'};
    if(url===backend+'/api/health'){
      healthCount++;
      const gate=healthGate;
      if(gate)await gate.promise;
      return route.fulfill({status:200,headers,contentType:'application/json',
        body:JSON.stringify({vertex_configured:true,local_ready:true})});
    }
    if(url===backend+'/api/jobs'){
      if(request.method()==='OPTIONS')return route.fulfill({status:204,headers});
      assert.equal(request.method(),'POST');
      const body=request.postDataJSON();requests.push(body);
      const fingerprint=JSON.stringify({...body,force:false});
      const job_id=(!body.force&&jobFingerprints.get(fingerprint))||'mock-job-'+requests.length;
      if(!jobs.has(job_id)){
        jobs.set(job_id,body);jobFingerprints.set(fingerprint,job_id);
        if(nextJobHeld){heldJobs.add(job_id);jobTitles.set(job_id,'Replacement check finished');nextJobHeld=false;}
      }
      return route.fulfill({status:200,headers,contentType:'application/json',
        body:JSON.stringify({job_id,status:'running',progress:{stages:[{id:'reading',state:'done'},{id:'sources',state:'running'}]}})});
    }
    if(url.startsWith(backend+'/api/jobs/mock-job-')){
      const job_id=url.split('/').at(-1),body=jobs.get(job_id);
      assert.ok(body,'Job polling must refer to the returned job id');
      if(heldJobs.has(job_id))return route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify({job_id,status:'running',progress:{stages:[{id:'sources',state:'running'}]}})});
      return route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify({job_id,status:'complete',progress:{stages:[{id:'done',state:'done'}]},result:{provider:'vertex',original_text:body.text,
          overall:{label:'UNVERIFIED_CLAIM',confidence:'low',summary:jobTitles.get(job_id)||'Mock check finished',is_preliminary:false},
          summary:'Mock check finished',overview:'Deterministic extension test.',statements:[],search_suggestions:[]}})});
    }
    unexpected.push(url);
    return route.abort('blockedbyclient');
  });
  const seed=async(post,paired=true)=>{
    await worker.evaluate(async({post,settings,paired})=>{
      await chrome.storage.session.clear();
      await chrome.storage.local.set({settings:paired?settings:{...settings,token:''}});
      if(post)await chrome.storage.session.set({selection:post});
    },{post,settings,paired});
  };
  const open=async()=>{const page=await context.newPage();await page.goto(`chrome-extension://${id}/panel.html`);return page;};
  const connected=page=>page.getByText('Connected · Gemini via Vertex AI',{exact:true}).waitFor();
  const result=async page=>{await page.locator('#results:not([hidden]) .cr-overall').waitFor();await page.locator('.cr-assessment-summary').filter({hasText:'Mock check finished'}).waitFor({state:'attached'});};
  const pair=async page=>{
    await page.locator('#backend').selectOption(backend);
    await page.locator('#pair-token').fill(settings.token);
    await page.getByRole('button',{name:'Save connection',exact:true}).click();
    await connected(page);
  };
  const noMoreRequests=async(page,count)=>{
    // Allow storage events and claim round trips to settle before an absence assertion.
    await page.waitForTimeout(300);
    assert.equal(requests.length,count);
  };

  await seed(selection('cold-start','Cold start post.'));
  let panel=await open();
  await result(panel);
  assert.equal(requests.length,1);
  assert.equal(requests[0].text,'Cold start post.');
  await noMoreRequests(panel,1);
  assert.equal((await worker.evaluate(()=>chrome.storage.session.get('selection'))).selection.autoCheckClaimed,true);
  passed.push('cold startup submits once');

  await panel.reload();await connected(panel);
  await result(panel);await panel.locator('.cr-cache').waitFor({state:'attached'});
  await noMoreRequests(panel,1);
  passed.push('reload does not rerun claimed selection');

  await worker.evaluate(post=>chrome.storage.session.set({selection:post}),selection('warm-start','Warm selected post.'));
  await result(panel);
  assert.equal(requests.length,2);
  assert.equal(requests[1].text,'Warm selected post.');
  await noMoreRequests(panel,2);
  passed.push('warm selection submits once');

  await worker.evaluate(()=>chrome.storage.session.set({selection:{text:'Legacy manual post.',url:null,imageUrl:null,truncated:false}}));
  await panel.waitForFunction(()=>document.getElementById('post-text').value==='Legacy manual post.');
  await noMoreRequests(panel,2);
  passed.push('legacy manual selection does not submit');
  await panel.close();

  await seed(selection('before-pairing','Selected before pairing.'),false);
  panel=await open();
  await panel.getByText('Pair your extension to start',{exact:true}).waitFor();
  await noMoreRequests(panel,2);
  await pair(panel);await result(panel);
  assert.equal(requests.length,3);
  assert.equal(requests[2].text,'Selected before pairing.');
  await noMoreRequests(panel,3);
  passed.push('pending selection runs after pairing');
  await panel.close();

  await seed(selection('cancel-before-pairing','Original canceled post.'),false);
  panel=await open();
  await panel.getByText('Pair your extension to start',{exact:true}).waitFor();
  await panel.locator('#post-text').fill('Edited draft, not submitted.');
  await pair(panel);await noMoreRequests(panel,3);
  await panel.close();panel=await open();await connected(panel);
  await noMoreRequests(panel,3);
  passed.push('editing cancels pending intent across reopening');
  await panel.close();

  await seed(selection('manual-during-connect','One check during slow connection.'));
  healthGate=deferred();
  const initialHealthCount=healthCount;
  panel=await open();
  await panel.getByText('Connecting…',{exact:true}).waitFor();
  assert.ok(healthCount>initialHealthCount);
  await panel.getByRole('button',{name:'Check this post',exact:true}).click();
  healthGate.resolve();healthGate=null;
  await result(panel);
  await noMoreRequests(panel,4);
  assert.equal(requests[3].text,'One check during slow connection.');
  passed.push('manual check during connection submits once');

  await panel.close();panel=await open();await result(panel);await panel.locator('.cr-cache').waitFor({state:'attached'});
  await noMoreRequests(panel,4);
  passed.push('reopening restores cached result without another analysis');

  await panel.getByRole('button',{name:'Re-analyze',exact:true}).click();
  await panel.locator('#loading:not([hidden])').waitFor();await result(panel);
  assert.equal(requests.length,5);assert.equal(requests.at(-1).force,true);
  passed.push('explicit re-analysis forces a new check');

  await panel.locator('#settings-toggle').click();
  await panel.locator('#clear-cache').click();
  await panel.locator('#cache-status').filter({hasText:'0 saved checks'}).waitFor();
  assert.equal(await panel.locator('#results').isHidden(),true);
  await panel.getByRole('button',{name:'Check this post',exact:true}).click();await result(panel);
  assert.equal(requests.length,6);
  passed.push('clear saved checks removes results and a new check runs');

  if(await panel.locator('#settings').isHidden())await panel.locator('#settings-toggle').click();
  await panel.locator('#language').selectOption('ro');
  await panel.getByRole('button',{name:'Save connection',exact:true}).click();await connected(panel);
  await panel.getByRole('button',{name:'Check this post',exact:true}).click();await result(panel);
  assert.equal(requests.length,7);assert.equal(requests.at(-1).language,'ro');
  passed.push('language change cannot reuse an English result');

  const sameText='One check during slow connection.';
  await worker.evaluate(post=>chrome.storage.session.set({selection:post}),{...selection('new-origin',sameText),origin:{poster_name:'Different author',poster_url:'https://www.facebook.com/different',context:'unknown'}});
  await panel.locator('#loading:not([hidden])').waitFor();await result(panel);
  assert.equal(requests.length,8);assert.equal(requests.at(-1).origin.poster_name,'Different author');
  passed.push('a different visible origin receives a fresh result');

  // Keep A cached, time out the forced B request, then Retry must reattach to B
  // instead of accepting the older cache entry. Shorten only the client's 25s
  // deadline in this isolated test; normal API polling remains unchanged.
  await panel.evaluate(()=>{const original=setTimeout;window.setTimeout=(fn,ms,...args)=>original(fn,ms===25000&&window.__shortClarDeadline?40:ms,...args);window.__shortClarDeadline=true;});
  nextJobHeld=true;
  await panel.getByRole('button',{name:'Verifică din nou',exact:true}).click();
  await panel.locator('#panel-retry-button:not([hidden])').waitFor();
  assert.match(await panel.locator('#error').textContent(),/longer than 25 seconds/);
  assert.equal(requests.length,9);assert.equal(requests.at(-1).force,true);
  await worker.evaluate(async()=>{const {clarResultCacheV4:cache}=await chrome.storage.local.get('clarResultCacheV4');await chrome.storage.local.set({clarResultCacheV4:{...cache,unrelated:{stored_at:Date.now(),expires_at:Date.now()+60000,result:{original_text:'Different post'}}}});});
  await panel.waitForTimeout(100);
  assert.equal(await panel.locator('#panel-retry-button').isVisible(),true,'An unrelated cache update must not restore stale A during a forced retry');
  const created=jobs.size;
  heldJobs.clear();await panel.evaluate(()=>{window.__shortClarDeadline=false;});
  await panel.getByRole('button',{name:'Retry check',exact:true}).click();
  await panel.locator('.cr-assessment-summary').filter({hasText:'Replacement check finished'}).waitFor({state:'attached'});
  assert.equal(requests.length,10);assert.equal(requests.at(-1).force,false);
  assert.equal(jobs.size,created,'Retry must reuse the newest pending/completed server job');
  assert.equal(await panel.locator('.cr-cache').count(),0,'Retry must not surface cached A');
  passed.push('retry after a forced timeout resumes B instead of showing cached A');

  await panel.close();
  await seed({...selection('failed-external','Failed external selection.'),autoCheck:false,externalCheck:true,externalStatus:'failed',externalError:'External check timed out.'});
  panel=await open();await connected(panel);
  await panel.locator('#panel-retry-button:not([hidden])').waitFor();
  assert.equal(await panel.locator('#loading').isVisible(),false,'Reopening failed external check must not wait forever');
  await noMoreRequests(panel,10);
  await panel.getByRole('button',{name:'Retry check',exact:true}).click();await result(panel);
  assert.equal(requests.length,11);
  await panel.reload();await result(panel);
  assert.equal(await panel.locator('#error').isVisible(),false,'Cached success overrides old external failure');
  passed.push('failed external selection reopens with Retry and cached success clears its error');
  await panel.close();
  await seed({...selection('orphan-external','Resume a worker-owned check.'),autoCheck:false,externalCheck:true,externalStatus:'running'});
  panel=await open();await result(panel);
  assert.equal(requests.length,12);
  passed.push('reopening an external selection reattaches after worker state is lost');

  await panel.setViewportSize({width:380,height:950});
  assert.equal(await panel.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);

  assert.deepEqual(errors,[]);
  assert.deepEqual(unexpected,[]);
  console.log(JSON.stringify({extensionId:id,api:'mocked only',checks:passed,analysisRequests:requests.length,pageErrors:errors}));
}finally{
  healthGate?.resolve();
  await context.close();
  fs.rmSync(profile,{recursive:true,force:true});
}
