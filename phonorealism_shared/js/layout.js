/*
 * layout.js — casting off.
 *
 * Decides how a continuous score becomes systems and pages: where each system
 * starts and ends in time, which parts it carries, and how the systems fall
 * onto pages. Shared between the engraver's canvas and its export, because a
 * page break the user placed has to land in exactly the same place on paper as
 * it did on screen — two layout implementations would eventually disagree, and
 * the disagreement would only surface after printing.
 *
 * Terms follow Dorico, since that is the vocabulary in use:
 *
 *   note spacing   how much horizontal room a second of music occupies
 *   staff spacing  the vertical size of one part's band and the gaps around it
 *   system break   force the next music onto a new system
 *   page break     force it onto a new page
 *
 * With no breaks at all the music casts off automatically, filling each system
 * before wrapping. Breaks override that; they never merely suggest.
 */

export const GLOBAL = '*';

/** Default page: A4 landscape at 96 dpi. */
export function defaultPage() {
  return { w: 1123, h: 794, margin: 54 };
}

export function defaultLayout() {
  return {
    /* --- note spacing (horizontal) --- */
    pxPerSecond: 46,

    /* --- staff spacing (vertical) --- */
    staffHeight: 84, // one part's band
    staffGap: 12, // between parts within a system
    systemGap: 34, // between systems

    /* --- ink --- */
    ribbonScale: 18,
    labelWidth: 88,

    /*
     * Furniture, all off by default. The notation is the ribbon; rules, grids
     * and running heads are additions the engraver should opt into rather than
     * have to strip out of every export.
     */
    showStaffLines: false,
    showBarlines: false,
    showTitle: false,
    showPageNumbers: false,
    showPartLabels: true,

    /** Lowest-sounding part at the bottom, as in a conventional score. */
    lowestAtBottom: true,

    page: defaultPage(),
  };
}

/**
 * Parts in display order.
 *
 * Lowest at the bottom means iterating from the highest part downwards, ranked
 * by the lowest partial each contains — so partial 1 sits on the bottom system
 * and the spectrum reads upward, the way an orchestral score does.
 */
export function orderedParts(parts, layout) {
  const list = [...(parts || [])];
  if (!layout?.lowestAtBottom) return list;
  const rank = (p) => Math.min(...(p.partials?.length ? p.partials : [Infinity]));
  return list.sort((a, b) => rank(b) - rank(a));
}

/** Breaks that apply to a given layout target, in time order. */
export function breaksFor(project, target) {
  return (project.breaks || [])
    .filter((b) => b.scope === GLOBAL || (target !== 'score' && b.scope === target))
    .sort((x, y) => x.t - y.t);
}

/**
 * Cast the score off into systems and pages.
 *
 * @param {object} score
 * @param {object} project
 * @param {object} opts
 *   target  'score' for every part on each system, or a part id for a part layout
 * @returns {{pages: Array, layout: object, parts: Array}}
 */
export function castOff(score, project, opts = {}) {
  const target = opts.target || 'score';
  const layout = { ...defaultLayout(), ...(project.layout || {}), ...(opts.layout || {}) };
  const page = { ...defaultPage(), ...(layout.page || {}) };

  const all = project.parts || [];
  const parts =
    target === 'score' ? orderedParts(all, layout) : all.filter((p) => p.id === target);
  if (!parts.length) return { pages: [], layout, parts: [] };

  const duration = score?.duration || 0;
  const systemW = page.w - page.margin * 2 - (layout.showPartLabels ? layout.labelWidth : 0);
  const autoSeconds = Math.max(0.5, systemW / Math.max(1, layout.pxPerSecond));

  const marks = breaksFor(project, target);
  const systemHeight = parts.length * layout.staffHeight + (parts.length - 1) * layout.staffGap;
  const usableH = page.h - page.margin * 2;

  const pages = [];
  let current = { systems: [] };
  let usedH = 0;
  let t = 0;

  const pushPage = () => {
    if (current.systems.length) pages.push(current);
    current = { systems: [] };
    usedH = 0;
  };

  let guard = 0;
  while (t < duration - 1e-6 && guard++ < 10000) {
    // A system runs until the next break or until it is full, whichever first.
    const next = marks.find((b) => b.t > t + 1e-6);
    const autoEnd = t + autoSeconds;
    let end = Math.min(duration, autoEnd);
    let forcedBy = null;
    if (next && next.t < end - 1e-6) {
      end = next.t;
      forcedBy = next;
    }

    const needed = systemHeight + (current.systems.length ? layout.systemGap : 0);
    if (usedH + needed > usableH && current.systems.length) pushPage();

    current.systems.push({
      tA: t,
      tB: end,
      parts,
      // Recorded so the canvas can show where a break took effect.
      brokenBy: forcedBy ? forcedBy.kind : null,
    });
    usedH += systemHeight + (current.systems.length > 1 ? layout.systemGap : 0);

    t = end;

    // A page break starts the next system on a fresh page.
    if (forcedBy && forcedBy.kind === 'page') pushPage();
  }
  pushPage();

  return { pages, layout, parts, page, systemHeight };
}

/**
 * Geometry for one system on a page: where each part's band sits.
 * @returns {Array<{part, top, height, centre, span, ampRef}>}
 */
export function systemBands(system, score, layout, top) {
  const bands = [];
  let y = top;
  for (const part of system.parts) {
    const partials = (part.partials || [])
      .map((i) => score.partials[i - 1])
      .filter(Boolean);
    let lo = Infinity;
    let hi = -Infinity;
    let aMax = 0;
    for (const p of partials) {
      lo = Math.min(lo, p.fMin);
      hi = Math.max(hi, p.fMax);
      aMax = Math.max(aMax, p.aMax);
    }
    if (!Number.isFinite(lo) || !(hi > 0)) {
      lo = 220;
      hi = 880;
    }
    bands.push({
      part,
      partials,
      top: y,
      height: layout.staffHeight,
      // Each part is scaled to its own register. A phonorealism score can span
      // five octaves across its partials; one shared axis would flatten every
      // individual line into a thread.
      centre: 1200 * Math.log2(Math.sqrt(lo * hi) / 440),
      span: Math.max(180, 1200 * Math.log2(hi / lo) * 0.62),
      ampRef: aMax > 1e-6 ? aMax : 1,
    });
    y += layout.staffHeight + layout.staffGap;
  }
  return bands;
}

/* ------------------------------------------------------------------ *
 * Breaks
 * ------------------------------------------------------------------ */

let breakCounter = 0;

export function makeBreak({ kind = 'system', t = 0, scope = GLOBAL } = {}) {
  breakCounter += 1;
  return { id: `b${Date.now().toString(36)}${breakCounter.toString(36)}`, kind, t, scope };
}

export function addBreak(project, spec) {
  if (!project.breaks) project.breaks = [];
  // One break per instant per scope; re-adding toggles its kind instead of
  // stacking two invisible breaks on top of each other.
  const existing = project.breaks.find(
    (b) => b.scope === (spec.scope ?? GLOBAL) && Math.abs(b.t - spec.t) < 0.02
  );
  if (existing) {
    existing.kind = spec.kind ?? existing.kind;
    return existing;
  }
  const b = makeBreak(spec);
  project.breaks.push(b);
  return b;
}

export function removeBreak(project, id) {
  if (!project.breaks) return false;
  const i = project.breaks.findIndex((b) => b.id === id);
  if (i >= 0) project.breaks.splice(i, 1);
  return i >= 0;
}
