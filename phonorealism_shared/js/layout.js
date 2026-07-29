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

/**
 * Paper sizes at 96 dpi, stored as long and short edges so orientation is a
 * separate choice rather than a different size entry.
 */
export const PAGE_SIZES = {
  a4: { label: 'A4', long: 1123, short: 794 },
  letter: { label: 'US Letter', long: 1056, short: 816 },
  a3: { label: 'A3', long: 1587, short: 1123 },
  tabloid: { label: 'Tabloid', long: 1632, short: 1056 },
};

/** Resolve a layout's page setup into concrete dimensions. */
export function pageGeometry(layout = {}) {
  const size = PAGE_SIZES[layout.pageSize] || PAGE_SIZES.a4;
  const landscape = (layout.orientation || 'landscape') === 'landscape';
  return {
    w: landscape ? size.long : size.short,
    h: landscape ? size.short : size.long,
    margin: layout.margin ?? 54,
  };
}

export function defaultPage() {
  return pageGeometry({});
}

export function defaultLayout() {
  return {
    /* --- page setup --- */
    pageSize: 'a4',
    orientation: 'landscape',
    margin: 54,

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
    showTitle: false,
    showPageNumbers: false,
    showPartLabels: true,

    /* --- time rules (see timeMarkers) --- */
    rulesStyle: 'none', // none | ticks | barlines | grid
    /**
     * Marker rate as a tempo: 60 puts a marker every second, 120 every half
     * second. Expressed in BPM because that is the unit this music is actually
     * cued against, even though it has no metre of its own.
     */
    rulesRate: 60,
    /** Emphasise every Nth marker, giving a pulse. 0 for an even grid. */
    rulesGroup: 4,
    rulesLabels: 'seconds', // none | seconds | mmss | count
    /** The horizontal rule under a staff. Off by default; it carries no data. */
    showStaffOutline: false,

    /** Lowest-sounding part at the bottom, as in a conventional score. */
    lowestAtBottom: true,
  };
}

/**
 * Separate layout profiles for the full score and for the parts.
 *
 * A conductor's score and a player's part are engraved differently on purpose:
 * the score has to fit every part on a page and can afford to be tight, while a
 * part is read from a stand at a distance and wants room. Sharing one set of
 * spacing values would force a compromise that suits neither.
 *
 * Keyed by target so a single part can later be given its own profile without
 * changing the shape of the file.
 */
export function defaultLayouts() {
  return {
    score: {
      ...defaultLayout(),
      orientation: 'landscape',
      staffHeight: 64,
      staffGap: 8,
      systemGap: 24,
      ribbonScale: 13,
      pxPerSecond: 40,
    },
    parts: {
      ...defaultLayout(),
      orientation: 'landscape',
      staffHeight: 132,
      staffGap: 14,
      systemGap: 46,
      ribbonScale: 24,
      pxPerSecond: 64,
    },
  };
}

/**
 * The layout profile governing a target: the score profile for the full score,
 * a part's own profile if it has one, otherwise the shared parts profile.
 */
export function layoutFor(project, target = 'score') {
  const set = project?.layouts || {};
  const chosen =
    target === 'score' ? set.score : set[target] || set.parts;
  return { ...defaultLayout(), ...(chosen || {}) };
}

/** Which profile key a target edits. */
export function profileKeyFor(target) {
  return target === 'score' ? 'score' : 'parts';
}

/**
 * Time markers across a span: pseudo-barlines at a chosen rate.
 *
 * This music has no metre, so nothing derives a barline for us. What a player
 * can actually use is a regular time reference, and the natural unit to specify
 * it in is tempo — 60 gives one marker a second, 120 one every half second.
 * Grouping emphasises every Nth marker so the eye gets a pulse rather than an
 * undifferentiated comb.
 *
 * @param {number} pxPerSecond used to thin markers that would collide
 * @returns {Array<{t:number, index:number, strong:boolean}>}
 */
export function timeMarkers(tA, tB, { rate = 60, group = 4, pxPerSecond = 40 } = {}) {
  const interval = 60 / Math.max(1, rate);
  if (!(interval > 0) || !Number.isFinite(interval)) return [];

  // Below roughly 5 px apart the markers stop reading as separate lines and
  // start reading as a fill, so thin to the emphasised ones and then give up
  // entirely rather than blacking out the staff.
  const spacing = interval * pxPerSecond;
  let step = 1;
  if (spacing < 5) {
    if (!group || group * spacing < 5) return [];
    step = group;
  }

  const out = [];
  const first = Math.ceil(tA / interval - 1e-9);
  const last = Math.floor(tB / interval + 1e-9);
  for (let i = first; i <= last; i++) {
    if (i % step !== 0) continue;
    out.push({
      t: i * interval,
      index: i,
      strong: !!group && i % group === 0,
    });
  }
  return out;
}

/** Label for a marker, in the requested format. */
export function markerLabel(marker, mode, rate = 60) {
  if (mode === 'none' || !mode) return '';
  if (mode === 'count') return String(marker.index);
  const t = marker.t;
  if (mode === 'mmss') {
    const m = Math.floor(t / 60);
    const sec = t - m * 60;
    return `${m}:${sec < 10 ? '0' : ''}${sec.toFixed(sec % 1 ? 1 : 0)}`;
  }
  // seconds
  return `${t.toFixed(t % 1 ? 1 : 0)}s`;
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
  const layout = { ...layoutFor(project, target), ...(opts.layout || {}) };
  const page = pageGeometry(layout);

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
