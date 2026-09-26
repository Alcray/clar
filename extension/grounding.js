export function appendSearchSuggestions(root,suggestions){
  for(const html of Array.isArray(suggestions)?suggestions:[]){
    if(typeof html!=='string'||html.length>100000)continue;
    const frame=document.createElement('iframe');
    frame.className='grounding-widget search-widget';frame.title='Google Search suggestions';
    frame.setAttribute('sandbox','allow-popups allow-popups-to-escape-sandbox');
    frame.referrerPolicy='no-referrer';
    frame.srcdoc='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src https: data:; base-uri \'none\'"><base target="_blank">'+html;
    root.append(frame);
  }
}
