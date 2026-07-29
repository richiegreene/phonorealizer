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
    /**
     * Crop every staff to the pitch its part actually uses in that system, so
     * no vertical space is spent on register the music never reaches.
     *
     * The pitch axis is cropped, not rescaled: a partial keeps the same slope
     * whichever way this is set, because rescaling per system would make the
     * same glissando look steeper on one system than the next. See
     * measureBands().
     */
    normalizeHeights: false,

    /* --- ink --- */
    ribbonScale: 18,

    /*
     * Furniture, all off by default. The notation is the ribbon; rules, grids
     * and running heads are additions the engraver should opt into rather than
     * have to strip out of every export.
     */
    showTitle: false,
    showPageNumbers: false,
    showPartLabels: true,
    /**
     * Engraved size of a part name, in px. Held fixed on screen rather than
     * scaled with the zoom, so the name reads the same while the page is being
     * inspected — this slider is the only thing that changes it.
     */
    partLabelSize: 10,
    /** The gutter part names are set in, taken off the system's width. */
    labelWidth: 88,

    /* --- grid rules, vertical: in time (see timeMarkers) --- */
    rulesStyle: 'none', // none | ticks | barlines
    /**
     * Marker rate as a tempo: 60 puts a marker every second, 120 every half
     * second. Expressed in BPM because that is the unit this music is actually
     * cued against, even though it has no metre of its own.
     */
    rulesRate: 60,
    /** Emphasise every Nth marker, giving a pulse. 0 for an even grid. */
    rulesGroup: 4,
    rulesLabels: 'seconds', // none | seconds | mmss | count
    /** Height of the tick row within a staff: 0 at the bottom, 1 at the top. */
    rulesTickPos: 0,

    /* --- grid rules, horizontal: in pitch (see pitchGrid) --- */
    pitchGrid: 'none', // none | semitones | piano | pianoLines
    /** How dark a piano-roll chromatic region is drawn. */
    pitchGridOpacity: 0.1,

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
      partLabelSize: 9,
    },
    parts: {
      ...defaultLayout(),
      orientation: 'landscape',
      staffHeight: 132,
      staffGap: 14,
      systemGap: 46,
      ribbonScale: 24,
      pxPerSecond: 64,
      partLabelSize: 11,
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
  const layout = { ...defaultLayout(), ...(chosen || {}) };
  // 'grid' — barlines carried on through the gap below the staff — has been
  // withdrawn now that the horizontal grid does the joining-up. Projects saved
  // with it read as plain barlines rather than silently losing their rules.
  if (layout.rulesStyle === 'grid') layout.rulesStyle = 'barlines';
  return layout;
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

/* ------------------------------------------------------------------ *
 * Grid rules, horizontal: pitch
 * ------------------------------------------------------------------ */

/**
 * The chromatic pitch classes, counted in semitones up from A.
 *
 * Everything vertical in this project is cents relative to A440, so semitone n
 * is exactly n * 100 cents and its pitch class is n mod 12 from A: A(0) A♯(1)
 * B(2) C(3) C♯(4) D(5) D♯(6) E(7) F(8) F♯(9) G(10) G♯(11). The five here are
 * the piano's black notes.
 */
const BLACK_CLASSES = new Set([1, 4, 6, 9, 11]);

/** Semitones up from A to C — where a piano-roll octave is read from. */
const CLASS_C = 3;

export function isBlackClass(semitone) {
  return BLACK_CLASSES.has(((semitone % 12) + 12) % 12);
}

/**
 * Horizontal pitch grid across a range of cents.
 *
 * Two readings of the same 12-edo lattice, either or both:
 *
 *   lines  a rule *at* each semitone, so a partial's pitch can be read off the
 *          line it is sitting on. Emphasised at every C.
 *   bands  the piano-roll reading: each chromatic region shaded, one semitone
 *          tall and centred on its black note, so a partial in the middle of a
 *          dark region is on that black note.
 *
 * Both are derived from the same cents-from-A440 scale the ribbon is drawn
 * against, so they line up with the notation rather than approximating it.
 *
 * @param {number} pxPerCent vertical scale, used to thin an unreadable grid
 * @returns {{lines: Array<{cents:number, strong:boolean}>, bands: Array<{c0:number, c1:number}>}}
 */
export function pitchGrid(centsLo, centsHi, pxPerCent, mode = 'none') {
  const out = { lines: [], bands: [] };
  if (!mode || mode === 'none') return out;
  if (!(centsHi > centsLo) || !(pxPerCent > 0)) return out;

  const wantBands = mode === 'piano' || mode === 'pianoLines';
  const wantLines = mode === 'semitones' || mode === 'pianoLines';
  const px = 100 * pxPerCent; // one semitone, in pixels

  // Below roughly five pixels a semitone the lines stop reading as separate
  // rules and start reading as a fill, so thin to the octaves and then give up
  // rather than blacking out the staff. Shading survives closer spacing than
  // lines do, since alternating light and dark still reads as a pattern.
  const lineStep = px >= 5 ? 1 : px * 12 >= 9 ? 12 : 0;
  const bandsReadable = px >= 2;

  const first = Math.floor(centsLo / 100) - 1;
  const last = Math.ceil(centsHi / 100) + 1;
  for (let n = first; n <= last; n++) {
    const pc = ((n % 12) + 12) % 12;
    if (wantBands && bandsReadable && BLACK_CLASSES.has(pc)) {
      out.bands.push({ c0: (n - 0.5) * 100, c1: (n + 0.5) * 100 });
    }
    if (wantLines && lineStep && (lineStep === 1 || pc === CLASS_C)) {
      out.lines.push({ cents: n * 100, strong: pc === CLASS_C });
    }
  }
  return out;
}

/**
 * The name a part is labelled with on a given system.
 *
 * Engraving convention: the full name where the part first appears, the short
 * form on every system after it — which is the whole reason a nickname is worth
 * setting. A part without one keeps its full name throughout, rather than going
 * unlabelled from the second system on.
 */
export function partLabelFor(part, systemIndex = 0) {
  const full = (part?.name || '').trim();
  if (!systemIndex) return full;
  return (part?.nick || '').trim() || full;
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
  const usableH = page.h - page.margin * 2;

  const pages = [];
  let current = { systems: [] };
  let usedH = 0;
  let t = 0;
  let index = 0;
  let tallest = 0;

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

    // Measured here rather than once for the whole score: with normalised
    // heights every system is a different height, and how many fit on a page
    // cannot be known until each one has been measured.
    const metrics = measureBands(parts, score, layout, t, end, {
      project,
      pxPerSecond: systemW / Math.max(1e-6, end - t),
    });
    const systemHeight = measuredHeight(metrics, layout);
    tallest = Math.max(tallest, systemHeight);

    const needed = systemHeight + (current.systems.length ? layout.systemGap : 0);
    if (usedH + needed > usableH && current.systems.length) pushPage();

    current.systems.push({
      tA: t,
      tB: end,
      parts,
      metrics,
      height: systemHeight,
      /** Position in the layout: the first system is the one that names parts. */
      index: index++,
      // Recorded so the canvas can show where a break took effect.
      brokenBy: forcedBy ? forcedBy.kind : null,
    });
    usedH += systemHeight + (current.systems.length > 1 ? layout.systemGap : 0);

    t = end;

    // A page break starts the next system on a fresh page.
    if (forcedBy && forcedBy.kind === 'page') pushPage();
  }
  pushPage();

  return { pages, layout, parts, page, systemHeight: tallest };
}

/* ------------------------------------------------------------------ *
 * Staff geometry
 * ------------------------------------------------------------------ */

/** Smallest staff a normalised band is allowed to collapse to. */
const MIN_CORE = 10;

/**
 * How many rows of text a normalised staff will stack above or below itself.
 *
 * Marks are placed by hand at exact times, so a dense passage of lyrics can ask
 * for a row each. Past a few rows the staff has grown taller than the music it
 * carries, which is the opposite of what normalising is for — beyond this the
 * crowding is a spacing problem to solve horizontally, not by growing the page.
 */
const MAX_ROWS = 4;

/**
 * Rough text width, without a canvas to measure with.
 *
 * Used to decide which row an annotation is stacked in. The estimate has to be
 * shared by the screen and the SVG: if the two measured text differently they
 * could disagree about a row, and a mark would move between what was engraved
 * and what was printed.
 */
export function estimateTextWidth(text, size) {
  return String(text ?? '').length * size * 0.56;
}

/** Index of the first sample at or after t, by bisection. */
function lowerBound(times, t) {
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** A partial's frequency at a time, or 0 outside its own span. */
function freqAt(p, t) {
  const n = p.t.length;
  if (!n || t < p.t[0] || t > p.t[n - 1]) return 0;
  const i = Math.max(0, lowerBound(p.t, t) - 1);
  if (i + 1 >= n) return p.f[n - 1];
  const span = p.t[i + 1] - p.t[i];
  const u = span > 0 ? (t - p.t[i]) / span : 0;
  return p.f[i] + u * (p.f[i + 1] - p.f[i]);
}

/**
 * The pitch range a set of partials actually occupies within a time window, in
 * cents relative to A440. Null if they are silent throughout it.
 *
 * Scanned by bisecting into the sample arrays rather than walking them, because
 * this runs once per part per system on every redraw.
 */
function centsWindow(partials, tA, tB) {
  let lo = Infinity;
  let hi = -Infinity;
  const see = (f) => {
    if (!(f > 0)) return;
    if (f < lo) lo = f;
    if (f > hi) hi = f;
  };
  for (const p of partials) {
    const from = lowerBound(p.t, tA);
    for (let i = from; i < p.t.length && p.t[i] <= tB; i++) see(p.f[i]);
    // A partial crossing an edge of the window is sounding at that edge even
    // when no sample lands exactly on it.
    see(freqAt(p, tA));
    see(freqAt(p, tB));
  }
  if (!Number.isFinite(lo) || !(hi > 0)) return null;
  return { lo: 1200 * Math.log2(lo / 440), hi: 1200 * Math.log2(hi / 440) };
}

/**
 * Stack annotations of one part into rows, and report how much room the rows
 * outside the staff need.
 *
 * Two things are being solved with one mechanism.
 *
 * A normalised staff is only as tall as the music, so there is no slack inside
 * it to hold text: every above or below mark goes *outward*, clear of the
 * ribbon, in as many rows as it takes for none of them to collide, and the staff
 * reserves room for them. The vertical nudge is folded into that room, so
 * dragging a mark further out still leaves it inside its own staff rather than
 * over the neighbouring one.
 *
 * A mark aligned to the staff wants the same collision-free rows, but measured
 * from a fixed height in its zone rather than from the sounding line. Where the
 * staff has slack — an un-normalised one always does — those rows stack *inward*
 * and cost the staff nothing.
 */
function annotationRows(project, part, tA, tB, pxPerSecond, pxPerCent, outward) {
  // A mark is formatted into a row when the staff has no room for it inside
  // (normalised) or when it has been aligned to the staff on purpose.
  const eligible = (a) =>
    (outward && (a.place === 'above' || a.place === 'below')) || a.align === 'staff';

  const marks = (project?.annotations || [])
    .filter(
      (a) =>
        (a.scope === GLOBAL || a.scope === part.id) &&
        a.t >= tA - 0.001 &&
        a.t <= tB + 0.001 &&
        eligible(a)
    )
    .sort((x, y) => x.t - y.t || String(x.id).localeCompare(String(y.id)));

  const rows = new Map();
  if (!marks.length) return { rows, rowH: 0, padTop: 0, padBottom: 0 };

  let maxSize = 0;
  for (const a of marks) maxSize = Math.max(maxSize, a.style?.size || 13);
  // Deep enough that a row's text, its descenders and a hair of leading all sit
  // inside it — see annotationY, which depends on this.
  const rowH = maxSize + 6;

  const ends = { above: [], below: [], on: [] };
  let padTop = 0;
  let padBottom = 0;
  for (const a of marks) {
    const size = a.style?.size || 13;
    const x = (a.t - tA) * pxPerSecond;
    const right = Math.max(
      x + estimateTextWidth(a.text, size) + 8,
      a.t2 != null && a.t2 > a.t ? (Math.min(a.t2, tB) - tA) * pxPerSecond : 0
    );
    const lane = ends[a.place] || ends.on;
    let row = 0;
    while (row < lane.length && lane[row] > x) row++;
    if (row >= MAX_ROWS) {
      // Every row is still occupied here. Take the one that clears soonest: it
      // is the least bad collision available, and the alternative is a staff
      // that keeps growing.
      row = 0;
      for (let i = 1; i < MAX_ROWS; i++) if (lane[i] < lane[row]) row = i;
    }
    lane[row] = Math.max(lane[row] ?? 0, right);

    const outer = outward && (a.place === 'above' || a.place === 'below');
    rows.set(a.id, { place: a.place, row, size, outward: outer });

    if (!outer) continue;
    const nudge = (a.dy || 0) * pxPerCent;
    const need = (row + 1) * rowH;
    if (a.place === 'above') padTop = Math.max(padTop, need + Math.max(0, nudge));
    else padBottom = Math.max(padBottom, need + Math.max(0, -nudge));
  }
  return { rows, rowH, padTop, padBottom };
}

/**
 * Measure each part's staff for one system, without placing it yet.
 *
 * Returns pixel heights at 1:1. Positions come later, in systemBands, so that
 * casting off can add these up to find a system's height before it knows where
 * on the page the system will land.
 *
 * @param {number|null} tA window the parts are measured over; null measures
 *   them over their whole extent, which is what the un-normalised setting does
 *   in any case
 */
export function measureBands(parts, score, layout, tA = null, tB = null, opts = {}) {
  const windowed =
    !!layout.normalizeHeights && score && Number.isFinite(tA) && Number.isFinite(tB);
  const pxPerSecond = opts.pxPerSecond || layout.pxPerSecond || 40;
  const out = [];

  for (const part of parts) {
    const partials = (part.partials || [])
      .map((i) => score?.partials?.[i - 1])
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

    // Each part is scaled to its own register. A phonorealism score can span
    // five octaves across its partials; one shared axis would flatten every
    // individual line into a thread.
    const fullCentre = 1200 * Math.log2(Math.sqrt(lo * hi) / 440);
    const fullSpan = Math.max(180, 1200 * Math.log2(hi / lo) * 0.62);
    // The scale the staff-height setting implies. Normalising crops to this
    // scale rather than choosing a new one per system.
    const pxPerCent = layout.staffHeight / 2 / fullSpan;
    const metric = {
      part,
      partials,
      ampRef: aMax > 1e-6 ? aMax : 1,
      pxPerCent,
      normalized: windowed,
      rows: null,
      rowH: 0,
      padTop: 0,
      padBottom: 0,
    };

    // Half the thickest the ribbon can get, so its edge is not clipped by the
    // crop that its own centreline exactly fits.
    const ribbonHalf = (0.4 + (layout.ribbonScale || 0)) / 2;
    const win = windowed ? centsWindow(partials, tA, tB) : null;

    if (!windowed) {
      metric.centre = fullCentre;
      metric.span = fullSpan;
      metric.coreH = layout.staffHeight;
    } else if (!win) {
      // Nothing sounding here. A part that is tacit through a system earns no
      // height in it; the label still has a sliver to sit against.
      metric.centre = fullCentre;
      metric.coreH = Math.max(MIN_CORE, ribbonHalf * 2);
      metric.span = metric.coreH / 2 / pxPerCent;
    } else {
      const coreH = Math.max(MIN_CORE, (win.hi - win.lo) * pxPerCent + ribbonHalf * 2);
      metric.centre = (win.lo + win.hi) / 2;
      metric.coreH = coreH;
      metric.span = coreH / 2 / pxPerCent;
    }

    // Rows are wanted either way: outward when the staff has no slack of its
    // own, inward for marks aligned to the staff, which an un-normalised staff
    // has room for.
    if (Number.isFinite(tA) && Number.isFinite(tB)) {
      const rows = annotationRows(
        opts.project, part, tA, tB, pxPerSecond, pxPerCent, windowed
      );
      metric.rows = rows.rows;
      metric.rowH = rows.rowH;
      metric.padTop = rows.padTop;
      metric.padBottom = rows.padBottom;
    }
    out.push(metric);
  }
  return out;
}

/** Total height of a measured system, gaps included. */
export function measuredHeight(metrics, layout) {
  if (!metrics.length) return 0;
  const ink = metrics.reduce((sum, m) => sum + m.padTop + m.coreH + m.padBottom, 0);
  return ink + (metrics.length - 1) * layout.staffGap;
}

/**
 * Geometry for one system: where each part's band sits.
 *
 * A band has two rectangles. `top`/`height` is the whole thing, which is what
 * stacks and what clips; `coreTop`/`coreH` is the pitch area the ribbon is
 * drawn in, with the annotation rows in the padding outside it. Un-normalised
 * they are the same rectangle.
 *
 * @param {object} opts { scale, project, pxPerSecond }
 * @returns {Array<{part, top, height, coreTop, coreH, centre, span, ampRef}>}
 */
export function systemBands(system, score, layout, top, opts = {}) {
  const scale = opts.scale || 1;
  const metrics =
    system.metrics ||
    measureBands(system.parts, score, layout, system.tA, system.tB, opts);

  const bands = [];
  let y = top;
  for (const m of metrics) {
    // Measurements are pixels at 1:1; the view scales them rather than
    // measuring again, so what is on screen is the page, zoomed.
    const padTop = m.padTop * scale;
    const coreH = m.coreH * scale;
    const padBottom = m.padBottom * scale;
    const height = padTop + coreH + padBottom;
    bands.push({
      ...m,
      top: y,
      height,
      coreTop: y + padTop,
      coreH,
      padTop,
      padBottom,
      rowH: m.rowH * scale,
      pxPerCent: m.pxPerCent * scale,
    });
    y += height + layout.staffGap * scale;
  }
  return bands;
}

/**
 * The tick row for a band: how long the marks are and where they sit.
 *
 * Ticks are a time reference rather than notation, so they are pushed to
 * whichever height in the staff the music leaves clear — bottom by default,
 * anywhere up to the top on request.
 */
export function tickRow(band, layout, strong, scale = 1) {
  const len = Math.min(10 * scale, band.coreH * 0.16) * (strong ? 1.6 : 1);
  const raw = layout.rulesTickPos;
  const pos = Math.max(0, Math.min(1, Number.isFinite(raw) ? raw : 0));
  return { len, top: band.coreTop + (1 - pos) * Math.max(0, band.coreH - len) };
}

/** Pixel y of a pitch, in cents relative to A440, within a band. */
export function yForBand(b, cents) {
  return b.coreTop + b.coreH / 2 - ((cents - b.centre) / b.span) * (b.coreH / 2);
}

/** The inverse: what pitch a point in a band represents. */
export function centsForBand(b, y) {
  return b.centre + ((b.coreTop + b.coreH / 2 - y) * 2 * b.span) / b.coreH;
}

/**
 * Where an annotation's baseline goes.
 *
 * Three cases, in the order they take precedence:
 *
 *   outward row  a normalised staff has no room inside it, so above and below
 *                marks are stacked clear of the ribbon in space the staff
 *                reserved for them.
 *   staff-aligned  a fixed height in the zone, stacking inward into the slack
 *                the staff has. Every mark placed this way shares one baseline,
 *                which is the point of it.
 *   line-relative  the default: a conventional offset from the sounding line,
 *                so the mark travels with the partial it belongs to.
 */
export function annotationY(b, a, size, base, scale = 1) {
  const row = b.rows?.get(a.id);
  const nudge = ((a.dy || 0) / b.span) * (b.coreH / 2);
  const inset = 3 * scale;
  const clamp = (y) =>
    Math.min(
      b.coreTop + b.coreH - 4 * scale,
      Math.max(b.coreTop + size + 2 * scale, y)
    );

  if (row?.outward) {
    return row.place === 'above'
      ? b.coreTop - row.row * b.rowH - inset - nudge
      : b.coreTop + b.coreH + row.row * b.rowH + size + inset - nudge;
  }

  if (a.align === 'staff') {
    const step = (row?.row || 0) * (b.rowH || size + 6 * scale);
    const y =
      a.place === 'above'
        ? b.coreTop + size + inset + step
        : a.place === 'below'
          ? b.coreTop + b.coreH - inset - step
          : b.coreTop + b.coreH / 2 + size / 2 + step;
    return clamp(y - nudge);
  }

  const off = (a.place === 'above' ? -18 : a.place === 'below' ? 22 : 3) * scale;
  return clamp(base + off - nudge);
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
