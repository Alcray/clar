import {BACKENDS,DEFAULT_SETTINGS,validBackend,photoUrl,postPayload} from './config.js';
import {requestAnalysis} from './client.js';
import {renderResults,renderProgress} from './results.js';
import {appendSearchSuggestions} from './grounding.js';
const $=id=>document.getElementById(id);
const state={settings:{...DEFAULT_SETTINGS},post:null,mode:'text',connected:false,connecting:null,
  controller:null,generation:0,ready:false,pendingAuto:null,dismissedSelectionId:null,edited:false,waitingExternal:false};
const send=message=>chrome.runtime.sendMessage(message);
function error(message){$('error').textContent=message||'';$('error').hidden=!message;}
function headers(){return {Authorization:'Bearer '+state.settings.token,'X-CLAR-Extension':chrome.runtime.id};}
function updateCount(){$('char-count').textContent=`${$('post-text').value.length.toLocaleString()} / 6,000`;}
function settingsForm(){
  $('backend').replaceChildren(...BACKENDS.map(backend=>{const option=document.createElement('option');option.value=backend;option.textContent=backend;return option;}));
  for(const id of ['backend','provider','language'])$(id).value=state.settings[id];
  $('pair-token').value=state.settings.token;$('pair-link').href=state.settings.backend+'/#extension';
  $('feedback-link').href=state.settings.backend+'/#feedback';
  $('auto-scan').checked=state.settings.autoScan===true;$('show-highlights').checked=state.settings.showHighlights!==false;
  $('privacy').textContent='The selected post is sent to your CLAR server. Auto-scan, when enabled, also sends visible post text for a preliminary reading. Results are cached on this device for 24 hours; image files are not cached. Server jobs stay in memory for up to 30 minutes to support Retry. '+(state.settings.provider==='local'?'The server’s configured model processes the analysis.':'Google processes the analysis.');
}
async function connect(){
  if(state.connecting)return state.connecting;
  state.connected=false;
  if(!state.settings.token){$('connection').textContent='Pair your extension to start';$('settings').hidden=false;return false;}
  const identity=()=>JSON.stringify([state.settings.backend,state.settings.provider,state.settings.token]);
  const fingerprint=identity();
  $('connection').textContent='Connecting…';
  state.connecting=(async()=>{
    try{
      const response=await fetch(state.settings.backend+'/api/health',{headers:headers(),credentials:'omit',redirect:'error',signal:AbortSignal.timeout(15000)});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Pairing failed.');
      if(fingerprint!==identity())return false;
      if(state.settings.provider==='vertex'&&!data.vertex_configured)throw new Error('Vertex AI is not configured on this server.');
      if(state.settings.provider==='gemini'&&!data.configured)throw new Error('The Gemini API is not configured on this server.');
      if(state.settings.provider==='local'&&!data.local_ready)throw new Error('The local model is not ready on this server.');
      state.connected=true;$('connection').textContent={vertex:'Connected · Gemini via Vertex AI',gemini:'Connected · Gemini API',local:'Connected · Local model'}[state.settings.provider];return true;
    }catch(e){$('connection').textContent='Connection unavailable';error(e.name==='TimeoutError'?'Could not reach CLAR. Cached checks remain available.':e.message);return false;}
    finally{state.connecting=null;}
  })();return state.connecting;
}
function stop(){state.generation++;state.pendingAuto=null;state.waitingExternal=false;state.controller?.abort();state.controller=null;$('loading').hidden=true;$('analyze-button').disabled=false;$('analyze-button').textContent='Check this post';}
function cancelPendingCheck(){state.pendingAuto=null;if(state.post?.autoCheck&&state.post.selectionId)void send({type:'CLAR_CLAIM_AUTO_CHECK',selectionId:state.post.selectionId}).catch(()=>{});}
function setMode(mode){state.mode=mode;$('post-text').hidden=mode!=='text';$('image-wrap').hidden=mode!=='image';$('text-mode').setAttribute('aria-pressed',String(mode==='text'));$('image-mode').setAttribute('aria-pressed',String(mode==='image'));$('results').hidden=true;}
function select(post){
  stop();state.post=post;state.edited=false;error('');$('panel-retry-button').hidden=true;
  $('empty').hidden=true;$('composer').hidden=false;$('results').hidden=true;
  $('post-text').value=post.text||'';$('post-date').value='';$('date-hint').textContent=post.visibleDate?`Shown on Facebook: ${post.visibleDate}`:'';
  $('truncated').hidden=!post.truncated;$('post-link').hidden=!post.url;if(post.url)$('post-link').href=post.url;
  $('mode-tabs').hidden=!post.imageUrl||!post.text;
  if(post.imageUrl)$('post-image').src=post.imageUrl;else $('post-image').removeAttribute('src');
  setMode(post.imageUrl&&!post.text?'image':'text');updateCount();
}
function payloadForCurrent(){
  const post={...(state.post||{}),text:$('post-text').value.trim()};
  if(state.edited){post.origin=null;post.url=null;}
  const payload=postPayload(post,state.settings,$('post-date').value);
  if(state.mode==='image'){payload.text='';payload.image_url=state.post?.imageUrl;}
  return payload;
}
async function cacheCount(){const info=await send({type:'CLAR_CACHE_INFO'}).catch(()=>null);if(info?.ok)$('cache-status').textContent=`${info.entries} saved check${info.entries===1?'':'s'} · expires after 24 hours`;}
function showResult(result,payload){
  state.waitingExternal=false;error('');
  $('loading').hidden=true;$('analyze-button').disabled=false;$('analyze-button').textContent='Check this post';
  renderResults($('results'),result,{language:state.settings.language,onReanalyze:()=>analyze({force:true})});
  appendSearchSuggestions($('results'),result.search_suggestions);$('results').hidden=false;
  $('panel-retry-button').hidden=true;$('results').scrollIntoView({block:'start'});
  if(state.post?.selectionId)void send({type:'CLAR_FULL_RESULT',selectionId:state.post.selectionId,payload,result});
  void cacheCount();
}
async function restoreOrRun(post){
  if(!state.ready)return;
  const generation=state.generation,payload=payloadForCurrent();
  const cached=await send({type:'CLAR_CACHE_GET',payload}).catch(()=>null);
  if(generation!==state.generation)return;
  if(cached?.hit){showResult(cached.result,payload);cancelPendingCheck();return;}
  if(post.externalCheck){
    const {selection}=await chrome.storage.session.get('selection');
    if(generation!==state.generation||selection?.selectionId!==post.selectionId)return;
    if(selection.externalStatus==='failed'){externalError(selection.externalError);return;}
    if(selection.externalStatus==='complete'){
      // Completion may land between the first cache read and this selection
      // read, before waitingExternal is set and storage notifications are used.
      const completed=await send({type:'CLAR_CACHE_GET',payload}).catch(()=>null);
      if(generation!==state.generation||state.post?.selectionId!==post.selectionId)return;
      if(completed?.hit){showResult(completed.result,payload);cancelPendingCheck();}
      // A cleared/expired entry remains available for an explicit fresh check.
      return;
    }
    state.waitingExternal=true;$('loading').hidden=false;$('analyze-button').disabled=true;
    renderProgress($('panel-progress'),{stages:[]},{language:state.settings.language});
    void restoreCompletedElsewhere();
    const resumed=await send({type:'CLAR_RESUME_SELECTION',selectionId:post.selectionId}).catch(()=>null);
    if(generation===state.generation&&state.waitingExternal&&!resumed?.ok)externalError(resumed?.error||'Could not resume the check. Please retry.');
    return;
  }
  if(post.autoCheck===true&&!post.autoCheckClaimed){state.pendingAuto=post.selectionId;void runPendingCheck();}
  else if(post.autoCheckClaimed){state.waitingExternal=true;void restoreCompletedElsewhere();}
}
async function restoreCompletedElsewhere(){
  // Another window's panel may own the single automatic check. Its completed
  // cache entry should populate this view without starting another request.
  if(!state.ready||!state.waitingExternal||state.controller||!state.post||!$('results').hidden)return;
  const generation=state.generation,payload=payloadForCurrent();
  const cached=await send({type:'CLAR_CACHE_GET',payload}).catch(()=>null);
  if(generation===state.generation&&state.waitingExternal&&!state.controller&&cached?.hit&&$('results').hidden){showResult(cached.result,payload);cancelPendingCheck();}
}
function receiveSelection(post){
  if(post.selectionId&&(post.selectionId===state.dismissedSelectionId||post.selectionId===state.post?.selectionId))return;
  select(post);void restoreOrRun(post);
}
function externalError(message){
  state.waitingExternal=false;$('loading').hidden=true;$('analyze-button').disabled=false;
  error(message||'The check could not finish.');$('panel-retry-button').hidden=false;
}
async function runPendingCheck(){
  if(!state.ready||!state.settings.token||!state.pendingAuto)return;
  const selectionId=state.pendingAuto,generation=state.generation;state.pendingAuto=null;
  try{
    const result=await send({type:'CLAR_CLAIM_AUTO_CHECK',selectionId});
    if(generation!==state.generation||state.post?.selectionId!==selectionId)return;
    if(!result?.ok)throw new Error('The automatic check could not start. Press Check this post to retry.');
    if(result.claimed)void analyze();
    else{state.waitingExternal=true;void restoreCompletedElsewhere();}
  }catch(e){if(generation===state.generation)error(e.message);}
}
async function photoData(url,signal){if(!photoUrl(url))throw new Error('The photo URL is not a supported Facebook image.');const response=await fetch(url,{credentials:'omit',redirect:'error',signal});if(!response.ok)throw new Error('The photo could not be downloaded. Check the post text instead.');const type=(response.headers.get('content-type')||'').split(';')[0];if(!['image/png','image/jpeg','image/webp'].includes(type))throw new Error('Use a JPEG, PNG, or WebP photo.');if(Number(response.headers.get('content-length'))>5*1024*1024)throw new Error('This photo is larger than 5 MB.');const reader=response.body.getReader(),chunks=[];let length=0;while(true){const {value,done}=await reader.read();if(done)break;length+=value.length;if(length>5*1024*1024){await reader.cancel();throw new Error('This photo is larger than 5 MB.');}chunks.push(value);}const blob=new Blob(chunks,{type});return new Promise((resolve,reject)=>{const file=new FileReader();file.onerror=()=>reject(new Error('The photo could not be read.'));file.onload=()=>resolve({mime_type:type,data:String(file.result).split(',')[1]});file.readAsDataURL(blob);});}
async function analyze({force=false,resume=false}={}){
  stop();const generation=state.generation;error('');$('panel-retry-button').hidden=true;
  const payload=payloadForCurrent();
  if(state.mode==='text'&&!payload.text){error('Select or paste a post first.');return;}
  if(state.mode==='image'&&!photoUrl(payload.image_url)){error('No supported photo was selected.');return;}
  const cached=await send({type:'CLAR_CACHE_GET',payload}).catch(()=>null);
  if(generation!==state.generation)return;
  if(!force&&!resume&&cached?.hit){showResult(cached.result,payload);return;}
  if(!state.connected){await connect();if(generation!==state.generation||!state.connected)return;}
  const controller=new AbortController();state.controller=controller;
  $('analyze-button').disabled=true;$('analyze-button').textContent='Checking…';$('loading').hidden=false;$('results').hidden=true;
  renderProgress($('panel-progress'),{stages:[]},{language:state.settings.language});$('loading').scrollIntoView({block:'start'});
  try{
    if(state.mode==='image')payload.image=await photoData(payload.image_url,controller.signal);
    if(generation!==state.generation)return;
    const result=await requestAnalysis({backend:state.settings.backend,payload,force,headers:headers(),signal:controller.signal,
      onProgress:progress=>{if(generation===state.generation)renderProgress($('panel-progress'),progress,{language:state.settings.language});}});
    if(generation!==state.generation)return;
    await send({type:'CLAR_CACHE_PUT',payload,result,epoch:cached?.epoch});
    if(generation===state.generation)showResult(result,payload);
  }catch(e){if(generation===state.generation){error(e.name==='AbortError'?'Check stopped.':e.message||'Could not reach CLAR.');$('panel-retry-button').hidden=e.name==='AbortError';}}
  finally{if(generation===state.generation){state.controller=null;$('loading').hidden=true;$('analyze-button').disabled=false;$('analyze-button').textContent='Check this post';}}
}
function clearPost(){state.dismissedSelectionId=state.post?.selectionId||state.dismissedSelectionId;stop();state.post=null;state.edited=false;$('composer').hidden=true;$('results').hidden=true;$('empty').hidden=false;$('post-text').value='';$('post-image').removeAttribute('src');error('');}
$('settings-toggle').addEventListener('click',()=>{$('settings').hidden=!$('settings').hidden;void cacheCount();});
$('backend').addEventListener('change',()=>{if(validBackend($('backend').value))$('pair-link').href=$('backend').value+'/#extension';});
$('settings-form').addEventListener('submit',async event=>{
  event.preventDefault();const backend=$('backend').value,token=$('pair-token').value.trim();
  if(!validBackend(backend)||token.length<16){error('Choose a server and paste its pairing code.');return;}
  const pending=state.pendingAuto;stop();state.pendingAuto=pending;$('results').hidden=true;
  state.settings={backend,token,provider:$('provider').value,language:$('language').value,autoScan:$('auto-scan').checked,showHighlights:$('show-highlights').checked};
  await chrome.storage.local.set({settings:state.settings});settingsForm();error('');state.connected=false;
  await connect();if(!state.connected)await connect();if(state.connected){$('settings').hidden=true;void runPendingCheck();}
});
for(const [id,key] of [['auto-scan','autoScan'],['show-highlights','showHighlights']])$(id).addEventListener('change',async()=>{
  if(key==='autoScan'&&$(id).checked&&!state.settings.token){$(id).checked=false;error('Pair CLAR before enabling automatic scans.');return;}
  state.settings[key]=$(id).checked;await chrome.storage.local.set({settings:state.settings});
});
$('clear-cache').addEventListener('click',async()=>{cancelPendingCheck();stop();await send({type:'CLAR_CACHE_CLEAR'});$('results').hidden=true;await cacheCount();});
$('analyze-button').addEventListener('click',()=>{cancelPendingCheck();void analyze();});
$('panel-retry-button').addEventListener('click',()=>analyze({resume:true}));
$('stop-button').addEventListener('click',()=>{if(state.post?.externalCheck)void send({type:'CLAR_CANCEL_SELECTION',selectionId:state.post.selectionId});cancelPendingCheck();stop();});
$('post-text').addEventListener('input',()=>{cancelPendingCheck();stop();state.edited=true;updateCount();$('results').hidden=true;});
$('post-date').addEventListener('change',()=>{cancelPendingCheck();stop();$('results').hidden=true;});
for(const mode of ['text','image'])$(mode+'-mode').addEventListener('click',()=>{cancelPendingCheck();stop();setMode(mode);});
$('paste-button').addEventListener('click',()=>{cancelPendingCheck();select({text:'',url:null,imageUrl:null,truncated:false});});
$('clear-button').addEventListener('click',async()=>{const selectionId=state.post?.selectionId;clearPost();await send({type:'CLAR_CLEAR_SELECTION',selectionId}).catch(()=>{});});
chrome.storage.onChanged.addListener((changes,area)=>{
  if(area==='local'&&changes.clarResultCacheV4)void restoreCompletedElsewhere();
  if(area==='session'&&changes.selection){if(changes.selection.newValue)receiveSelection(changes.selection.newValue);else if(changes.selection.oldValue?.selectionId===state.post?.selectionId)clearPost();}
  if(area==='session'&&changes.selectionError?.newValue)error(changes.selectionError.newValue);
  if(area==='session'&&changes.scanPause?.newValue)error(changes.scanPause.newValue);
});
chrome.runtime.onMessage.addListener((message,sender)=>{
  if(sender.id!==chrome.runtime.id||!state.post?.externalCheck||message.selectionId!==state.post.selectionId||!state.waitingExternal)return;
  if(message.type==='CLAR_PANEL_PROGRESS'){
    $('loading').querySelector('h2').textContent=message.progress?.queued?'Queued for analysis':'Checking the evidence';
    renderProgress($('panel-progress'),message.progress,{language:state.settings.language});
  }
  if(message.type==='CLAR_PANEL_RESULT')showResult(message.result,payloadForCurrent());
  if(message.type==='CLAR_PANEL_ERROR'){
    externalError(message.error);
  }
});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();cancelPendingCheck();stop();void send({type:'CLAR_CLOSE_PANEL'});}});
window.addEventListener('pagehide',stop);
const saved=await chrome.storage.local.get('settings');if(saved.settings&&validBackend(saved.settings.backend))state.settings={...DEFAULT_SETTINGS,...saved.settings};
settingsForm();const initial=await chrome.storage.session.get(['selection','selectionError']);state.ready=true;
if(initial.selection&&!state.post)receiveSelection(initial.selection);else if(state.post)void restoreOrRun(state.post);
if(initial.selectionError)error(initial.selectionError);void connect();void cacheCount();
