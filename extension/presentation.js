/* A presentation-only view of the existing assessment. No research or verdicts
 * are generated here. Loaded as a classic script in Facebook and for its side
 * effect by the extension/web ES modules. */
(() => {
  'use strict';
  const TEXT = {
    en: {
      analyze: 'ANALYZE', analyzing: 'Analyzing…', queued: 'Queued…', retry: 'Retry', error: "Couldn't analyze",
      fullAnalysis: 'Full analysis', disagree: 'Disagree?', feedbackSaved: 'Saved on this device',
      preliminary: 'Preliminary · facts not checked', close: 'Close', intent: 'Apparent intent',
      source: 'Source', evidence: 'Evidence', riskNote: 'A reading aid, not proof of intent.',
      low: 'LOW RISK', moderate: 'MODERATE RISK', high: 'HIGH RISK', inconclusive: 'INCONCLUSIVE',
      labels: { supported: 'Supported', contradicted: 'Contradicted', misleading: 'Missing context',
        unresolved: 'Unverified', opinion: 'Opinion', prediction: 'Prediction', mixed: 'Mixed findings',
        context: 'Needs context', framing: 'Persuasion cues', advertising: 'Advertising', preliminary: 'Not fact-checked' },
      tags: { opinion: 'Opinion', no_primary_source: 'No primary source', official_source: 'Official source',
        anonymous_origin: 'Anonymous origin', emotional_framing: 'Emotional framing', fear_tactics: 'Fear tactics',
        us_vs_them: 'Us vs them', commercial_intent: 'Commercial intent', previously_debunked: 'Previously debunked' },
      intents: { inform: 'Appears to share information', sell: 'Appears to promote a product or service',
        persuade: 'Appears to influence the reader’s view', mobilize: 'Appears to encourage action',
        entertain: 'Appears to entertain', mixed: 'Appears to combine information and persuasion',
        unclear: 'Intent is unclear from this post', fear: 'Fear-based wording may encourage a reaction',
        divide: 'Divisive wording may encourage taking sides', emotional: 'Emotional wording may influence the reader’s response' }
    },
    ro: {
      analyze: 'ANALIZEAZĂ', analyzing: 'Se analizează…', queued: 'În așteptare…', retry: 'Reîncearcă', error: 'Analiza nu a reușit',
      fullAnalysis: 'Analiza completă', disagree: 'Nu ești de acord?', feedbackSaved: 'Salvat pe acest dispozitiv',
      preliminary: 'Preliminar · faptele nu sunt verificate', close: 'Închide', intent: 'Intenție aparentă',
      source: 'Sursă', evidence: 'Dovezi', riskNote: 'Ajutor de lectură, nu dovadă a intenției.',
      low: 'RISC SCĂZUT', moderate: 'RISC MODERAT', high: 'RISC RIDICAT', inconclusive: 'NECONCLUDENT',
      labels: { supported: 'Susținut', contradicted: 'Contrazis', misleading: 'Context omis',
        unresolved: 'Neverificat', opinion: 'Opinie', prediction: 'Predicție', mixed: 'Rezultate mixte',
        context: 'Necesită context', framing: 'Indicii persuasive', advertising: 'Publicitate', preliminary: 'Fapte neverificate' },
      tags: { opinion: 'Opinie', no_primary_source: 'Fără sursă primară', official_source: 'Sursă oficială',
        anonymous_origin: 'Origine anonimă', emotional_framing: 'Încadrare emoțională', fear_tactics: 'Apel la frică',
        us_vs_them: 'Noi contra lor', commercial_intent: 'Intenție comercială', previously_debunked: 'Dezmințit anterior' },
      intents: { inform: 'Pare să transmită informații', sell: 'Pare să promoveze un produs sau serviciu',
        persuade: 'Pare să influențeze opinia cititorului', mobilize: 'Pare să îndemne la acțiune',
        entertain: 'Pare să ofere divertisment', mixed: 'Pare să combine informarea și persuasiunea',
        unclear: 'Intenția nu reiese clar din postare', fear: 'Apelul la frică poate provoca o reacție',
        divide: 'Formularea divizivă poate încuraja alegerea unei tabere', emotional: 'Formularea emoțională poate influența reacția cititorului' }
    },
    ru: {
      analyze: 'АНАЛИЗИРОВАТЬ', analyzing: 'Анализируем…', queued: 'В очереди…', retry: 'Повторить', error: 'Не удалось проанализировать',
      fullAnalysis: 'Полный анализ', disagree: 'Не согласны?', feedbackSaved: 'Сохранено на устройстве',
      preliminary: 'Предварительно · факты не проверены', close: 'Закрыть', intent: 'Предполагаемая цель',
      source: 'Источник', evidence: 'Доказательства', riskNote: 'Помощь в чтении, не доказательство намерений.',
      low: 'НИЗКИЙ РИСК', moderate: 'УМЕРЕННЫЙ РИСК', high: 'ВЫСОКИЙ РИСК', inconclusive: 'НЕДОСТАТОЧНО ДАННЫХ',
      labels: { supported: 'Подтверждено', contradicted: 'Опровергнуто', misleading: 'Упущен контекст',
        unresolved: 'Не проверено', opinion: 'Мнение', prediction: 'Прогноз', mixed: 'Смешанные выводы',
        context: 'Нужен контекст', framing: 'Приёмы убеждения', advertising: 'Реклама', preliminary: 'Факты не проверены' },
      tags: { opinion: 'Мнение', no_primary_source: 'Нет первичного источника', official_source: 'Официальный источник',
        anonymous_origin: 'Анонимный автор', emotional_framing: 'Эмоциональная подача', fear_tactics: 'Апелляция к страху',
        us_vs_them: 'Мы против них', commercial_intent: 'Коммерческая цель', previously_debunked: 'Ранее опровергнуто' },
      intents: { inform: 'Вероятно, передать информацию', sell: 'Вероятно, продвинуть товар или услугу',
        persuade: 'Вероятно, повлиять на мнение читателя', mobilize: 'Вероятно, побудить к действию',
        entertain: 'Вероятно, развлечь', mixed: 'Вероятно, сочетать информирование и убеждение',
        unclear: 'Цель публикации неясна', fear: 'Апелляция к страху может вызвать реакцию',
        divide: 'Противопоставление может побуждать выбрать сторону', emotional: 'Эмоциональные формулировки могут влиять на реакцию' }
    }
  };
  const LEGACY = { supported: 'VERIFIED_FACT', contradicted: 'FALSE', misleading: 'MISLEADING',
    insufficient: 'UNVERIFIED_CLAIM', conflicting: 'UNVERIFIED_CLAIM', opinion: 'OPINION',
    prediction: 'PREDICTION', unclear: 'UNCLEAR' };
  const FRAMING = new Set(['emotional_language', 'fear_appeal', 'urgency', 'us_vs_them', 'loaded_framing',
    'unsupported_certainty', 'false_choice', 'selective_context', 'commercial_pressure',
    'conspiracy_appeal', 'ad_hominem', 'whataboutism', 'call_to_action_without_evidence']);
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const array = value => Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];
  const labelOf = statement => statement.label || LEGACY[statement.kind === 'factual' ? statement.verdict : statement.kind] || 'UNCLEAR';
  const evidenceOf = statement => array(statement.evidence || statement.sources);
  function sourceDomain(title) {
    // Grounding redirects keep their original href. A retrieved title may be
    // the publisher's bare hostname, but never turn prose into a new URL.
    if (typeof title !== 'string' || title.length > 253 || title !== title.trim()) return null;
    const labels = title.toLowerCase().split('.');
    if (labels.length < 2 || !/^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$/.test(labels.at(-1))) return null;
    if (!labels.every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return null;
    return labels.join('.').replace(/^www\./, '');
  }
  function safeSource(value, title) {
    if (typeof value !== 'string' || value.length > 8192) return null;
    try {
      const url = new URL(value);
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return null;
      return {domain: sourceDomain(title) || url.hostname.replace(/^www\./, ''), url: value};
    } catch { return null; }
  }
  function matchedDebunk(statement) {
    const check = object(statement.fact_check);
    // Legacy matched records omit relation. They are attached by the backend
    // only after checking scope and author stance. Related articles have an
    // explicit relation and must never transfer a verdict to the post.
    return ['FALSE', 'MISLEADING'].includes(labelOf(statement))
      && (!check.relation || check.relation === 'same_claim')
      && check.verdict_verified === true
      && ['FALSE', 'MISLEADING'].includes(check.verdict)
      && Boolean(safeSource(check.url));
  }
  function copy(language = 'en') {
    const text = TEXT[language] || TEXT.en;
    return {...text, labels: {...text.labels}, tags: {...text.tags}, intents: {...text.intents}};
  }
  function summarize(input, {language = 'en'} = {}) {
    const result = object(input), c = TEXT[language] || TEXT.en, overall = object(result.overall);
    const claims = array(result.statements || result.claims);
    const factual = claims.filter(s => s.kind === 'factual' || ['VERIFIED_FACT', 'FALSE', 'MISLEADING', 'UNVERIFIED_CLAIM'].includes(labelOf(s)));
    const original = typeof result.original_text === 'string' ? result.original_text : '';
    const media = object(result.media_literacy);
    const cues = [...array(result.techniques), ...array(media.signals)].filter(signal =>
      typeof signal.quote === 'string' && signal.quote.trim() && original.includes(signal.quote));
    const types = new Set(cues.map(signal => signal.type));
    const framing = [...types].some(type => FRAMING.has(type));
    const preliminary = overall.is_preliminary === true;
    const confidence = ['high', 'medium', 'low'].includes(overall.confidence) ? overall.confidence : 'low';
    const kinds = new Set(claims.map(labelOf));
    const assessment = overall.label || (kinds.size === 1 ? [...kinds][0] : kinds.size ? 'MIXED' : 'UNCLEAR');
    const purpose = object(media.purpose);
    const purposeType = typeof purpose.quote === 'string' && purpose.quote && original.includes(purpose.quote)
      && Object.hasOwn(c.intents, purpose.category) ? purpose.category : 'unclear';
    const selling = purposeType === 'sell' || types.has('commercial_pressure') || assessment === 'ADVERTISING';
    const debunked = preliminary ? [] : factual.filter(matchedDebunk);
    const contradictory = factual.filter(s => labelOf(s) === 'FALSE' && evidenceOf(s).some(source =>
      source.stance === 'contradicts' && safeSource(source.url)));
    const adverse = factual.some(s => ['FALSE', 'MISLEADING', 'UNVERIFIED_CLAIM'].includes(labelOf(s)));
    const resolved = factual.length > 0 && factual.every(s => labelOf(s) === 'VERIFIED_FACT'
      && evidenceOf(s).some(source => source.stance === 'confirms' && safeSource(source.url)));
    const opinionsOnly = claims.length > 0 && claims.every(s => labelOf(s) === 'OPINION');
    let level = 'inconclusive', label = 'context';
    if (preliminary) {
      if (framing || selling || factual.length || assessment === 'CHECKABLE_CLAIMS') level = 'moderate';
      label = selling ? 'advertising' : framing ? 'framing' : 'preliminary';
    } else if (['FALSE', 'MISLEADING', 'MIXED'].includes(assessment) || adverse) {
      level = confidence === 'high' && ['FALSE', 'MISLEADING', 'MIXED'].includes(assessment)
        && (contradictory.length || debunked.length) ? 'high' : 'moderate';
      label = assessment === 'MIXED' ? 'mixed' : assessment === 'FALSE' ? 'contradicted'
        : assessment === 'MISLEADING' ? 'misleading' : 'unresolved';
    } else if (selling || framing) {
      level = 'moderate'; label = selling ? 'advertising' : 'framing';
    } else if (resolved && assessment === 'VERIFIED_FACT') {
      level = 'low'; label = 'supported';
    } else if (opinionsOnly && assessment === 'OPINION') {
      level = 'low'; label = 'opinion';
    } else if (['VERIFIED_FACT', 'UNVERIFIED_CLAIM', 'CHECKABLE_CLAIMS'].includes(assessment)) {
      level = 'moderate'; label = 'unresolved';
    } else if (assessment === 'PREDICTION') {
      label = 'prediction';
    }

    const origin = object(result.origin), supportedTags = [];
    const add = (condition, id) => { if (condition) supportedTags.push({id, text: c.tags[id]}); };
    add(debunked.length, 'previously_debunked');
    add(types.has('fear_appeal'), 'fear_tactics');
    add(types.has('us_vs_them'), 'us_vs_them');
    add(types.has('emotional_language') || types.has('loaded_framing'), 'emotional_framing');
    add(selling, 'commercial_intent');
    add(origin.type === 'anonymous_group', 'anonymous_origin');
    add(origin.type === 'official' && Boolean(origin.matched_registry), 'official_source');
    add(claims.some(s => labelOf(s) === 'OPINION') || assessment === 'OPINION', 'opinion');
    // Lack of a familiar domain does not establish lack of a primary source.
    // Only use this tag when a completed search explicitly has no evidence.
    add(!preliminary && factual.length && factual.every(s =>
      (Array.isArray(s.evidence) || Array.isArray(s.sources)) && evidenceOf(s).length === 0), 'no_primary_source');

    let intent = c.intents[purposeType];
    if (purposeType === 'unclear') {
      if (selling) intent = c.intents.sell;
      else if (types.has('fear_appeal')) intent = c.intents.fear;
      else if (types.has('us_vs_them')) intent = c.intents.divide;
      else if (types.has('emotional_language') || types.has('loaded_framing')) intent = c.intents.emotional;
    }
    // Choose a citation attached to the finding driving the card. Provenance
    // profile URLs and generated narrative text are never treated as evidence.
    let source = null;
    if (!preliminary) {
      // A verified article behind the displayed debunk is clearer than the
      // search engine's redirect link and is already part of the assessment.
      source = debunked.map(claim => safeSource(object(claim.fact_check).url)).find(Boolean) || null;
      const ordered = [...contradictory, ...debunked, ...factual, ...claims];
      for (const claim of ordered) {
        if (source) break;
        const label = labelOf(claim), desired = label === 'FALSE' ? 'contradicts' : label === 'VERIFIED_FACT' ? 'confirms' : 'context';
        const entries = evidenceOf(claim);
        const preferred = entries.filter(item => item.stance === desired);
        source = [...preferred, ...entries].map(item => safeSource(item.url, item.title)).find(Boolean)
          || safeSource(object(claim.fact_check).url);
      }
    }
    return {level, levelText: c[level], label: c.labels[label], tags: supportedTags.slice(0, 3),
      intent, source: source || null, confidence, preliminary};
  }
  globalThis.CLAR_PRESENTATION = Object.freeze({summarize, copy});
})();
