export const ANALYSIS_VERSION = 'clar-0.4.1';
export class CheckError extends Error {
  constructor(message,code='analysis_failed'){super(message);this.code=code;}
}
function sleep(ms,signal){return new Promise((resolve,reject)=>{
  const done=()=>{signal?.removeEventListener('abort',abort);resolve();};
  const timer=setTimeout(done,ms);
  const abort=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);reject(new DOMException('Stopped','AbortError'));};
  if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
});}
export async function requestAnalysis({backend='',payload,headers={},task='analyze',force=false,signal,onProgress=()=>{},fetcher=fetch,timeoutMs=25000}){
  const controller=new AbortController();
  let timedOut=false,jobId=null,finished=false;
  const abort=()=>controller.abort();
  if(signal?.aborted)throw new DOMException('Stopped','AbortError');
  signal?.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);
  const options={headers:{'Content-Type':'application/json',...headers},credentials:backend?'omit':'same-origin',redirect:'error'};
  async function json(path,init={}){
    const response=await fetcher(backend+path,{...options,...init,signal:controller.signal});
    const data=await response.json();
    if(!response.ok)throw new CheckError(data.error||'The check could not finish.',data.code||'request_failed');
    return data;
  }
  try{
    let job=await json('/api/jobs',{method:'POST',body:JSON.stringify({...payload,task,force})});
    jobId=job.job_id;
    if(typeof jobId!=='string')throw new CheckError('The check could not start.');
    while(true){
      onProgress(job.progress||{stages:[]});
      if(job.status==='complete'){finished=true;return job.result;}
      if(job.status==='failed')throw new CheckError(job.error?.error||'The check could not finish.',job.error?.code);
      if(job.status==='cancelled')throw new DOMException('Stopped','AbortError');
      await sleep(650,controller.signal);
      job=await json('/api/jobs/'+encodeURIComponent(jobId));
    }
  }catch(error){
    if(timedOut)throw new CheckError('This check is taking longer than 25 seconds. Retry to resume it without starting a duplicate check.','check_timeout');
    throw error;
  }finally{
    clearTimeout(timer);signal?.removeEventListener('abort',abort);
    // Waiting can time out while the original server job finishes. A retry
    // reattaches by fingerprint. Explicit Stop cancels it instead.
    if(!finished&&!timedOut&&signal?.aborted&&jobId){
      void fetcher(backend+'/api/jobs/'+encodeURIComponent(jobId)+'/cancel',{
        ...options,method:'POST',body:'{}'
      }).catch(()=>{});
    }
  }
}
