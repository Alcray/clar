import {ANALYSIS_VERSION} from './client.js';
const STORE='clarResultCacheV4';
const TTL=24*60*60*1000,MAX_BYTES=3_500_000,MAX_ITEMS=50;
let queue=Promise.resolve(),epoch=0;
const lock=fn=>{const next=queue.then(fn);queue=next.catch(()=>{});return next;};
export const normalizedText=value=>String(value||'').replace(/\s+/gu,' ').trim();
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?
  Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
async function digest(value){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(b=>b.toString(16).padStart(2,'0')).join('');}
export async function cacheKey(payload,settings,task='analyze'){
  const image=payload.image_url?await digest(payload.image_url):(payload.image?await digest(payload.image.data||''):'');
  return digest(JSON.stringify([ANALYSIS_VERSION,task,settings.backend,settings.provider,
    settings.language,await digest(settings.token||''),normalizedText(payload.text),
    payload.post_date||'',canonical(payload.origin||null),payload.post_url||null,image]));
}
function rebase(result,text){
  const copy=structuredClone(result),old=copy.original_text||'';
  if(!text||old===text||normalizedText(old)!==normalizedText(text))return copy;
  let normalized='',map=[],space=false;
  for(let i=0;i<text.length;i++){
    if(/\s/u.test(text[i])){if(normalized&&!space){normalized+=' ';map.push(i);}space=true;}
    else{normalized+=text[i];map.push(i);space=false;}
  }
  normalized=normalized.trimEnd();
  const quote=value=>{if(typeof value!=='string')return value;const q=normalizedText(value),at=q?normalized.indexOf(q):-1;return at<0?value:text.slice(map[at],map[at+q.length-1]+1);};
  copy.original_text=text;
  for(const s of copy.statements||[])s.text=quote(s.text);
  for(const t of copy.techniques||[]){t.quote=quote(t.quote);delete t.start;delete t.end;}
  const media=copy.media_literacy;
  if(media){if(media.purpose)media.purpose.quote=quote(media.purpose.quote);if(media.desired_response)media.desired_response.quote=quote(media.desired_response.quote);for(const s of media.signals||[])s.quote=quote(s.quote);}
  return copy;
}
async function entries(){const saved=await chrome.storage.local.get(STORE);const data=saved[STORE];return data&&typeof data==='object'&&!Array.isArray(data)?data:{};}
function prune(data){for(const [key,item] of Object.entries(data)){if(!item||item.expires_at<=Date.now()||!item.result)delete data[key];}return data;}
export async function getCached(payload,settings,task='analyze'){
  const key=await cacheKey(payload,settings,task);
  return lock(async()=>{
    const data=prune(await entries()),item=data[key];
    if(!item)return {hit:false,epoch};
    const result=rebase(item.result,payload.text);
    result.cache={hit:true,stored_at:new Date(item.stored_at).toISOString(),expires_at:new Date(item.expires_at).toISOString()};
    return {hit:true,result,epoch};
  });
}
export async function putCached(payload,settings,result,task='analyze',expectedEpoch=epoch){
  const key=await cacheKey(payload,settings,task);
  return lock(async()=>{
    if(expectedEpoch!==epoch||!result||typeof result!=='object')return false;
    const clean=structuredClone(result);delete clean.cache;
    // Screenshots, payload credentials and input bodies are never cached.
    if(new TextEncoder().encode(JSON.stringify(clean)).byteLength>500_000)return false;
    const data=prune(await entries()),now=Date.now();
    data[key]={result:clean,stored_at:now,expires_at:now+TTL};
    const oldest=Object.keys(data).sort((a,b)=>data[a].stored_at-data[b].stored_at);
    while(oldest.length>MAX_ITEMS||new TextEncoder().encode(JSON.stringify(data)).byteLength>MAX_BYTES)delete data[oldest.shift()];
    await chrome.storage.local.set({[STORE]:data});
    return true;
  });
}
export async function clearCached(){return lock(async()=>{epoch++;await chrome.storage.local.remove(STORE);return {cleared:true,epoch};});}
export async function cacheInfo(){return lock(async()=>({entries:Object.keys(prune(await entries())).length,epoch,ttl_hours:24}));}
