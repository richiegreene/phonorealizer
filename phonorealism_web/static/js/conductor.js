/*
 * conductor.js — the conductor's device.
 *
 * Loads and parses the score locally (both format readers live in the browser,
 * so there is exactly one implementation of each), uploads the normalised form
 * for the performers to fetch, and then does the one thing that has to be
 * centralised: name the instant of the downbeat.
 *
 * The readiness grid is the point of this screen. Before starting you can see
 * who has claimed what, whose microphone is live, and — importantly — how
 * tightly each device is locked to the hub's clock, so a bad network is
 * something you notice before the downbeat rather than after it.
 */

import { Net, uploadScore, uploadAnnotations } from './net.js';
import { loadScoreFile, scoreToJSON, defaultParts, partLabel } from '/shared/score.js';

const $ = (id) => document.getElementById(id);

const el = {
  loadBtn: $('loadBtn'),
  fileInput: $('fileInput'),
  scoreInfo: $('scoreInfo'),
  scoreName: $('scoreName'),
  scoreErr: $('scoreErr'),
  ampCurve: $('ampCurve'),
  qrBox: $('qrBox'),
  joinUrl: $('joinUrl'),
  joinHint: $('joinHint'),
  insecureNote: $('insecureNote'),
  partEditor: $('partEditor'),
  autoParts: $('autoParts'),
  addPart: $('addPart'),
  exportParts: $('exportParts'),
  importParts: $('importParts'),
  partsFile: $('partsFile'),
  players: $('players'),
  leadIn: $('leadIn'),
  leadLabel: $('leadLabel'),
  startBtn: $('startBtn'),
  stopBtn: $('stopBtn'),
  readyHint: $('readyHint'),
  partsStatus: $('partsStatus'),
  connPill: $('connPill'),
};

const state = {
  score: null,
  parts: [],
  lastFile: null,
  meters: new Map(),
};

const net = new Net({ role: 'conductor', name: 'conductor' });

/* ------------------------------------------------------------------ *
 * Score loading
 * ------------------------------------------------------------------ */

el.loadBtn.onclick = () => el.fileInput.click();

el.fileInput.onchange = async () => {
  const file = el.fileInput.files[0];
  if (file) {
    state.lastFile = file;
    await ingest(file);
  }
};

// Changing the amplitude interpretation means re-reading the source file:
// it changes the numbers, not just how they are drawn.
el.ampCurve.onchange = async () => {
  if (state.lastFile) await ingest(state.lastFile);
};

async function ingest(file) {
  el.scoreErr.classList.add('hidden');
  el.scoreInfo.textContent = 'Reading…';
  try {
    const score = await loadScoreFile(file, { ampCurve: el.ampCurve.value });
    state.score = score;
    state.parts = defaultParts(score);
    score.parts = state.parts;

    el.scoreName.textContent = score.name;
    el.scoreInfo.textContent =
      `${score.partials.length} partials · ${score.duration.toFixed(1)} s · ` +
      `${score.pointCount.toLocaleString()} points · ${score.source}` +
      (score.simplified ? ' · thinned' : '');

    const json = scoreToJSON(score);
    await uploadScore(json);
    renderPartEditor();
    net.setParts(state.parts);
  } catch (err) {
    el.scoreErr.textContent = err.message;
    el.scoreErr.classList.remove('hidden');
    el.scoreInfo.textContent = 'justidraw .sav or phonorealizer CSV';
  }
}

/* ------------------------------------------------------------------ *
 * Part map editing
 * ------------------------------------------------------------------ */

/**
 * Rebuilding this list is destructive: each row holds a text input, so a
 * rebuild while the conductor is mid-word throws away what they were typing
 * and drops the caret. State broadcasts arrive on every performer heartbeat,
 * so the rebuild has to be gated on the content actually having changed.
 */
function partEditorSignature() {
  const claims = (net.session?.clients || [])
    .filter((c) => c.part_id)
    .map((c) => `${c.part_id}:${c.name}`)
    .sort()
    .join('|');
  const parts = state.parts.map((p) => `${p.id}~${p.name}~${p.partials.join('.')}`).join('|');
  return `${state.score ? state.score.name : ''}#${parts}#${claims}`;
}

let partEditorSig = null;

function renderPartEditor(force = false) {
  const sig = partEditorSignature();
  if (!force && sig === partEditorSig) return;
  partEditorSig = sig;

  el.partEditor.innerHTML = '';
  if (!state.score) {
    el.partEditor.innerHTML = '<div class="hint">Load a score first.</div>';
    return;
  }

  const claimed = new Map();
  for (const c of net.session?.clients || []) {
    if (c.part_id) claimed.set(c.part_id, c.name || 'unnamed');
  }

  for (const part of state.parts) {
    const row = document.createElement('div');
    row.className = 'part';
    row.style.cursor = 'default';

    const info = document.createElement('div');
    info.style.flex = '1';
    info.style.minWidth = '0';

    const name = document.createElement('input');
    name.type = 'text';
    name.value = part.name;
    name.style.marginBottom = '4px';
    name.onchange = () => {
      part.name = name.value.trim() || part.name;
      part.auto = false;
      pushParts();
    };

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = `partials ${part.partials.join(', ')} · ${partLabel(state.score, part)}`;

    info.append(name, meta);
    row.append(info);

    if (claimed.has(part.id)) {
      const who = document.createElement('div');
      who.className = 'who';
      who.textContent = claimed.get(part.id);
      row.append(who);
    }

    const del = document.createElement('button');
    del.className = 'sm ghost';
    del.textContent = '✕';
    del.onclick = () => {
      state.parts = state.parts.filter((p) => p !== part);
      pushParts();
      renderPartEditor();
    };
    row.append(del);

    el.partEditor.append(row);
  }
}

function pushParts() {
  if (state.score) state.score.parts = state.parts;
  net.setParts(state.parts);
}

el.autoParts.onclick = () => {
  if (!state.score) return;
  state.parts = defaultParts(state.score);
  pushParts();
  renderPartEditor();
};

el.addPart.onclick = () => {
  if (!state.score) return;
  const name = prompt('Part name (e.g. "Violin 1")');
  if (!name) return;
  const spec = prompt(
    `Which partials? 1–${state.score.partials.length}. ` +
      'Comma separated, ranges allowed (e.g. "3, 7, 12-14")'
  );
  if (!spec) return;
  const partials = parsePartialSpec(spec, state.score.partials.length);
  if (!partials.length) {
    alert('No valid partial numbers in that.');
    return;
  }
  state.parts.push({
    id: `g${Date.now().toString(36)}`,
    name: name.trim(),
    partials,
    auto: false,
  });
  pushParts();
  renderPartEditor();
};

/** Parse "3, 7, 12-14" into [3,7,12,13,14], clamped to the score. */
function parsePartialSpec(spec, max) {
  const out = new Set();
  for (const chunk of spec.split(',')) {
    const range = chunk.trim().match(/^(\d+)\s*[-–]\s*(\d+)$/);
    if (range) {
      const a = parseInt(range[1], 10);
      const b = parseInt(range[2], 10);
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) {
        if (i >= 1 && i <= max) out.add(i);
      }
    } else {
      const n = parseInt(chunk.trim(), 10);
      if (n >= 1 && n <= max) out.add(n);
    }
  }
  return [...out].sort((a, b) => a - b);
}

el.exportParts.onclick = () => {
  const blob = new Blob([JSON.stringify({ v: 1, parts: state.parts }, null, 2)], {
    type: 'application/json',
  });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${(state.score?.name || 'parts').replace(/\s+/g, '_')}_parts.json`;
  a.click();
  URL.revokeObjectURL(a.href);
};

el.importParts.onclick = () => el.partsFile.click();

/**
 * Accepts either a bare part map or a full engraving project from
 * phonorealism_engraver. The engraver owns the part map, so importing its
 * project adopts both the parts and the marks in one step — keeping them
 * together is the point, since marks are addressed by part id.
 */
el.partsFile.onchange = async () => {
  const f = el.partsFile.files[0];
  if (!f) return;
  try {
    const obj = JSON.parse(await f.text());
    if (!Array.isArray(obj.parts)) throw new Error('no parts array');
    state.parts = obj.parts;
    pushParts();
    renderPartEditor(true);
    el.partsStatus.textContent = `Imported ${obj.parts.length} parts.`;

    if (obj.kind === 'phonorealism-engraving') {
      const res = await uploadAnnotations(obj);
      el.scoreErr.classList.add('hidden');
      el.partsStatus.textContent =
        `Imported ${res.parts} parts and ${res.annotations} marks from the engraver.`;
    }
  } catch (err) {
    alert(`Could not read that file: ${err.message}`);
  }
};

/* ------------------------------------------------------------------ *
 * Ensemble readiness
 * ------------------------------------------------------------------ */

/** Live meter elements, so the 4 Hz refresh does not rebuild the whole grid. */
const meterEls = new Map();
let rosterSig = null;

function renderPlayers() {
  const clients = (net.session?.clients || []).filter((c) => c.role === 'performer');

  // Cheap path: the roster is unchanged, so only the moving numbers need
  // touching. Rebuilding the grid four times a second would otherwise fight
  // the conductor for the scroll position on a long ensemble list.
  const sig = clients
    .map((c) => `${c.id}~${c.name}~${c.part_id}~${c.ready}~${c.mic}~${(c.spread ?? -1).toFixed(0)}`)
    .join('|');
  if (sig === rosterSig) {
    for (const c of clients) {
      const refs = meterEls.get(c.id);
      if (!refs) continue;
      const m = state.meters.get(c.id);
      const dev = m && m.conf > 0.15 && m.cents != null ? m.cents : null;
      refs.bar.style.width = `${Math.min(100, (m?.amp || 0) * 100)}%`;
      refs.devText.textContent =
        dev == null ? '—' : `${dev > 0 ? '+' : ''}${dev.toFixed(0)}¢`;
      refs.devDot.className = `dot ${
        dev == null ? '' : Math.abs(dev) <= 10 ? 'good' : Math.abs(dev) <= 30 ? 'fair' : 'bad'
      }`;
    }
    updateStartButton(clients);
    return;
  }
  rosterSig = sig;
  meterEls.clear();

  if (!clients.length) {
    el.players.innerHTML = '<div class="hint">Nobody has joined yet.</div>';
    updateStartButton(clients);
    return;
  }

  el.players.innerHTML = '';
  for (const c of clients) {
    const part = state.parts.find((p) => p.id === c.part_id);
    const card = document.createElement('div');
    card.className = 'player' + (c.ready ? ' ready' : '');

    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = c.name || `player ${c.id.slice(0, 4)}`;

    const pn = document.createElement('div');
    pn.className = 'part-name';
    pn.textContent = part ? part.name : 'no part chosen';

    const stats = document.createElement('div');
    stats.className = 'stats';
    stats.append(
      pill(c.mic ? 'good' : 'bad', c.mic ? 'mic' : 'no mic'),
      pill(c.ready ? 'good' : '', c.ready ? 'ready' : 'standby'),
      pill(gradeFor(c.spread), c.spread == null ? 'no sync' : `±${c.spread.toFixed(0)} ms`)
    );

    const m = state.meters.get(c.id);
    const dev = m && m.conf > 0.15 && m.cents != null ? m.cents : null;
    const devPill = pill(
      dev == null ? '' : Math.abs(dev) <= 10 ? 'good' : Math.abs(dev) <= 30 ? 'fair' : 'bad',
      dev == null ? '—' : `${dev > 0 ? '+' : ''}${dev.toFixed(0)}¢`
    );
    stats.append(devPill);

    const meter = document.createElement('div');
    meter.className = 'meter';
    const bar = document.createElement('i');
    bar.style.width = `${Math.min(100, (m?.amp || 0) * 100)}%`;
    meter.append(bar);

    meterEls.set(c.id, {
      bar,
      devDot: devPill.querySelector('.dot'),
      devText: devPill.querySelector('span'),
    });

    card.append(who, pn, stats, meter);
    el.players.append(card);
  }
  updateStartButton(clients);
}

function pill(grade, text) {
  const s = document.createElement('span');
  s.className = 'pill';
  const d = document.createElement('i');
  d.className = `dot ${grade}`;
  const t = document.createElement('span');
  t.textContent = text;
  s.append(d, t);
  return s;
}

function gradeFor(spread) {
  if (spread == null) return '';
  if (spread <= 8) return 'good';
  if (spread <= 25) return 'fair';
  return 'bad';
}

/**
 * Start stays enabled as long as a score is loaded and somebody has a part —
 * the conductor's discretion is the point, so an unready player is reported,
 * never a veto.
 */
function updateStartButton(clients) {
  const withPart = clients.filter((c) => c.part_id);
  const ready = withPart.filter((c) => c.ready && c.mic);
  el.startBtn.disabled = !state.score || withPart.length === 0;

  const worst = clients.reduce(
    (m, c) => (c.spread != null && c.spread > m ? c.spread : m),
    0
  );
  const bits = [`${ready.length}/${withPart.length} ready`];
  if (worst > 0) bits.push(`worst sync ±${worst.toFixed(0)} ms`);
  if (worst > 25) bits.push('— consider a better network before starting');
  el.readyHint.textContent = bits.join(' · ');
}

/* ------------------------------------------------------------------ *
 * Transport
 * ------------------------------------------------------------------ */

el.leadIn.oninput = () => {
  el.leadLabel.textContent = `Lead-in — ${parseFloat(el.leadIn.value).toFixed(1)} s`;
};

el.startBtn.onclick = () => net.start(parseFloat(el.leadIn.value) * 1000);
el.stopBtn.onclick = () => net.stop();

/* ------------------------------------------------------------------ *
 * Join details
 * ------------------------------------------------------------------ */

async function loadJoinInfo() {
  try {
    const info = await (await fetch('/api/info')).json();

    // If the conductor opened this page on localhost, `joinUrl` points at
    // loopback — and every phone that scanned it would resolve that to itself.
    // Hand out the LAN address instead, which is the one other devices in the
    // room can actually reach.
    const isLoopback = /^(https?:\/\/)?(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i;
    const join =
      isLoopback.test(info.joinUrl) && info.lanUrl && !isLoopback.test(info.lanUrl)
        ? info.lanUrl
        : info.joinUrl;
    el.joinUrl.textContent = join;
    if (join !== info.joinUrl) {
      el.joinHint.textContent =
        'You are viewing this on localhost; the code above is the address other ' +
        'devices on this network need.';
    }

    if (!info.secure) {
      el.insecureNote.classList.remove('hidden');
      el.insecureNote.innerHTML =
        '<strong>This origin cannot use microphones.</strong> Performers joining ' +
        'over plain http will be refused microphone access by their browser. ' +
        'Expose the hub over your domain with <code>cloudflared tunnel --url ' +
        'http://localhost:8000</code>, or restart the hub with <code>--tls</code>.';
    }

    const res = await fetch(`/api/qr?url=${encodeURIComponent(join)}`);
    if (res.ok) {
      el.qrBox.innerHTML = await res.text();
    } else {
      el.qrBox.remove();
      el.joinHint.textContent = 'Install `segno` for a scannable code, or type the URL above.';
    }
  } catch {
    el.joinUrl.textContent = `${location.origin}/performer`;
  }
}

/* ------------------------------------------------------------------ *
 * Hub events
 * ------------------------------------------------------------------ */

net.addEventListener('state', (ev) => {
  const s = ev.detail;
  // Adopt the hub's part list when we have none — e.g. after a page reload
  // mid-rehearsal, where the score is already cached server-side.
  if (!state.parts.length && s.parts?.length) {
    state.parts = s.parts;
    renderPartEditor();
  }
  if (s.scoreMeta && !state.score) {
    el.scoreName.textContent = s.scoreMeta.name;
    el.scoreInfo.textContent =
      `${s.scoreMeta.partials} partials · ${(s.scoreMeta.duration || 0).toFixed(1)} s · ` +
      `${s.scoreMeta.source} · loaded earlier`;
  }
  renderPlayers();
  renderPartEditor();
});

net.addEventListener('meter', (ev) => {
  const m = ev.detail;
  state.meters.set(m.id, { cents: m.cents, amp: m.amp, conf: m.conf });
});

net.addEventListener('sync', () => {
  const q = net.quality;
  el.connPill.querySelector('.dot').className = `dot ${q.grade}`;
  el.connPill.querySelector('span').textContent = q.locked
    ? `hub ±${q.spread.toFixed(0)} ms`
    : 'hub';
});

net.addEventListener('close', () => {
  el.connPill.querySelector('.dot').className = 'dot bad';
  el.connPill.querySelector('span').textContent = 'reconnecting';
});

/* ------------------------------------------------------------------ *
 * Boot
 * ------------------------------------------------------------------ */

el.leadIn.oninput();
renderPartEditor();
loadJoinInfo();
net.connect();
// The meter stream is high rate; repaint on a timer rather than per message.
setInterval(renderPlayers, 250);
