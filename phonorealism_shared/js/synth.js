/*
 * synth.js — re-synthesis of a score for listening to.
 *
 * Two callers, one engine. In the performer app each player hears their own line
 * with a balance fader against the rest of the ensemble; in the engraver the same
 * split plays the layout on screen — the part being engraved against everything
 * else, or the full score alone. The distinction is only which partials are
 * called "own", so there is one implementation rather than two that would
 * eventually disagree about what the score sounds like.
 *
 * Both mixes are rendered up front into AudioBuffers rather than driven by live
 * oscillators: a phonorealism score can carry dozens of simultaneous partials,
 * and a pre-rendered buffer starts sample-accurately at a scheduled time, which
 * a pile of oscillator nodes does not reliably do on a phone.
 */

/**
 * Hard ceiling on how much score gets pre-rendered.
 *
 * A decoded buffer costs 4 bytes per sample per mix, so at 48 kHz five minutes
 * is ~58 MB for each of the two mixes. Phones are the constraint here, not
 * laptops, and an out-of-memory kill during a rehearsal is the worst possible
 * failure — hence a budget rather than optimism.
 */
const MAX_RENDER_SECONDS = 300;

/** Total AudioBuffer budget. Past this the ensemble mix is dropped first. */
const MAX_BUFFER_BYTES = 96 * 1024 * 1024;

export class ScorePlayer {
  constructor(ctx) {
    this.ctx = ctx;
    this.worker = null;
    this.ownBuffer = null;
    this.restBuffer = null;
    this.sources = [];
    this.ready = false;
    this.startedAtCtxTime = null;
    this.startOffset = 0;

    this.ownGain = ctx.createGain();
    this.restGain = ctx.createGain();
    this.master = ctx.createGain();
    this.ownGain.connect(this.master);
    this.restGain.connect(this.master);
    this.master.connect(ctx.destination);
    this.master.gain.value = 0.8;
    // Start with the performer's own line alone. Learning a spectral part means
    // hearing it isolated first; the ensemble is something you fade in once you
    // know your own line.
    this.setBalance(0);
  }

  /**
   * Equal-power crossfade. 0 = own part alone, 1 = ensemble alone.
   * Equal-power rather than linear so that sweeping the fader does not dip in
   * perceived loudness at the midpoint — the two mixes are uncorrelated.
   */
  setBalance(x) {
    this.balance = Math.min(1, Math.max(0, x));
    const t = (this.balance * Math.PI) / 2;
    this.ownGain.gain.value = Math.cos(t);
    this.restGain.gain.value = Math.sin(t);
  }

  setVolume(v) {
    this.master.gain.value = Math.min(1, Math.max(0, v));
  }

  /**
   * Render the score to buffers.
   * @param {object} scoreJSON   wire-format score (see score.js)
   * @param {number[]} ownIndices canonical partial indices for this performer
   * @param {number} detuneCents  applied to everything the performer hears
   * @param {number} timbre       0..300: sine, triangle, saw, square
   */
  prepare(scoreJSON, ownIndices, detuneCents = 0, timbre = 100) {
    this.ready = false;
    const duration = Math.min(scoreJSON.duration, MAX_RENDER_SECONDS);
    const truncated = scoreJSON.duration > MAX_RENDER_SECONDS;

    // Decide up front whether both mixes fit. The performer's own line is
    // non-negotiable; the ensemble mix is the one that gets dropped.
    const bytesPerMix = duration * this.ctx.sampleRate * 4;
    const ownSet = new Set(ownIndices || []);
    const hasRest = scoreJSON.partials.some((p) => !ownSet.has(p.i));
    const withEnsemble = hasRest && bytesPerMix * 2 <= MAX_BUFFER_BYTES;

    // Resolved against this module's own URL rather than hard-coded, because
    // the two applications mount the shared directory at different paths.
    if (!this.worker) {
      this.worker = new Worker(new URL('./render-worker.js', import.meta.url));
    }
    const id = Math.random().toString(36).slice(2);

    return new Promise((resolve, reject) => {
      const onMessage = (ev) => {
        if (ev.data.id !== id) return;
        this.worker.removeEventListener('message', onMessage);
        if (!ev.data.ok) return reject(new Error(ev.data.error));

        this.ownBuffer = this._toAudioBuffer(ev.data.own);
        this.restBuffer = ev.data.rest && ev.data.rest.length
          ? this._toAudioBuffer(ev.data.rest)
          : null;
        this.ready = true;
        resolve({
          duration,
          truncated,
          ensemble: !!this.restBuffer,
          ensembleDropped: hasRest && !withEnsemble,
          megabytes: Math.round((bytesPerMix * (withEnsemble ? 2 : 1)) / 1048576),
        });
      };
      this.worker.addEventListener('message', onMessage);
      this.worker.postMessage({
        id,
        partials: scoreJSON.partials,
        ownIndices,
        sampleRate: this.ctx.sampleRate,
        duration,
        detune: Math.pow(2, detuneCents / 1200),
        withEnsemble,
        timbre,
      });
    });
  }

  _toAudioBuffer(float32) {
    const buf = this.ctx.createBuffer(1, float32.length, this.ctx.sampleRate);
    buf.copyToChannel(float32, 0);
    return buf;
  }

  /**
   * Translate a `performance.now()` instant into AudioContext time.
   *
   * `getOutputTimestamp` pairs a context time with the performance time of the
   * *same instant of audible output*, so scheduling through it also absorbs the
   * device's output latency — which on Bluetooth earbuds can be 150 ms and
   * varies per performer. That correction is the difference between an ensemble
   * that lines up and one that does not, so the fallback path below adds
   * `outputLatency` by hand when the API is unavailable.
   */
  ctxTimeFor(localMs) {
    const ctx = this.ctx;
    const ts = ctx.getOutputTimestamp ? ctx.getOutputTimestamp() : null;
    if (ts && ts.contextTime != null && ts.performanceTime) {
      return ts.contextTime + (localMs - ts.performanceTime) / 1000;
    }
    const latency = (ctx.outputLatency || ctx.baseLatency || 0);
    return ctx.currentTime + (localMs - performance.now()) / 1000 + latency;
  }

  /**
   * Start both mixes at a scheduled context time.
   * @param {number} atCtxTime  AudioContext time of the downbeat
   * @param {number} offset     seconds into the score to begin at
   */
  start(atCtxTime, offset = 0) {
    this.stop();
    if (!this.ready) return false;

    const when = Math.max(atCtxTime, this.ctx.currentTime + 0.005);
    for (const [buffer, gain] of [
      [this.ownBuffer, this.ownGain],
      [this.restBuffer, this.restGain],
    ]) {
      if (!buffer || buffer.length === 0) continue;
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(gain);
      // A negative offset would throw; the caller may legitimately ask to start
      // partway in after a late join.
      src.start(when, Math.max(0, offset));
      this.sources.push(src);
    }
    this.startedAtCtxTime = when;
    this.startOffset = offset;
    return true;
  }

  stop() {
    for (const s of this.sources) {
      try {
        s.stop();
      } catch {
        /* already finished */
      }
      s.disconnect();
    }
    this.sources = [];
    this.startedAtCtxTime = null;
  }

  dispose() {
    this.stop();
    if (this.worker) this.worker.terminate();
    this.worker = null;
    this.ownBuffer = null;
    this.restBuffer = null;
  }
}

/* ------------------------------------------------------------------ *
 * Timbre
 *
 * The morph position, 0..300, runs sine -> triangle -> saw -> square with a
 * linear crossfade between adjacent shapes, matching the "Basic Shapes" preset
 * in the desktop modifier's wavetable dialog. Naming and drawing it live here
 * beside the renderer so that the label, the picture and the sound cannot
 * disagree about what the slider is set to.
 * ------------------------------------------------------------------ */

export const TIMBRE_MAX = 300;

const SHAPE_NAMES = ['Sine', 'Triangle', 'Sawtooth', 'Square'];

/**
 * Naive shape functions, for the preview only.
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

/** Where a slider position sits between two shapes. */
function morph(value) {
  const pos = Math.min(3, Math.max(0, value / 100));
  const lo = Math.min(2, Math.floor(pos));
  return { lo, frac: pos - lo };
}

/** What to call a timbre setting: a shape, or how far between two of them. */
export function timbreName(value) {
  const { lo, frac } = morph(value);
  if (frac < 0.02) return SHAPE_NAMES[lo];
  if (frac > 0.98) return SHAPE_NAMES[lo + 1];
  return `${SHAPE_NAMES[lo]} → ${SHAPE_NAMES[lo + 1]} ${Math.round(frac * 100)}%`;
}

/**
 * Draw two cycles of the chosen wave into a canvas, sizing it for the display.
 * @param {HTMLCanvasElement} canvas
 * @param {number} value 0..TIMBRE_MAX
 */
export function drawTimbreWave(canvas, value, { line = '#4da3ff', axis = '#232a33' } = {}) {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(rect.width));
  const h = Math.max(1, Math.round(rect.height));
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr;
    canvas.height = h * dpr;
  }
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const { lo, frac } = morph(value);
  const a = SHAPE_FNS[lo];
  const b = SHAPE_FNS[Math.min(3, lo + 1)];

  g.strokeStyle = axis;
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(0, h / 2 + 0.5);
  g.lineTo(w, h / 2 + 0.5);
  g.stroke();

  g.strokeStyle = line;
  g.lineWidth = 2;
  g.lineJoin = 'round';
  g.shadowColor = line;
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

/**
 * A short countdown tick so performers feel the lead-in rather than watching a
 * number. Scheduled on the same clock as everything else.
 * @param {AudioContext} ctx
 * @param {number} downbeatCtxTime
 * @param {number} beats how many ticks before the downbeat
 * @param {number} spacing seconds between ticks
 */
export function scheduleCountIn(ctx, downbeatCtxTime, beats = 4, spacing = 0.5, out = null) {
  const dest = out || ctx.destination;
  const made = [];
  for (let i = beats; i >= 1; i--) {
    const when = downbeatCtxTime - i * spacing;
    if (when < ctx.currentTime) continue;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    // The downbeat itself gets a higher, louder tick so it is unmistakable.
    osc.frequency.value = i === 1 ? 1760 : 880;
    g.gain.setValueAtTime(0.0001, when);
    g.gain.exponentialRampToValueAtTime(i === 1 ? 0.35 : 0.18, when + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, when + 0.09);
    osc.connect(g);
    g.connect(dest);
    osc.start(when);
    osc.stop(when + 0.12);
    made.push(osc);
  }
  return made;
}
