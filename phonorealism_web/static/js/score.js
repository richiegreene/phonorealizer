/*
 * score.js — one normalised score model, fed by either source format.
 *
 *   justidraw .sav   binser-serialised `song` table (the primary workflow)
 *   phonorealizer    CSV: time,frequency,amplitude,harmonic_index
 *
 * Both collapse to the same shape: a list of partials, each a breakpoint
 * envelope of (time, frequency, linear amplitude). A "part" is what a performer
 * actually claims — by default one per partial, but the conductor can group
 * partials into named parts ("Violin 1" = partials 3 and 7).
 *
 * Unit mappings for justidraw, verified against a round-tripped export of
 * lowlands_test (51,680 vertices / 32 partials / 1615 frames):
 *
 *   time (s)   = x * 60 / (400 * bpm)      -- audio.lua advances the playhead
 *                                             by 4*100*bpm/(60*sr) per sample
 *   freq (Hz)  = 440 * 2^(-y / 1200)       -- y is negative cents from A440
 *   amplitude  = w                         -- see AMP_CURVES below
 */

import { deserializeOne } from './lib/binser.js';

/** Above this many breakpoints, thin the envelopes before shipping them out. */
const SIMPLIFY_THRESHOLD = 400000;

/**
 * How a justidraw vertex width `w` becomes an amplitude.
 *
 * The phonorealizer export writes `w` = linear amplitude straight from the
 * spectral analysis, so `linear` is what the composer actually notated and is
 * the right thing to hold a performer to. justidraw's own synth, though, plays
 * `w` through `amp_curve(x) = x*x`, so `justidraw` is the setting that makes the
 * displayed envelope match what you hear when you press play in justidraw.
 */
export const AMP_CURVES = {
  linear: (w) => w,
  justidraw: (w) => w * w,
};

export const A4 = 440;

export function hzToCents(hz, ref = A4) {
  return 1200 * Math.log2(hz / ref);
}

export function centsToHz(cents, ref = A4) {
  return ref * Math.pow(2, cents / 1200);
}

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

export function hzToNoteName(hz) {
  if (!(hz > 0)) return '—';
  const midi = Math.round(69 + 12 * Math.log2(hz / A4));
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

/* ------------------------------------------------------------------ *
 * Partial construction
 * ------------------------------------------------------------------ */

function makePartial(srcIndex, t, f, a) {
  const p = {
    index: srcIndex, // replaced with the canonical ordering in finalise()
    srcIndex,
    t: Float64Array.from(t),
    f: Float64Array.from(f),
    a: Float64Array.from(a),
  };
  computeStats(p);
  return p;
}

function computeStats(p) {
  const n = p.t.length;
  p.t0 = n ? p.t[0] : 0;
  p.t1 = n ? p.t[n - 1] : 0;

  let fMin = Infinity;
  let fMax = -Infinity;
  let aMax = 0;
  // Median frequency weighted by nothing fancy — it just wants to be a stable
  // label for the part, robust against a stray zero at the head or tail.
  const sorted = [];
  for (let i = 0; i < n; i++) {
    const f = p.f[i];
    if (f > 0) {
      if (f < fMin) fMin = f;
      if (f > fMax) fMax = f;
      sorted.push(f);
    }
    if (p.a[i] > aMax) aMax = p.a[i];
  }
  sorted.sort((x, y) => x - y);
  p.fMin = Number.isFinite(fMin) ? fMin : 0;
  p.fMax = Number.isFinite(fMax) ? fMax : 0;
  p.fMed = sorted.length ? sorted[sorted.length >> 1] : 0;
  p.aMax = aMax;
  return p;
}

/**
 * Sample a partial at time `t` with linear interpolation, matching how both
 * justidraw's audio callback and the desktop Perform window read an envelope.
 * `cursor` is an optional hint index for sequential scans.
 * Returns null outside the partial's extent.
 */
export function sampleAt(p, t, cursor = 0) {
  const n = p.t.length;
  if (n === 0 || t < p.t[0] || t > p.t[n - 1]) return null;

  let i = Math.min(Math.max(cursor, 0), n - 1);
  if (p.t[i] > t) i = 0;
  while (i + 1 < n && p.t[i + 1] <= t) i++;
  if (i + 1 >= n) return { f: p.f[n - 1], a: p.a[n - 1], i: n - 1 };

  const span = p.t[i + 1] - p.t[i];
  const u = span > 0 ? (t - p.t[i]) / span : 0;
  return {
    f: p.f[i] + u * (p.f[i + 1] - p.f[i]),
    a: p.a[i] + u * (p.a[i + 1] - p.a[i]),
    i,
  };
}

/* ------------------------------------------------------------------ *
 * justidraw .sav
 * ------------------------------------------------------------------ */

/**
 * Walk a justidraw track's vertex soup into ordered curves.
 *
 * Vertices are a doubly-linked chain via `l`/`r`. Chain heads are the vertices
 * with no `l`. Heads are visited in the track's own array order, which for a
 * phonorealizer export is already partial order (lowest first).
 */
function extractCurves(track) {
  const verts = track.arr;
  const seen = new Set();
  const curves = [];

  const walk = (head) => {
    const chain = [];
    let v = head;
    while (v && !seen.has(v)) {
      seen.add(v);
      chain.push(v);
      v = v.get('r');
    }
    if (chain.length >= 2) curves.push(chain);
  };

  for (const v of verts) {
    if (v && !v.get('l') && !seen.has(v)) walk(v);
  }
  // Anything left over is either a cycle or a chain whose head was clipped;
  // pick it up so no notated material silently vanishes.
  for (const v of verts) {
    if (v && !seen.has(v)) walk(v);
  }
  return curves;
}

export function parseJustidraw(arrayBuffer, { name, ampCurve = 'linear' } = {}) {
  const song = deserializeOne(arrayBuffer);
  if (!song || typeof song.get !== 'function' || !song.get('track')) {
    throw new Error('Not a justidraw save file (no `track` in the song table).');
  }

  const bpm = song.get('bpm') || 120;
  const secondsPerX = 60 / (400 * bpm);
  const toAmp = AMP_CURVES[ampCurve] || AMP_CURVES.linear;

  const partials = [];
  const trackTable = song.get('track');
  for (let ti = 1; ti <= trackTable.length; ti++) {
    const track = trackTable.at(ti);
    if (!track || !track.arr) continue;
    for (const chain of extractCurves(track)) {
      const t = [];
      const f = [];
      const a = [];
      for (const v of chain) {
        const x = v.get('x');
        const y = v.get('y');
        const w = v.get('w');
        if (typeof x !== 'number' || typeof y !== 'number') continue;
        if (Number.isNaN(x) || Number.isNaN(y)) continue; // justidraw strips these too
        t.push(x * secondsPerX);
        f.push(centsToHz(-y));
        a.push(toAmp(typeof w === 'number' && !Number.isNaN(w) ? w : 0));
      }
      if (t.length >= 2) partials.push(makePartial(partials.length + 1, t, f, a));
    }
  }

  if (!partials.length) throw new Error('justidraw file contains no drawn material.');

  return finalise({
    name: name || song.get('name') || 'justidraw score',
    source: 'justidraw',
    bpm,
    ampCurve,
    partials,
  });
}

/* ------------------------------------------------------------------ *
 * phonorealizer CSV
 * ------------------------------------------------------------------ */

/**
 * The modifier writes amplitude either as linear 0..1 or as dBFS depending on
 * the export path, and the column is named the same either way. Negative or
 * large values mean dB; a clean 0..1 range means linear.
 */
function amplitudeIsDecibels(values) {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min < -0.0001 || max > 1.5;
}

export function parseCSV(text, { name } = {}) {
  const lines = text.split(/\r?\n/);
  let start = 0;
  while (start < lines.length && !lines[start].trim()) start++;
  if (start >= lines.length) throw new Error('CSV is empty.');

  const header = lines[start].split(',').map((h) => h.trim().toLowerCase());
  const col = (...names) => {
    for (const n of names) {
      const i = header.indexOf(n);
      if (i >= 0) return i;
    }
    return -1;
  };
  const iT = col('time', 't');
  const iF = col('frequency', 'freq', 'hz');
  const iA = col('amplitude', 'amp');
  const iH = col('harmonic_index', 'partial', 'partial_index', 'index');
  if (iT < 0 || iF < 0 || iA < 0) {
    throw new Error('CSV needs at least time, frequency and amplitude columns.');
  }

  const groups = new Map();
  const rawAmps = [];
  for (let li = start + 1; li < lines.length; li++) {
    const line = lines[li];
    if (!line) continue;
    const cells = line.split(',');
    if (cells.length <= iF) continue;
    const t = parseFloat(cells[iT]);
    const f = parseFloat(cells[iF]);
    const a = parseFloat(cells[iA]);
    if (!Number.isFinite(t) || !Number.isFinite(f)) continue;
    const key = iH >= 0 ? parseInt(cells[iH], 10) || 0 : 1;
    let g = groups.get(key);
    if (!g) groups.set(key, (g = { t: [], f: [], a: [] }));
    g.t.push(t);
    g.f.push(f);
    const amp = Number.isFinite(a) ? a : 0;
    g.a.push(amp);
    rawAmps.push(amp);
  }
  if (!groups.size) throw new Error('CSV contains no usable rows.');

  const asDb = amplitudeIsDecibels(rawAmps);
  const partials = [];
  for (const key of [...groups.keys()].sort((x, y) => x - y)) {
    const g = groups.get(key);
    // Rows can arrive out of order; envelopes must be monotonic in time.
    const order = g.t.map((_, i) => i).sort((i, j) => g.t[i] - g.t[j]);
    const t = order.map((i) => g.t[i]);
    const f = order.map((i) => g.f[i]);
    const a = order.map((i) => {
      const v = g.a[i];
      return asDb ? (v <= -120 ? 0 : Math.pow(10, v / 20)) : v;
    });
    if (t.length >= 2) partials.push(makePartial(key, t, f, a));
  }
  if (!partials.length) throw new Error('CSV contains no partial with two or more points.');

  return finalise({
    name: name || 'phonorealizer score',
    source: 'csv',
    bpm: null,
    ampCurve: asDb ? 'dB→linear' : 'linear',
    partials,
  });
}

/* ------------------------------------------------------------------ *
 * Simplification — only kicks in for very large scores
 * ------------------------------------------------------------------ */

/**
 * Drop breakpoints that linear interpolation would have reconstructed anyway.
 * Tolerances are perceptual: cents for pitch, absolute for amplitude.
 */
function simplifyPartial(p, centsTol = 1.5, ampTol = 0.004) {
  const n = p.t.length;
  if (n < 3) return p;
  const keep = new Uint8Array(n);
  keep[0] = 1;
  keep[n - 1] = 1;

  let anchor = 0;
  for (let i = 1; i < n - 1; i++) {
    const span = p.t[i + 1] - p.t[anchor];
    const u = span > 0 ? (p.t[i] - p.t[anchor]) / span : 0;
    const fLerp = p.f[anchor] + u * (p.f[i + 1] - p.f[anchor]);
    const aLerp = p.a[anchor] + u * (p.a[i + 1] - p.a[anchor]);
    const centsErr =
      p.f[i] > 0 && fLerp > 0 ? Math.abs(1200 * Math.log2(p.f[i] / fLerp)) : 0;
    if (centsErr > centsTol || Math.abs(p.a[i] - aLerp) > ampTol) {
      keep[i] = 1;
      anchor = i;
    }
  }

  const t = [];
  const f = [];
  const a = [];
  for (let i = 0; i < n; i++) {
    if (keep[i]) {
      t.push(p.t[i]);
      f.push(p.f[i]);
      a.push(p.a[i]);
    }
  }
  return makePartial(p.index, t, f, a);
}

/* ------------------------------------------------------------------ *
 * Assembly, parts, (de)serialisation
 * ------------------------------------------------------------------ */

function finalise(score) {
  let total = score.partials.reduce((s, p) => s + p.t.length, 0);
  if (total > SIMPLIFY_THRESHOLD) {
    score.partials = score.partials.map((p) => simplifyPartial(p));
    score.simplified = true;
    total = score.partials.reduce((s, p) => s + p.t.length, 0);
  }

  // Number partials canonically, lowest first, rather than trusting whatever
  // order the source file happened to use. The two formats disagree here: a
  // justidraw export comes out in frequency order, while the CSV carries
  // SPEAR's `harmonic_index`, which is a tracking id in arbitrary order. Both
  // describe the same music, so "partial 7" has to name the same line either
  // way — a performer's part assignment must survive a re-export.
  if (!score.canonical) {
    score.partials.sort((p, q) => p.fMed - q.fMed || p.srcIndex - q.srcIndex);
    score.partials.forEach((p, i) => {
      p.index = i + 1;
    });
    score.canonical = true;
  }

  score.pointCount = total;
  score.duration = score.partials.reduce((d, p) => Math.max(d, p.t1), 0);
  if (!score.parts) score.parts = defaultParts(score);
  return score;
}

/** One part per partial, labelled with its register so it is pickable by ear. */
export function defaultParts(score) {
  return score.partials.map((p) => ({
    id: `p${p.index}`,
    name: `Partial ${p.index}`,
    partials: [p.index],
    auto: true,
  }));
}

export function partLabel(score, part) {
  const ps = part.partials.map((i) => score.partials[i - 1]).filter(Boolean);
  if (!ps.length) return '—';
  const lo = Math.min(...ps.map((p) => p.fMin));
  const hi = Math.max(...ps.map((p) => p.fMax));
  const med = ps[0].fMed;
  return `${hzToNoteName(med)} · ${lo.toFixed(0)}–${hi.toFixed(0)} Hz`;
}

/** Partials belonging to a part, in score order. */
export function partPartials(score, part) {
  if (!part) return [];
  return part.partials.map((i) => score.partials[i - 1]).filter(Boolean);
}

const r = (v, dp) => {
  const m = Math.pow(10, dp);
  return Math.round(v * m) / m;
};

/** Compact JSON for the wire. Rounding here is well below perceptual limits. */
export function scoreToJSON(score) {
  return {
    v: 1,
    name: score.name,
    source: score.source,
    bpm: score.bpm,
    ampCurve: score.ampCurve,
    duration: r(score.duration, 6),
    simplified: !!score.simplified,
    parts: score.parts,
    partials: score.partials.map((p) => ({
      i: p.index,
      s: p.srcIndex,
      t: Array.from(p.t, (v) => r(v, 5)),
      f: Array.from(p.f, (v) => r(v, 4)),
      a: Array.from(p.a, (v) => r(v, 5)),
    })),
  };
}

export function scoreFromJSON(obj) {
  const score = {
    name: obj.name,
    source: obj.source,
    bpm: obj.bpm,
    ampCurve: obj.ampCurve,
    simplified: obj.simplified,
    // Already numbered canonically by the sender; keep those indices exactly,
    // so a part claimed before reload still refers to the same line.
    canonical: true,
    partials: obj.partials.map((p) => {
      const q = makePartial(p.i, p.t, p.f, p.a);
      q.srcIndex = p.s ?? p.i;
      return q;
    }),
  };
  score.parts = obj.parts && obj.parts.length ? obj.parts : null;
  return finalise(score);
}

/* ------------------------------------------------------------------ *
 * File dispatch
 * ------------------------------------------------------------------ */

/**
 * Load whichever of the two formats the user handed us.
 *
 * Note that .sav is ambiguous in this project: justidraw writes binser binary,
 * while the modifier's Tessera export writes a Lua source table under the same
 * extension. Sniff the first byte rather than trusting the name — 207 is
 * binser's TABLE tag, whereas Tessera files start with "local project".
 */
export async function loadScoreFile(file, opts = {}) {
  const lower = file.name.toLowerCase();
  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  const looksBinser = bytes[0] === 207;
  const name = file.name.replace(/\.[^.]+$/, '');

  if (looksBinser) return parseJustidraw(buf, { ...opts, name });

  const text = new TextDecoder('utf-8').decode(bytes);
  if (/^\s*local\s+project\s*=/.test(text)) {
    throw new Error(
      'This is a Tessera .sav (Lua source), not a justidraw save. ' +
        'Export CSV from the modifier, or save from justidraw itself.'
    );
  }
  if (lower.endsWith('.csv') || /(^|\n)\s*time\s*,/i.test(text)) {
    return parseCSV(text, { ...opts, name });
  }
  throw new Error(`Unrecognised score file: ${file.name}`);
}
