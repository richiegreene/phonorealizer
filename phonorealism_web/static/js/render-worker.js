/*
 * render-worker.js — additive re-synthesis of score partials, off the main
 * thread so the scrolling display never stutters while a score loads.
 *
 * Deliberately a classic (non-module) worker: module workers are still patchy
 * on older iOS Safari, and performers turn up with whatever phone they own.
 *
 * The synthesis mirrors the desktop exporter's `_generate_partial_waveform` —
 * linear interpolation of frequency and amplitude between breakpoints, with
 * phase accumulated sample by sample so that frequency sweeps stay continuous.
 */

const TWO_PI = Math.PI * 2;

/**
 * @param {Array} partials  [{t:[], f:[], a:[]}]
 * @param {number} sr
 * @param {number} duration seconds
 * @param {number} detune   frequency multiplier (octave/transposition)
 */
function renderPartials(partials, sr, duration, detune) {
  const n = Math.max(1, Math.ceil(duration * sr) + 1);
  const out = new Float32Array(n);

  for (const p of partials) {
    const t = p.t;
    const f = p.f;
    const a = p.a;
    const len = t.length;
    if (len < 2) continue;

    const first = Math.max(0, Math.floor(t[0] * sr));
    const last = Math.min(n - 1, Math.ceil(t[len - 1] * sr));
    let k = 0;
    let phase = 0;

    for (let i = first; i <= last; i++) {
      const time = i / sr;
      // Breakpoints are sorted, so the segment cursor only ever moves forward.
      while (k + 2 < len && t[k + 1] <= time) k++;
      const span = t[k + 1] - t[k];
      const u = span > 0 ? (time - t[k]) / span : 0;
      const freq = (f[k] + u * (f[k + 1] - f[k])) * detune;
      const amp = a[k] + u * (a[k + 1] - a[k]);
      phase += (TWO_PI * freq) / sr;
      if (phase > TWO_PI) phase -= TWO_PI; // keep float precision from decaying
      out[i] += amp * Math.sin(phase);
    }
  }
  return out;
}

/** Scale to a peak of `peak`, reporting the factor so levels stay comparable. */
function normalise(buf, peak) {
  let max = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = buf[i] < 0 ? -buf[i] : buf[i];
    if (v > max) max = v;
  }
  if (max > 0) {
    const g = peak / max;
    for (let i = 0; i < buf.length; i++) buf[i] *= g;
    return g;
  }
  return 1;
}

self.onmessage = (ev) => {
  const {
    id, partials, ownIndices, sampleRate, duration, detune = 1, withEnsemble = true,
  } = ev.data;
  try {
    const ownSet = new Set(ownIndices || []);
    const own = partials.filter((p) => ownSet.has(p.i));
    // "Full" excludes the performer's own line so the balance fader is a true
    // crossfade between "me" and "everyone else" rather than me against a mix
    // that already contains me.
    const rest = withEnsemble ? partials.filter((p) => !ownSet.has(p.i)) : [];

    const ownBuf = renderPartials(own, sampleRate, duration, detune);
    normalise(ownBuf, 0.9);

    // Skipped entirely rather than rendered silent — on a long score the
    // allocation itself is the problem.
    const restBuf = rest.length
      ? renderPartials(rest, sampleRate, duration, detune)
      : new Float32Array(0);
    if (rest.length) normalise(restBuf, 0.9);

    self.postMessage({ id, ok: true, own: ownBuf, rest: restBuf }, [
      ownBuf.buffer,
      restBuf.buffer,
    ]);
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err && err.message) || 'render failed' });
  }
};
