import {sanitizePost,DEFAULT_SETTINGS,validBackend,postPayload,photoUrl} from './config.js';
import {getCached,putCached,clearCached,cacheInfo,cacheKey} from './cache.js';
import {requestAnalysis} from './client.js';

chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'}).catch(()=>{});
chrome.storage.session.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'}).catch(()=>{});
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(()=>{});

function isFacebookSender(sender) {
  try {return sender.id===chrome.runtime.id&&Number.isInteger(sender.tab?.id)&&sender.frameId===0&&new URL(sender.url).origin==='https://www.facebook.com';}catch{return false;}
}
function isFacebookTab(tab) {try{return Number.isInteger(tab?.id)&&new URL(tab.url).origin==='https://www.facebook.com';}catch{return false;}}
function isPanelSender(sender) {
  try{return sender.id===chrome.runtime.id&&new URL(sender.url).href===chrome.runtime.getURL('panel.html');}catch{return false;}
}
async function settings(){const {settings:saved}=await chrome.storage.local.get('settings');return {...DEFAULT_SETTINGS,...(saved&&validBackend(saved.backend)?saved:{})};}
let scanPaused='',scanActive=0;
const scanQueue=[],scanControllers=new Map();
const fullChecks=new Map();
const fullQueue=[],queuedFullChecks=new Map();
const MAX_WAITING_FULL=8;
let feedbackWrites=Promise.resolve();
async function publicSettings(){const value=await settings();return {autoScan:value.autoScan===true&&!scanPaused,language:value.language,showHighlights:value.showHighlights!==false,pauseReason:scanPaused};}
async function broadcast(message){
  const tabs=await chrome.tabs.query({url:'https://www.facebook.com/*'});
  await Promise.allSettled(tabs.map(tab=>chrome.tabs.sendMessage(tab.id,message)));
}
function cancelScans(tabId){
  for(let i=scanQueue.length-1;i>=0;i--){if(tabId==null||scanQueue[i].tabId===tabId){scanQueue.splice(i,1)[0].resolve({ok:false,error:'Automatic scanning stopped.',code:'scan_disabled'});}}
  for(const [controller,id] of scanControllers){if(tabId==null||id===tabId)controller.abort();}
}
async function pumpScans(){
  while(scanActive<2&&scanQueue.length){
    const entry=scanQueue.shift();scanActive++;
    (async()=>{
      const controller=new AbortController();scanControllers.set(controller,entry.tabId);
      try{
        const prefs=await settings();
        if(!prefs.autoScan||scanPaused)throw new Error('Automatic scanning is paused.');
        if(!prefs.token)throw new Error('Pair CLAR before enabling automatic scans.');
        const payload=postPayload(entry.post,prefs);
        const full=await getCached(payload,prefs,'analyze');
        if(full.hit){entry.resolve({ok:true,result:full.result,cached:true});return;}
        const cached=await getCached(payload,prefs,'precheck');
        if(cached.hit){entry.resolve({ok:true,result:cached.result,cached:true});return;}
        const result=await requestAnalysis({backend:prefs.backend,payload,task:'precheck',signal:controller.signal,
          headers:{Authorization:'Bearer '+prefs.token,'X-CLAR-Extension':chrome.runtime.id}});
        if(controller.signal.aborted)throw new DOMException('Stopped','AbortError');
        await putCached(payload,prefs,result,'precheck',cached.epoch);
        entry.resolve({ok:true,result});
      }catch(error){
        if(['daily_limit_reached','api_quota','queue_full'].includes(error.code)){
          scanPaused=error.message;cancelScans();
          await chrome.storage.session.set({scanPause:scanPaused});
          await broadcast({type:'CLAR_SETTINGS_CHANGED',settings:await publicSettings()});
        }
        entry.resolve({ok:false,error:error.name==='AbortError'?'Automatic scanning stopped.':error.message,code:error.code||'scan_failed'});
      }finally{scanControllers.delete(controller);scanActive--;void pumpScans();}
    })();
  }
}
async function publishResult(selectionId,payload,result){
  const {selection}=await chrome.storage.session.get('selection');
  if(!selection||selection.selectionId!==selectionId||!selection.tabId)return;
  if(payload.text&&payload.text.trim()!==selection.text.trim())return;
  await chrome.tabs.sendMessage(selection.tabId,{type:'CLAR_RESULT',postKey:selection.postKey,text:selection.text,
    result}).catch(()=>{});
}

// The feed and detailed panel share the same job API and result cache. Opening
// the compact view never requires a second model request.
async function feedPhoto(url,signal){
  if(!photoUrl(url))throw new Error('This photo is not supported.');
  const downloadSignal=AbortSignal.any([signal,AbortSignal.timeout(10000)]);
  const response=await fetch(url,{credentials:'omit',redirect:'error',signal:downloadSignal});
  if(!response.ok)throw new Error('The photo could not be downloaded.');
  const mime=(response.headers.get('content-type')||'').split(';')[0];
  if(!['image/png','image/jpeg','image/webp'].includes(mime))throw new Error('Use a JPEG, PNG, or WebP photo.');
  const limit=5*1024*1024;
  if(Number(response.headers.get('content-length'))>limit)throw new Error('This photo is larger than 5 MB.');
  const reader=response.body.getReader(),chunks=[];let length=0;
  while(true){const {value,done}=await reader.read();if(done)break;length+=value.length;
    if(length>limit){await reader.cancel();throw new Error('This photo is larger than 5 MB.');}chunks.push(value);}
  let binary='';for(const chunk of chunks)for(let i=0;i<chunk.length;i+=8192)binary+=String.fromCharCode(...chunk.subarray(i,i+8192));
  return {mime_type:mime,data:btoa(binary)};
}
async function analyzeFromFeed(post,postKey,tabId){
  const prefs=await settings();
  if(!prefs.token)return {ok:false,code:'pairing_required',error:'Open CLAR from the Chrome toolbar and pair it in Settings first.'};
  const payload=postPayload(post,prefs);
  if(!post.text&&post.imageUrl){payload.text='';payload.image_url=post.imageUrl;}
  const cached=await getCached(payload,prefs);
  if(cached.hit)return {ok:true,result:cached.result,cached:true};
  const key=await cacheKey(payload,prefs);
  if(fullChecks.has(key)){const entry=fullChecks.get(key);entry.subscribers.set(tabId,postKey);return entry.promise;}
  if(queuedFullChecks.has(key)){
    const entry=queuedFullChecks.get(key);entry.subscribers.set(tabId,postKey);
    notifyQueued(entry);return entry.promise;
  }
  if(fullQueue.length>=MAX_WAITING_FULL)return {ok:false,code:'queue_full',error:'The check queue is full. Retry after earlier checks finish.'};
  const controller=new AbortController();
  const subscribers=new Map([[tabId,postKey]]);
  let resolve;
  const promise=new Promise(done=>{resolve=done;});
  const entry={key,post,payload,prefs,cached,controller,subscribers,promise,resolve};
  fullQueue.push(entry);queuedFullChecks.set(key,entry);
  pumpFullChecks();
  if(queuedFullChecks.has(key))notifyQueued(entry);
  return promise;
}
function notifyQueued(entry){
  const position=fullQueue.indexOf(entry)+1;
  if(position<=0)return;
  for(const [tabId,postKey] of entry.subscribers)
    void chrome.tabs.sendMessage(tabId,{type:'CLAR_POST_PROGRESS',postKey,text:entry.post.text,
      progress:{queued:true,position}}).catch(()=>{});
  void chrome.storage.session.get('selection').then(({selection})=>{
    if(selection?.externalCheck&&entry.subscribers.get(selection.tabId)===selection.postKey)
      return chrome.runtime.sendMessage({type:'CLAR_PANEL_PROGRESS',selectionId:selection.selectionId,
        progress:{queued:true,position}});
  }).catch(()=>{});
}
function pumpFullChecks(){
  while(fullChecks.size<2&&fullQueue.length){
    const entry=fullQueue.shift();queuedFullChecks.delete(entry.key);
    if(entry.controller.signal.aborted||!entry.subscribers.size){
      entry.resolve({ok:false,code:'stopped',error:'Check stopped.'});continue;
    }
    fullChecks.set(entry.key,entry);
    void runFullCheck(entry);
  }
  for(const entry of fullQueue)notifyQueued(entry);
}
async function runFullCheck(entry){
  const {key,post,payload,prefs,cached,controller,subscribers,resolve}=entry;
  const started=Date.now();
  let response;
  try{
    const refreshed=await getCached(payload,prefs);
    if(refreshed.hit){response={ok:true,result:refreshed.result,cached:true};return;}
    try{
      if(payload.image_url)payload.image=await feedPhoto(payload.image_url,controller.signal);
      const result=await requestAnalysis({backend:prefs.backend,payload,signal:controller.signal,timeoutMs:Math.max(1000,25000-(Date.now()-started)),
        headers:{Authorization:'Bearer '+prefs.token,'X-CLAR-Extension':chrome.runtime.id},
        onProgress:progress=>{
          for(const [id,key] of subscribers)void chrome.tabs.sendMessage(id,{type:'CLAR_POST_PROGRESS',postKey:key,text:post.text,progress}).catch(()=>{});
          void chrome.storage.session.get('selection').then(({selection})=>{
            if(selection?.externalCheck&&subscribers.get(selection.tabId)===selection.postKey)
              return chrome.runtime.sendMessage({type:'CLAR_PANEL_PROGRESS',selectionId:selection.selectionId,progress});
          }).catch(()=>{});
        }});
      if(controller.signal.aborted)throw new DOMException('Stopped','AbortError');
      await putCached(payload,prefs,result,'analyze',cached.epoch);
      if(controller.signal.aborted)throw new DOMException('Stopped','AbortError');
      response={ok:true,result};
    }catch(error){response={ok:false,error:error.name==='AbortError'?'Check stopped.':error.name==='TimeoutError'?'The photo download timed out. Retry to try again.':error.message||'The check could not finish.',code:error.name==='TimeoutError'?'photo_timeout':error.code||'analysis_failed'};}
  }catch{
    response={ok:false,code:'analysis_failed',error:'The check could not finish.'};
  }finally{
    if(fullChecks.get(key)===entry)fullChecks.delete(key);
    resolve(response||{ok:false,code:'analysis_failed',error:'The check could not finish.'});
    pumpFullChecks();
  }
}
function cancelFullChecks(tabId,postKey){
  for(const entry of fullChecks.values()){
  if(tabId==null)entry.controller.abort();
  else if(postKey==null||entry.subscribers.get(tabId)===postKey){entry.subscribers.delete(tabId);if(!entry.subscribers.size)entry.controller.abort();}
  }
  for(let i=fullQueue.length-1;i>=0;i--){
    const entry=fullQueue[i];
    if(tabId==null)entry.subscribers.clear();
    else if(postKey==null||entry.subscribers.get(tabId)===postKey)entry.subscribers.delete(tabId);
    if(!entry.subscribers.size){
      fullQueue.splice(i,1);queuedFullChecks.delete(entry.key);entry.controller.abort();
      entry.resolve({ok:false,code:'stopped',error:'Check stopped.'});
    }
  }
  for(const entry of fullQueue)notifyQueued(entry);
}
function saveDisagreement(message){
  const write=feedbackWrites.then(async()=>{
    if(typeof message.postKey!=='string'||!/^post-[a-z0-9]+-[a-z0-9]+$/.test(message.postKey))throw new Error('Invalid post.');
    if(!['low','moderate','high','inconclusive'].includes(message.level))throw new Error('Invalid assessment.');
    const {clarDisagreements=[]}=await chrome.storage.local.get('clarDisagreements');
    const entries=Array.isArray(clarDisagreements)?clarDisagreements:[];
    const record={postKey:message.postKey,level:message.level,label:String(message.label||'').slice(0,120),recordedAt:new Date().toISOString(),extensionVersion:chrome.runtime.getManifest().version};
    await chrome.storage.local.set({clarDisagreements:[...entries.slice(-199),record]});
    return {ok:true};
  });
  feedbackWrites=write.catch(()=>{});return write;
}
// Serialize selection and claim writes, including requests from multiple panels.
let selectionQueue=Promise.resolve();
function withSelectionLock(operation) {
  const result=selectionQueue.then(operation);
  selectionQueue=result.catch(()=>{});
  return result;
}
async function selectPost(post,tab,postKey) {
  const paired=Boolean((await settings()).token);
  const selected={...sanitizePost(post),tabId:tab.id,postKey:typeof postKey==='string'?postKey.slice(0,180):null,selectionId:crypto.randomUUID(),selectedAt:Date.now(),autoCheck:!paired,externalCheck:paired,externalStatus:paired?'running':null};
  await withSelectionLock(()=>chrome.storage.session.set({selection:selected,selectionError:null}));
  if(!paired)return selected;
  void finishSelectedCheck(selected);
  return selected;
}
async function finishSelectedCheck(selected){
  try{
    const response=await analyzeFromFeed(selected,selected.postKey,selected.tabId);
    const current=await withSelectionLock(async()=>{
      const {selection}=await chrome.storage.session.get('selection');
      if(selection?.selectionId!==selected.selectionId)return false;
      await chrome.storage.session.set({selection:{...selection,externalStatus:response.ok?'complete':'failed',externalError:response.ok?null:response.error||'The check could not finish.'},selectionError:null});
      return true;
    });
    if(!current)return;
    if(response.ok){
      await publishResult(selected.selectionId,postPayload(selected,await settings()),response.result);
      await chrome.runtime.sendMessage({type:'CLAR_PANEL_RESULT',selectionId:selected.selectionId,result:response.result}).catch(()=>{});
    }else{
      await chrome.runtime.sendMessage({type:'CLAR_PANEL_ERROR',selectionId:selected.selectionId,error:response.error}).catch(()=>{});
    }
  }catch{/* A closed selection has no active UI recipient. */}
}
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
  if(message?.type==='CLAR_RESUME_SELECTION'&&isPanelSender(sender)){
    chrome.storage.session.get('selection').then(({selection})=>{
      if(selection?.selectionId!==message.selectionId||!selection.externalCheck)return sendResponse({ok:false});
      if(selection.externalStatus==='failed')return sendResponse({ok:false,error:selection.externalError});
      void finishSelectedCheck(selection);sendResponse({ok:true});
    }).catch(()=>sendResponse({ok:false}));return true;
  }
  if(message?.type==='CLAR_CANCEL_SELECTION'&&isPanelSender(sender)){
    chrome.storage.session.get('selection').then(({selection})=>{
      if(selection?.selectionId===message.selectionId)cancelFullChecks(selection.tabId,selection.postKey);
      sendResponse({ok:true});
    }).catch(()=>sendResponse({ok:false}));return true;
  }
  if(message?.type==='CLAR_ANALYZE_POST'){
    if(!isFacebookSender(sender)){sendResponse({ok:false});return;}
    try{
      const post=sanitizePost(message.post),key=String(message.postKey||'').slice(0,180);
      analyzeFromFeed(post,key,sender.tab.id).then(sendResponse,()=>sendResponse({ok:false,error:'The check could not finish.'}));
    }catch(error){sendResponse({ok:false,error:error.message});}
    return true;
  }
  if(message?.type==='CLAR_DISAGREE'){
    if(!isFacebookSender(sender)){sendResponse({ok:false});return;}
    saveDisagreement(message).then(sendResponse,()=>sendResponse({ok:false,error:'Could not save feedback on this device.'}));return true;
  }
  if(message?.type==='CLAR_GET_PUBLIC_SETTINGS'&&isFacebookSender(sender)){
    publicSettings().then(value=>sendResponse({ok:true,settings:value}));return true;
  }
  if(message?.type==='CLAR_CANCEL_SCANS'&&isFacebookSender(sender)){
    cancelScans(sender.tab.id);sendResponse({ok:true});return;
  }
  if(message?.type==='CLAR_SCAN_POST'&&isFacebookSender(sender)){
    (async()=>{
      try{
        const prefs=await publicSettings();
        if(!prefs.autoScan){sendResponse({ok:false,error:prefs.pauseReason||'Automatic scanning is off.',code:'scan_disabled'});return;}
        const post=sanitizePost(message.post);
        if(post.truncated||post.text.split(/\s+/u).filter(Boolean).length<15){sendResponse({ok:false,error:'Open the full post to check it.',code:'short_post'});return;}
        if(scanQueue.length>=40){sendResponse({ok:false,error:'The scan queue is full.',code:'queue_full'});return;}
        scanQueue.push({post,tabId:sender.tab.id,resolve:sendResponse});void pumpScans();
      }catch{sendResponse({ok:false,error:'This post could not be read.',code:'input'});}
    })();return true;
  }
  if(['CLAR_CACHE_GET','CLAR_CACHE_PUT','CLAR_CACHE_CLEAR','CLAR_CACHE_INFO','CLAR_FULL_RESULT','CLAR_CLOSE_PANEL'].includes(message?.type)){
    if(!isPanelSender(sender)){sendResponse({ok:false});return;}
    (async()=>{
      try{
        const prefs=await settings();
        if(message.type==='CLAR_CACHE_GET')return sendResponse({ok:true,...await getCached(message.payload,prefs,message.task||'analyze')});
        if(message.type==='CLAR_CACHE_PUT')return sendResponse({ok:true,stored:await putCached(message.payload,prefs,message.result,message.task||'analyze',message.epoch)});
        if(message.type==='CLAR_CACHE_INFO')return sendResponse({ok:true,...await cacheInfo()});
        if(message.type==='CLAR_FULL_RESULT'){await publishResult(message.selectionId,message.payload,message.result);return sendResponse({ok:true});}
        if(message.type==='CLAR_CACHE_CLEAR'){cancelScans();cancelFullChecks();await clearCached();await broadcast({type:'CLAR_CLEAR_RESULTS'});return sendResponse({ok:true});}
        if(message.type==='CLAR_CLOSE_PANEL'){
          if(typeof chrome.sidePanel.close==='function'){const win=await chrome.windows.getCurrent();await chrome.sidePanel.close({windowId:win.id});}
          return sendResponse({ok:true});
        }
      }catch{sendResponse({ok:false,error:'CLAR could not complete that action.'});}
    })();return true;
  }
  if(message?.type==='CLAR_CLEAR_SELECTION'){
    if(!isPanelSender(sender)){sendResponse({ok:false});return;}
    withSelectionLock(async()=>{
      const {selection}=await chrome.storage.session.get('selection');
      if(!message.selectionId||selection?.selectionId===message.selectionId)await chrome.storage.session.remove('selection');
      return {ok:true};
    }).then(sendResponse,()=>sendResponse({ok:false}));
    return true;
  }
  if(message?.type==='CLAR_CLAIM_AUTO_CHECK'){
    if(!isPanelSender(sender)){sendResponse({ok:false});return;}
    withSelectionLock(async()=>{
      const {selection}=await chrome.storage.session.get('selection');
      if(!selection?.autoCheck||selection.selectionId!==message.selectionId||selection.autoCheckClaimed)return {ok:true,claimed:false};
      await chrome.storage.session.set({selection:{...selection,autoCheckClaimed:true}});
      return {ok:true,claimed:true};
    }).then(sendResponse,()=>sendResponse({ok:false}));
    return true;
  }
  if(message?.type!=='CLAR_SELECT_POST')return;
  if(!isFacebookSender(sender)){sendResponse({ok:false,error:'Only Facebook posts can be selected.'});return;}
  let post;
  try{post=sanitizePost(message.post);}catch(error){sendResponse({ok:false,error:error.message});return;}
  // Must happen synchronously inside the forwarded user gesture, before awaits.
  const opening=chrome.sidePanel.open({tabId:sender.tab.id});
  (async()=>{try{await selectPost(post,sender.tab,message.postKey);await opening;sendResponse({ok:true});}catch{sendResponse({ok:false,error:'Open CLAR using the extension toolbar button.'});}})();
  return true;
});
chrome.storage.onChanged.addListener((changes,area)=>{
  if(area!=='local'||!changes.settings)return;
  scanPaused='';cancelScans();
  const previous=changes.settings.oldValue||{},next=changes.settings.newValue||{};
  if(['backend','token','provider','language'].some(key=>previous[key]!==next[key]))cancelFullChecks();
  void chrome.storage.session.remove('scanPause');
  void publicSettings().then(value=>broadcast({type:'CLAR_SETTINGS_CHANGED',settings:value}));
});
chrome.tabs.onRemoved.addListener(tabId=>{cancelScans(tabId);cancelFullChecks(tabId);});

chrome.runtime.onInstalled.addListener(()=>{
  chrome.contextMenus.removeAll(()=>chrome.contextMenus.create({id:'clar-selected-text',title:'Check selected post text with CLAR',contexts:['selection'],documentUrlPatterns:['https://www.facebook.com/*']}));
});
chrome.contextMenus.onClicked.addListener((info,tab)=>{
  if(info.menuItemId!=='clar-selected-text'||!isFacebookTab(tab))return;
  const opening=chrome.sidePanel.open({tabId:tab.id});
  (async()=>{try{
    const response=await chrome.tabs.sendMessage(tab.id,{type:'CLAR_GET_SELECTION'});
    if(!response?.ok)throw new Error(response?.error||'Select text within one Facebook post.');
    await selectPost(response.post,tab,response.postKey);await opening;
  }catch(error){await chrome.storage.session.set({selectionError:error.message});await opening.catch(()=>{});}})();
});
