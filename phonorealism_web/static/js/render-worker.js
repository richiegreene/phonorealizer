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

/* ------------------------------------------------------------------ *
 * Wavetables
 *
 * Timbre morphs sine -> triangle -> saw -> square, matching the "Basic
 * Shapes" preset in the desktop modifier's wavetable dialog (0-300, linear
 * crossfade between adjacent shapes).
 *
 * Unlike the desktop version these tables are *band-limited*. A naive saw or
 * square is built from harmonics that never stop, and a phonorealism score
 * carries partials up to 19 kHz — every harmonic above Nyquist would fold back
 * down as inharmonic noise, right in the range the performer is trying to tune
 * against. So each shape is synthesised additively with only the harmonics that
 * fit, at a range of octave "mip" levels, and the renderer picks the level that
 * suits the frequency it is currently sounding.
 * ------------------------------------------------------------------ */

const TABLE_SIZE = 2048;
const TABLE_MASK = TABLE_SIZE - 1;
const MIP_BASE_HZ = 20;
const MIP_COUNT = 11; // 20 Hz .. ~20 kHz
/** Beyond this the tables stop improving but the build cost keeps rising. */
const MAX_HARMONICS = 256;

/** Harmonic amplitude for each shape, or 0 if that harmonic is absent. */
const SHAPES = [
  (n) => (n === 1 ? 1 : 0), // sine
  (n) => (n % 2 ? (((n - 1) / 2) % 2 ? -1 : 1) / (n * n) : 0), // triangle
  (n) => (n % 2 ? 1 : -1) / n, // sawtooth
  (n) => (n % 2 ? 1 / n : 0), // square
];

/** Highest harmonic that stays below Nyquist for this mip's top fundamental. */
function harmonicLimit(mip, sr) {
  const topHz = MIP_BASE_HZ * Math.pow(2, mip);
  return Math.max(1, Math.min(MAX_HARMONICS, Math.floor(sr / 2 / topHz)));
}

function buildShapeTable(shapeFn, harmonics) {
  const table = new Float32Array(TABLE_SIZE);
  for (let n = 1; n <= harmonics; n++) {
    const amp = shapeFn(n);
    if (amp === 0) continue;
    const step = (TWO_PI * n) / TABLE_SIZE;
    for (let i = 0; i < TABLE_SIZE; i++) table[i] += amp * Math.sin(step * i);
  }
  let max = 0;
  for (let i = 0; i < TABLE_SIZE; i++) max = Math.max(max, Math.abs(table[i]));
  if (max > 0) for (let i = 0; i < TABLE_SIZE; i++) table[i] /= max;
  return table;
}

let tableCache = null;

/**
 * Band-limited tables for one morph position, one per mip level.
 * @param {number} timbre 0..300 (0 sine, 100 triangle, 200 saw, 300 square)
 */
function wavetablesFor(timbre, sr) {
  if (tableCache && tableCache.timbre === timbre && tableCache.sr === sr) {
    return tableCache.mips;
  }

  const pos = Math.min(3, Math.max(0, timbre / 100));
  const lo = Math.min(2, Math.floor(pos));
  const frac = pos - lo;

  const mips = [];
  for (let m = 0; m < MIP_COUNT; m++) {
    const h = harmonicLimit(m, sr);
    const a = buildShapeTable(SHAPES[lo], h);
    if (frac === 0) {
      mips.push(a);
      continue;
    }
    // Blending two tables that are band-limited to the same harmonic count
    // keeps the result band-limited, so the crossfade cannot reintroduce
    // aliasing partials.
    const b = buildShapeTable(SHAPES[lo + 1], h);
    const out = new Float32Array(TABLE_SIZE);
    for (let i = 0; i < TABLE_SIZE; i++) out[i] = a[i] + frac * (b[i] - a[i]);
    mips.push(out);
  }

  tableCache = { timbre, sr, mips };
  return mips;
}

const INV_LOG2 = 1 / Math.log(2);

function mipFor(freq) {
  if (!(freq > MIP_BASE_HZ)) return 0;
  const m = Math.ceil(Math.log(freq / MIP_BASE_HZ) * INV_LOG2);
  return m < 0 ? 0 : m >= MIP_COUNT ? MIP_COUNT - 1 : m;
}

/**
 * @param {Array} partials  [{t:[], f:[], a:[]}]
 * @param {number} sr
 * @param {number} duration seconds
 * @param {number} detune   frequency multiplier (octave/transposition)
 * @param {Float32Array[]} mips band-limited tables from wavetablesFor()
 */
function renderPartials(partials, sr, duration, detune, mips) {
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
    // Phase as a normalised [0,1) accumulator: it indexes the table directly
    // and keeps its precision over long renders.
    let phase = 0;

    for (let i = first; i <= last; i++) {
      const time = i / sr;
      // Breakpoints are sorted, so the segment cursor only ever moves forward.
      while (k + 2 < len && t[k + 1] <= time) k++;
      const span = t[k + 1] - t[k];
      const u = span > 0 ? (time - t[k]) / span : 0;
      const freq = (f[k] + u * (f[k + 1] - f[k])) * detune;
      const amp = a[k] + u * (a[k + 1] - a[k]);

      phase += freq / sr;
      if (phase >= 1) phase -= 1;

      const table = mips[mipFor(freq)];
      const x = phase * TABLE_SIZE;
      const i0 = x | 0;
      const fr = x - i0;
      const s = table[i0] + fr * (table[(i0 + 1) & TABLE_MASK] - table[i0]);
      out[i] += amp * s;
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
    timbre = 100,
  } = ev.data;
  try {
    const mips = wavetablesFor(timbre, sampleRate);
    const ownSet = new Set(ownIndices || []);
    const own = partials.filter((p) => ownSet.has(p.i));
    // "Full" excludes the performer's own line so the balance fader is a true
    // crossfade between "me" and "everyone else" rather than me against a mix
    // that already contains me.
    const rest = withEnsemble ? partials.filter((p) => !ownSet.has(p.i)) : [];

    const ownBuf = renderPartials(own, sampleRate, duration, detune, mips);
    normalise(ownBuf, 0.9);

    // Skipped entirely rather than rendered silent — on a long score the
    // allocation itself is the problem.
    const restBuf = rest.length
      ? renderPartials(rest, sampleRate, duration, detune, mips)
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
