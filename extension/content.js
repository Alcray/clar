(() => {
  "use strict";

  if (location.hostname !== "www.facebook.com" || location.protocol !== "https:") return;
  if (globalThis.__clarPostControlsInstalled) return;
  globalThis.__clarPostControlsInstalled = true;

  const selectors = globalThis.CLAR_SELECTORS;
  const presentation = globalThis.CLAR_PRESENTATION;
  if (!selectors || !presentation) return;
  const MESSAGE = selectors.message;
  const FALLBACK_MESSAGE = selectors.fallbackMessage;
  const EXCLUDED = selectors.excluded;
  const SKIP_TEXT = selectors.skipText;
  const controls = new Map();
  const textGroups = new WeakMap();
  let settings = { autoScan: false, language: 'en', showHighlights: true };
  let scanGeneration = 0;
  let activeScans = 0;
  let scanTimer;
  let scanning = false;
  let tooltip;
  let tooltipTarget;
  let popover;
  let positionFrame;
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();

  const copy = key => presentation.copy(settings.language)[key] || presentation.copy('en')[key] || key;
  const riskColors = { low: '#1F6F50', moderate: '#B7791F', high: '#B42318', inconclusive: '#64748b' };
  const componentCss = `
    :host{color-scheme:light;--surface:#fcfcfd;--ink:#17212f;--muted:#64748b;--line:#d9dfe7;--hover:#f1f4f7;--accent:#64748b;--accent-ink:var(--accent);font-family:Inter,system-ui,-apple-system,sans-serif}
    :host([data-theme="dark"]){color-scheme:dark;--surface:#20252d;--ink:#e6eaf0;--muted:#a6b0bf;--line:#414955;--hover:#2b323c}
    :host([data-theme="dark"][data-risk="low"]){--accent-ink:#77ba9b}:host([data-theme="dark"][data-risk="moderate"]){--accent-ink:#e1b469}:host([data-theme="dark"][data-risk="high"]){--accent-ink:#ef988e}:host([data-theme="dark"][data-risk="inconclusive"]){--accent-ink:#a6b0bf}
    *,*::before,*::after{box-sizing:border-box}button,a{-webkit-tap-highlight-color:transparent}button{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible{outline:2px solid #64748b;outline-offset:3px}button:disabled{cursor:wait}svg{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}button{transition:background 150ms,color 150ms,border-color 150ms}button:hover{background:var(--hover)}.eyebrow{font-size:11px;font-weight:700;line-height:1.4;letter-spacing:.08em;text-transform:uppercase;color:var(--accent-ink)}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
  `;

  function icon(name, className = '') {
    const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    node.setAttribute('viewBox', '0 0 24 24');
    node.setAttribute('aria-hidden', 'true');
    if (className) node.setAttribute('class', className);
    const path = document.createElementNS(node.namespaceURI, 'path');
    path.setAttribute('d', ({ shield: 'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3ZM9 12l2 2 4-4', arrow: 'M5 12h14M14 7l5 5-5 5', close: 'm6 6 12 12M18 6 6 18', source: 'M14 3h7v7M21 3l-9 9M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5' })[name] || 'M12 4v8m0 4v.01');
    node.append(path);
    return node;
  }

  function themeFor(root) {
    for (let node = root; node instanceof Element; node = node.parentElement) {
      const color = getComputedStyle(node).backgroundColor;
      const values = color.match(/[\d.]+/g)?.map(Number);
      if (!values || values.length < 3 || (values.length > 3 && values[3] < .6)) continue;
      return .2126 * values[0] + .7152 * values[1] + .0722 * values[2] < 130 ? 'dark' : 'light';
    }
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function syncTheme(root, control) {
    const theme = themeFor(root);
    control.host.dataset.theme = theme;
    if (control.banner) control.banner.dataset.theme = theme;
    if (popover?.control === control) popover.host.dataset.theme = theme;
  }

  function setState(control, state, message = '') {
    control.button.dataset.state = state;
    control.host.dataset.clarState = state;
    if (state !== 'error') control.button.removeAttribute('aria-description');
    if (state === 'idle' || state === 'pending') control.button.title = '';
    control.button.disabled = state === 'pending';
    if (state === 'pending') control.button.setAttribute('aria-busy', 'true');
    else control.button.removeAttribute('aria-busy');
    control.label.textContent = message || (state === 'pending' ? copy('analyzing') : state === 'error' ? `${copy('error')} · ${copy('retry')}` : copy('analyze'));
    control.button.setAttribute('aria-label', control.label.textContent);
  }

  function closePopover(restoreFocus = false) {
    if (!popover) return;
    const previous = popover;
    popover = null;
    previous.host.remove();
    previous.control.button.setAttribute('aria-expanded', 'false');
    if (restoreFocus && previous.control.button.isConnected) previous.control.button.focus({preventScroll: true});
  }

  function positionPopover() {
    positionFrame = null;
    if (!popover) return;
    if (!popover.root.isConnected || !popover.control.host.isConnected) { closePopover(); return; }
    const anchor = popover.control.button.getBoundingClientRect();
    const box = popover.host.getBoundingClientRect();
    // A detached offscreen card must not look like it belongs to another post.
    if (anchor.bottom < 0 || anchor.top > innerHeight) { closePopover(); return; }
    const left = Math.max(8, Math.min(anchor.left, innerWidth - box.width - 8));
    const below = anchor.bottom + 8;
    const top = below + box.height <= innerHeight - 8 ? below : Math.max(8, anchor.top - box.height - 8);
    popover.host.style.left = `${left}px`;
    popover.host.style.top = `${top}px`;
  }

  function schedulePosition() {
    if (popover && !positionFrame) positionFrame = requestAnimationFrame(positionPopover);
  }

  function clearRisk(root, control) {
    control.banner?.remove();
    control.banner = null;
    if (control.riskShadow !== undefined) {
      if (root.style.getPropertyValue('box-shadow') === control.appliedShadow) {
        if (control.riskShadow) root.style.setProperty('box-shadow', control.riskShadow, control.riskShadowPriority);
        else root.style.removeProperty('box-shadow');
      }
      delete control.riskShadow;
      delete control.appliedShadow;
    }
    delete root.dataset.clarRisk;
  }

  function showRisk(root, control, info) {
    clearRisk(root, control);
    if (info.level !== 'high' || info.preliminary) return;
    root.dataset.clarRisk = 'high';
    control.riskShadow = root.style.getPropertyValue('box-shadow');
    control.riskShadowPriority = root.style.getPropertyPriority('box-shadow');
    // An inset accent reads as a 3px left border without shifting Facebook's layout.
    const existingShadow = control.riskShadow || getComputedStyle(root).boxShadow;
    control.appliedShadow = `inset 3px 0 0 ${riskColors.high}${existingShadow && existingShadow !== 'none' ? `, ${existingShadow}` : ''}`;
    root.style.setProperty('box-shadow', control.appliedShadow);
    control.appliedShadow = root.style.getPropertyValue('box-shadow');
    const host = document.createElement('div');
    host.dataset.clarControl = 'banner';
    host.dataset.clarBanner = '';
    host.dataset.risk = 'high';
    host.dataset.theme = themeFor(root);
    host.style.cssText = 'display:block;max-width:100%;';
    const shadow = host.attachShadow({mode: 'closed'});
    const style = document.createElement('style');
    style.textContent = `${componentCss}:host{--accent:#B42318}.banner{padding:7px 12px;border-bottom:1px solid var(--line);background:var(--surface);font-size:11px;font-weight:700;letter-spacing:.06em;line-height:1.4;color:var(--accent-ink);text-transform:uppercase;overflow-wrap:anywhere}`;
    const banner = document.createElement('div');
    banner.className = 'banner';
    banner.textContent = `${info.levelText} · ${info.tags[0]?.text || info.label}`;
    shadow.append(style, banner);
    root.prepend(host);
    control.banner = host;
  }

  function showPopover(root, control) {
    const post = extract(root);
    if (!post || postKey(post) !== control.key || !control.result) return;
    closeTooltip();
    closePopover();
    const info = presentation.summarize(control.result, {language: settings.language});
    const host = document.createElement('div');
    host.dataset.clarPopover = '';
    host.dataset.risk = info.level;
    host.dataset.clarControl = 'popover';
    host.dataset.theme = themeFor(root);
    host.style.cssText = 'position:fixed;z-index:2147483646;width:280px;max-width:calc(100vw - 16px);left:8px;top:8px;';
    const shadow = host.attachShadow({mode: 'closed'});
    const style = document.createElement('style');
    style.textContent = `${componentCss}:host{--accent:${riskColors[info.level] || riskColors.inconclusive}}.card{border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:6px;padding:16px;background:var(--surface);color:var(--ink);box-shadow:0 8px 30px #0002;font-size:13px;line-height:1.45;max-height:calc(100vh - 16px);overflow:auto;animation:clar-appear 150ms ease-out}.head{display:flex;align-items:flex-start;gap:8px}.head>div{flex:1;min-width:0}.label{margin:3px 0 0;font-size:17px;line-height:1.3;font-weight:600;overflow-wrap:anywhere}.close{display:flex;padding:2px;background:none;border:0;color:var(--muted);border-radius:4px}.tags{display:flex;flex-wrap:wrap;gap:5px;margin:13px 0}.tag,.source{border:1px solid var(--line);border-radius:4px;background:var(--surface);font-size:11px;line-height:1.4;padding:4px 6px;color:var(--muted);overflow-wrap:anywhere}.source{display:inline-flex;align-items:center;gap:6px;color:var(--ink);text-decoration:none;max-width:100%}.source svg{width:12px;height:12px}.intent{margin:12px 0;color:var(--ink);overflow-wrap:anywhere}.preliminary{margin:9px 0;color:var(--muted);font-size:11px}.full{display:flex;align-items:center;justify-content:space-between;width:100%;padding:9px 10px;margin-top:14px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:4px;font-weight:600;font-size:12px}.feedback{display:block;margin:11px 0 0;padding:0;color:var(--muted);background:none;border:0;font-size:11px;text-decoration:underline;text-underline-offset:3px}.feedback:disabled{text-decoration:none;cursor:default}@keyframes clar-appear{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:translateY(0)}}`;
    const card = document.createElement('section');
    card.className = 'card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', `${info.levelText} · ${info.label}`);
    const head = document.createElement('div'); head.className = 'head';
    const titles = document.createElement('div');
    const risk = document.createElement('div'); risk.className = 'eyebrow'; risk.textContent = info.levelText;
    const label = document.createElement('h2'); label.className = 'label'; label.textContent = info.label;
    titles.append(risk, label);
    const close = document.createElement('button'); close.type = 'button'; close.className = 'close'; close.setAttribute('aria-label', copy('close')); close.append(icon('close')); close.addEventListener('click', () => closePopover(true));
    head.append(titles, close); card.append(head);
    const tags = document.createElement('div'); tags.className = 'tags';
    for (const tag of info.tags.slice(0, 3)) { const node = document.createElement('span'); node.className = 'tag'; node.textContent = tag.text; tags.append(node); }
    if (tags.childElementCount) card.append(tags);
    if (info.source) {
      try {
        const url = new URL(info.source.url);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('Unsafe source');
        const source = document.createElement('a'); source.className = 'source'; source.href = url.href; source.target = '_blank'; source.rel = 'noopener noreferrer'; source.append(document.createTextNode(info.source.domain), icon('source')); card.append(source);
      } catch { /* Only analysis/retrieval URLs admitted by the adapter can be shown. */ }
    }
    if (info.intent) { const intent = document.createElement('p'); intent.className = 'intent'; intent.textContent = info.intent.split(/\s+/).slice(0, 10).join(' '); card.append(intent); }
    if (info.preliminary) { const preliminary = document.createElement('p'); preliminary.className = 'preliminary'; preliminary.textContent = copy('preliminary'); card.append(preliminary); }
    const full = document.createElement('button'); full.className = 'full'; full.type = 'button'; full.append(document.createTextNode(copy('fullAnalysis')), icon('arrow'));
    full.addEventListener('click', async event => {
      if (!event.isTrusted || full.disabled) return;
      const fresh = extract(root);
      if (!fresh || postKey(fresh) !== control.key) { closePopover(); scheduleScan(); return; }
      full.disabled = true;
      try {
        const response = await chrome.runtime.sendMessage({type: 'CLAR_SELECT_POST', post: fresh, postKey: control.key});
        if (!response?.ok) throw new Error('Unable to open');
        closePopover();
      } catch { full.textContent = `${copy('error')} · ${copy('retry')}`; full.disabled = false; }
    });
    const disagree = document.createElement('button'); disagree.type = 'button'; disagree.className = 'feedback'; disagree.textContent = copy('disagree');
    disagree.addEventListener('click', async event => {
      if (!event.isTrusted || disagree.disabled) return;
      disagree.disabled = true;
      try {
        const response = await chrome.runtime.sendMessage({type: 'CLAR_DISAGREE', postKey: control.key, level: info.level, label: info.label});
        if (!response?.ok) throw new Error('Unable to save');
        disagree.textContent = copy('feedbackSaved');
      } catch { disagree.disabled = false; disagree.textContent = copy('retry'); }
    });
    card.append(full, disagree); shadow.append(style, card); document.documentElement.append(host);
    popover = {root, control, host};
    control.button.setAttribute('aria-expanded', 'true');
    positionPopover();
    close.focus({preventScroll: true});
  }

  function postKey(post) {
    // An identity hint, not a security boundary. Exact text is checked again
    // before applying a result to a potentially recycled Facebook container.
    const input = JSON.stringify([post.text, post.url, post.imageUrl]);
    let hash = 2166136261;
    let second = 5381;
    for (let i = 0; i < input.length; i += 1) {
      hash = Math.imul(hash ^ input.charCodeAt(i), 16777619);
      second = Math.imul(second, 33) ^ input.charCodeAt(i);
    }
    return `post-${(hash >>> 0).toString(36)}-${(second >>> 0).toString(36)}`;
  }

  function scheduleScan() {
    // Throttle rather than continuously resetting a debounce: active feeds
    // must still receive controls while Facebook keeps mutating the DOM.
    if (scanTimer) return;
    scanTimer = setTimeout(() => { scanTimer = null; scan(); }, 250);
  }

  function visible(node) {
    if (!(node instanceof Element) || !node.isConnected || !node.getClientRects().length) return false;
    const style = getComputedStyle(node);
    return style.display !== 'none' && style.visibility !== 'hidden' && style.visibility !== 'collapse';
  }

  function postRoot(node) {
    const element = node instanceof Element ? node : node?.parentElement;
    if (!element || element.closest(EXCLUDED)) return null;
    // Some desktop layouts omit both FeedUnit and role=article. Keep the
    // fallback within Facebook's explicit per-post virtualization boundary.
    const boundary = element.closest(selectors.boundary);
    if (boundary?.matches('[data-pagelet^="FeedUnit"]')) return boundary;
    if (boundary && boundary.closest('[role="main"], [role="feed"]') &&
        boundary.querySelector(selectors.author)) return boundary;
    let article = element.closest(selectors.article);
    if (!article) return null;
    // Nested articles commonly represent comments or embedded shared posts.
    while (article.parentElement?.closest('[role="article"]')) {
      article = article.parentElement.closest('[role="article"]');
    }
    return article;
  }

  function ownedBy(root, element) {
    if (!root.contains(element) || element.closest(EXCLUDED)) return false;
    let articleCount = 0;
    for (let node = element; node && node !== root; node = node.parentElement) {
      if (node.matches(selectors.boundary)) return false;
      if (node.matches(selectors.article)) articleCount += 1;
    }
    // A FeedUnit may wrap the main article. A second article is an embedded item.
    return articleCount <= (root.matches('[role="article"]') ? 0 : 1);
  }

  function messageFor(root) {
    for (const selector of [MESSAGE, FALLBACK_MESSAGE]) {
      const candidates = root.querySelectorAll(selector);
      for (const candidate of candidates) {
        if (ownedBy(root, candidate) && visible(candidate)) return candidate;
      }
    }
    return null;
  }

  function sourceText(message, root) {
    let text = '';
    const positions = [];
    const groups = [];
    const walker = document.createTreeWalker(message, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        return parent && !parent.closest(SKIP_TEXT) && ownedBy(root, parent) && visible(parent)
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const group = textGroups.get(node) || node;
      const last = groups.at(-1);
      if (last?.id === group) last.nodes.push(node);
      else groups.push({ id: group, nodes: [node] });
    }
    for (const group of groups) {
      let raw = '';
      const rawPositions = [];
      for (const node of group.nodes) {
        raw += node.nodeValue;
        for (let offset = 0; offset < node.nodeValue.length; offset += 1) rawPositions.push({ node, offset });
      }
      const start = raw.search(/\S/);
      if (start < 0) continue;
      const end = raw.search(/\s*$/);
      if (text) { text += ' '; positions.push(null); }
      for (let offset = start; offset < end; offset += 1) {
        if (/\s/.test(raw[offset])) {
          if (text.endsWith(' ')) continue;
          text += ' ';
        } else text += raw[offset];
        positions.push(rawPositions[offset]);
      }
    }
    return { text, positions };
  }

  const visibleText = (message, root) => sourceText(message, root).text;

  function permalink(value) {
    try {
      const url = new URL(value, location.href);
      if (url.protocol !== 'https:' || !['facebook.com', 'www.facebook.com', 'm.facebook.com'].includes(url.hostname)) return null;
      if (url.searchParams.has('comment_id') || url.searchParams.has('reply_comment_id')) return null;
      const postPath = /\/(?:posts|videos)\/[^/]+\/?$/.test(url.pathname) || /^\/reel\/[^/]+\/?$/.test(url.pathname);
      const storyPath = /^\/(?:permalink|story)\.php$/.test(url.pathname) && url.searchParams.has('story_fbid');
      const photoPath = /^\/photo(?:\.php|\/)?$/.test(url.pathname) && url.searchParams.has('fbid');
      if (!postPath && !storyPath && !photoPath) return null;
      const clean = new URL(url.pathname, 'https://www.facebook.com');
      for (const key of ['story_fbid', 'id', 'fbid']) {
        if (url.searchParams.has(key)) clean.searchParams.set(key, url.searchParams.get(key));
      }
      return clean.href;
    } catch {
      return null;
    }
  }

  function imageFor(root, requirePhotoLink = false) {
    for (const img of root.querySelectorAll('img')) {
      if (!ownedBy(root, img) || !visible(img)) continue;
      const size = img.getBoundingClientRect();
      if (size.width < 200 || size.height < 120) continue;
      const photoLink = img.closest('a[href*="/photo"]');
      let actualPhotoLink = false;
      if (photoLink) {
        try {
          const target = new URL(photoLink.href);
          actualPhotoLink = target.protocol === 'https:' &&
            ['facebook.com', 'www.facebook.com', 'm.facebook.com'].includes(target.hostname) &&
            !target.searchParams.has('comment_id') && !target.searchParams.has('reply_comment_id') &&
            ((/^\/photo(?:\.php|\/)?$/.test(target.pathname) && target.searchParams.has('fbid')) ||
              /\/photos\/(?:[^/]+\/)*\d+\/?$/.test(target.pathname));
        } catch { /* A link with an invalid URL cannot identify a post photo. */ }
      }
      const descriptiveAlt = /(?:may be an image|photo of|image of)/i.test(img.alt || '');
      if (requirePhotoLink ? !actualPhotoLink : !actualPhotoLink && !descriptiveAlt) continue;
      if (/profile picture|avatar/i.test(img.alt || '')) continue;
      try {
        const source = new URL(img.currentSrc || img.src);
        if (source.protocol === 'https:' && source.hostname.endsWith('.fbcdn.net')) {
          return { node: img, anchor: photoLink || img, url: source.href };
        }
      } catch { /* Invalid or transient image sources are ignored. */ }
    }
    return null;
  }

  function metadata(root, message) {
    let url = null;
    let visibleDate = null;
    for (const link of root.querySelectorAll('a[href]')) {
      if (!ownedBy(root, link) || message?.contains(link) || !visible(link)) continue;
      const candidate = permalink(link.href);
      if (!candidate) continue;
      url = candidate;
      // Do not guess dates from obfuscated labels or extract author/profile text.
      const date = link.querySelector('time, abbr');
      if (date && visible(date)) visibleDate = date.innerText.trim().slice(0, 160) || null;
      break;
    }
    return { url, visibleDate, imageUrl: imageFor(root, !message)?.url || null, origin: originFor(root, message) };
  }

  function facebookIdentityUrl(value) {
    try {
      const url = new URL(value, location.href);
      if (url.protocol !== 'https:' || !['facebook.com', 'www.facebook.com', 'm.facebook.com'].includes(url.hostname)) return null;
      if (url.pathname === '/l.php' || url.pathname.startsWith('/share')) return null;
      const clean = new URL(url.pathname, 'https://www.facebook.com');
      if (url.pathname === '/profile.php' && /^\d+$/.test(url.searchParams.get('id') || '')) clean.searchParams.set('id', url.searchParams.get('id'));
      return clean.href;
    } catch { return null; }
  }

  function originFor(root, message) {
    const headings = [...root.querySelectorAll(selectors.heading)].filter(node => ownedBy(root, node) && visible(node) && !message?.contains(node));
    const links = [...root.querySelectorAll(selectors.author)].filter(node => ownedBy(root, node) && visible(node) && !message?.contains(node));
    const group = links.find(node => /\/groups\//.test(facebookIdentityUrl(node.href) || ''));
    const author = links.find(node => node !== group && !permalink(node.href)) || null;
    const headingText = headings.map(node => normalize(node.innerText)).join(' ');
    const anonymous = /(?:anonymous (?:participant|member|post)|participant anonim|membru anonim|postare anonimă|анонимный участник|анонимная публикация)/i.test(headingText);
    let context = group ? 'group' : 'unknown';
    // Facebook uses profile.php for both people and Pages. Do not infer one
    // from its URL or from the author's name; use an explicit visible label.
    const visibleNotes = [];
    const labelled = [...root.querySelectorAll('[aria-label]')].filter(node => ownedBy(root, node) && visible(node) && !message?.contains(node));
    if (!group && labelled.some(node => /^(?:Facebook Page|Pagină Facebook|Страница Facebook)$/i.test(node.getAttribute('aria-label')))) context = 'page';
    if (group) visibleNotes.push(`Group shown: ${normalize(group.innerText).slice(0, 180)}`);
    if (labelled.some(node => /^(?:Verified account|Verified Page|Cont verificat|Подтвержденный аккаунт)$/i.test(node.getAttribute('aria-label')))) visibleNotes.push('Facebook displays a verification badge; this does not verify the post.');
    return {
      poster_name: (anonymous ? headingText : normalize(author?.innerText || headings[0]?.innerText)).slice(0, 200),
      poster_url: author ? facebookIdentityUrl(author.href) : null,
      context, anonymous, visible_notes: visibleNotes,
    };
  }

  function isTruncated(message, rawText) {
    if (rawText.length > 6000) return true;
    if (message.scrollHeight > message.clientHeight + 2 && getComputedStyle(message).overflowY === 'hidden') return true;
    return [...message.querySelectorAll('button, [role="button"], a')].some(node =>
      visible(node) && /^(?:see more|show more|read more|vezi mai mult|afișează mai mult|ещ[её]|показать полностью)$/i.test(node.innerText.trim())
    );
  }

  function extract(root, selectedText) {
    if (!root.isConnected || !visible(root)) return null;
    const message = messageFor(root);
    const rawText = selectedText ?? (message ? visibleText(message, root) : '');
    const details = metadata(root, message);
    if (!rawText.trim() && !details.imageUrl) return null;
    return {
      text: rawText.trim().slice(0, 6000),
      ...details,
      truncated: message ? isTruncated(message, rawText) : false
    };
  }

  function closeTooltip() {
    tooltip?.remove();
    tooltip = null;
    tooltipTarget = null;
  }

  function currentHighlight(mark) {
    if (!mark?.isConnected) return false;
    const root = postRoot(mark);
    const control = controls.get(root);
    const post = root && extract(root);
    return !!(control?.marks.has(mark) && post && postKey(post) === control.key);
  }

  function positionTooltip(host, mark) {
    const anchor = mark.getBoundingClientRect();
    if (anchor.bottom < 0 || anchor.top > innerHeight || anchor.right < 0 || anchor.left > innerWidth) return false;
    const tip = host.getBoundingClientRect();
    const gap = 8;
    const clamp = (value, size, limit) => Math.max(gap, Math.min(value, Math.max(gap, limit - size - gap)));
    const overlap = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    const card = popover?.host.getBoundingClientRect();
    const paddedCard = card && {left: card.left - gap, right: card.right + gap, top: card.top - gap, bottom: card.bottom + gap};
    const xs = [anchor.left, anchor.right - tip.width, anchor.left - tip.width - gap, anchor.right + gap];
    const ys = [anchor.bottom + gap, anchor.top - tip.height - gap, anchor.top];
    if (card) {
      xs.push(card.left - tip.width - gap, card.right + gap);
      ys.push(card.top - tip.height - gap, card.bottom + gap);
    }
    let best;
    for (const rawX of xs) for (const rawY of ys) {
      const left = clamp(rawX, tip.width, innerWidth);
      const top = clamp(rawY, tip.height, innerHeight);
      const rect = {left, top, right: left + tip.width, bottom: top + tip.height};
      const score = [paddedCard ? overlap(rect, paddedCard) : 0, overlap(rect, anchor), Math.abs(left - anchor.left) + Math.abs(top - (anchor.bottom + gap))];
      if (!best || score.some((value, index) => value < best.score[index] && score.slice(0, index).every((prior, i) => prior === best.score[i]))) best = {left, top, score};
    }
    // A very small viewport may have no space beside an open card.
    if (paddedCard && best.score[0] > 0) return false;
    host.style.left = `${best.left}px`;
    host.style.top = `${best.top}px`;
    host.style.visibility = 'visible';
    return true;
  }

  function showTooltip(mark) {
    if (!mark.isConnected || !mark.dataset.clarExplanation) return;
    if (!currentHighlight(mark)) { closeTooltip(); scheduleScan(); return; }
    if (tooltip?.isConnected && tooltipTarget === mark) return;
    closeTooltip();
    const host = document.createElement('div');
    host.dataset.clarTooltip = '';
    host.dataset.theme = themeFor(mark);
    host.setAttribute('role', 'tooltip');
    host.style.cssText = 'position:fixed;z-index:2147483647;left:8px;top:8px;width:max-content;max-width:min(320px, calc(100vw - 16px));visibility:hidden;pointer-events:none;';
    const shadow = host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = `${componentCss}.tip{padding:11px 13px;border:1px solid var(--line);border-radius:5px;background:var(--surface);color:var(--ink);font:13px/1.5 system-ui,sans-serif;box-shadow:0 4px 20px #0002;overflow-wrap:anywhere;max-height:calc(100vh - 16px);overflow:hidden}strong{display:block;margin-bottom:3px}p{margin:0}`;
    const card = document.createElement('div');
    card.className = 'tip';
    const title = document.createElement('strong');
    title.textContent = mark.dataset.clarTechnique;
    const explanation = document.createElement('p');
    explanation.textContent = mark.dataset.clarExplanation;
    card.append(title, explanation);
    shadow.append(style, card);
    document.documentElement.append(host);
    if (!positionTooltip(host, mark)) { host.remove(); return; }
    tooltip = host;
    tooltipTarget = mark;
  }

  function clearHighlights(control) {
    if (control.marks?.has(tooltipTarget)) closeTooltip();
    for (const mark of control.marks || []) {
      if (mark.isConnected) mark.replaceWith(...mark.childNodes);
    }
    control.marks = new Set();
  }

  function labelInfo(result) {
    const info = presentation.summarize(result, {language: settings.language});
    return {...info, color: riskColors[info.level] || riskColors.inconclusive};
  }

  function highlightResult(root, control, result) {
    clearHighlights(control);
    if (!settings.showHighlights) return;
    const message = messageFor(root);
    if (!message) return;
    const source = sourceText(message, root);
    const techniques = Array.isArray(result?.techniques) ? result.techniques : result?.media_literacy?.signals;
    if (!Array.isArray(techniques)) return;
    const chosen = [];
    for (const technique of techniques.slice(0, 8)) {
      const quote = normalize(technique.quote);
      if (quote.length < 3 || quote.length > 1200) continue;
      const start = source.text.indexOf(quote);
      const end = start + quote.length;
      if (start < 0 || chosen.some(range => start < range.end && end > range.start)) continue;
      const positions = source.positions.slice(start, end).filter(Boolean);
      if (!positions.length || positions.some(position => position.node.parentElement.closest(selectors.interactive))) continue;
      chosen.push({ start, end, positions, technique });
    }
    const ranges = new Map();
    for (const { positions, technique } of chosen) {
      for (const { node, offset } of positions) {
        if (!ranges.has(node)) ranges.set(node, []);
        const list = ranges.get(node);
        let range = list.find(item => item.technique === technique);
        if (!range) { range = { start: offset, end: offset + 1, technique }; list.push(range); }
        range.end = Math.max(range.end, offset + 1);
      }
    }
    const color = labelInfo(result).color;
    for (const [node, pieces] of ranges) {
      const group = textGroups.get(node) || {};
      textGroups.set(node, group);
      for (const { start, end, technique } of pieces.sort((a, b) => b.start - a.start)) {
        if (!node.parentElement || end > node.length) continue;
        const trailing = node.splitText(end);
        const quoted = node.splitText(start);
        textGroups.set(trailing, group);
        textGroups.set(quoted, group);
        const mark = document.createElement('span');
        mark.dataset.clarHighlight = '';
        mark.dataset.clarTechnique = String(technique.name || technique.label || technique.type || 'Reading cue').slice(0, 120);
        mark.dataset.clarExplanation = String(technique.explanation || '').slice(0, 700);
        mark.setAttribute('aria-label', `${mark.dataset.clarTechnique}: ${mark.dataset.clarExplanation}`);
        mark.tabIndex = 0;
        mark.style.cssText = `color:inherit;background:transparent;text-decoration-line:underline;text-decoration-style:dotted;text-decoration-thickness:2px;text-underline-offset:3px;text-decoration-color:${color};cursor:help;`;
        quoted.replaceWith(mark);
        mark.append(quoted);
        control.marks.add(mark);
      }
    }
  }

  function applyResult(root, control, post, result) {
    const fresh = extract(root);
    if (!fresh || control.key !== postKey(fresh) || fresh.text !== post.text || postKey(post) !== control.key) return;
    if (!result?.overall || typeof result.overall !== 'object') return;
    if (control.result?.overall?.is_preliminary === false && result.overall.is_preliminary !== false) return;
    if (control.manualPending && result.overall.is_preliminary !== false) return;
    control.result = result;
    control.failureCode = null;
    const info = labelInfo(result);
    setState(control, 'result', `${info.levelText} · ${info.label}`);
    control.host.style.setProperty('--accent', info.color);
    control.host.dataset.risk = info.level;
    control.button.title = info.preliminary ? copy('preliminary') : `${info.levelText} · ${info.label}`;
    syncTheme(root, control);
    showRisk(root, control, info);
    highlightResult(root, control, result);
    if (popover?.control === control) showPopover(root, control);
  }

  async function analyzePost(root, control) {
    const post = extract(root);
    if (!post) { setState(control, 'error'); return; }
    const key = postKey(post);
    if (key !== control.key) resetControl(root, control, key);
    const requestId = ++control.requestId;
    control.manualPending = true;
    setState(control, 'pending');
    closePopover();
    try {
      const response = await chrome.runtime.sendMessage({type: 'CLAR_ANALYZE_POST', post, postKey: key});
      if (controls.get(root) !== control || control.key !== key || requestId !== control.requestId) return;
      control.manualPending = false;
      if (!response?.ok || !response.result?.overall) {
        control.failureCode = response?.code || null;
        throw new Error(response?.error || copy('error'));
      }
      applyResult(root, control, post, response.result);
    } catch (error) {
      if (controls.get(root) !== control || control.key !== key || requestId !== control.requestId) return;
      control.manualPending = false;
      setState(control, 'error');
      control.button.title = String(error?.message || copy('retry')).slice(0, 300);
      control.button.setAttribute('aria-description', control.button.title);
    }
  }

  function resetControl(root, control, key) {
    if (popover?.control === control) closePopover();
    clearHighlights(control);
    clearRisk(root, control);
    control.requestId += 1;
    control.manualPending = false;
    control.key = key;
    control.result = null;
    control.failureCode = null;
    control.scanState = null;
    control.host.style.removeProperty('--accent');
    delete control.host.dataset.risk;
    setState(control, 'idle');
  }

  function inViewport(control) {
    const box = control.anchor.getBoundingClientRect();
    return visible(control.anchor) && box.bottom > 0 && box.top < innerHeight && box.right > 0 && box.left < innerWidth;
  }

  function pumpScans() {
    if (!settings.autoScan) return;
    for (const [root, control] of controls) {
      if (activeScans >= 2) return;
      if (!control.intersecting || !inViewport(control) || control.scanState || control.result || control.manualPending) continue;
      const post = extract(root);
      if (!post || post.truncated || normalize(post.text).split(' ').filter(Boolean).length < 15) continue;
      const key = postKey(post);
      if (key !== control.key) { scheduleScan(); continue; }
      const generation = scanGeneration;
      control.scanState = 'pending';
      activeScans += 1;
      setState(control, 'pending');
      control.button.title = copy('preliminary');
      Promise.resolve().then(() => chrome.runtime.sendMessage({ type: 'CLAR_SCAN_POST', post, postKey: key })).then(response => {
        if (!settings.autoScan || generation !== scanGeneration || control.key !== key || controls.get(root) !== control) return;
        control.scanState = 'done';
        if (response?.ok && response.result?.overall) applyResult(root, control, post, response.result);
        else if (!control.result && !control.manualPending) {
          setState(control, 'error');
          control.button.title = String(response?.error || copy('retry')).slice(0, 300);
        }
      }).catch(() => {
        if (generation === scanGeneration && control.key === key && !control.result && !control.manualPending) {
          control.scanState = 'done';
          setState(control, 'error');
        }
      }).finally(() => {
        activeScans -= 1;
        pumpScans();
      });
    }
  }

  const intersection = new IntersectionObserver(entries => {
    for (const entry of entries) {
      const root = postRoot(entry.target);
      const control = controls.get(root);
      if (control?.anchor === entry.target) control.intersecting = entry.isIntersecting;
    }
    pumpScans();
  }, { threshold: 0.01 });

  function attach(root) {
    const message = messageFor(root);
    const anchor = message || imageFor(root, true)?.anchor;
    if (!anchor) return;
    const existing = controls.get(root);
    if (existing?.host.isConnected) {
      if (existing.anchor !== anchor) {
        intersection.unobserve(existing.anchor);
        anchor.insertAdjacentElement('afterend', existing.host);
        existing.anchor = anchor;
        intersection.observe(anchor);
      }
      const post = extract(root);
      if (post && existing.key !== postKey(post)) resetControl(root, existing, postKey(post));
      syncTheme(root, existing);
      return;
    }
    if (existing) { intersection.unobserve(existing.anchor); clearHighlights(existing); clearRisk(root, existing); if (popover?.control === existing) closePopover(); }
    const host = document.createElement('div');
    host.dataset.clarControl = '';
    const shadow = host.attachShadow({mode: 'closed'});
    const style = document.createElement('style');
    style.textContent = `${componentCss}:host{display:block;margin:10px 0 12px;clear:both}.pill{display:inline-flex;align-items:center;gap:7px;max-width:100%;padding:7px 10px;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:5px;background:var(--surface);color:var(--ink);font-size:11px;font-weight:650;line-height:1.4;letter-spacing:.04em;text-align:left;min-height:32px}.pill[data-state="idle"] .label{text-transform:uppercase}.pill[data-state="result"]{color:var(--accent-ink)}.label{min-width:0;overflow-wrap:anywhere}.mark{width:15px;height:15px}.pill[data-state="pending"] .mark{width:14px;height:14px;border:1.5px solid var(--line);border-top-color:var(--muted);border-radius:50%;animation:clar-spin .8s linear infinite}.pill[data-state="pending"] .mark path{display:none}.pill[data-state="pending"]{color:var(--muted)}.pill[data-state="error"]{color:var(--muted)}@keyframes clar-spin{to{transform:rotate(360deg)}}`;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'pill'; button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-expanded', 'false');
    const label = document.createElement('span'); label.className = 'label'; label.setAttribute('aria-live', 'polite');
    button.append(icon('shield', 'mark'), label); shadow.append(style, button);
    const control = {host, anchor, button, label, key: postKey(extract(root) || {}), marks: new Set(), intersecting: false, scanState: null, result: null, requestId: 0, manualPending: false};
    button.addEventListener('click', event => {
      if (!event.isTrusted || button.disabled) return;
      event.preventDefault(); event.stopPropagation();
      const post = extract(root);
      if (!post) { setState(control, 'error'); return; }
      if (postKey(post) !== control.key) resetControl(root, control, postKey(post));
      if (control.failureCode === 'pairing_required') {
        // Opening Settings needs this direct user gesture. The failed analysis
        // did not send a post to an unpaired server.
        chrome.runtime.sendMessage({type: 'CLAR_SELECT_POST', post, postKey: control.key}).then(response => {
          if (response?.ok) { control.failureCode = null; setState(control, 'idle'); }
        }).catch(() => {});
        return;
      }
      if (control.result && button.dataset.state === 'result') {
        if (popover?.control === control) closePopover();
        else showPopover(root, control);
      } else analyzePost(root, control);
    });
    anchor.insertAdjacentElement('afterend', host);
    controls.set(root, control);
    setState(control, 'idle'); syncTheme(root, control);
    intersection.observe(anchor);
  }

  function scan() {
    if (scanning) return;
    scanning = true;
    try {
      for (const [root, control] of controls) {
        if (!root.isConnected || (!messageFor(root) && !imageFor(root, true))) {
          intersection.unobserve(control.anchor);
          clearHighlights(control);
          clearRisk(root, control);
          if (popover?.control === control) closePopover();
          control.host.remove();
          controls.delete(root);
        }
      }
      // Only explicit message containers or large linked post photos are eligible.
      // Image-only posts never fall back to article text, authors, or reactions.
      const roots = new Set();
      for (const message of document.querySelectorAll(`${MESSAGE}, ${FALLBACK_MESSAGE}`)) {
        const root = postRoot(message);
        if (root && ownedBy(root, message) && visible(message)) roots.add(root);
      }
      for (const image of document.querySelectorAll('a[href*="/photo"] img')) {
        const root = postRoot(image);
        if (root && ownedBy(root, image) && !roots.has(root) && imageFor(root, true)) roots.add(root);
      }
      for (const root of roots) attach(root);
      pumpScans();
    } finally {
      scanning = false;
    }
  }

  const observer = new MutationObserver(mutations => {
    if (tooltipTarget && !currentHighlight(tooltipTarget)) closeTooltip();
    // Ignore our own controls, including their insertion, to avoid rescan loops.
    const relevant = mutations.some(mutation => {
      if (mutation.target instanceof Element && mutation.target.closest('[data-clar-control], [data-clar-tooltip]')) return false;
      if (mutation.type !== 'childList') return true;
      return [...mutation.addedNodes, ...mutation.removedNodes].some(node =>
        !(node instanceof Element && node.matches('[data-clar-control], [data-clar-tooltip]'))
      );
    });
    if (!relevant) return;
    scheduleScan();
  });

  function updateSettings(next) {
    if (!next || typeof next !== 'object') return;
    const previous = settings;
    settings = {autoScan: next.autoScan === true, language: ['en', 'ro', 'ru'].includes(next.language) ? next.language : 'en', showHighlights: next.showHighlights !== false};
    if (previous.autoScan && !settings.autoScan || previous.language !== settings.language) {
      scanGeneration += 1;
      Promise.resolve().then(() => chrome.runtime.sendMessage({type: 'CLAR_CANCEL_SCANS'})).catch(() => {});
      for (const [root, control] of controls) {
        if (control.scanState === 'pending') {
          control.scanState = null;
          if (!control.manualPending && !control.result) setState(control, 'idle');
        }
        if (previous.language !== settings.language) resetControl(root, control, control.key);
      }
    }
    for (const [root, control] of controls) {
      if (control.button.dataset.state === 'idle') setState(control, 'idle');
      if (!settings.showHighlights) clearHighlights(control);
      else if (control.result) { const post = extract(root); if (post) applyResult(root, control, post, control.result); }
      syncTheme(root, control);
    }
    pumpScans();
  }

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id) return;
    if (request?.type === 'CLAR_SETTINGS_CHANGED') { updateSettings(request.settings); return; }
    if (request?.type === 'CLAR_POST_PROGRESS') {
      for (const [root, control] of controls) {
        if (control.key !== request.postKey || !control.manualPending || extract(root)?.text !== request.text) continue;
        const message = request.progress?.queued ? copy('queued') : copy('analyzing');
        setState(control, 'pending', message);
        control.button.title = message;
      }
      return;
    }
    if (request?.type === 'CLAR_RESULT') {
      for (const [root, control] of controls) {
        if (control.key !== request.postKey) continue;
        const post = extract(root);
        if (post?.text === request.text) applyResult(root, control, post, request.result);
      }
      return;
    }
    if (request?.type === 'CLAR_CLEAR_RESULTS') {
      scanGeneration += 1;
      closeTooltip();
      closePopover();
      for (const [root, control] of controls) {
        resetControl(root, control, control.key);
        control.scanState = 'cleared';
      }
      return;
    }
    if (request?.type !== 'CLAR_GET_SELECTION') return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount !== 1) {
      sendResponse({ ok: false, error: 'Select text within one Facebook post first.' });
      return;
    }
    const range = selection.getRangeAt(0);
    const root = postRoot(range.startContainer);
    const message = root && messageFor(root);
    // Both ends must belong to the same message, excluding authors and comments.
    if (!root || root !== postRoot(range.endContainer) || !message?.contains(range.startContainer) || !message.contains(range.endContainer)) {
      sendResponse({ ok: false, error: 'Select text within a single post message.' });
      return;
    }
    const selectedText = selection.toString().trim();
    const post = extract(root, selectedText);
    sendResponse(post ? { ok: true, post, postKey: postKey(post) } : { ok: false, error: 'The selected post is unavailable.' });
  });

  // Facebook may set the photo source after inserting a lazy-loaded image.
  document.addEventListener('load', event => {
    if (event.target instanceof HTMLImageElement && event.target.closest('a[href*="/photo"]')) {
      scheduleScan();
    }
  }, true);
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['data-ad-preview', 'data-ad-comet-preview', 'data-pagelet', 'data-virtualized', 'role', 'src', 'srcset'] });
  for (const eventName of ['pointerover', 'focusin']) document.addEventListener(eventName, event => {
    const mark = event.target instanceof Element && event.target.closest('[data-clar-highlight]');
    if (mark) showTooltip(mark);
  });
  for (const eventName of ['pointerout', 'focusout']) document.addEventListener(eventName, event => {
    const mark = event.target instanceof Element && event.target.closest('[data-clar-highlight]');
    if (mark && mark === tooltipTarget && !mark.contains(event.relatedTarget)) closeTooltip();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && (tooltip || popover)) { event.preventDefault(); event.stopPropagation(); closeTooltip(); closePopover(true); } }, true);
  document.addEventListener('pointerdown', event => {
    if (!popover) return;
    const path = event.composedPath();
    if (!path.includes(popover.host) && !path.includes(popover.control.host)) closePopover();
  }, true);
  addEventListener('scroll', () => { closeTooltip(); schedulePosition(); scheduleScan(); }, {passive: true, capture: true});
  addEventListener('resize', () => { closeTooltip(); schedulePosition(); scheduleScan(); }, {passive: true});
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { for (const [root, control] of controls) syncTheme(root, control); });
  const themeObserver = new MutationObserver(() => { for (const [root, control] of controls) syncTheme(root, control); });
  themeObserver.observe(document.documentElement, {attributes: true, attributeFilter: ['class', 'style', 'data-theme']});
  if (document.body) themeObserver.observe(document.body, {attributes: true, attributeFilter: ['class', 'style', 'data-theme']});
  scan();
  Promise.resolve().then(() => chrome.runtime.sendMessage({ type: 'CLAR_GET_PUBLIC_SETTINGS' })).then(response => {
    if (response?.ok && response.settings) updateSettings(response.settings);
  }).catch(() => { /* Stay opted out until a trusted settings response arrives. */ });
})();
