/*
 * synth.js — the in-ear reference.
 *
 * Each performer hears their own line re-synthesised from the score, with a
 * balance fader against the rest of the ensemble. Both are rendered up front
 * into AudioBuffers rather than driven by live oscillators: a phonorealism
 * score can carry dozens of simultaneous partials, and a pre-rendered buffer
 * starts sample-accurately at a scheduled time, which a pile of oscillator
 * nodes does not reliably do on a phone.
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

    if (!this.worker) this.worker = new Worker('/static/js/render-worker.js');
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
