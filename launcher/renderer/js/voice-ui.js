/**
 * voice-ui.js — JARVIS Voice UI Controller
 * Manages the voice page WebSocket connection,
 * orb animations, transcript display, and state machine.
 *
 * States: IDLE → LISTENING → PROCESSING → SPEAKING → IDLE
 */

const VoiceUI = (() => {

  const BACKEND_WS = 'ws://localhost:8000/voice/ws';

  let ws        = null;
  let state     = 'IDLE';
  let reconnectTimer = null;

  // DOM refs (set on init)
  let orb, statusText, transcript, micBtn, stopBtn;

  // ── State machine ─────────────────────────────────────────
  const STATES = {
    IDLE: {
      orbClass:    '',
      status:      'SAY JARVIS OR TAP',
      micLabel:    '● START',
    },
    LISTENING: {
      orbClass:    'listening',
      status:      'LISTENING...',
      micLabel:    '● LISTENING',
    },
    PROCESSING: {
      orbClass:    'processing',
      status:      'PROCESSING...',
      micLabel:    '◌ THINKING',
    },
    SPEAKING: {
      orbClass:    'speaking',
      status:      'SPEAKING...',
      micLabel:    '◈ SPEAKING',
    },
  };

  function setState(s) {
    state = s;
    const cfg = STATES[s] || STATES.IDLE;
    if (orb) {
      orb.className = 'orb' + (cfg.orbClass ? ' ' + cfg.orbClass : '');
    }
    if (statusText) statusText.textContent = cfg.status;
    if (micBtn)     micBtn.textContent     = cfg.micLabel;
  }

  function showTranscript(text, role = 'system') {
    if (!transcript) return;
    transcript.className = 'transcript-box';
    transcript.textContent = (role === 'user' ? 'YOU: ' : 'JARVIS: ') + text;
  }

  // ── WebSocket ────────────────────────────────────────────
  function connect() {
    if (ws && ws.readyState <= 1) return;

    ws = new WebSocket(BACKEND_WS);

    ws.onopen = () => {
      console.log('[voice] WS connected');
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    };

    ws.onmessage = (e) => {
      let data;
      try { data = JSON.parse(e.data); } catch { return; }
      handleServerEvent(data);
    };

    ws.onclose = () => {
      console.log('[voice] WS disconnected — reconnecting in 3s');
      setState('IDLE');
      reconnectTimer = setTimeout(connect, 3000);
    };

    ws.onerror = (err) => console.error('[voice] WS error', err);
  }

  function send(data) {
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify(data));
    }
  }

  // ── Server events ────────────────────────────────────────
  function handleServerEvent(data) {
    switch (data.type) {
      case 'listening':
        setState('LISTENING');
        showTranscript('Listening...', 'system');
        break;

      case 'processing':
        setState('PROCESSING');
        showTranscript('Processing...', 'system');
        break;

      case 'transcript':
        showTranscript(data.text, 'user');
        break;

      case 'response':
        setState('SPEAKING');
        showTranscript(data.text, 'assistant');
        break;

      case 'speaking':
        setState('SPEAKING');
        break;

      case 'empty':
        setState('IDLE');
        showTranscript('Nothing heard. Try again.', 'system');
        break;

      case 'no_wake':
        setState('IDLE');
        showTranscript('Say "Jarvis" to wake, or tap to speak.', 'system');
        break;

      case 'error':
        setState('IDLE');
        showTranscript('[ERROR] ' + (data.message || 'Unknown error'), 'system');
        break;

      case 'pong':
        break;

      default:
        // After speaking finishes, return to idle
        if (state === 'SPEAKING') {
          setTimeout(() => setState('IDLE'), 2000);
        }
    }
  }

  // ── Controls ─────────────────────────────────────────────
  function startListening() {
    if (state !== 'IDLE') return;
    send({ type: 'start' });
    setState('LISTENING');
  }

  function stopListening() {
    if (state !== 'LISTENING') return;
    send({ type: 'stop' });
    setState('PROCESSING');
  }

  function toggleListen() {
    if (state === 'IDLE')      startListening();
    else if (state === 'LISTENING') stopListening();
  }

  // ── Init ─────────────────────────────────────────────────
  function init() {
    orb        = document.getElementById('orb');
    statusText = document.getElementById('voice-status');
    transcript = document.getElementById('transcript');
    micBtn     = document.getElementById('mic-btn');
    stopBtn    = document.getElementById('stop-btn');

    if (!orb) return;   // not on voice page

    orb.addEventListener('click', toggleListen);
    micBtn?.addEventListener('click', () => state === 'LISTENING' ? stopListening() : startListening());
    stopBtn?.addEventListener('click', stopListening);

    // Keep-alive ping every 20s
    setInterval(() => send({ type: 'ping' }), 20000);

    // Auto-return to IDLE after speaking
    setInterval(() => {
      if (state === 'SPEAKING') setState('IDLE');
    }, 4000);

    connect();
    setState('IDLE');
  }

  return { init, startListening, stopListening, toggleListen, getState: () => state };
})();

// Auto-init when DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', VoiceUI.init);
} else {
  VoiceUI.init();
}
