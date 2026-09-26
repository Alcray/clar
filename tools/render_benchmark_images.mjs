// Render synthetic text fixtures. No Facebook page, account or model is used.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dataset=JSON.parse(fs.readFileSync(path.join(root,'benchmarks/data/editorial-v1.json'),'utf8'));
const cases=Array.isArray(dataset)?dataset:dataset.cases;
const ids=['calendar-en','calendar-ro','calendar-ru','pin-refund-en','pin-refund-ro','pin-refund-ru'];
const output=path.join(root,'benchmarks/data/images');fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true});
try{
  const page=await browser.newPage({viewport:{width:760,height:800},deviceScaleFactor:1});
  for(const id of ids){
    const item=cases.find(c=>c.id===id);if(!item)throw new Error('Missing fixture '+id);
    await page.setContent('<html><head><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;background:#fff}#post{width:760px;padding:36px;color:#18212c;font:26px/1.6 Arial,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><div id="post"></div></body></html>');
    await page.locator('#post').evaluate((node,text)=>{node.textContent=text;},item.text);
    await page.locator('#post').screenshot({path:path.join(output,id+'.png')});
  }
  console.log('Rendered six original synthetic benchmark screenshots');
}finally{await browser.close();}
