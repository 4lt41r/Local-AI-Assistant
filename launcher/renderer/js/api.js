/**
 * api.js — Backend HTTP + WebSocket client
 */

const API = (() => {
  const BASE = 'http://localhost:8000';
  let ws = null;
  let wsListeners = {};

  // ── HTTP ──────────────────────────────────────
  async function get(path) {
    const r = await fetch(`${BASE}${path}`);
    return r.json();
  }

  async function post(path, body) {
    const r = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    return r.json();
  }

  // ── WebSocket ─────────────────────────────────
  function connectWS(onMessage) {
    if (ws && ws.readyState <= 1) return;
    ws = new WebSocket('ws://localhost:8000/ws');
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (wsListeners[data.type]) wsListeners[data.type](data);
        if (onMessage) onMessage(data);
      } catch {}
    };
    ws.onclose = () => setTimeout(connectWS, 3000);
  }

  function onEvent(type, cb) { wsListeners[type] = cb; }

  function sendWS(data) {
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify(data));
    }
  }

  // ── Health ─────────────────────────────────────
  async function checkHealth() {
    try {
      const r = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) });
      return r.ok;
    } catch { return false; }
  }

  // ── Chat ───────────────────────────────────────
  async function chat(message, model = null) {
    return post('/chat', { message, model });
  }

  // ── Models ─────────────────────────────────────
  async function getModels()      { return get('/models'); }
  async function loadModel(name)  { return post('/models/load', { name }); }

  // ── System ─────────────────────────────────────
  async function getSystemStats() { return get('/system/stats'); }

  return { get, post, connectWS, onEvent, sendWS, checkHealth, chat, getModels, loadModel, getSystemStats };
})();

window.API = API;
