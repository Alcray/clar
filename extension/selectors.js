(() => {
  'use strict';
  // Deliberately use Facebook's rendered post boundaries, never private React state.
  // Keep all DOM heuristics here so a feed markup change has one place to fix.
  globalThis.CLAR_SELECTORS = Object.freeze({
    message: '[data-ad-preview="message"], [data-ad-comet-preview="message"]',
    fallbackMessage: '[data-testid="post_message"], [data-testid="post-message"], .userContent',
    boundary: '[data-pagelet^="FeedUnit"], [data-virtualized]',
    article: '[role="article"]',
    author: 'h2 a[href], h3 a[href], h4 a[href], [role="heading"] a[href]',
    heading: 'h2, h3, h4, [role="heading"]',
    excluded: [
      '[data-clar-control]', '[data-clar-tooltip]', 'nav', '[role="navigation"]', '[role="dialog"]',
      'blockquote', '[data-commentid]', '[data-testid*="comment"]', '[data-pagelet*="Comment"]',
      '[data-testid*="shared"]', '[data-pagelet*="Shared"]', '[aria-label^="Comment by"]',
      '[aria-label^="Reply by"]', '[aria-label="Shared post"]'
    ].join(','),
    skipText: 'button, [role="button"], script, style, svg, [aria-hidden="true"], [hidden], [data-clar-control], [data-clar-tooltip]',
    interactive: 'a, button, input, textarea, select, [role="button"], [contenteditable="true"], [tabindex]:not([data-clar-highlight])',
    photo: 'a[href*="/photo"] img',
  });
})();
