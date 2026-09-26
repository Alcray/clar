// Isolated browser with mocked public API. No real invitation or model call.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const origin='https://clar.test';
const files={'/':'index.html','/app.js':'app.js','/results.js':'results.js','/presentation.js':'presentation.js','/results.css':'results.css','/client.js':'client.js','/grounding.js':'grounding.js','/styles.css':'styles.css','/favicon.svg':'favicon.svg'};
const type={'html':'text/html','js':'text/javascript','css':'text/css','svg':'image/svg+xml'};

async function preview(browser,{initialAccess=false,expireOnFirstCheck=false}={}){
  const context=await browser.newContext({viewport:{width:1280,height:900}});
  let granted=initialAccess;
  let checkCount=0;
  const feedback=[];
  const assetReferers=[];
  const pageErrors=[];
  context.on('page',page=>page.on('pageerror',error=>pageErrors.push(error.message)));
  await context.route(origin+'/**',async route=>{
    const request=route.request();
    const url=new URL(request.url());
    if(files[url.pathname]){
      if(url.pathname!=='/')assetReferers.push(request.headers()['referer']||'');
      const name=files[url.pathname];
      return route.fulfill({status:200,contentType:type[name.split('.').pop()],body:fs.readFileSync(path.join(root,'public',name))});
    }
    if(url.pathname==='/api/health')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({public_access_required:true,access_granted:granted,default_provider:'vertex',vertex_configured:true,local_ready:false,configured:false})});
    if(url.pathname==='/api/access'){
      const body=request.postDataJSON();
      if(body.code!=='invite-ok')return route.fulfill({status:403,contentType:'application/json',body:'{"error":"invalid_invite"}'});
      granted=true;
      return route.fulfill({status:200,headers:{'set-cookie':'clar_access=fixture; Secure; HttpOnly; SameSite=Lax; Path=/'},contentType:'application/json',body:'{"ok":true}'});
    }
    if(url.pathname==='/api/extension-setup')return route.fulfill({status:granted?200:401,contentType:'application/json',body:granted?'{"token":"personal-pairing-code"}':'{"error":"access_required"}'});
    if(url.pathname==='/api/feedback'){
      if(!granted)return route.fulfill({status:401,contentType:'application/json',body:'{"error":"access_required"}'});
      feedback.push(request.postDataJSON());
      return route.fulfill({status:201,contentType:'application/json',body:'{"ok":true}'});
    }
    if(url.pathname==='/api/examples')return route.fulfill({contentType:'application/json',body:'[]'});
    if(url.pathname==='/api/jobs'){
      checkCount++;
      if(expireOnFirstCheck&&checkCount===1){granted=false;return route.fulfill({status:401,contentType:'application/json',body:'{"error":"access_required"}'});}
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job_id:'synthetic-job-for-share-test',status:'complete',result:{mode:'live',original_text:request.postDataJSON().text,summary:'Checked post',overview:'Fixture only.',statements:[],queries:[],search_suggestions:[]}})});
    }
    return route.fulfill({status:404,body:'Not found'});
  });
  const page=await context.newPage();
  return {context,page,feedback,assetReferers,pageErrors,get checkCount(){return checkCount;}};
}

const browser=await chromium.launch({headless:true});
try{
  const invited=await preview(browser);
  await invited.page.goto(origin+'/?invite=invite-ok#extension');
  await invited.page.locator('#extension-dialog[open]').waitFor();
  assert.equal(new URL(invited.page.url()).searchParams.has('invite'),false);
  assert.ok(invited.assetReferers.every(value=>!value.includes('invite-ok')));
  assert.equal(await invited.page.locator('#extension-token').inputValue(),'personal-pairing-code');
  assert.equal(await invited.page.locator('#download-extension').getAttribute('href'),'/clar-extension.zip');
  assert.ok((await invited.page.locator('#extension-dialog').innerText()).includes('Reload'));
  await invited.page.locator('#close-extension-dialog').click();
  assert.equal(await invited.page.locator('#feedback-card').isVisible(),true);
  await invited.page.evaluate(()=>{location.hash='#feedback';});
  await invited.page.waitForFunction(()=>document.activeElement?.id==='feedback-card');
  await invited.page.locator('#feedback-category').selectOption('media_literacy');
  await invited.page.locator('#feedback-source').selectOption('extension');
  await invited.page.locator('#feedback-post-url').fill('https://www.facebook.com/example/posts/123');
  await invited.page.locator('#feedback-message').fill('The wording explanation needs another example.');
  await invited.page.locator('#feedback-submit').click();
  await invited.page.getByText('Thanks — your feedback was saved for review.').waitFor();
  assert.deepEqual(invited.feedback,[{category:'media_literacy',source:'extension',post_url:'https://www.facebook.com/example/posts/123',message:'The wording explanation needs another example.'}]);
  await invited.page.setViewportSize({width:390,height:844});
  assert.equal(await invited.page.locator('#extension-setup-button').isVisible(),true);
  assert.equal(await invited.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await invited.page.locator('#extension-setup-button').click();
  const guide=await invited.page.locator('#extension-dialog').boundingBox();
  assert.ok(guide&&guide.x>=0&&guide.x+guide.width<=390&&guide.height<=844);
  fs.mkdirSync(path.join(root,'.runtime'),{recursive:true});
  await invited.page.screenshot({path:path.join(root,'.runtime/share-guide-mobile.png')});
  assert.deepEqual(invited.pageErrors,[]);
  await invited.context.close();

  const gated=await preview(browser,{expireOnFirstCheck:true});
  await gated.page.goto(origin+'/');
  await gated.page.locator('#invite-dialog[open]').waitFor();
  assert.equal(await gated.page.locator('#feedback-card').isVisible(),false);
  await gated.page.locator('#invite-code').fill('wrong-code');
  await gated.page.locator('#invite-submit').click();
  await gated.page.getByText('That invitation code did not work. Ask the sender for a new code.').waitFor();
  await gated.page.locator('#invite-code').fill('invite-ok');
  await gated.page.locator('#invite-submit').click();
  await gated.page.locator('#invite-dialog').waitFor({state:'hidden'});
  await gated.page.locator('#post-text').fill('A public test claim.');
  await gated.page.locator('#analyze-button').click();
  await gated.page.locator('#invite-dialog[open]').waitFor();
  assert.equal(gated.checkCount,1);
  await gated.page.locator('#invite-code').fill('invite-ok');
  await gated.page.locator('#invite-submit').click();
  await gated.page.locator('.cr-assessment-summary').filter({hasText:'Checked post'}).waitFor({state:'attached'});
  assert.equal(gated.checkCount,2);
  assert.deepEqual(gated.pageErrors,[]);
  await gated.context.close();
  console.log('PASS: invite link removal, guide and pairing, feedback payload, invalid code, 401 reentry and single safe retry');
}finally{await browser.close();}
