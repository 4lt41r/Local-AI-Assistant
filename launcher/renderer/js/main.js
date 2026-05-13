/**
 * main.js — App bootstrap, window controls, status polling
 */

document.addEventListener('DOMContentLoaded', async () => {

  // ── Window controls ──────────────────────────
  document.getElementById('btn-minimize')?.addEventListener('click', () => window.jarvis?.minimize());
  document.getElementById('btn-maximize')?.addEventListener('click', () => window.jarvis?.maximize());
  document.getElementById('btn-close')?.addEventListener('click',    () => window.jarvis?.close());

  // ── Backend health polling ───────────────────
  const statusDot = document.getElementById('backend-status');

  async function pollStatus() {
    const alive = await API.checkHealth();
    statusDot.className = 'status-dot ' + (alive ? 'online' : 'offline');
  }

  statusDot.className = 'status-dot loading';
  await pollStatus();
  setInterval(pollStatus, 8000);

  // ── WebSocket connection ─────────────────────
  API.connectWS();
});
