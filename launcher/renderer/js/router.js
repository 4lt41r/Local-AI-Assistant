/**
 * router.js — Multi-iframe SPA router for JARVIS
 *
 * Each page gets its own persistent iframe, created once on startup and
 * kept alive for the entire session. Navigating just toggles display:none/block.
 * This preserves all JS state — WebSocket connections, chat history, DOM —
 * across tab switches without any reloads.
 */

const Router = (() => {

  const PAGE_MAP = {
    home:     'pages/home.html',
    chat:     'pages/chat.html',
    code:     'pages/code.html',
    voice:    'pages/voice.html',
    settings: 'pages/settings.html',
  };

  let currentPage = null;
  const frames    = {};   // page -> iframe element
  const loaded    = {};   // page -> bool (iframe fired 'load')

  function init() {
    const container = document.getElementById('page-container');
    const loader    = document.getElementById('page-loading');

    // Container must be positioned for absolute children
    container.style.position = 'relative';
    container.style.overflow = 'hidden';

    // Pre-create all iframes hidden — they start loading in background immediately
    Object.entries(PAGE_MAP).forEach(([page, src]) => {
      const f   = document.createElement('iframe');
      f.id      = `frame-${page}`;
      f.src     = src;
      f.style.cssText =
        'position:absolute;top:0;left:0;width:100%;height:100%;' +
        'border:none;display:none;opacity:0;transition:opacity 0.25s;';

      container.appendChild(f);
      frames[page] = f;
      loaded[page] = false;

      f.addEventListener('load', () => {
        loaded[page] = true;
        // Only reveal if this is the page currently being shown
        if (currentPage === page) {
          loader.style.display = 'none';
          f.style.opacity = '1';
        }
      });
    });

    // Wire nav clicks
    document.querySelectorAll('.nav-item[data-page]').forEach(el => {
      el.addEventListener('click', () => navigate(el.dataset.page));
    });

    navigate('home');
  }

  function navigate(page) {
    if (!PAGE_MAP[page] || page === currentPage) return;

    // Update sidebar active state
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.page === page);
    });

    // Hide the current page without destroying it
    if (currentPage && frames[currentPage]) {
      frames[currentPage].style.display = 'none';
      frames[currentPage].style.opacity = '0';
    }

    currentPage = page;
    const loader = document.getElementById('page-loading');

    if (loaded[page]) {
      // Already loaded — instant reveal
      frames[page].style.display = 'block';
      frames[page].style.opacity = '1';
      loader.style.display = 'none';
    } else {
      // Still loading — show spinner until iframe fires 'load'
      loader.style.display = 'flex';
      frames[page].style.display = 'block';
    }
  }

  return { init, navigate, currentPage: () => currentPage };
})();

document.addEventListener('DOMContentLoaded', () => Router.init());
