import {BUILD_CONFIG} from './build-config.js';
export const BACKENDS = BUILD_CONFIG.backends;
export const DEFAULT_SETTINGS = Object.freeze({backend: BACKENDS[0], token: '', provider: BUILD_CONFIG.defaultProvider, language: 'en',autoScan:false,showHighlights:true});
// The packaged list and manifest/CSP are generated together. Settings cannot
// add a server with wider network permissions than the operator approved.
export function validBackend(value) {return BACKENDS.includes(value);}
export function facebookUrl(value) {
  try {const url=new URL(value);return url.protocol==='https:'&&['www.facebook.com','facebook.com','m.facebook.com'].includes(url.hostname)?url.href:null;}catch{return null;}
}
export function photoUrl(value) {
  try {const url=new URL(value);return url.protocol==='https:'&&url.hostname.endsWith('.fbcdn.net')&&!url.username&&!url.password?url.href:null;}catch{return null;}
}
export function sanitizePost(post) {
  if(!post||typeof post!=='object')throw new Error('No post was selected.');
  const text=typeof post.text==='string'?post.text.trim().slice(0,6000):'';
  const imageUrl=typeof post.imageUrl==='string'&&post.imageUrl.length<=4096?photoUrl(post.imageUrl):null;
  if(!text&&!imageUrl)throw new Error('This post has no readable text or supported photo.');
  const source=post.origin&&typeof post.origin==='object'?post.origin:{};
  const origin={poster_name:typeof source.poster_name==='string'?source.poster_name.slice(0,200):'',
    poster_url:typeof source.poster_url==='string'?facebookUrl(source.poster_url):null,
    context:['page','group','individual','unknown'].includes(source.context)?source.context:'unknown',
    anonymous:source.anonymous===true,
    visible_notes:Array.isArray(source.visible_notes)?source.visible_notes.filter(x=>typeof x==='string').slice(0,4).map(x=>x.slice(0,160)):[]};
  return {text,imageUrl,origin,url:typeof post.url==='string'?facebookUrl(post.url):null,
    visibleDate:typeof post.visibleDate==='string'?post.visibleDate.slice(0,160):null,
    truncated:post.truncated===true};
}
export function postPayload(post,settings,date='',image=null){return {provider:settings.provider,language:settings.language,post_date:date,text:image?'':post.text||'',image,origin:post.origin||null,post_url:post.url||null};}
