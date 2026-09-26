// UI regression with synthetic posts and mocked model responses only.
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
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'clar-literacy-ui-'));
const backend='http://127.0.0.1:8765';
const original='Parlamentul are 150 de deputați. Numai trădătorii se îndoiesc. Distribuie acum, înainte să ne reducă la tăcere.';
const fixture={mode:'live',provider:'vertex',original_text:original,summary:'One factual claim. One opinion.',overview:'Inspect both the evidence and the wording.',
  statements:[{id:'C1',text:'Parlamentul are 150 de deputați.',kind:'factual',verdict:'contradicted',explanation:'The supplied evidence gives a different number.',evidence:[]},
    {id:'C2',text:'Numai trădătorii se îndoiesc.',kind:'opinion',verdict:'not_applicable',explanation:'A judgment about people who disagree.',evidence:[]}],
  queries:[],search_suggestions:[],media_literacy:{status:'available',
    purpose:{category:'persuade',explanation:'The wording appears to encourage sharing the criticism and dismissing disagreement.',quote:'Distribuie acum, înainte să ne reducă la tăcere.'},
    desired_response:{description:'Share the post quickly and treat doubt as disloyalty.',quote:'Numai trădătorii se îndoiesc.'},
    signals:[{type:'us_vs_them',label:'Discrediting disagreement',quote:'Numai trădătorii se îndoiesc.',explanation:'Calling doubters traitors can discourage readers from asking questions.',question:'Can someone disagree without being disloyal?'},
      {type:'urgency',label:'Pressure to share quickly',quote:'Distribuie acum, înainte să ne reducă la tăcere.',explanation:'The call to act now connects sharing with a feared loss of voice.',question:'What evidence establishes this urgency?'}],
    reading_tip:'Check the number independently before sharing the post.',limitations:'Wording can suggest a purpose; it cannot establish the author’s private intent.'}};
let response=structuredClone(fixture),sequence=0;
const errors=[];
const context=await chromium.launchPersistentContext(profile,{channel:'chromium',headless:true,viewport:{width:1440,height:1050},
  args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]});
try{
  context.on('page',page=>page.on('pageerror',e=>errors.push(e.message)));
  let worker=context.serviceWorkers()[0];if(!worker)worker=await context.waitForEvent('serviceworker');
  await context.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(!['http:','https:'].includes(url.protocol))return route.continue();
    if(url.origin!==backend)return route.abort();
    if(url.pathname==='/api/health')return route.fulfill({contentType:'application/json',body:JSON.stringify({default_provider:'vertex',vertex_configured:true,local_ready:true})});
    if(url.pathname==='/api/jobs')return route.fulfill({contentType:'application/json',body:JSON.stringify({job_id:'synthetic-job-for-ui-only',status:'complete',result:response,progress:{stages:[{id:'done',state:'done'}]}})});
    if(url.pathname==='/api/examples')return route.fulfill({contentType:'application/json',body:'[]'});
    const files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/results.js':'results.js','/presentation.js':'presentation.js','/results.css':'results.css','/client.js':'client.js','/grounding.js':'grounding.js','/styles.css':'styles.css','/favicon.svg':'favicon.svg'};
    const name=files[url.pathname];if(!name)return route.abort();
    const contentType=name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.svg')?'image/svg+xml':'text/html';
    return route.fulfill({contentType,body:fs.readFileSync(path.join(root,'public',name))});
  });
  const page=await context.newPage();await page.goto(backend);
  await page.getByText('Vertex AI connected',{exact:true}).waitFor();
  const checkWeb=async value=>{
    response=structuredClone(value);
    await page.locator('#post-text').fill(original);
    await page.locator('#analyze-button').click();
    await page.locator('#results:not([hidden])').waitFor();
  };
  await checkWeb(fixture);
  assert.equal(await page.locator('.claim-card').count(),2);
  assert.equal(await page.locator('.media-literacy .literacy-cue').count(),2);
  assert.ok((await page.locator('.media-literacy').innerText()).includes('Share the post quickly'));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  fs.mkdirSync(path.join(root,'.runtime'),{recursive:true});
  await page.locator('.media-literacy').screenshot({path:path.join(root,'.runtime/media-literacy-web.png')});
  await page.setViewportSize({width:390,height:844});
  await page.locator('.media-literacy .literacy-cue').first().locator('summary').click();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.locator('.media-literacy').screenshot({path:path.join(root,'.runtime/media-literacy-mobile.png')});
  const inert=structuredClone(fixture);
  inert.media_literacy.reading_tip='<img src=x onerror="globalThis.injected=true">';
  inert.media_literacy.signals.push({...fixture.media_literacy.signals[0],quote:'A sentence the author never wrote.'});
  await checkWeb(inert);
  assert.equal(await page.locator('.media-literacy .literacy-cue').count(),2);
  assert.equal(await page.locator('.media-literacy img').count(),0);
  assert.equal(await page.evaluate(()=>globalThis.injected),undefined);
  const unavailable={...fixture,media_literacy:{status:'unavailable',limitations:'This additional reading could not be completed.'}};
  await checkWeb(unavailable);
  assert.equal(await page.locator('.claim-card').count(),2);
  assert.equal(await page.locator('.media-literacy .literacy-cue').count(),0);
  assert.equal(await page.locator('.media-literacy').count(),1);
  const legacy=structuredClone(fixture);delete legacy.media_literacy;
  await checkWeb(legacy);
  assert.equal(await page.locator('.claim-card').count(),2);
  assert.equal(await page.locator('.media-literacy').count(),0);
  await worker.evaluate(async({backend})=>{
    await chrome.storage.local.set({settings:{backend,token:'fake-pairing-code-for-ui-test-only',provider:'vertex',language:'en'}});
    await chrome.storage.session.clear();
  },{backend});
  const panel=await context.newPage();await panel.setViewportSize({width:410,height:1050});
  await panel.goto(`chrome-extension://${id}/panel.html`);
  await panel.getByText('Connected · Gemini via Vertex AI',{exact:true}).waitFor();
  const checkPanel=async value=>{
    response=structuredClone(value);
    await worker.evaluate(()=>chrome.storage.local.remove('clarResultCacheV4'));
    const pending=panel.waitForResponse(r=>r.url()===backend+'/api/jobs');
    await worker.evaluate(post=>chrome.storage.session.set({selection:post}),{selectionId:`literacy-${++sequence}`,autoCheck:true,text:original,truncated:false,imageUrl:null,url:null});
    await pending;await panel.locator('#results:not([hidden])').waitFor();
  };
  await checkPanel(fixture);
  assert.equal(await panel.locator('.claim').count(),2);
  assert.equal(await panel.locator('.media-literacy .literacy-cue').count(),2);
  await panel.locator('.media-literacy .literacy-cue').first().locator('summary').click();
  assert.equal(await panel.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await panel.locator('.media-literacy').screenshot({path:path.join(root,'.runtime/media-literacy-extension.png')});
  await checkPanel(inert);
  assert.equal(await panel.locator('.media-literacy .literacy-cue').count(),2);
  assert.equal(await panel.locator('.media-literacy img').count(),0);
  assert.equal(await panel.evaluate(()=>globalThis.injected),undefined);
  await checkPanel(unavailable);
  assert.equal(await panel.locator('.claim').count(),2);
  assert.equal(await panel.locator('.media-literacy').count(),1);
  await checkPanel(legacy);
  assert.equal(await panel.locator('.claim').count(),2);
  assert.equal(await panel.locator('.media-literacy').count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS: web + extension literacy, retained fact cards, mobile layout, exact quotes, inert HTML, unavailable and legacy responses');
}finally{await context.close();fs.rmSync(profile,{recursive:true,force:true});}
