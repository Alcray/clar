import './presentation.js';

const COPY={
 en:{evidence:'Evidence check',preliminary:'Preliminary reading',strength:'Evidence strength',classification:'Assessment',origin:'Origin',intent:'What this post encourages',claims:'Statement by statement',sources:'Sources',noSource:'No attributable source found for this claim.',factcheck:'Existing fact-check',relatedFactcheck:'Related fact-check · context',reviewedClaim:'Claim discussed in the article',dateUnknown:'Date not supplied',publisherRating:'Publisher rating',ratingUnknown:'No verified publisher rating',matched:'Matching claim',related:'Related coverage',media:'Media literacy',read:'Read between the lines',purpose:'Apparent purpose',response:'Response encouraged',cues:'Persuasion cues to consider',ask:'Ask yourself',tip:'Before you share',none:'No clear persuasion cues identified in this text.',noneNote:'This does not establish that the post is neutral, complete, or true.',unavailable:'The additional reading could not finish. The factual checks remain available.',caution:'Wording can suggest a purpose; it cannot establish private intent or coordinated propaganda.',cached:'Saved on this device',expires:'Expires',retry:'Re-analyze',footer:'AI analysis can be wrong. Open the sources and check the context.',unknown:'Not provided',high:'High',medium:'Medium',low:'Low',confirms:'Confirms',contradicts:'Contradicts',context:'Context',reading:'Reading the post',originStage:'Checking visible origin',sourcesStage:'Searching original sources',factchecksStage:'Checking fact-checkers',formatting:'Assessing evidence and wording',done:'Done',skipped:'Not needed'},
 ro:{evidence:'Verificarea dovezilor',preliminary:'Lectură preliminară',strength:'Puterea dovezilor',classification:'Evaluare',origin:'Proveniență',intent:'Ce încurajează postarea',claims:'Afirmație cu afirmație',sources:'Surse',noSource:'Nu a fost găsită o sursă atribuibilă pentru această afirmație.',factcheck:'Verificare existentă',relatedFactcheck:'Verificare conexă · context',reviewedClaim:'Afirmația discutată în articol',dateUnknown:'Data nu este disponibilă',publisherRating:'Verdictul publicației',ratingUnknown:'Verdictul publicației nu este verificat',matched:'Aceeași afirmație',related:'Material conex',media:'Educație media',read:'Citește printre rânduri',purpose:'Scop aparent',response:'Reacția încurajată',cues:'Indicii persuasive de analizat',ask:'Întreabă-te',tip:'Înainte de distribuire',none:'Nu au fost identificate indicii persuasive clare.',noneNote:'Aceasta nu confirmă că postarea este neutră, completă sau adevărată.',unavailable:'Lectura suplimentară nu a putut fi finalizată. Verificările factuale sunt disponibile.',caution:'Formularea poate sugera un scop, dar nu stabilește intenții ascunse sau propagandă coordonată.',cached:'Salvat pe acest dispozitiv',expires:'Expiră',retry:'Verifică din nou',footer:'Analiza AI poate greși. Deschide sursele și verifică contextul.',unknown:'Nespecificată',high:'Ridicată',medium:'Medie',low:'Scăzută',confirms:'Confirmă',contradicts:'Contrazice',context:'Context',reading:'Citirea postării',originStage:'Verificarea provenienței vizibile',sourcesStage:'Căutarea surselor originale',factchecksStage:'Consultarea verificatorilor',formatting:'Evaluarea dovezilor și formulării',done:'Gata',skipped:'Nu este necesar'},
 ru:{evidence:'Проверка доказательств',preliminary:'Предварительный разбор',strength:'Сила доказательств',classification:'Оценка',origin:'Происхождение',intent:'К чему побуждает публикация',claims:'Разбор утверждений',sources:'Источники',noSource:'Проверяемый источник для этого утверждения не найден.',factcheck:'Существующая проверка',relatedFactcheck:'Связанная проверка · контекст',reviewedClaim:'Утверждение, обсуждаемое в статье',dateUnknown:'Дата не указана',publisherRating:'Оценка издания',ratingUnknown:'Оценка издания не подтверждена',matched:'То же утверждение',related:'Связанный материал',media:'Медиаграмотность',read:'Читаем между строк',purpose:'Предполагаемая цель',response:'Ожидаемая реакция',cues:'Приёмы убеждения',ask:'Спросите себя',tip:'Перед публикацией',none:'Явных приёмов убеждения в тексте не обнаружено.',noneNote:'Это не доказывает нейтральность, полноту или правдивость публикации.',unavailable:'Дополнительный разбор не завершился. Проверка фактов остаётся доступна.',caution:'Формулировки могут указывать на цель, но не доказывают скрытые намерения или координированную пропаганду.',cached:'Сохранено на устройстве',expires:'Истекает',retry:'Проверить снова',footer:'ИИ может ошибаться. Откройте источники и проверьте контекст.',unknown:'Не указано',high:'Высокая',medium:'Средняя',low:'Низкая',confirms:'Подтверждает',contradicts:'Противоречит',context:'Контекст',reading:'Читаем публикацию',originStage:'Проверяем видимый источник',sourcesStage:'Ищем первичные источники',factchecksStage:'Ищем проверки фактов',formatting:'Оцениваем доказательства и формулировки',done:'Готово',skipped:'Не требуется'}
};
const LABELS={
 en:{VERIFIED_FACT:'Supported',FALSE:'Contradicted',MISLEADING:'Misleading context',UNVERIFIED_CLAIM:'Unresolved',OPINION:'Opinion',PREDICTION:'Prediction',UNCLEAR:'Needs context',MIXED:'Mixed findings',CHECKABLE_CLAIMS:'Claims to check',PERSUASION_CUES:'Persuasion cues',ADVERTISING:'Advertising',NEEDS_CONTEXT:'Needs context'},
 ro:{VERIFIED_FACT:'Susținut',FALSE:'Contrazis',MISLEADING:'Context înșelător',UNVERIFIED_CLAIM:'Nedeterminat',OPINION:'Opinie',PREDICTION:'Predicție',UNCLEAR:'Necesită context',MIXED:'Rezultate mixte',CHECKABLE_CLAIMS:'Afirmații de verificat',PERSUASION_CUES:'Indicii persuasive',ADVERTISING:'Publicitate',NEEDS_CONTEXT:'Necesită context'},
 ru:{VERIFIED_FACT:'Подтверждено',FALSE:'Опровергнуто',MISLEADING:'Вводящий в заблуждение контекст',UNVERIFIED_CLAIM:'Не установлено',OPINION:'Мнение',PREDICTION:'Прогноз',UNCLEAR:'Нужен контекст',MIXED:'Смешанные выводы',CHECKABLE_CLAIMS:'Требует проверки',PERSUASION_CUES:'Приёмы убеждения',ADVERTISING:'Реклама',NEEDS_CONTEXT:'Нужен контекст'}
};
const ORIGINS={en:{official:'Official page · registry match',known_media:'Known media · registry match',unknown_page:'Unverified profile',anonymous_group:'Anonymous group post',individual:'Individual',unknown:'Unknown'},ro:{official:'Pagină oficială · registru',known_media:'Presă cunoscută · registru',unknown_page:'Profil neverificat',anonymous_group:'Postare anonimă în grup',individual:'Persoană',unknown:'Necunoscut'},ru:{official:'Официальная страница · реестр',known_media:'Известное СМИ · реестр',unknown_page:'Непроверенный профиль',anonymous_group:'Анонимно в группе',individual:'Частное лицо',unknown:'Неизвестно'}};
const PURPOSES={en:{inform:'Inform',sell:'Sell or promote',persuade:'Persuade',mobilize:'Encourage action',entertain:'Entertain',mixed:'Mixed purpose',unclear:'Unclear'},ro:{inform:'Informare',sell:'Vânzare sau promovare',persuade:'Convingere',mobilize:'Îndemn la acțiune',entertain:'Divertisment',mixed:'Scop mixt',unclear:'Neclar'},ru:{inform:'Информирование',sell:'Продажа или продвижение',persuade:'Убеждение',mobilize:'Призыв к действию',entertain:'Развлечение',mixed:'Смешанная цель',unclear:'Неясно'}};
const DETAIL_COPY={en:{assessment:'Assessment details',original:'Original post',intent:'Intent',source:'Source',caution:'Limits of this reading'},ro:{assessment:'Detaliile evaluării',original:'Postarea originală',intent:'Intenție',source:'Sursă',caution:'Limitele acestei interpretări'},ru:{assessment:'Подробности оценки',original:'Исходная публикация',intent:'Цель',source:'Источник',caution:'Ограничения разбора'}};
const legacy={supported:'VERIFIED_FACT',contradicted:'FALSE',misleading:'MISLEADING',conflicting:'MIXED',insufficient:'UNVERIFIED_CLAIM',opinion:'OPINION',prediction:'PREDICTION',unclear:'UNCLEAR'};
const colors={VERIFIED_FACT:'supported',FALSE:'contradicted',MISLEADING:'misleading',UNVERIFIED_CLAIM:'unverified',OPINION:'opinion',PREDICTION:'prediction',UNCLEAR:'unverified',MIXED:'mixed',CHECKABLE_CLAIMS:'unverified',PERSUASION_CUES:'persuasion',ADVERTISING:'advertising',NEEDS_CONTEXT:'unverified'};
const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
function icon(name,cls='cr-icon'){
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false',class:cls}))svg.setAttribute(key,value);
  const paths={chevron:['m6 9 6 6 6-6'],external:['M15 3h6v6','M10 14 21 3','M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5'],shield:['M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7z'],check:['m5 12 4 4L19 6'],minus:['M6 12h12'],refresh:['M20 7v5h-5','M4 17v-5h5','M6.1 7a7 7 0 0 1 11.6-2L20 8','M4 16l2.3 3A7 7 0 0 0 17.9 17']};
  for(const d of paths[name]||[]){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);svg.append(path);}return svg;
}
function disclosure(title,cls){const item=node('details',cls),summary=node('summary');summary.append(node('span',null,title),icon('chevron','cr-icon cr-chevron'));item.append(summary);return item;}
const safeLink=value=>{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}};
const labelOf=s=>s.label||legacy[s.kind==='factual'?s.verdict:s.kind]||'UNCLEAR';
function pill(label,lang){return node('span',`cr-pill ${colors[label]||'unverified'}`,LABELS[lang][label]||label);}
function strength(item,c){const n=node('span','cr-confidence',`${c.strength}: ${c[item.confidence]||c.low}`);if(item.confidence_note)n.title=item.confidence_note;return n;}
function quote(parent,value,original,cls='ml-quote'){if(typeof value==='string'&&value.trim()&&original.includes(value))parent.append(node('blockquote',cls,value));}
function annotate(original,statements){
  const block=node('div','annotated annotated-post');let cursor=0;
  for(const {item,start} of statements.map(item=>({item,start:original.indexOf(item.text)})).filter(x=>x.start>=0).sort((a,b)=>a.start-b.start)){
    if(start<cursor||typeof item.text!=='string'||!item.text)continue;
    block.append(document.createTextNode(original.slice(cursor,start)),node('mark',colors[labelOf(item)]||'unverified',item.text));cursor=start+item.text.length;
  }
  block.append(document.createTextNode(original.slice(cursor)));return block;
}
function mediaReading(data,original,lang,c,techniques){
  if(!data&&!(techniques||[]).length)return null;
  const section=node('section','media-literacy');section.setAttribute('aria-label',c.media);
  section.append(node('h3',null,c.media));
  if(data?.status==='unavailable'){section.append(node('p','ml-unavailable',c.unavailable));return section;}
  if(data){
    const overview=node('div','ml-overview');
    const purpose=node('div','ml-overview-card');purpose.append(node('p','ml-label',c.purpose),node('span','ml-purpose',PURPOSES[lang][data.purpose?.category]||PURPOSES[lang].unclear));
    if(data.purpose?.explanation)purpose.append(node('p','ml-description',data.purpose.explanation));quote(purpose,data.purpose?.quote,original);
    const response=node('div','ml-overview-card');response.append(node('p','ml-label',c.response),node('p','ml-description',data.desired_response?.description||c.unknown));quote(response,data.desired_response?.quote,original);
    overview.append(purpose,response);section.append(overview);
  }
  const input=Array.isArray(data?.signals)?data.signals:Array.isArray(techniques)?techniques:[];
  const signals=input.filter(s=>s&&typeof s.quote==='string'&&s.quote.trim()&&original.includes(s.quote)).slice(0,8);
  if(signals.length){section.append(node('p','ml-cues-heading',c.cues));for(const signal of signals){
    const card=node('details','ml-cue literacy-cue'),summary=node('summary');summary.append(node('strong','ml-cue-label',signal.label||signal.name||signal.type),icon('chevron','cr-icon ml-chevron'));quote(summary,signal.quote,original,'ml-cue-quote');
    const body=node('div','ml-cue-body');body.append(node('p',null,signal.explanation||''));if(signal.question){const question=node('div','ml-question');question.append(node('strong','ml-label',c.ask),node('p',null,signal.question));body.append(question);}card.append(summary,body);section.append(card);
  }}else{const empty=node('div','ml-no-signals');empty.append(node('p',null,c.none),node('small',null,c.noneNote));section.append(empty);}
  if(data?.reading_tip){const tip=node('div','ml-tip');tip.append(node('strong','ml-label',c.tip),node('p',null,data.reading_tip));section.append(tip);}
  const caution=disclosure(DETAIL_COPY[lang].caution,'cr-disclosure ml-caution');caution.append(node('p','ml-intro',c.caution));if(data?.limitations)caution.append(node('p','ml-limitations',data.limitations));section.append(caution);return section;
}
export function renderResults(root,data,{language='en',onReanalyze}={}){
  const lang=COPY[language]?language:'en',c=COPY[lang],original=String(data.original_text||'');
  const statements=Array.isArray(data.statements)?data.statements:Array.isArray(data.claims)?data.claims:[];
  root.replaceChildren();root.classList.add('clar-results');
  let overall=data.overall||{label:'MIXED',summary:data.summary};
  if(overall.is_preliminary&&['VERIFIED_FACT','FALSE','MISLEADING'].includes(overall.label))overall={...overall,label:'NEEDS_CONTEXT'};
  const compact=globalThis.CLAR_PRESENTATION.summarize(data,{language:lang}),d=DETAIL_COPY[lang];
  const risk=['low','moderate','high','inconclusive'].includes(compact.level)?compact.level:'inconclusive';
  const header=node('section',`cr-overall cr-risk-${risk}`);header.setAttribute('aria-label',compact.levelText);header.dataset.risk=risk;
  const riskLine=node('div','cr-risk-line');riskLine.append(icon('shield'),node('span','cr-risk-level',compact.levelText));if(compact.preliminary)riskLine.append(node('span','cr-preliminary',c.preliminary));header.append(riskLine);
  header.append(node('h3','summary-title result-heading',compact.label));
  const tags=node('div','cr-tags');for(const tag of (compact.tags||[]).slice(0,3))tags.append(node('span','cr-tag',tag.text));if(tags.childElementCount)header.append(tags);
  if(compact.intent){const intent=node('p','cr-short-intent');intent.append(node('span','cr-field-label',d.intent),document.createTextNode(compact.intent));header.append(intent);}
  const sourceUrl=safeLink(compact.source?.url);if(sourceUrl){const source=node('a','cr-source-chip',compact.source.domain||new URL(sourceUrl).hostname);source.href=sourceUrl;source.target='_blank';source.rel='noopener noreferrer';source.setAttribute('aria-label',d.source+': '+source.textContent);source.append(icon('external'));header.append(source);}
  root.append(header);
  const assessment=disclosure(d.assessment,'cr-disclosure cr-assessment');const assessmentBody=node('div','cr-assessment-body');assessmentBody.append(pill(overall.label||'MIXED',lang));if(overall.confidence)assessmentBody.append(strength(overall,c));
  if(overall.summary||data.summary)assessmentBody.append(node('p','cr-assessment-summary',overall.summary||data.summary));if(overall.confidence_note)assessmentBody.append(node('p','cr-note',overall.confidence_note));if(data.overview)assessmentBody.append(node('p','summary-text result-overview',data.overview));
  const fullIntent=overall.intent||data.media_literacy?.desired_response?.description;if(fullIntent&&fullIntent!==compact.intent){const intent=node('div','cr-intent');intent.append(node('h3',null,c.intent),node('p',null,fullIntent));assessmentBody.append(intent);}
  const origin=data.origin;if(origin){const box=node('section','cr-origin');box.append(node('h3',null,c.origin),node('span','cr-origin-type',origin.poster_name||origin.url?ORIGINS[lang][origin.type]||c.unknown:c.unknown));const url=safeLink(origin.url);if(origin.poster_name){const name=node(url?'a':'strong','cr-poster',origin.poster_name);if(url){name.href=url;name.target='_blank';name.rel='noopener noreferrer';}box.append(name);}if(origin.note)box.append(node('p','cr-note',origin.note));assessmentBody.append(box);}
  if(data.cache?.hit){const cache=node('p','cr-cache');cache.textContent=`${c.cached}: ${new Date(data.cache.stored_at).toLocaleString(lang)} · ${c.expires}: ${new Date(data.cache.expires_at).toLocaleString(lang)}`;assessmentBody.append(cache);}assessment.append(assessmentBody);root.append(assessment);
  if(original){const post=disclosure(d.original,'cr-disclosure cr-original'),counts=node('div','counts'),totals={};for(const s of statements){const key=labelOf(s);totals[key]=(totals[key]||0)+1;}for(const [label,count] of Object.entries(totals)){const p=pill(label,lang);p.prepend(document.createTextNode(count+' '));counts.append(p);}post.append(counts,annotate(original,statements));root.append(post);}
  root.append(node('h3','statement-heading',c.claims));
  statements.forEach((s,index)=>{
    const card=node('details','claim claim-card');card.open=index===0;const summary=node('summary'),top=node('div','claim-top');top.append(node('span','claim-number',String(index+1).padStart(2,'0')),pill(labelOf(s),lang));if(s.confidence)top.append(strength(s,c));top.append(icon('chevron','cr-icon chevron'));summary.append(top,node('p','claim-quote',s.text||''));
    const detail=node('div','detail claim-detail');detail.append(node('p','claim-explanation',s.explanation||s.reason||''));if(s.research_note)detail.append(node('p','cr-note',s.research_note));if(s.confidence_note)detail.append(node('p','cr-note',s.confidence_note));
    const fc=s.fact_check,url=safeLink(fc?.url);if(fc&&url){const banner=node('aside','cr-factcheck');banner.append(node('strong',null,`${fc.relation==='related_context'?c.relatedFactcheck:c.factcheck} · ${fc.outlet||''}`),node('p',null,`${fc.date_verified?fc.date:c.dateUnknown} · ${fc.publisher_rating_verified&&fc.publisher_verdict?c.publisherRating+': '+fc.publisher_verdict:c.ratingUnknown}`));const link=node('a',null,(fc.title||c.matched)+' ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';banner.append(link);if(fc.relation==='related_context'&&fc.reviewed_claim)banner.append(node('p',null,c.reviewedClaim+': '+fc.reviewed_claim));if(fc.rating_note)banner.append(node('p','cr-note',fc.rating_note));if(fc.match_explanation)banner.append(node('p',null,fc.match_explanation));detail.append(banner);}
    const sources=Array.isArray(s.evidence)?s.evidence:Array.isArray(s.sources)?s.sources:[];
    if(!sources.length&&s.kind==='factual')detail.append(node('p','cr-no-source',c.noSource));
    for(const source of sources){const url=safeLink(source.url);if(!url)continue;const item=node('div','evidence');item.append(node('span','cr-stance',c[source.stance]||c.context));const a=node('a',null,(source.title||new URL(url).hostname)+' ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';item.append(a);if(source.finding)item.append(node('p',null,source.finding));if(source.label)item.append(node('small',null,source.label));detail.append(item);}
    card.append(summary,detail);root.append(card);
  });
  const media=mediaReading(data.media_literacy,original,lang,c,data.techniques);if(media)root.append(media);
  root.append(node('p','cr-footer',c.footer));if(typeof onReanalyze==='function'){const button=node('button','cr-reanalyze');button.append(icon('refresh'),document.createTextNode(c.retry));button.type='button';button.addEventListener('click',onReanalyze);root.append(button);}
  root.hidden=false;
}
export function renderProgress(root,progress,{language='en'}={}){
  const c=COPY[language]||COPY.en,states=new Map((progress?.stages||[]).map(s=>[s.id,s.state]));
  root.replaceChildren();const list=node('ol','cr-progress');
  for(const [id,key] of [['reading','reading'],['origin','originStage'],['sources','sourcesStage'],['factchecks','factchecksStage'],['formatting','formatting'],['done','done']]){
    const state=states.get(id)||'pending',item=node('li',`cr-stage ${state}`);item.dataset.stage=id;item.dataset.state=state;
    const stageIcon=node('span','cr-stage-icon');if(state==='done')stageIcon.append(icon('check'));else if(state==='skipped')stageIcon.append(icon('minus'));else stageIcon.append(node('span','cr-stage-dot'));item.append(stageIcon,node('span',null,c[key]+(state==='skipped'?' · '+c.skipped:'')));
    if(state==='running')item.setAttribute('aria-current','step');list.append(item);
  }root.append(list);
}
