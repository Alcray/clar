// Shared renderer contract; no account, credential, or model requests.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(import.meta.dirname,'..');
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:390,height:844}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://renderer.test/**',route=>{
    const name=new URL(route.request().url()).pathname;
    if(name==='/results.js'||name==='/results.css'||name==='/presentation.js')return route.fulfill({contentType:name.endsWith('js')?'text/javascript':'text/css',body:fs.readFileSync(path.join(root,'shared',name.slice(1)))});
    return route.fulfill({contentType:'text/html',body:'<html><head><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/results.css"></head><body><main id="results"></main><div id="progress"></div></body></html>'});
  });
  await page.goto('https://renderer.test');
  const result={original_text:'They say everything collapsed.',summary:'A broad claim needs context.',
    overall:{label:'MISLEADING',confidence:'medium',summary:'Mixed indicators need context.',confidence_note:'Grounded summaries, not independently checked quotations.',intent:'Encourage distrust.',is_preliminary:false},
    origin:{poster_name:'<img src=x onerror=alert(1)>',type:'unknown_page',url:'javascript:alert(1)',note:'Unverified profile.'},
    statements:[{text:'They say everything collapsed.',kind:'factual',label:'MISLEADING',confidence:'medium',explanation:'Different indicators moved in different directions.',
      fact_check:{outlet:'StopFals',date:'2026-09-19',date_verified:true,verdict:'MISLEADING',publisher_verdict:'',publisher_rating_verified:false,rating_note:'CLAR interpretation; the publisher gives no explicit rating.',url:'https://stopfals.md/example',title:'Context for the indicators',match_explanation:'Same claim and period.'},
      evidence:[{url:'javascript:alert(1)',title:'Unsafe source'},{url:'https://gov.md/example',title:'Source',stance:'context',finding:'Read the original figures.'}]}],
    techniques:[{name:'Overgeneralization',quote:'everything collapsed',explanation:'Treats all indicators alike.'}]};
  const render=async(language='en',data=result)=>page.evaluate(async({language,data})=>{
    const {renderResults}=await import('/results.js');renderResults(document.querySelector('#results'),data,{language});
  },{language,data});
  await render();
  assert.equal(await page.locator('.cr-factcheck').getByText('Publisher rating: MISLEADING').count(),0);
  assert.ok((await page.locator('.cr-factcheck').innerText()).includes('No verified publisher rating'));
  assert.equal(await page.locator('a[href^="javascript"],img').count(),0);
  assert.equal(await page.locator('.evidence').count(),1);
  assert.equal(await page.locator('.literacy-cue').count(),1);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  const verified=structuredClone(result);Object.assign(verified.statements[0].fact_check,{publisher_verdict:'FALS',publisher_rating_verified:true,date_verified:false});
  await render('ro',verified);
  assert.ok((await page.locator('.cr-factcheck').innerText()).includes('Verdictul publicației: FALS'));
  assert.ok((await page.locator('.cr-factcheck').innerText()).includes('Data nu este disponibilă'));
  assert.ok((await page.locator('.cr-intent').textContent()).includes('Ce încurajează postarea'));
  const contextOnly=structuredClone(result);contextOnly.statements[0].fact_check.relation='related_context';
  await render('en',contextOnly);assert.ok((await page.locator('.cr-factcheck').innerText()).includes('Related fact-check · context'));
  await render('ru');
  assert.ok((await page.locator('.cr-intent').textContent()).includes('К чему побуждает публикация'));
  const precheck=structuredClone(result);precheck.overall={label:'FALSE',is_preliminary:true};precheck.statements=[];
  await render('en',precheck);
  assert.equal(await page.locator('.cr-overall').getAttribute('data-risk'),'inconclusive');
  assert.equal(await page.locator('.cr-preliminary').innerText(),'Preliminary reading');
  await page.evaluate(async()=>{
    const {renderProgress}=await import('/results.js');renderProgress(document.querySelector('#progress'),{stages:[{id:'reading',state:'done'},{id:'origin',state:'done'},{id:'sources',state:'running'},{id:'factchecks',state:'skipped'}]});
  });
  assert.equal(await page.locator('[data-stage="sources"]').getAttribute('aria-current'),'step');
  assert.equal(await page.locator('[data-stage="done"]').getAttribute('data-state'),'pending');
  assert.equal(await page.locator('[data-stage="factchecks"]').getAttribute('data-state'),'skipped');
  assert.deepEqual(errors,[]);
  console.log('PASS: shared v2 results, publisher attribution, safe links/text, language, mobile, real progress, preliminary guard');
} finally {await browser.close();}
