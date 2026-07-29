/*
 * annotations.js — the engraving layer.
 *
 * Text set against a score: lyrics, expression markings, rehearsal marks. Kept
 * in a sidecar file and never written back into the justidraw .sav, because
 * those are the one irreplaceable artefact in this project and a round-trip
 * through a foreign writer is a needless risk. A sidecar also survives
 * re-exporting the score from the modifier.
 *
 * Two anchoring decisions carry the design:
 *
 *   Time, not x-position. Everything is stamped in seconds, so annotations stay
 *   correct when the engraver zooms, when the performer app scrolls at a
 *   different rate, and when a printed page breaks somewhere else entirely.
 *
 *   Cents, not pixels, for the vertical nudge. An annotation glued to a line
 *   has to travel with it as the pitch scale changes; a pixel offset would
 *   drift off its partial the moment the view rescaled.
 *
 * Scope is either a part id or GLOBAL, which is what lets the same mark be set
 * on one player's part or on everybody's at once.
 */

/**
 * Scope for a mark or a break that belongs to the whole work rather than one
 * player's part. Called "Full Score" throughout the interface, matching the
 * layout it applies to.
 */
export const GLOBAL = '*';

/**
 * Annotation kinds. `place` and styling defaults follow ordinary engraving
 * convention so that a mark looks right without the user styling it.
 */
export const KINDS = {
  lyric: { label: 'Lyric', place: 'below', italic: false, size: 14 },
  expression: { label: 'Expression', place: 'below', italic: true, size: 13 },
  dynamic: { label: 'Dynamic', place: 'below', italic: true, size: 15, bold: true },
  rehearsal: { label: 'Rehearsal mark', place: 'above', italic: false, size: 15, bold: true, boxed: true },
  text: { label: 'Text', place: 'above', italic: false, size: 13 },
};

export const KIND_ORDER = ['lyric', 'expression', 'dynamic', 'rehearsal', 'text'];

let counter = 0;
function newId() {
  counter += 1;
  return `a${Date.now().toString(36)}${counter.toString(36)}`;
}

/**
 * @typedef {object} Annotation
 * @property {string} id
 * @property {string} scope   part id, or GLOBAL for every part at once
 * @property {string} kind    key of KINDS
 * @property {number} t       seconds
 * @property {number|null} t2 optional end time; present means it spans
 * @property {string} text
 * @property {'above'|'below'|'on'} place
 * @property {number} dy      vertical nudge in cents, relative to the line
 * @property {object} style   { size, italic, bold }
 */

export function makeAnnotation({
  scope = GLOBAL,
  kind = 'text',
  t = 0,
  t2 = null,
  text = '',
  place = null,
  dy = 0,
  style = null,
} = {}) {
  const def = KINDS[kind] || KINDS.text;
  return {
    id: newId(),
    scope,
    kind,
    t,
    t2,
    text,
    place: place || def.place,
    dy,
    style: style || {
      size: def.size,
      italic: !!def.italic,
      bold: !!def.bold,
    },
  };
}

/* ------------------------------------------------------------------ *
 * Project document
 * ------------------------------------------------------------------ */

/**
 * An engraving project: which score it belongs to, the part map, and the marks.
 * The score itself is NOT embedded — it is referenced by name and metadata, so
 * the sidecar stays small and the composer keeps editing the .sav freely.
 */
export function makeProject(score = null, parts = null) {
  return {
    v: 1,
    kind: 'phonorealism-engraving',
    /** System and page breaks; see layout.js. */
    breaks: [],
    /** Per-layout engraving profiles (score / parts); see layout.js. */
    layouts: null,
    score: score
      ? {
          name: score.name,
          source: score.source,
          duration: score.duration,
          partials: score.partials.length,
        }
      : null,
    parts: parts || [],
    annotations: [],
  };
}

/**
 * Check a project against a freshly loaded score.
 *
 * Partial numbering is canonical (ascending median frequency), so a part map
 * survives re-export from the modifier — but only if the score still has at
 * least as many partials. Anything referring past the end is reported rather
 * than silently dropped.
 */
export function validate(project, score) {
  const issues = [];
  if (!project || project.kind !== 'phonorealism-engraving') {
    issues.push({ level: 'error', message: 'Not a phonorealism engraving file.' });
    return issues;
  }
  if (!score) return issues;

  const n = score.partials.length;
  for (const part of project.parts || []) {
    const bad = (part.partials || []).filter((i) => i < 1 || i > n);
    if (bad.length) {
      issues.push({
        level: 'error',
        message: `Part "${part.name}" refers to partial ${bad.join(', ')}, but this score has ${n}.`,
      });
    }
  }
  if (project.score && Math.abs((project.score.duration || 0) - score.duration) > 0.5) {
    issues.push({
      level: 'warn',
      message:
        `Score duration changed (${(project.score.duration || 0).toFixed(1)} s → ` +
        `${score.duration.toFixed(1)} s). Time-anchored marks may need moving.`,
    });
  }
  const ids = new Set((project.parts || []).map((p) => p.id));
  const orphans = (project.annotations || []).filter(
    (a) => a.scope !== GLOBAL && !ids.has(a.scope)
  );
  if (orphans.length) {
    issues.push({
      level: 'warn',
      message: `${orphans.length} annotation(s) belong to a part that no longer exists.`,
    });
  }
  return issues;
}

/** Annotations that should appear on a given part, in time order. */
export function forPart(project, partId) {
  return (project.annotations || [])
    .filter((a) => a.scope === GLOBAL || a.scope === partId)
    .sort((x, y) => x.t - y.t || x.id.localeCompare(y.id));
}

/** All annotations in time order, for the full-score view. */
export function allSorted(project) {
  return [...(project.annotations || [])].sort(
    (x, y) => x.t - y.t || x.id.localeCompare(y.id)
  );
}

export function addAnnotation(project, spec) {
  const a = makeAnnotation(spec);
  project.annotations.push(a);
  return a;
}

export function removeAnnotation(project, id) {
  const i = project.annotations.findIndex((a) => a.id === id);
  if (i >= 0) project.annotations.splice(i, 1);
  return i >= 0;
}

export function updateAnnotation(project, id, patch) {
  const a = project.annotations.find((x) => x.id === id);
  if (!a) return null;
  Object.assign(a, patch);
  // Changing kind adopts that kind's conventional placement unless the user
  // has already moved it deliberately.
  if (patch.kind && !patch.place) {
    const def = KINDS[patch.kind];
    if (def) a.place = def.place;
  }
  return a;
}

/**
 * Duplicate a mark onto every part — the "all simultaneously" case, when the
 * user wants per-part copies they can then edit individually rather than one
 * shared global mark.
 */
export function explodeToParts(project, id) {
  const src = project.annotations.find((a) => a.id === id);
  if (!src) return [];
  const made = [];
  for (const part of project.parts) {
    made.push(addAnnotation(project, { ...src, scope: part.id }));
  }
  removeAnnotation(project, id);
  return made;
}

/* ------------------------------------------------------------------ *
 * Part map interchange
 * ------------------------------------------------------------------ */

/**
 * The part-map file the conductor page imports. Deliberately the same shape it
 * already exports, so the two remain interchangeable in both directions.
 */
export function toPartMap(project) {
  return {
    v: 1,
    parts: project.parts.map((p) => ({
      id: p.id,
      name: p.name,
      partials: [...p.partials],
      auto: false,
    })),
  };
}

export function fromPartMap(obj) {
  if (!obj || !Array.isArray(obj.parts)) throw new Error('Not a part map file.');
  return obj.parts.map((p) => ({
    id: String(p.id),
    name: String(p.name || 'Part'),
    partials: (p.partials || []).map(Number).filter((n) => Number.isFinite(n) && n >= 1),
  }));
}
