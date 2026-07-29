/*
 * performer.js — the player's device.
 *
 * Lifecycle: join the hub, claim a part, open the microphone, declare ready,
 * then wait. The conductor's start message carries one hub timestamp; this
 * device converts it through its own measured clock offset and schedules both
 * the audio and the scroll against it. After that the network is irrelevant —
 * everything runs off the local AudioContext clock.
 */

import { Net, fetchScore } from './net.js';
import { scoreFromJSON, partPartials, partLabel, hzToNoteName } from './score.js';
import { MicAnalyser, Smoother } from './analyser.js';
import { ScorePlayer, scheduleCountIn } from './synth.js';
import { PerformanceView } from './render.js';

const $ = (id) => document.getElementById(id);

const el = {
  lobby: $('lobby'),
  stage: $('stage'),
  settings: $('settings'),
  view: $('view'),
  waiting: $('waiting'),
  waitingBig: $('waitingBig'),
  waitingHint: $('waitingHint'),
  partTitle: $('partTitle'),
  scoreName: $('scoreName'),
  syncPill: $('syncPill'),
  partList: $('partList'),
  nameInput: $('nameInput'),
  micBtn: $('micBtn'),
  calBtn: $('calBtn'),
  micHint: $('micHint'),
  readyBtn: $('readyBtn'),
  readyStatus: $('readyStatus'),
  insecureWarn: $('insecureWarn'),
  settingsBtn: $('settingsBtn'),
  closeSettings: $('closeSettings'),
  backBtn: $('backBtn'),
  balance: $('balance'),
  balLabel: $('balLabel'),
  volume: $('volume'),
  volLabel: $('volLabel'),
  timeWindow: $('timeWindow'),
  winLabel: $('winLabel'),
  pitchSpan: $('pitchSpan'),
  spanLabel: $('spanLabel'),
  modeBtn: $('modeBtn'),
  ensembleBtn: $('ensembleBtn'),
  band: $('band'),
  bandLabel: $('bandLabel'),
  transpose: $('transpose'),
  timbre: $('timbre'),
  timbreLabel: $('timbreLabel'),
  waveView: $('waveView'),
  inputDevice: $('inputDevice'),
  inputGain: $('inputGain'),
  gainLabel: $('gainLabel'),
};

const state = {
  score: null,
  scoreJSON: null,
  part: null,
  partials: [],
  others: [],
  transposeCents: 0,
  timbre: 100, // 0 sine, 100 triangle, 200 saw, 300 square
  calibrationGain: 1,
  gainDb: 0,
  running: false,
  ready: false,
  startAtServer: null,
  scoreTime: 0,
  prepared: false,
};

const net = new Net({ role: 'performer', name: localStorage.getItem('pr.name') || '' });
const mic = new MicAnalyser();
const view = new PerformanceView(el.view);
const pitchSmooth = new Smoother(0.45);
const ampSmooth = new Smoother(0.35);

let ctx = null;
let player = null;
let lastMeterSent = 0;

/* ------------------------------------------------------------------ *
 * Secure-context gate
 * ------------------------------------------------------------------ */

if (!window.isSecureContext) {
  el.insecureWarn.classList.remove('hidden');
  el.micBtn.disabled = true;
  el.micHint.textContent =
    'Unavailable on this origin. See the notice above — this is a browser rule, not a setting.';
}

/* ------------------------------------------------------------------ *
 * Transposition
 * ------------------------------------------------------------------ */

/**
 * Build transposed copies of the partials. Both the in-ear reference and the
 * pitch the performer is measured against have to move together, or the display
 * would be asking for one octave while the ear is being given another.
 */
function transposed(partials, cents) {
  if (!cents) return partials;
  const r = Math.pow(2, cents / 1200);
  return partials.map((p) => {
    const q = Object.create(Object.getPrototypeOf(p));
    Object.assign(q, p);
    q.f = Float64Array.from(p.f, (v) => v * r);
    q.fMin = p.fMin * r;
    q.fMax = p.fMax * r;
    q.fMed = p.fMed * r;
    return q;
  });
}

function applyPartSelection() {
  if (!state.score || !state.part) {
    state.partials = [];
    state.others = [];
    view.setScore(null, [], []);
    return;
  }
  const own = partPartials(state.score, state.part);
  const ownSet = new Set(own.map((p) => p.index));
  const others = state.score.partials.filter((p) => !ownSet.has(p.index));

  state.partials = transposed(own, state.transposeCents);
  state.others = transposed(others, state.transposeCents);
  view.setScore(state.score, state.partials, state.others);

  el.partTitle.textContent = state.part.name;
  state.prepared = false;
}

/* ------------------------------------------------------------------ *
 * Score + parts UI
 * ------------------------------------------------------------------ */

async function loadScore() {
  const json = await fetchScore();
  if (!json) return;
  state.scoreJSON = json;
  state.score = scoreFromJSON(json);
  el.scoreName.textContent = `${state.score.name} · ${state.score.duration.toFixed(1)} s`;
  // A re-uploaded score renumbers nothing (indices are canonical), but the
  // claimed part may no longer exist.
  if (state.part) {
    const still = (net.session?.parts || []).find((p) => p.id === state.part.id);
    state.part = still || null;
  }
  renderParts();
  applyPartSelection();
}

function renderParts() {
  const parts = net.session?.parts || [];
  if (!state.score || !parts.length) {
    el.partList.innerHTML = '<div class="hint">Waiting for the conductor to load a score…</div>';
    return;
  }

  const takenBy = new Map();
  for (const c of net.session.clients || []) {
    if (c.role === 'performer' && c.part_id && c.id !== net.id) {
      takenBy.set(c.part_id, c.name || 'someone');
    }
  }

  el.partList.innerHTML = '';
  for (const part of parts) {
    const btn = document.createElement('button');
    btn.className = 'part';
    if (state.part && state.part.id === part.id) btn.classList.add('selected');
    const who = takenBy.get(part.id);
    if (who) btn.classList.add('taken');

    const info = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = part.name;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = partLabel(state.score, part);
    info.append(name, meta);
    btn.append(info);

    if (who) {
      const w = document.createElement('div');
      w.className = 'who';
      w.textContent = who;
      btn.append(w);
    }

    btn.onclick = () => {
      state.part = part;
      net.claim(part.id);
      applyPartSelection();
      renderParts();
      updateReadyButton();
    };
    el.partList.append(btn);
  }
}

/* ------------------------------------------------------------------ *
 * Microphone
 * ------------------------------------------------------------------ */

function ensureContext() {
  if (!ctx) {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    mic.ctx = ctx;
    player = new ScorePlayer(ctx);
    player.setBalance(parseFloat(el.balance.value));
    player.setVolume(parseFloat(el.volume.value));
  }
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}

el.micBtn.onclick = async () => {
  ensureContext();
  el.micBtn.disabled = true;
  el.micBtn.textContent = 'Requesting…';
  try {
    await mic.start({ deviceId: el.inputDevice.value || undefined });
    el.micBtn.textContent = 'Microphone live';
    el.micBtn.classList.remove('primary');
    el.calBtn.disabled = false;
    net.status({ mic: true });
    // Enable Ready in the same tick the label changes. Doing this after the
    // awaited device enumeration leaves a window where the page claims the mic
    // is live but the button is still dead to the touch.
    updateReadyButton();
    await listDevices();
    updateReadyButton();
  } catch (err) {
    el.micBtn.disabled = false;
    el.micBtn.textContent = 'Enable microphone';
    el.micHint.textContent = `Could not open the microphone: ${err.message}`;
  }
};

el.calBtn.onclick = async () => {
  const peak = state.partials.length ? Math.max(...state.partials.map((p) => p.aMax)) : 1;
  el.calBtn.disabled = true;
  el.calBtn.textContent = 'Play your loudest…';
  const res = await mic.calibrate(3000, peak);
  state.calibrationGain = res.gain;
  applyGain();
  el.calBtn.disabled = false;
  el.calBtn.textContent = res.ok ? 'Recalibrate' : 'Nothing heard — retry';
};

function applyGain() {
  mic.gain = state.calibrationGain * Math.pow(10, state.gainDb / 20);
}

async function listDevices() {
  const inputs = await MicAnalyser.listInputs();
  if (!inputs.length) return;
  const current = el.inputDevice.value;
  el.inputDevice.innerHTML = '';
  for (const d of inputs) {
    const o = document.createElement('option');
    o.value = d.deviceId;
    o.textContent = d.label || 'Microphone';
    el.inputDevice.append(o);
  }
  if (current) el.inputDevice.value = current;
}

el.inputDevice.onchange = async () => {
  if (!mic.running) return;
  mic.stop();
  await mic.start({ deviceId: el.inputDevice.value || undefined });
};

/* ------------------------------------------------------------------ *
 * Readiness
 * ------------------------------------------------------------------ */

function updateReadyButton() {
  const ok = !!state.part && mic.running;
  el.readyBtn.disabled = !ok;
  el.readyBtn.textContent = state.ready ? "Ready — tap to stand down" : "I'm ready";
}

el.readyBtn.onclick = async () => {
  state.ready = !state.ready;
  net.status({ ready: state.ready });
  updateReadyButton();
  if (state.ready) await prepareAudio();
};

/**
 * Pre-render the monitor mix. Done at "ready" rather than at the downbeat so
 * that a slow phone finishes its work while the ensemble is still assembling
 * instead of during the lead-in.
 */
async function prepareAudio() {
  if (!state.scoreJSON || !state.part || state.prepared) return;
  ensureContext();
  const own = partPartials(state.score, state.part).map((p) => p.index);
  // Synthesis is roughly real-time-over-30 on a laptop and a good deal slower
  // on a phone, so a long score takes visible seconds. Say so rather than
  // appearing to hang.
  const busy = 'Preparing your monitor mix…';
  el.waitingHint.textContent = busy;
  el.readyStatus.textContent = busy;
  try {
    const r = await player.prepare(
      state.scoreJSON,
      own,
      state.transposeCents,
      state.timbre
    );
    state.prepared = true;

    const notes = [];
    if (r.ensembleDropped) {
      notes.push(
        'The ensemble mix was left out — this score is too long to hold both ' +
          'mixes in memory. You will still hear your own part.'
      );
      el.balance.disabled = true;
    } else {
      el.balance.disabled = !r.ensemble;
    }
    if (r.truncated) notes.push(`Playback is capped at ${Math.round(r.duration / 60)} minutes.`);

    const msg = notes.length
      ? notes.join(' ')
      : 'Ready. The conductor starts the downbeat for everyone.';
    el.waitingHint.textContent = notes.length ? msg : 'The conductor will start playback.';
    el.readyStatus.textContent = msg;
  } catch (err) {
    const msg = `Could not prepare audio: ${err.message}`;
    el.waitingHint.textContent = msg;
    el.readyStatus.textContent = msg;
  }
}

/* ------------------------------------------------------------------ *
 * Transport
 * ------------------------------------------------------------------ */

net.addEventListener('transport', async (ev) => {
  const msg = ev.detail;
  if (msg.action === 'stop') return stopRun();
  if (msg.action === 'start') {
    if (!state.part) return;
    await prepareAudio();
    beginRun(msg.startAt);
  }
});

function beginRun(startAtServer) {
  state.startAtServer = startAtServer;
  state.running = true;
  view.clearLive();
  pitchSmooth.reset();
  ampSmooth.reset();

  el.lobby.classList.add('hidden');
  el.settings.classList.add('hidden');
  el.stage.classList.remove('hidden');
  view.resize();

  // The downbeat, expressed in this device's audio clock.
  const localMs = net.toLocal(startAtServer);
  const downbeat = player ? player.ctxTimeFor(localMs) : 0;

  if (player && player.ready) {
    const offset = Math.max(0, (net.serverNow() - startAtServer) / 1000);
    player.start(downbeat, offset);
    if (offset === 0) scheduleCountIn(ctx, downbeat, 3, 0.6, player.master);
  }

  if (!rafHandle) loop();
}

function stopRun() {
  state.running = false;
  state.startAtServer = null;
  if (player) player.stop();
  view.countdown = null;
  el.stage.classList.add('hidden');
  el.lobby.classList.remove('hidden');
}

/* ------------------------------------------------------------------ *
 * Frame loop
 * ------------------------------------------------------------------ */

let rafHandle = null;

function loop() {
  rafHandle = requestAnimationFrame(loop);
  if (!state.running || state.startAtServer == null) return;

  const t = (net.serverNow() - state.startAtServer) / 1000;
  state.scoreTime = t;

  if (t < 0) {
    view.countdown = Math.ceil(-t);
    view.setTime(0);
    view.draw();
    return;
  }
  view.countdown = null;
  el.waiting.classList.add('hidden');

  view.setTime(t);

  // Point the tracker at whatever is written right now, so a quiet high partial
  // is not lost under a louder neighbour.
  if (view.notated) mic.setTarget(view.notated.hz);

  const r = mic.read();
  if (r) {
    const hz = r.conf > 0.15 ? pitchSmooth.push(r.hz) : (pitchSmooth.reset(), 0);
    const amp = ampSmooth.push(r.level) ?? 0;
    view.pushLive(t, hz || 0, amp, r.conf);

    const now = performance.now();
    if (now - lastMeterSent > 120) {
      lastMeterSent = now;
      net.meter(view.deviation, amp, r.conf);
    }
  }

  view.draw();

  if (state.score && t > state.score.duration + 1.5) stopRun();
}

/* ------------------------------------------------------------------ *
 * Settings wiring
 * ------------------------------------------------------------------ */

el.settingsBtn.onclick = () => {
  el.settings.classList.toggle('hidden');
  // The canvas has no measurable width while the drawer is hidden, so it can
  // only be sized once it is actually on screen.
  if (!el.settings.classList.contains('hidden')) drawWave(state.timbre);
};
el.closeSettings.onclick = () => el.settings.classList.add('hidden');
el.backBtn.onclick = () => stopRun();

el.balance.oninput = () => {
  const v = parseFloat(el.balance.value);
  if (player) player.setBalance(v);
  el.balLabel.textContent = `Balance — your part ${Math.round((1 - v) * 100)}% / ensemble ${Math.round(v * 100)}%`;
};

el.volume.oninput = () => {
  const v = parseFloat(el.volume.value);
  if (player) player.setVolume(v);
  el.volLabel.textContent = `Volume — ${Math.round(v * 100)}%`;
};

el.timeWindow.oninput = () => {
  view.window = parseFloat(el.timeWindow.value);
  el.winLabel.textContent = `Time window — ${view.window.toFixed(1)} s`;
};

el.pitchSpan.oninput = () => {
  view.pitchSpan = parseFloat(el.pitchSpan.value);
  el.spanLabel.textContent = `Pitch span — ±${view.pitchSpan} cents`;
};

el.modeBtn.onclick = () => {
  view.pitchMode = view.pitchMode === 'follow' ? 'range' : 'follow';
  el.modeBtn.textContent = `Mode: ${view.pitchMode}`;
};

el.ensembleBtn.onclick = () => {
  view.showEnsemble = !view.showEnsemble;
  el.ensembleBtn.textContent = `Ensemble lines: ${view.showEnsemble ? 'on' : 'off'}`;
};

el.band.oninput = () => {
  mic.bandSemitones = parseFloat(el.band.value);
  mic.bandLimited = mic.bandSemitones < 48;
  el.bandLabel.textContent = mic.bandLimited
    ? `Search band — ±${mic.bandSemitones} semitones`
    : 'Search band — full range';
};

/* ---- playback timbre ---- */

const SHAPE_NAMES = ['Sine', 'Triangle', 'Sawtooth', 'Square'];

/**
 * Naive shape functions for the preview only.
 *
 * What you actually hear is band-limited (see render-worker.js), but an ideal
 * square reads as a square at a glance, whereas a band-limited one at this size
 * is mostly Gibbs ringing. The picture is an affordance for choosing a shape,
 * not an oscilloscope.
 */
const SHAPE_FNS = [
  (x) => Math.sin(2 * Math.PI * x),
  (x) => 4 * Math.abs(x - Math.floor(x + 0.5)) - 1,
  (x) => 2 * (x - Math.floor(x + 0.5)),
  (x) => (x % 1 < 0.5 ? 1 : -1),
];

function timbreName(v) {
  const pos = v / 100;
  const lo = Math.min(2, Math.floor(pos));
  const frac = pos - lo;
  if (frac < 0.02) return SHAPE_NAMES[lo];
  if (frac > 0.98) return SHAPE_NAMES[lo + 1];
  return `${SHAPE_NAMES[lo]} → ${SHAPE_NAMES[lo + 1]} ${Math.round(frac * 100)}%`;
}

function drawWave(v) {
  const c = el.waveView;
  const rect = c.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(rect.width));
  const h = Math.max(1, Math.round(rect.height));
  if (c.width !== w * dpr || c.height !== h * dpr) {
    c.width = w * dpr;
    c.height = h * dpr;
  }
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const pos = Math.min(3, Math.max(0, v / 100));
  const lo = Math.min(2, Math.floor(pos));
  const frac = pos - lo;
  const a = SHAPE_FNS[lo];
  const b = SHAPE_FNS[Math.min(3, lo + 1)];

  g.strokeStyle = '#232a33';
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(0, h / 2 + 0.5);
  g.lineTo(w, h / 2 + 0.5);
  g.stroke();

  g.strokeStyle = '#4da3ff';
  g.lineWidth = 2;
  g.lineJoin = 'round';
  g.shadowColor = '#4da3ff';
  g.shadowBlur = 6;
  g.beginPath();
  const cycles = 2;
  for (let px = 0; px <= w; px++) {
    const x = (px / w) * cycles;
    const y = a(x) + frac * (b(x) - a(x));
    const py = h / 2 - y * (h / 2 - 8);
    if (px === 0) g.moveTo(px, py);
    else g.lineTo(px, py);
  }
  g.stroke();
  g.shadowBlur = 0;
}

el.timbre.oninput = () => {
  state.timbre = parseFloat(el.timbre.value);
  el.timbreLabel.textContent = timbreName(state.timbre);
  drawWave(state.timbre);
};

// Re-render only on release: each change rebuilds both monitor buffers, which
// is far too heavy to do on every pixel of slider travel.
el.timbre.onchange = async () => {
  state.prepared = false;
  if (state.ready && !state.running) await prepareAudio();
};

el.transpose.onchange = async () => {
  state.transposeCents = parseFloat(el.transpose.value) || 0;
  applyPartSelection();
  state.prepared = false;
  if (state.ready) await prepareAudio();
};

el.inputGain.oninput = () => {
  state.gainDb = parseFloat(el.inputGain.value);
  applyGain();
  el.gainLabel.textContent = `Input gain — ${state.gainDb > 0 ? '+' : ''}${state.gainDb} dB`;
};

el.nameInput.oninput = () => {
  const v = el.nameInput.value.trim();
  localStorage.setItem('pr.name', v);
  net.setName(v);
};
el.nameInput.value = localStorage.getItem('pr.name') || '';

/* ------------------------------------------------------------------ *
 * Hub events
 * ------------------------------------------------------------------ */

net.addEventListener('sync', () => {
  const q = net.quality;
  const dot = el.syncPill.querySelector('.dot');
  const label = el.syncPill.querySelector('span');
  dot.className = `dot ${q.grade}`;
  label.textContent = q.locked ? `±${q.spread.toFixed(0)} ms` : 'syncing';
  net.status({ spread: q.spread });
});

net.addEventListener('state', async (ev) => {
  const s = ev.detail;
  if (s.scoreMeta && (!state.score || state.score.name !== s.scoreMeta.name)) {
    await loadScore();
  }
  renderParts();

  // Reconnected into a performance already under way.
  if (s.transport?.state === 'running' && s.transport.startAt != null && !state.running) {
    if (state.part) {
      prepareAudio().then(() => beginRun(s.transport.startAt));
    }
  }
});

net.addEventListener('scoreChanged', async () => {
  state.part = null;
  state.ready = false;
  await loadScore();
  updateReadyButton();
});

net.addEventListener('close', () => {
  const dot = el.syncPill.querySelector('.dot');
  dot.className = 'dot bad';
});

/* ------------------------------------------------------------------ *
 * Boot
 * ------------------------------------------------------------------ */

// Reflect initial slider values into their labels.
for (const fn of [
  el.balance.oninput,
  el.volume.oninput,
  el.timeWindow.oninput,
  el.pitchSpan.oninput,
  el.band.oninput,
  el.inputGain.oninput,
  el.timbre.oninput,
]) {
  fn();
}

net.connect();
loop();
