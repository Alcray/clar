import {renderResults,renderProgress} from './results.js';
import {requestAnalysis} from './client.js';
import {appendSearchSuggestions} from './grounding.js';
'use strict';
const $ = (id) => document.getElementById(id);
const state = { mode: 'text', image: null, key: '', configured: false, vertexConfigured: false, localReady: false, provider: 'local', localLocation: 'your computer', healthInitialized: false, busy: false, result: null };
const access = {required:false, granted:true, waiters:[], ready:null};
const arrival = new URL(window.location.href);
let inviteFromLink = arrival.searchParams.get('invite');
if (arrival.searchParams.has('invite')) {
  arrival.searchParams.delete('invite');
  history.replaceState(history.state, '', arrival.pathname + arrival.search + arrival.hash);
}
const SAMPLE = 'Republica Moldova și-a declarat independența pe 27 august 1991. Parlamentul are 150 de deputați. Mi se pare că politicienii ar trebui să fie mai transparenți.';
const DEMO = {
  mode: 'example', original_text: SAMPLE, summary: 'Two factual claims. One personal opinion.',
  overview: 'The independence date is supported. The number of MPs is contradicted by the Constitution. The final sentence expresses a preference.',
  statements: [
    { id: 'C1', text: 'Republica Moldova și-a declarat independența pe 27 august 1991.', kind: 'factual', verdict: 'supported', explanation: 'The Republic of Moldova declared its independence on 27 August 1991. The date in this statement matches the official historical record.', evidence: [{title:'Ministry of Foreign Affairs · History',url:'https://ue.mfa.gov.md/en/content/history-0',finding:'The official history places the declaration of independence on 27 August 1991.',label:'Prepared example · source summary'}]},
    { id: 'C2', text: 'Parlamentul are 150 de deputați.', kind: 'factual', verdict: 'contradicted', explanation: 'Article 60(2) of the Constitution specifies 101 members of Parliament. The post says 150.', evidence: [{title:'Constitution of the Republic of Moldova · Article 60',url:'https://presedinte.md/app/webroot/Constitutia_RM/Constitutia_RM_EN.pdf',finding:'Article 60(2) establishes a Parliament with 101 members.',label:'Prepared example · source summary'}]},
    { id: 'C3', text: 'Mi se pare că politicienii ar trebui să fie mai transparenți.', kind: 'opinion', verdict: 'not_applicable', explanation: 'This expresses the author’s preference for greater transparency. It makes no specific factual allegation to verify.', evidence: [] }
  ], queries: [], search_suggestions: [],
  media_literacy: {
    status: 'available',
    purpose: {category:'mixed',explanation:'The post combines historical and institutional claims with a preference for greater political transparency.',quote:'Mi se pare că politicienii ar trebui să fie mai transparenți.'},
    desired_response: {description:'Consider greater transparency a desirable standard for politicians.',quote:'politicienii ar trebui să fie mai transparenți'},
    signals: [],
    reading_tip:'Assess the factual claims separately from the preference. Agreement with a value does not make the number of MPs correct.',
    limitations:'This short excerpt does not show the author’s wider argument or any proposed action.'
  }
};
const LABELS = {supported:'Supported',contradicted:'Contradicted',conflicting:'Conflicting evidence',insufficient:'Unresolved',opinion:'Opinion',prediction:'Prediction',unclear:'Needs context'};
function el(tag, cls, text) {const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function safeLink(url){try{const u=new URL(url);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;}}
function feedbackLinkIsValid(url){
  if(!url)return true;
  try{const parsed=new URL(url);return parsed.protocol==='https:'&&['facebook.com','www.facebook.com','m.facebook.com'].includes(parsed.hostname)&&!parsed.username&&!parsed.password&&(!parsed.port||parsed.port==='443');}
  catch{return false;}
}
function keyOf(s){return s.kind==='factual'?s.verdict:s.kind;}
function colorOf(s){const k=keyOf(s);return k==='opinion'?'opinion-label':k;}
function showError(message){$('input-error').textContent=message;$('input-error').hidden=!message;}
function showInviteError(message){$('invite-error').textContent=message;$('invite-error').hidden=!message;}
function showInviteDialog(message=''){
  showInviteError(message);
  if(!$('invite-dialog').open)$('invite-dialog').showModal();
  $('invite-code').focus();
}
function releaseAccessWaiters(){for(const done of access.waiters.splice(0))done();}
function applyHealth(data){
  access.required=data.public_access_required===true;
  access.granted=!access.required||data.access_granted===true;
  state.configured=data.configured;
  state.vertexConfigured=data.vertex_configured;
  state.localReady=data.local_ready;
  state.localLocation=data.local_location||'your computer';
  if(!state.healthInitialized&&data.default_provider){state.provider=data.default_provider;state.healthInitialized=true;}
  updateConnection();
  $('feedback-card').hidden=!(access.required&&access.granted);
  if(access.required&&!access.granted){$('connection-label').textContent='Invitation needed';showInviteDialog();}
  else{if($('invite-dialog').open)$('invite-dialog').close();releaseAccessWaiters();}
}
async function refreshHealth(){
  const response=await fetch('/api/health',{credentials:'same-origin',cache:'no-store'});
  if(!response.ok)throw new Error('The CLAR server is unavailable. Refresh this page in a moment.');
  const data=await response.json();
  applyHealth(data);
  return data;
}
async function redeemInvite(code){
  const response=await fetch('/api/access',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});
  if(!response.ok)throw new Error('That invitation code did not work. Ask the sender for a new code.');
  const health=await refreshHealth();
  if(health.public_access_required&&!health.access_granted)throw new Error('Your invitation could not be confirmed. Please try again.');
}
async function requireAccess(){
  if(access.ready)await access.ready;
  if(!access.required||access.granted)return;
  showInviteDialog();
  await new Promise(resolve=>access.waiters.push(resolve));
}
function isAccessRequired(response,data){return response.status===401&&(data?.error==='access_required'||data?.code==='access_required');}
async function accessFetch(path,options){
  await requireAccess();
  for(let attempt=0;attempt<2;attempt++){
    const response=await fetch(path,{credentials:'same-origin',...options});
    if(attempt===0&&response.status===401){
      const data=await response.clone().json().catch(()=>null);
      if(isAccessRequired(response,data)){
        access.required=true;access.granted=false;
        await requireAccess();
        continue;
      }
    }
    return response;
  }
  throw new Error('Your invitation could not be confirmed. Please try again.');
}
function updateCount(){$('char-count').textContent=`${$('post-text').value.length.toLocaleString()} / 6,000`;}
function setMode(mode){if(state.busy)return;state.mode=mode;for(const m of ['text','image']){const active=m===mode;$(m+'-tab').setAttribute('aria-selected',String(active));$(m+'-tab').tabIndex=active?0:-1;$(m+'-panel').hidden=!active;}showError('');}
function resetOutput(){state.result=null;$('results').hidden=true;$('empty-state').hidden=false;$('result-meta').textContent='Evidence over assumptions';}
function updateConnection(){
  const local=state.provider==='local', vertex=state.provider==='vertex';
  $('provider').value=state.provider;
  $('connection-label').textContent=local?(state.localReady?'Local model ready':'Local model connecting…'):vertex?(state.vertexConfigured?'Vertex AI connected':'Vertex AI unavailable'):(state.configured||state.key?'Gemini connected':'API key needed');
  $('connect-button').hidden=local||vertex;
  $('connect-button').textContent=state.configured?'Connection details':state.key?'Change API key ↗':'Connect Gemini ↗';
  $('privacy-note').textContent=local?`Your post is processed on ${state.localLocation}. The local preview checks a small collection of official Moldovan sources. Checks are held in server memory for up to 30 minutes so Retry can resume them; screenshots are not saved to disk.`:vertex?'Your post is sent to Gemini through Vertex AI and checked with Google Search. Checks are held in server memory for up to 30 minutes so Retry can resume them; screenshots are not saved to disk.':'Your post is sent to Gemini and checked with Google Search. Checks are held in server memory for up to 30 minutes so Retry can resume them; screenshots are not saved to disk.';
}
function setBusy(busy){state.busy=busy;$('analyze-button').disabled=busy;$('example-button').disabled=busy;$('empty-example').disabled=busy;$('post-text').disabled=busy;$('image-input').disabled=busy;$('remove-image').disabled=busy;$('text-tab').disabled=busy;$('image-tab').disabled=busy;$('language').disabled=busy;$('provider').disabled=busy;$('post-date').disabled=busy;$('loading-state').hidden=!busy;document.querySelector('.results-panel').setAttribute('aria-busy',String(busy));$('analyze-button').querySelector('span').textContent=busy?'Checking the post…':'Check this post';if(busy){$('empty-state').hidden=true;$('results').hidden=true;$('result-meta').textContent='Checking sources';}}
function renderResult(data){
  state.result=data;
  const root=$('results');
  renderResults(root,data,{language:$('language').value,onReanalyze:()=>checkPost({force:true})});
  if(data.mode==='example')root.prepend(el('div','example-banner','Prepared example · interface illustration, not a live check.'));
  if(data.example_input)root.prepend(el('div','example-banner','Constructed evaluation input · this analysis was run live.'));
  if(data.notice)root.prepend(el('div','local-banner',data.notice));
  appendSearchSuggestions(root,data.search_suggestions);
  $('empty-state').hidden=true;$('loading-state').hidden=true;$('retry-button').hidden=true;
  $('result-meta').textContent=data.mode==='example'?'Example analysis':`${new Date(data.checked_at||Date.now()).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})} · ${data.analysis_seconds?data.analysis_seconds+'s':'checked'}`;
}
function clearExample(){state.exampleOrigin=null;state.exampleId=null;$('example-input-note').hidden=true;}
function demo(){if(state.busy)return;clearExample();$('post-date').value='';setMode('text');$('post-text').value=SAMPLE;updateCount();showError('');renderResult(DEMO);}
async function readImage(file){if(state.busy||!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)){showError('Choose a PNG, JPG or WebP screenshot.');return;}if(file.size>5*1024*1024){showError('Please choose a screenshot smaller than 5 MB.');return;}const reader=new FileReader();reader.onload=()=>{if(state.busy)return;clearExample();state.image={mime_type:file.type,data:String(reader.result).split(',')[1]};$('image-preview').src=reader.result;$('image-name').textContent=file.name;$('image-preview-wrap').hidden=false;$('upload-area').hidden=true;showError('');resetOutput();};reader.readAsDataURL(file);}
async function checkPost({force=false}={}){
  if(state.busy)return;
  showError('');$('retry-button').hidden=true;
  const text=$('post-text').value.trim();
  if(state.mode==='text'&&!text){showError('Paste a Facebook post first.');return;}
  if(state.mode==='image'&&!state.image){showError('Choose a screenshot first.');return;}
  if(access.ready)await access.ready;
  if(state.provider==='gemini'&&!state.configured&&!state.key){$('connection-dialog').showModal();return;}
  if(state.provider==='vertex'&&!state.vertexConfigured){showError('Vertex AI is not configured on the server yet.');return;}
  if(state.provider==='local'&&!state.localReady){showError('The local model is still connecting. Refresh in a moment.');return;}
  const payload={provider:state.provider,text:state.mode==='text'?text:'',image:state.mode==='image'?state.image:null,
    post_date:$('post-date').value,language:$('language').value,api_key:state.provider==='gemini'?state.key:'',origin:state.mode==='text'?state.exampleOrigin||null:null,example_id:state.mode==='text'?state.exampleId||null:null};
  setBusy(true);renderProgress($('job-progress'),{stages:[]},{language:payload.language});
  const controller=new AbortController();state.controller=controller;
  try{
    await requireAccess();
    const data=await requestAnalysis({payload,force,signal:controller.signal,fetcher:accessFetch,
      onProgress:progress=>renderProgress($('job-progress'),progress,{language:payload.language})});
    renderResult(data);
  }catch(error){
    showError(error.name==='AbortError'?'Check stopped.':error.message);
    if(state.result)renderResult(state.result);else resetOutput();
    $('retry-button').hidden=error.name==='AbortError';
  }finally{state.controller=null;setBusy(false);}
}
$('post-form').addEventListener('submit',event=>{event.preventDefault();void checkPost();});
$('retry-button').addEventListener('click',()=>checkPost());
$('post-date').addEventListener('change',()=>{clearExample();resetOutput();});
$('web-stop-button').addEventListener('click',()=>state.controller?.abort());
$('post-text').addEventListener('input',()=>{clearExample();updateCount();resetOutput();});$('text-tab').addEventListener('click',()=>setMode('text'));$('image-tab').addEventListener('click',()=>setMode('image'));for(const id of ['text-tab','image-tab'])$(id).addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const next=state.mode==='text'?'image':'text';setMode(next);$(next+'-tab').focus();}});
$('example-button').addEventListener('click',demo);$('empty-example').addEventListener('click',demo);$('image-input').addEventListener('change',e=>readImage(e.target.files[0]));$('remove-image').addEventListener('click',()=>{state.image=null;$('image-input').value='';$('image-preview').removeAttribute('src');$('image-preview-wrap').hidden=true;$('upload-area').hidden=false;resetOutput();});const drop=$('upload-area');drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('dragover');});drop.addEventListener('dragleave',()=>drop.classList.remove('dragover'));drop.addEventListener('drop',e=>{e.preventDefault();if(state.busy)return;drop.classList.remove('dragover');if(e.dataTransfer.files.length!==1){showError('Upload one screenshot at a time.');return;}readImage(e.dataTransfer.files[0]);});
$('connect-button').addEventListener('click',()=>{if(state.configured){alert('A Gemini API key is configured on the server.');return;}$('connection-dialog').showModal();});$('close-dialog').addEventListener('click',()=>$('connection-dialog').close());$('key-form').addEventListener('submit',e=>{e.preventDefault();const key=$('api-key').value.trim();if(!key){$('api-key').focus();return;}state.key=key;state.provider='gemini';$('api-key').value='';$('connection-dialog').close();updateConnection();showError('');});
const inviteForm=$('invite-form');
$('invite-dialog').addEventListener('cancel',event=>{if(access.required&&!access.granted)event.preventDefault();});
inviteForm.addEventListener('submit',async(event)=>{
  event.preventDefault();
  const code=$('invite-code').value.trim();
  if(!code)return;
  $('invite-code').value='';
  $('invite-submit').disabled=true;showInviteError('');
  try{await redeemInvite(code);}
  catch(error){showInviteDialog(error.message);}
  finally{$('invite-submit').disabled=false;}
});
access.ready=(async()=>{
  let inviteError='';
  if(inviteFromLink){try{await redeemInvite(inviteFromLink);}catch(error){inviteError=error.message;}}
  inviteFromLink=null;
  try{await refreshHealth();}
  catch(error){showError(error.message);return;}
  if(inviteError&&access.required&&!access.granted)showInviteDialog(inviteError);
})();

$('provider').addEventListener('change',()=>{state.provider=$('provider').value;updateConnection();showError('');resetOutput();});

async function openExtensionSetup(){
  await requireAccess();
  $('backend-guide-label').textContent=access.required?'Shared CLAR preview':location.hostname==='localhost'?'Localhost (hostname)':location.hostname==='127.0.0.1'?'Localhost tunnel':'Private Tailscale server';
  $('extension-dialog').showModal();$('extension-setup-error').hidden=true;$('extension-token').value='';
  try{const response=await accessFetch('/api/extension-setup');const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not get the pairing code.');$('extension-token').value=data.token;}
  catch(e){$('extension-setup-error').textContent=e.message;$('extension-setup-error').hidden=false;}
}
$('extension-setup-button').addEventListener('click',openExtensionSetup);
$('heading-extension-button').addEventListener('click',openExtensionSetup);
$('review-extension').addEventListener('click',openExtensionSetup);
$('review-example').addEventListener('click',()=>{demo();$('results-heading').scrollIntoView({behavior:'smooth',block:'start'});});
$('review-post').addEventListener('click',()=>{$('post-text').focus();$('post-heading').scrollIntoView({behavior:'smooth',block:'start'});});
$('feedback-form').addEventListener('submit',async(event)=>{
  event.preventDefault();
  $('feedback-error').hidden=true;
  $('feedback-status').textContent='';
  const payload={category:$('feedback-category').value,source:$('feedback-source').value,
    post_url:$('feedback-post-url').value.trim(),message:$('feedback-message').value.trim()};
  if(payload.message.length<10){$('feedback-error').textContent='Please add a little more detail so we can act on the feedback.';$('feedback-error').hidden=false;return;}
  if(!feedbackLinkIsValid(payload.post_url)){$('feedback-error').textContent='Use a Facebook post link beginning with https://, or leave the link blank.';$('feedback-error').hidden=false;return;}
  $('feedback-submit').disabled=true;
  $('feedback-submit').textContent='Sending…';
  try{
    const response=await accessFetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||'Your feedback could not be sent. Please try again.');
    $('feedback-form').reset();
    $('feedback-status').textContent='Thanks — your feedback was saved for review.';
  }catch(error){$('feedback-error').textContent=error.message;$('feedback-error').hidden=false;}
  finally{$('feedback-submit').disabled=false;$('feedback-submit').textContent='Send feedback';}
});
$('close-extension-dialog').addEventListener('click',()=>$('extension-dialog').close());
$('copy-chrome-address').addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText('chrome://extensions');$('copy-chrome-address').textContent='Copied';setTimeout(()=>$('copy-chrome-address').textContent='Copy Chrome address',2000);}
  catch{$('copy-chrome-address').textContent='Type chrome://extensions in Chrome';}
});
$('copy-extension-token').addEventListener('click',async()=>{if(!$('extension-token').value)return;try{await navigator.clipboard.writeText($('extension-token').value);$('copy-extension-token').textContent='Copied';setTimeout(()=>$('copy-extension-token').textContent='Copy pairing code',2000);}catch{$('extension-token').select();$('extension-setup-error').textContent='Select the pairing code and copy it with your keyboard.';$('extension-setup-error').hidden=false;}});
async function routeHash(){
  if(location.hash==='#extension'){await openExtensionSetup();return;}
  if(location.hash==='#feedback'){
    await requireAccess();
    if(!$('feedback-card').hidden){
      $('feedback-card').scrollIntoView({behavior:'smooth',block:'start'});
      $('feedback-card').focus({preventScroll:true});
    }
  }
}
if(location.hash==='#extension'||location.hash==='#feedback')void routeHash();
window.addEventListener('hashchange',()=>{void routeHash();});

let evaluationExamples=[];
fetch('/api/examples').then(r=>r.ok?r.json():[]).then(items=>{
  evaluationExamples=Array.isArray(items)?items:[];
  for(const item of evaluationExamples){const option=document.createElement('option');option.value=item.id;option.textContent=item.title;$('evaluation-example').append(option);}
}).catch(()=>{});
$('load-evaluation').addEventListener('click',()=>{
  const item=evaluationExamples.find(x=>x.id===$('evaluation-example').value);if(!item||state.busy)return;
  setMode('text');$('post-text').value=item.text;$('post-date').value=item.post_date||'';$('language').value=item.language||'en';
  state.exampleOrigin=item.origin||null;state.exampleId=item.id;updateCount();resetOutput();
  $('example-input-note').hidden=false;$('post-text').focus();
});
